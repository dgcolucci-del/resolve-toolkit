"""Organizzazione del lavoro: file di passaggio tra chat, file creati, pulizia, archivio, stili usati, cancelli.

I "cancelli" sono le fasi che non si possono chiudere senza prove registrate (scope, misure audio).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time

from .connessione import ErroreToolkit, progetto
from .regole import regole

CARTELLA = os.path.expanduser("~/Library/Application Support/ResolveToolkit")


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s).strip("_") or "senza_nome"


def _json_leggi(path: str, vuoto):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return vuoto


def _json_scrivi(path: str, dati) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(dati, f, indent=2, ensure_ascii=False)


def _file_progetto(tipo: str, nome_progetto: str | None = None) -> str:
    nome = nome_progetto or progetto().GetName()
    return os.path.join(CARTELLA, tipo, _slug(nome) + ".json")


# ---------------------------------------------------------------- passaggio tra chat

def scrivi_passaggio(fase: str, fatto: list[str], verificato: list[str], non_verificato: list[str],
                     manca: list[str], impronta: str = "") -> dict:
    path = _file_progetto("passaggi")
    storia = _json_leggi(path, [])
    voce = {"ora": time.strftime("%Y-%m-%d %H:%M"), "fase": fase, "fatto": fatto, "verificato": verificato,
            "non_verificato": non_verificato, "manca": manca, "impronta_timeline": impronta}
    storia.append(voce)
    _json_scrivi(path, storia)
    return {"esito": "ok", "file": path, "voci": len(storia)}


def leggi_passaggio(nome_progetto: str | None = None) -> dict | None:
    storia = _json_leggi(_file_progetto("passaggi", nome_progetto), [])
    return {"ultima": storia[-1], "totale_voci": len(storia)} if storia else None


# ---------------------------------------------------------------- file creati dal toolkit

def registra_file(path: str, motivo: str) -> None:
    f = os.path.join(CARTELLA, "file_creati.json")
    elenco = _json_leggi(f, [])
    elenco.append({"file": path, "motivo": motivo, "ora": time.strftime("%Y-%m-%d %H:%M")})
    _json_scrivi(f, elenco)


def elenca_file_creati() -> dict:
    elenco = _json_leggi(os.path.join(CARTELLA, "file_creati.json"), [])
    for e in elenco:
        e["esiste"] = os.path.exists(e["file"])
    return {"esito": "ok", "file": [e for e in elenco if e["esiste"]],
            "nota": "Elenco da mostrare a Diego. Si cancella solo col suo via (sposta_nel_cestino)."}


def sposta_nel_cestino(file: list[str], conferma_diego: str) -> dict:
    """Cestino del Finder (recuperabile), mai rm. Solo file creati dal toolkit, solo col via di Diego."""
    if not conferma_diego.strip():
        raise ErroreToolkit("Serve il via di Diego: riporta le sue parole in conferma_diego.")
    noti = {e["file"] for e in _json_leggi(os.path.join(CARTELLA, "file_creati.json"), [])}
    estranei = [f for f in file if f not in noti]
    if estranei:
        raise ErroreToolkit(f"Questi file non li ha creati il toolkit, non li tocco: {estranei}")
    spostati = []
    for f in file:
        script = f'tell application "Finder" to delete POSIX file "{f}"'
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        if r.returncode != 0:
            raise ErroreToolkit(f"Cestino fallito per {f}: {r.stderr.strip()}")
        spostati.append(f)
    return {"esito": "ok", "spostati_nel_cestino": spostati}


# ---------------------------------------------------------------- archivio asset e salvataggio

def importa_asset(percorsi: list[str], cartella_media_pool: str = "") -> dict:
    ammesse = [regole()["archivio_asset"], regole().get("cartella_progetti", "")]
    ammesse = [a.rstrip("/") + "/" for a in ammesse if a]
    fuori = [p for p in percorsi if not any(os.path.abspath(p).startswith(a) for a in ammesse)]
    if fuori:
        raise ErroreToolkit(f"Si importa solo da {ammesse} (archivio asset o cartelle dei progetti). Fuori: {fuori}")
    mancanti = [p for p in percorsi if not os.path.exists(p)]
    if mancanti:
        raise ErroreToolkit(f"File non trovati (Diego li ha già scaricati?): {mancanti}")
    mp = progetto().GetMediaPool()
    if cartella_media_pool:
        radice = mp.GetRootFolder()
        dest = next((f for f in radice.GetSubFolderList() or [] if f.GetName() == cartella_media_pool), None)
        dest = dest or mp.AddSubFolder(radice, cartella_media_pool)
        mp.SetCurrentFolder(dest)
    clip = mp.ImportMedia(percorsi) or []
    return {"esito": "ok" if len(clip) == len(percorsi) else "parziale",
            "importate": [c.GetName() for c in clip], "richieste": len(percorsi)}


def salva_progetto(nome_deciso_da_diego: str) -> dict:
    p = progetto()
    if p.GetName() in ("Untitled Project", "Progetto senza titolo"):
        raise ErroreToolkit("Progetto mai salvato: il primo salvataggio con nome e cartella lo fa Diego in Resolve.")
    if nome_deciso_da_diego != p.GetName():
        raise ErroreToolkit(f"Il progetto aperto è '{p.GetName()}', non '{nome_deciso_da_diego}'. Non salvo.")
    from .connessione import resolve
    ok = resolve().GetProjectManager().SaveProject()
    return {"esito": "ok" if ok else "bloccato", "progetto": p.GetName()}


# ---------------------------------------------------------------- stili usati ("ogni reel è nuovo")

def registra_stile(cliente: str, reel: str, sottotitoli: str, effetti: list[str], transizioni: list[str]) -> dict:
    path = os.path.join(CARTELLA, "stili_usati.json")
    elenco = _json_leggi(path, [])
    elenco.append({"ora": time.strftime("%Y-%m-%d"), "cliente": cliente, "reel": reel,
                   "sottotitoli": sottotitoli, "effetti": effetti, "transizioni": transizioni})
    _json_scrivi(path, elenco)
    return {"esito": "ok", "reel_registrati": len(elenco)}


def _parole(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-zà-ù0-9]+", s.lower()) if len(w) > 2}


def controlla_novita(sottotitoli: str, effetti: list[str], transizioni: list[str], soglia: float = 0.6) -> dict:
    """Avvisa se la proposta somiglia troppo a un reel già fatto (stesso stile riciclato)."""
    proposta = _parole(sottotitoli) | {e.lower() for e in effetti + transizioni}
    simili = []
    for r in _json_leggi(os.path.join(CARTELLA, "stili_usati.json"), []):
        passato = _parole(r["sottotitoli"]) | {e.lower() for e in r["effetti"] + r["transizioni"]}
        if not proposta or not passato:
            continue
        j = len(proposta & passato) / len(proposta | passato)
        if j >= soglia:
            simili.append({"reel": r["reel"], "cliente": r["cliente"], "somiglianza": round(j, 2)})
    return {"esito": "ok" if not simili else "troppo_simile", "simili": simili,
            "regola": "ogni reel è un lavoro nuovo: grafiche, animazioni, transizioni e sottotitoli pensati da zero"}


# ---------------------------------------------------------------- cancello audio

def registra_misure_audio(voce_lufs: float, musica_lufs: float | None, sfx_lufs: float | None,
                          fonte: str, voce_pulita: bool) -> dict:
    """Numeri letti sul Loudness Meter Fairlight (Absolute Scale), traccia per traccia in solo."""
    path = _file_progetto("audio")
    dati = {"ora": time.strftime("%Y-%m-%d %H:%M"), "voce_lufs": voce_lufs, "musica_lufs": musica_lufs,
            "sfx_lufs": sfx_lufs, "fonte": fonte, "voce_pulita": voce_pulita}
    _json_scrivi(path, dati)
    return {"esito": "ok", **dati}


def stato_audio() -> dict:
    return _json_leggi(_file_progetto("audio"), {})


def chiudi_audio(misura_mix_file: dict) -> dict:
    """misura_mix_file = risultato di misura_loudness sul render audio della timeline attuale."""
    a = regole()["audio"]
    tracce = stato_audio()
    problemi = []
    if not tracce:
        problemi.append("Mancano le misure traccia per traccia dal Loudness Meter Fairlight.")
    elif not tracce.get("voce_pulita"):
        problemi.append("Voce non ancora pulita (Voice Isolation / Audio Assistant) prima della base.")
    l, tp = misura_mix_file.get("lufs_integrati"), misura_mix_file.get("true_peak_dbtp")
    if l is None or abs(l - a["lufs_obiettivo"]) > a["tolleranza_lufs"]:
        problemi.append(f"Mix a {l} LUFS, obiettivo {a['lufs_obiettivo']} ±{a['tolleranza_lufs']}.")
    if tp is None or tp > a["true_peak_max"]:
        problemi.append(f"True peak {tp} dBTP, massimo {a['true_peak_max']}.")
    return {"esito": "ok" if not problemi else "aperto", "problemi": problemi, "tracce": tracce, "mix": misura_mix_file}
