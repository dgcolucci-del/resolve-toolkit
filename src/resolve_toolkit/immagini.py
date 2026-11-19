"""Fotogrammi dalla timeline e misure numeriche sulle immagini (servono a SEGNALARE, non a promuovere)."""
from __future__ import annotations

import math
import os

import numpy as np
from PIL import Image

from .connessione import ErroreToolkit, progetto, resolve
from .operazioni import frame_a_timecode

CARTELLA_TEMP = os.path.expanduser("~/Library/Application Support/ResolveToolkit/temp")


def esporta_frame(t, frame_assoluto: int, path: str) -> str:
    if resolve().GetCurrentPage() not in ("edit", "color"):
        resolve().OpenPage("edit")
    fps = float(t.GetSetting("timelineFrameRate"))
    tc = frame_a_timecode(frame_assoluto, fps)
    if not t.SetCurrentTimecode(tc):
        raise ErroreToolkit(f"Non riesco a portare la testina a {tc}.")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not progetto().ExportCurrentFrameAsStill(path):
        raise ErroreToolkit(f"Export del frame {tc} fallito.")
    return path


def carica_rgb(path: str) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)


def analizza_colore(rgb: np.ndarray) -> dict:
    """Misure tipo scope su un frame 8 bit: bianchi, neri, bruciati, pelle (angolo vectorscope)."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    piatti = rgb.reshape(-1, 3)
    ordine = np.argsort(y.reshape(-1))
    n = max(50, int(len(ordine) * 0.005))  # i pixel più chiari/scuri veri (0,5%), non un percentile piatto
    bianchi = piatti[ordine[-n:]].mean(axis=0)
    neri = piatti[ordine[:n]].mean(axis=0)
    bruciati = float(((rgb >= 254).any(axis=-1)).mean() * 100)
    schiacciati = float(((rgb <= 1).all(axis=-1)).mean() * 100)
    cb = 128 - 0.1146 * r - 0.3854 * g + 0.5 * b
    cr = 128 + 0.5 * r - 0.4542 * g - 0.0458 * b
    pelle_mask = (cb > 77) & (cb < 127) & (cr > 133) & (cr < 173) & (y > 40) & (y < 230)
    pelle = None
    if pelle_mask.mean() > 0.01:
        angolo = math.degrees(math.atan2(float(cr[pelle_mask].mean() - 128), float(cb[pelle_mask].mean() - 128)))
        pelle = {"percentuale_frame": round(float(pelle_mask.mean() * 100), 1), "angolo": round(angolo, 1),
                 "scarto_da_linea_pelle": round(angolo - 123.0, 1)}
    return {
        "luma_media": round(float(y.mean()), 1),
        "bianchi_rgb": [round(float(v), 1) for v in bianchi],
        "dominante_bianchi": round(float(bianchi.max() - bianchi.min()), 1),
        "neri_rgb": [round(float(v), 1) for v in neri],
        "percento_bruciati": round(bruciati, 2),
        "percento_neri_schiacciati": round(schiacciati, 2),
        "pelle": pelle,
    }


def fuori_media(misure: dict[str, dict], soglie: dict | None = None) -> list[dict]:
    """Clip che si staccano dalla mediana del montato (per l'uniformità)."""
    s = {"luma": 20.0, "dominante": 12.0, "pelle_gradi": 8.0, "bruciati": 1.0, **(soglie or {})}
    if not misure:
        return []
    luma = np.median([m["luma_media"] for m in misure.values()])
    angoli = [m["pelle"]["angolo"] for m in misure.values() if m["pelle"]]
    angolo_med = np.median(angoli) if angoli else None
    out = []
    for nome, m in misure.items():
        motivi = []
        if abs(m["luma_media"] - luma) > s["luma"]:
            motivi.append(f"luminosità {m['luma_media']} contro mediana {luma:.1f}")
        if m["dominante_bianchi"] > s["dominante"]:
            motivi.append(f"bianchi non neutri (scarto RGB {m['dominante_bianchi']})")
        if m["percento_bruciati"] > s["bruciati"]:
            motivi.append(f"{m['percento_bruciati']}% pixel bruciati")
        if m["pelle"] and angolo_med is not None and abs(m["pelle"]["angolo"] - angolo_med) > s["pelle_gradi"]:
            motivi.append(f"pelle a {m['pelle']['angolo']}° contro {angolo_med:.1f}°")
        if motivi:
            out.append({"clip": nome, "motivi": motivi})
    return out
