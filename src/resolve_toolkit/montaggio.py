"""Montaggio del parlato: segmenti senza pause dall'audio vero, timeline costruita sui file originali,
riprese alternative da far scegliere a Diego, trascrizione con whisper sul Mac."""
from __future__ import annotations

import json
import time
import os
import subprocess
import tempfile

from . import audio
from .connessione import ErroreToolkit, progetto
from .operazioni import _clip_media_pool, inserisci_clip
from .regole import regole
from .stato import fotografia

VENDOR = "/Volumes/Tokiro 01/Progetti Video 2026/vendor"


def segmenti_parlato(silenzi: list[dict], durata_s: float, margine_s: float | None = None,
                     min_parlato_s: float = 0.12) -> list[list[float]]:
    """Dai silenzi misurati ai tratti di parlato da tenere, con un piccolo margine (respiro naturale)."""
    m = regole()["silenzi"]["margine_s"] if margine_s is None else margine_s
    segmenti, cursore = [], 0.0
    for s in silenzi:
        fine_parlato = s["inizio_s"] + m
        if fine_parlato - cursore >= min_parlato_s:
            segmenti.append([round(max(0.0, cursore), 3), round(min(durata_s, fine_parlato), 3)])
        cursore = (s["fine_s"] if s["fine_s"] is not None else durata_s) - m
    if durata_s - cursore >= min_parlato_s:
        segmenti.append([round(max(0.0, cursore), 3), round(durata_s, 3)])
    return segmenti


def proposta_tagli(file_audio: str, soglia_db: float | None = None, durata_min_s: float | None = None) -> dict:
    r = regole()["silenzi"]
    sil = audio.trova_silenzi(file_audio, soglia_db or r["soglia_db"], durata_min_s or r["durata_min_s"])
    durata = audio.formato(file_audio)["durata_s"]
    seg = segmenti_parlato(sil["silenzi"], durata)
    tenuto = sum(b - a for a, b in seg)
    return {"esito": "ok", "segmenti_s": seg, "pause_trovate": sil["numero"], "durata_originale_s": round(durata, 2),
            "durata_montata_s": round(tenuto, 2),
            "nota": "PROPOSTA: mostrarla a Diego prima di costruire la timeline."}


def monta_parlato(nome_clip: str, segmenti_s: list[list[float]], nome_nuova_timeline: str,
                  traccia: int = 1, cartella: str = "") -> dict:
    """Crea una timeline NUOVA con i soli tratti parlati, sui file originali, verificando ogni inserimento."""
    p = progetto()
    nomi = {p.GetTimelineByIndex(i).GetName() for i in range(1, p.GetTimelineCount() + 1)}
    if nome_nuova_timeline in nomi:
        raise ErroreToolkit(f"Esiste già una timeline '{nome_nuova_timeline}'.")
    mpi = _clip_media_pool(nome_clip, cartella or None)
    fps = float(mpi.GetClipProperty("FPS") or 0)
    if not fps:
        raise ErroreToolkit("FPS della clip non leggibile.")
    t = p.GetMediaPool().CreateEmptyTimeline(nome_nuova_timeline)
    if t is None:
        raise ErroreToolkit("Resolve non ha creato la timeline.")
    p.SetCurrentTimeline(t)
    fps_tl = float(t.GetSetting("timelineFrameRate"))
    if abs(fps_tl - fps) > 0.01:
        raise ErroreToolkit(f"La timeline nuova è a {fps_tl} fps e la clip a {fps}: impostare gli fps del progetto come il girato.")
    posizione, inseriti = 0, []
    for a, b in segmenti_s:
        da, fino = round(a * fps), round(b * fps)
        if fino <= da:
            continue
        imp = fotografia(nome_nuova_timeline)["impronta"]
        r = inserisci_clip(imp, nome_clip, da, fino, traccia, posizione, "entrambi", cartella or None, nome_nuova_timeline)
        inseriti.append({"sorgente": [da, fino], "posizione": posizione, "durata": r["durata"]})
        posizione += r["durata"]
    return {"esito": "ok", "timeline": nome_nuova_timeline, "segmenti": len(inseriti), "durata_frame": posizione,
            "inseriti": inseriti, "prossimo_passo": "fotogrammi_ai_tagli + ascolto dei tagli"}


def timeline_alternative(riprese: list[dict], nome_timeline: str, pausa_s: float = 1.0) -> dict:
    """riprese: [{"nome_clip","inizio_s","fine_s","etichetta"}]: in fila con un secondo di vuoto e un marker.
    Diego guarda e sceglie: io non scelgo (15 nov 2026)."""
    p = progetto()
    t = p.GetMediaPool().CreateEmptyTimeline(nome_timeline)
    if t is None:
        raise ErroreToolkit("Resolve non ha creato la timeline.")
    p.SetCurrentTimeline(t)
    fps = float(t.GetSetting("timelineFrameRate"))
    posizione, fatte = 0, []
    for r in riprese:
        mpi = _clip_media_pool(r["nome_clip"], r.get("cartella"))
        f_clip = float(mpi.GetClipProperty("FPS") or fps)
        da, fino = round(r["inizio_s"] * f_clip), round(r["fine_s"] * f_clip)
        imp = fotografia(nome_timeline)["impronta"]
        out = inserisci_clip(imp, r["nome_clip"], da, fino, 1, posizione, "entrambi", r.get("cartella"), nome_timeline)
        t.AddMarker(posizione, "Yellow", r.get("etichetta", f"Ripresa {len(fatte) + 1}"), r["nome_clip"], 1)
        fatte.append({"etichetta": r.get("etichetta"), "posizione": posizione})
        posizione += out["durata"] + round(pausa_s * fps)
    return {"esito": "ok", "timeline": nome_timeline, "riprese": fatte, "nota": "Far scegliere a Diego."}


def _leggi_trascrizione(base):
    with open(base + ".json") as f:
        dati = json.load(f)
    parole = []
    for s in dati.get("transcription", []):
        testo = s.get("text", "").strip()
        if testo:
            parole.append({"testo": testo, "inizio_s": s["offsets"]["from"] / 1000, "fine_s": s["offsets"]["to"] / 1000})
    return {"esito": "ok", "parole": parole, "testo": " ".join(p["testo"] for p in parole),
            "json": base + ".json",
            "nota": "I tempi di whisper vanno corretti sull'audio vero; il testo va fatto rileggere a Diego."}


def trascrivi(file_audio: str, lingua: str = "it", modello: str = "") -> dict:
    """whisper.cpp sul Mac, IN BACKGROUND (20 nov 2026: in sincrono superava il limite di 80 s del ponte).
    Prima chiamata: avvia e risponde "in_corso". Richiamala con lo stesso file: risponde col testo quando ha finito.
    Accetta wav, mov, mp4: l'audio viene estratto a 16 kHz mono. Il risultato resta in <file>.trascrizione.json."""
    if not os.path.exists(file_audio):
        raise ErroreToolkit(f"Non trovo {file_audio}.")
    base = os.path.splitext(file_audio)[0] + ".trascrizione"
    stato = base + ".stato"
    if os.path.exists(base + ".json") and os.path.getmtime(base + ".json") >= os.path.getmtime(file_audio):
        return _leggi_trascrizione(base)
    if os.path.exists(stato):
        with open(stato) as f:
            info = json.load(f)
        pid = info.get("pid")
        vivo = False
        if pid:
            try:
                os.kill(pid, 0)
                vivo = True
            except OSError:
                vivo = False
        if vivo:
            trascorsi = round(time.time() - info.get("avvio", time.time()))
            return {"esito": "in_corso", "trascorsi_s": trascorsi,
                    "stima_totale_s": info.get("stima_s"),
                    "prossimo_passo": "richiama trascrivi con lo stesso file tra 30-60 s"}
        log = info.get("log", "")
        coda = open(log).read()[-500:] if log and os.path.exists(log) else ""
        os.remove(stato)
        raise ErroreToolkit(f"whisper si è fermato senza risultato. Ultime righe: {coda}")

    cli = os.path.join(VENDOR, "whisper.cpp/build/bin/whisper-cli")
    modello = modello or os.path.join(VENDOR, "whisper.cpp/models/ggml-large-v3.bin")
    for p_ in (cli, modello):
        if not os.path.exists(p_):
            raise ErroreToolkit(f"Non trovo {p_}.")
    tmp = tempfile.mkdtemp(prefix="trascrizione_")
    wav = os.path.join(tmp, "audio16k.wav")
    subprocess.run([audio._ffmpeg(), "-y", "-v", "error", "-i", file_audio, "-vn", "-ac", "1", "-ar", "16000", wav],
                   check=True, timeout=60)
    durata = os.path.getsize(wav) / 32000  # 16 kHz mono 16 bit
    log = os.path.join(tmp, "whisper.log")
    with open(log, "w") as lf:
        proc = subprocess.Popen([cli, "-m", modello, "-f", wav, "-l", lingua, "-ml", "1", "-sow", "-ojf", "-of", base],
                                stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)
    with open(stato, "w") as f:
        json.dump({"pid": proc.pid, "avvio": time.time(), "log": log, "stima_s": round(durata * 2.3)}, f)
    return {"esito": "in_corso", "durata_audio_s": round(durata, 1), "stima_totale_s": round(durata * 2.3),
            "prossimo_passo": "richiama trascrivi con lo stesso file tra 30-60 s"}
