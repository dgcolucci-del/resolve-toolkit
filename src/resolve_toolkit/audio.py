"""Misure sul file vero con ffmpeg: loudness, true peak, silenzi, formato.

Regola: mai "a posto" senza numeri. loudness_qc del server advanced non è affidabile (13 nov 2026).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

from .connessione import ErroreToolkit

CANDIDATI_FFMPEG = [
    os.environ.get("RESOLVE_TOOLKIT_FFMPEG", ""),
    "/Volumes/Tokiro 01/Progetti Video 2026/vendor/bin/ffmpeg",
    "/opt/homebrew/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
]


def _ffmpeg(nome: str = "ffmpeg") -> str:
    for c in CANDIDATI_FFMPEG:
        if c:
            c = os.path.join(os.path.dirname(c), nome) if nome != "ffmpeg" else c
            if os.path.isfile(c) and os.access(c, os.X_OK):
                return c
    trovato = shutil.which(nome)
    if not trovato:
        raise ErroreToolkit(f"{nome} non trovato. Imposta RESOLVE_TOOLKIT_FFMPEG col percorso di ffmpeg.")
    return trovato


def _controlla_file(path: str) -> None:
    if not os.path.isfile(path):
        raise ErroreToolkit(f"File non trovato: {path}")


def analizza_ebur128(testo: str) -> dict:
    blocco = testo[testo.rfind("Summary:"):] if "Summary:" in testo else testo

    def num(etichetta):
        m = re.search(etichetta + r":\s*(-?[\d.]+|-inf)", blocco)
        return None if not m or m.group(1) == "-inf" else float(m.group(1))

    return {"lufs_integrati": num("I"), "lra": num("LRA"), "true_peak_dbtp": num("Peak")}


def misura_loudness(path: str) -> dict:
    _controlla_file(path)
    r = subprocess.run([_ffmpeg(), "-hide_banner", "-nostats", "-i", path, "-vn",
                        "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True)
    dati = analizza_ebur128(r.stderr)
    if dati["lufs_integrati"] is None:
        raise ErroreToolkit("ffmpeg non ha restituito il loudness (il file ha audio?).")
    return dati


def analizza_silenzi(testo: str) -> list[dict]:
    inizi = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", testo)]
    fini = re.findall(r"silence_end:\s*([\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)", testo)
    out = []
    for i, s in enumerate(inizi):
        if i < len(fini):
            out.append({"inizio_s": max(s, 0.0), "fine_s": float(fini[i][0]), "durata_s": float(fini[i][1])})
        else:
            out.append({"inizio_s": s, "fine_s": None, "durata_s": None})
    return out


def trova_silenzi(path: str, soglia_db: float = -30.0, durata_min_s: float = 0.15) -> dict:
    """Pause misurate sull'audio vero (regola 17 nov 2026), non sulla trascrizione."""
    _controlla_file(path)
    r = subprocess.run([_ffmpeg(), "-hide_banner", "-nostats", "-i", path, "-vn",
                        "-af", f"silencedetect=noise={soglia_db}dB:d={durata_min_s}", "-f", "null", "-"],
                       capture_output=True, text=True)
    silenzi = analizza_silenzi(r.stderr)
    return {"soglia_db": soglia_db, "durata_min_s": durata_min_s, "numero": len(silenzi), "silenzi": silenzi}


def formato(path: str) -> dict:
    _controlla_file(path)
    r = subprocess.run([_ffmpeg("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
                       capture_output=True, text=True)
    try:
        info = json.loads(r.stdout)
    except ValueError:
        raise ErroreToolkit("ffprobe non ha letto il file.")
    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    fps = None
    if video and video.get("r_frame_rate", "0/0") != "0/0":
        n, d = video["r_frame_rate"].split("/")
        fps = round(float(n) / float(d), 3)
    return {
        "larghezza": video and video.get("width"),
        "altezza": video and video.get("height"),
        "fps": fps,
        "codec_video": video and video.get("codec_name"),
        "codec_audio": audio and audio.get("codec_name"),
        "durata_s": float(info.get("format", {}).get("duration", 0) or 0),
    }


def leggi_pcm(path: str, sr: int = 48000):
    import numpy as np
    r = subprocess.run([_ffmpeg(), "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                       capture_output=True)
    if r.returncode != 0:
        raise ErroreToolkit(f"Non riesco a leggere l'audio di {path}.")
    return np.frombuffer(r.stdout, dtype=np.float32), sr


def impronta_audio(x) -> str:
    import hashlib
    return hashlib.sha1(x.tobytes()).hexdigest()[:12]


def livelli_nei_punti(path: str, tempi_s: list[float], finestra_s: float = 0.2, confronto: str = "") -> dict:
    """Picco e RMS (dBFS) attorno ai colpi: per confrontare SFX e musica sui colpi, non solo il LUFS.
    21 nov 2026 (SIMEL 005): due render "diversi" davano numeri identici perché l'audio ERA identico
    (il mute delle tracce via API non era stato applicato). Ora ogni misura riporta l'impronta dell'audio e,
    con `confronto`, la differenza col secondo file: se l'impronta è uguale lo dice invece di misurare."""
    import numpy as np
    x, sr = leggi_pcm(path)
    if confronto:
        y, _ = leggi_pcm(confronto)
        if impronta_audio(x) == impronta_audio(y):
            raise ErroreToolkit(f"{os.path.basename(path)} e {os.path.basename(confronto)} hanno lo stesso audio "
                                "(impronta identica): il mute/le modifiche non sono finite nel render.")
    out = []
    for t in tempi_s:
        a, b = max(0, int((t - finestra_s / 2) * sr)), int((t + finestra_s / 2) * sr)
        seg = x[a:b]
        if len(seg) == 0:
            out.append({"tempo_s": t, "picco_dbfs": None, "rms_dbfs": None})
            continue
        picco = float(np.abs(seg).max())
        rms = float(np.sqrt(np.mean(seg ** 2)))
        db = lambda v: round(20 * np.log10(v), 1) if v > 0 else None  # noqa: E731
        voce = {"tempo_s": t, "picco_dbfs": db(picco), "rms_dbfs": db(rms)}
        if confronto:
            seg2 = y[a:b]
            if len(seg2):
                diff = seg - seg2[:len(seg)] if len(seg2) >= len(seg) else seg[:len(seg2)] - seg2
                voce["differenza_rms_dbfs"] = db(float(np.sqrt(np.mean(diff ** 2))))
        out.append(voce)
    return {"file": path, "impronta_audio": impronta_audio(x), "confronto": confronto or None, "punti": out}


def verifica_render_prova(path: str, tempi_s: list[float] | None = None) -> dict:
    """Frame neri o congelati e fotogrammi estratti ai tempi indicati, da GUARDARE tutti."""
    _controlla_file(path)
    r = subprocess.run([_ffmpeg(), "-hide_banner", "-nostats", "-i", path, "-vf",
                        "blackdetect=d=0.04:pix_th=0.05,freezedetect=n=0.001:d=0.5", "-an", "-f", "null", "-"],
                       capture_output=True, text=True)
    neri = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", r.stderr)
    fermi = re.findall(r"freeze_start: ([\d.]+)", r.stderr)
    estratti = []
    if tempi_s:
        cartella = os.path.splitext(path)[0] + "_frame"
        os.makedirs(cartella, exist_ok=True)
        for t in tempi_s:
            out = os.path.join(cartella, f"t{t:07.3f}.png")
            subprocess.run([_ffmpeg(), "-y", "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1", out])
            if os.path.exists(out):
                estratti.append(out)
    problemi = [f"nero {a}-{b} s" for a, b in neri] + [f"immagine ferma da {a} s" for a in fermi]
    return {"esito": "ok" if not problemi else "da_guardare", "problemi": problemi, "frame_estratti": estratti,
            "formato": formato(path), "nota": "Guardare i frame estratti prima di dire che l'effetto è a posto."}


def controllo_consegna(path: str, larghezza: int = 1080, altezza: int = 1920,
                       lufs_obiettivo: float = -14.0, tolleranza_lufs: float = 1.0,
                       true_peak_max: float = -1.0) -> dict:
    """Controllo finale del file come lo vedrà Diego: formato + loudness, con esito per voce."""
    f = formato(path)
    l = misura_loudness(path)
    controlli = {
        "risoluzione": f["larghezza"] == larghezza and f["altezza"] == altezza,
        "loudness": abs(l["lufs_integrati"] - lufs_obiettivo) <= tolleranza_lufs,
        "true_peak": l["true_peak_dbtp"] is not None and l["true_peak_dbtp"] <= true_peak_max,
    }
    return {"file": path, "formato": f, "loudness": l, "controlli": controlli,
            "tutto_ok": all(controlli.values()),
            "non_verificato_qui": ["color (scope in Resolve)", "sottotitoli e safe zone (guardare i frame)",
                                   "ritmo e musica (ascolto)"]}
