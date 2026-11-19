"""Color: lettura delle catene di nodi, uniformità, cancello degli scope, gruppi colore.

Regole (colorist-davinci-master, 1 / 12 / 17 / 19 nov 2026):
- la color si fa clip per clip nella pagina Color guardando gli scope sul PHL: il toolkit NON corregge;
- niente copie di grade via script/DRX, niente LUT/CDL come scorciatoia (i comandi non esistono);
- prima di correggere: sorgente senza nodi + catena adatta a quella clip;
- "color completa" solo se ogni clip ha il controllo scope registrato dopo l'ultima modifica.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time

from . import immagini
from .connessione import ErroreToolkit, progetto, trova_timeline
from .lavoro import _file_progetto, _json_leggi, _json_scrivi, registra_file
from .stato import verifica_lucchetto

FAMIGLIE_LOG = {
    "slog3": ["slog3", "s-log3", "s log3", "slog 3"],
    "slog2": ["slog2", "s-log2"],
    "dlog": ["dlog", "d-log", "d log"],
    "vlog": ["vlog", "v-log"],
    "clog": ["clog", "c-log"],
    "hlg": ["hlg"],
}
CHIAVI_SORGENTE = ("gamma", "color", "camera", "codec", "resolution", "fps", "log")


def _famiglie(testo: str) -> set[str]:
    t = testo.lower()
    return {f for f, nomi in FAMIGLIE_LOG.items() if any(n in t for n in nomi)}


def _clip_video(t):
    for tr in range(1, (t.GetTrackCount("video") or 0) + 1):
        for i, item in enumerate(t.GetItemListInTrack("video", tr) or [], start=1):
            yield tr, i, item


def _catena(item) -> dict:
    if not hasattr(item, "GetNodeGraph"):
        return {"disponibile": False}
    g = item.GetNodeGraph()
    if not g:
        return {"disponibile": False}
    nodi = []
    for n in range(1, (g.GetNumNodes() or 0) + 1):
        nodi.append({
            "nodo": n,
            "etichetta": g.GetNodeLabel(n) if hasattr(g, "GetNodeLabel") else None,
            "lut": g.GetLUT(n) if hasattr(g, "GetLUT") else None,
            "strumenti": g.GetToolsInNode(n) if hasattr(g, "GetToolsInNode") else None,
        })
    gruppo = item.GetColorGroup() if hasattr(item, "GetColorGroup") else None
    return {"disponibile": True, "numero_nodi": len(nodi), "nodi": nodi,
            "gruppo": gruppo.GetName() if gruppo else None}


def impronta_grade(catena: dict) -> str:
    return hashlib.sha256(json.dumps(catena, sort_keys=True, default=str).encode()).hexdigest()[:12]


def stato_color(nome_timeline: str | None = None) -> dict:
    t = trova_timeline(nome_timeline)
    clip, avvisi = [], []
    for tr, i, item in _clip_video(t):
        mpi = item.GetMediaPoolItem()
        props = (mpi.GetClipProperty() or {}) if mpi else {}
        sorgente = {k: v for k, v in props.items() if any(c in k.lower() for c in CHIAVI_SORGENTE) and v}
        catena = _catena(item)
        testo_catena = json.dumps(catena.get("nodi", []), default=str)
        fam_catena, fam_sorgente = _famiglie(testo_catena), _famiglie(json.dumps(sorgente))
        voce = {"traccia": tr, "indice": i, "nome": item.GetName(), "id": item.GetUniqueId(),
                "sorgente": sorgente, "catena": catena, "impronta_grade": impronta_grade(catena)}
        if fam_catena and fam_sorgente and not fam_catena & fam_sorgente:
            avvisi.append(f"{item.GetName()}: catena {sorted(fam_catena)} ma sorgente {sorted(fam_sorgente)}: catena NON adatta.")
        elif fam_catena and not fam_sorgente:
            avvisi.append(f"{item.GetName()}: catena {sorted(fam_catena)}, sorgente senza indicazione di log: verificare la sorgente senza nodi.")
        elif fam_sorgente and not fam_catena:
            avvisi.append(f"{item.GetName()}: sorgente {sorted(fam_sorgente)} senza trasformazione colore riconoscibile nei nodi.")
        clip.append(voce)
    conteggi = {}
    for c in clip:
        n = c["catena"].get("numero_nodi")
        conteggi[n] = conteggi.get(n, 0) + 1
    return {"esito": "ok" if not avvisi else "da_verificare", "clip": clip, "avvisi": avvisi,
            "nodi_per_clip": conteggi,
            "nota": "Le etichette dei nodi aiutano: chiamare i nodi (CST, bilanciamento, HSV, pelle) rende il controllo affidabile."}


def uniformita(nome_timeline: str | None = None, cartella: str = "") -> dict:
    """Un fotogramma a metà di ogni clip video, misure e clip fuori dalla mediana. Solo per segnalare."""
    t = trova_timeline(nome_timeline)
    progetto().SetCurrentTimeline(t)
    cartella = cartella or os.path.join(immagini.CARTELLA_TEMP, "uniformita", time.strftime("%Y%m%d-%H%M%S"))
    misure, file = {}, {}
    for tr, i, item in _clip_video(t):
        meta = (item.GetStart() + item.GetEnd()) // 2
        nome = f"V{tr}_{i:03d}_{item.GetName()}"
        path = immagini.esporta_frame(t, meta, os.path.join(cartella, nome + ".png"))
        registra_file(path, "frame per controllo uniformità color")
        misure[nome] = immagini.analizza_colore(immagini.carica_rgb(path))
        file[nome] = path
    return {"esito": "ok", "misure": misure, "fuori_media": immagini.fuori_media(misure), "file": file,
            "attenzione": "Questi numeri NON sostituiscono gli scope di Resolve: servono solo a sapere dove guardare."}


# ---------------------------------------------------------------- cancello degli scope

def _registro():
    return _file_progetto("scope")


def registra_controllo_scope(nome_clip: str, parade: str, waveform: str, vectorscope: str,
                             esito: str, pelle: str = "", rumore: str = "", screenshot: str = "",
                             nome_timeline: str | None = None) -> dict:
    """Da chiamare DOPO aver guardato gli scope di Resolve sul PHL per quella clip."""
    if esito not in ("ok", "da_correggere"):
        raise ErroreToolkit("esito deve essere 'ok' o 'da_correggere'.")
    for campo, valore in (("parade", parade), ("waveform", waveform), ("vectorscope", vectorscope)):
        if len(valore.strip()) < 8:
            raise ErroreToolkit(f"Scrivi cosa hai letto davvero su {campo} (valori, non 'ok').")
    t = trova_timeline(nome_timeline)
    item = next((it for _, _, it in _clip_video(t) if it.GetName() == nome_clip), None)
    if item is None:
        raise ErroreToolkit(f"Clip '{nome_clip}' non trovata nella timeline.")
    reg = _json_leggi(_registro(), {})
    reg[item.GetUniqueId()] = {"nome": nome_clip, "ora": time.time(), "parade": parade, "waveform": waveform,
                               "vectorscope": vectorscope, "pelle": pelle, "rumore": rumore, "esito": esito,
                               "screenshot": screenshot, "impronta_grade": impronta_grade(_catena(item)),
                               "valido": True}
    _json_scrivi(_registro(), reg)
    return {"esito": "ok", "registrato": nome_clip}


def segna_modifica_color(nome_clip: str, nome_timeline: str | None = None) -> dict:
    """Da chiamare dopo OGNI ritocco a una clip nella pagina Color: il controllo precedente non vale più."""
    t = trova_timeline(nome_timeline)
    reg = _json_leggi(_registro(), {})
    toccate = 0
    for _, _, it in _clip_video(t):
        if it.GetName() == nome_clip and it.GetUniqueId() in reg:
            reg[it.GetUniqueId()]["valido"] = False
            toccate += 1
    _json_scrivi(_registro(), reg)
    return {"esito": "ok", "controlli_annullati": toccate}


def color_completa(nome_timeline: str | None = None) -> dict:
    t = trova_timeline(nome_timeline)
    reg = _json_leggi(_registro(), {})
    mancanti, da_correggere, ok = [], [], []
    for _, _, it in _clip_video(t):
        r = reg.get(it.GetUniqueId())
        if not r or not r["valido"]:
            mancanti.append(it.GetName())
        elif r["impronta_grade"] != impronta_grade(_catena(it)):
            mancanti.append(f"{it.GetName()} (nodi cambiati dopo il controllo)")
        elif r["esito"] != "ok":
            da_correggere.append(it.GetName())
        else:
            ok.append(it.GetName())
    chiusa = not mancanti and not da_correggere
    return {"esito": "completa" if chiusa else "aperta", "senza_controllo_scope": mancanti,
            "da_correggere": da_correggere, "controllate_ok": ok,
            "prossimo_passo": "render di prova da far vedere a Diego" if chiusa else "guardare gli scope sulle clip elencate"}


# ---------------------------------------------------------------- gruppi colore

def assegna_gruppo_colore(impronta: str, nome_gruppo: str, clip: list[str], crea_se_manca: bool = False,
                          nome_timeline: str | None = None) -> dict:
    verifica_lucchetto(impronta, nome_timeline)
    p = progetto()
    gruppi = p.GetColorGroupsList() or [] if hasattr(p, "GetColorGroupsList") else []
    gruppo = next((g for g in gruppi if g.GetName() == nome_gruppo), None)
    if gruppo is None:
        if not crea_se_manca or not hasattr(p, "AddColorGroup"):
            raise ErroreToolkit(f"Gruppo '{nome_gruppo}' non esiste. Crealo dalla UI (tasto destro sulla miniatura > "
                                "Add into a New Group, metodo del 18 nov) o passa crea_se_manca.")
        gruppo = p.AddColorGroup(nome_gruppo)
    t = trova_timeline(nome_timeline)
    fatte, non_trovate = [], list(clip)
    for _, _, it in _clip_video(t):
        if it.GetName() in clip:
            if it.AssignToColorGroup(gruppo):
                fatte.append(it.GetName())
            if it.GetName() in non_trovate:
                non_trovate.remove(it.GetName())
    return {"esito": "ok" if not non_trovate else "parziale", "assegnate": fatte, "non_trovate": non_trovate,
            "prossimo_passo": "lavorare sul nodo Group Post-Clip guardando gli scope a ogni passo"}
