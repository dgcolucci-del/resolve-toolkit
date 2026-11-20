"""Le regole di Diego in UN solo posto. Se una regola cambia, si cambia qui e vale per tutti i comandi.

Ogni regola riporta la data e il reel da cui viene (fonte: memoria e preferenze di Diego).
Il file utente ~/Library/Application Support/ResolveToolkit/regole.json può sovrascrivere i valori.
"""
from __future__ import annotations

import json
import os

FILE_UTENTE = os.path.expanduser("~/Library/Application Support/ResolveToolkit/regole.json")

PREDEFINITE = {
    # Formato reel (preferenze: reel verticali 1080x1920)
    "formato": {"larghezza": 1080, "altezza": 1920},
    # Safe zone Instagram (preferenze, 9 nov 2026)
    "safe_zone": {"alto_px": 250, "basso_px": 1470, "lato_sinistro_px": 65, "lato_destro_px": 100,
                  "basso_adv_meta_px": 1920 - 672},
    # Audio (protocollo, 15 nov 2026)
    "audio": {"lufs_obiettivo": -14.0, "tolleranza_lufs": 1.0, "true_peak_max": -1.0},
    # Musica (protocollo §4)
    "musica": {"scarto_max_battiti": 0.05, "battute_per_frase": 8, "battiti_per_battuta": 4},
    # Silenzi (17 nov 2026, reel Glow: "odia i silenzi a prescindere")
    "silenzi": {"soglia_db": -30.0, "durata_min_s": 0.15, "margine_s": 0.05},
    # Sottotitoli (preferenze: interlinea stretta 18 nov, stessa altezza 9 nov, mai sopra visi/loghi)
    "sottotitoli": {"interlinea_max": 1.0, "stessa_altezza": True, "margine_viso_px": 30},
    # Punch-in (17 nov 2026, SIMEL 004): margine sopra la testa
    "punch_in": {"margine_testa_px": 40},
    # Divieti espliciti
    "divieti": {
        "effetti": ["Drop Warp"],  # 12 nov 2026, REEL 014: "proprio non gli piace"
        "color": ["copia grade via script", "DRX su più clip", "LUT come scorciatoia", "CDL via script"],  # 19 nov
        "clip_orizzontali_in_verticale": True,  # preferenze
        "clip_ripetute_nello_stesso_reel": True,  # preferenze
        "ducking_musica_se_non_richiesto": True,  # 15 nov, REEL 015
    },
    # B-roll: sempre raffiche a tempo (preferenze); durata massima di una clip B-roll in battiti
    "broll": {"battiti_max_per_clip": 2},
    # Percorsi
    "archivio_asset": "/Volumes/Tokiro 01/SFX",  # dall'8 nov 2026
    # 20 nov 2026: overlay e grafiche del reel stanno nella cartella del progetto (es. REEL 003/_claude)
    "cartella_progetti": "/Volumes/Tokiro 01/Progetti Video 2026",
    # Skill del protocollo (protocollo-reel-diego §1): tutte, sempre
    "skill_avvio": [
        "regole-motion-diego", "reel-mralextech", "montaggio-capri", "effetti-jamie-fenn",
        "davinci-master-architect", "colorist-davinci-master", "davinci-fairlight-audio-master",
        "testi-effetti-sergio-mota", "deny-king", "fusion-compositing-vfx", "fusion-titoli-template",
        "davinci-motion", "remotion-motion-graphics", "hyperframes-motion", "art3-davinci-vfx-suite",
        "computer-use", "controllo-schermo-diego", "protocollo-reel-diego",
    ],
}


def _unisci(base: dict, extra: dict) -> dict:
    out = dict(base)
    for k, v in extra.items():
        out[k] = _unisci(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def regole() -> dict:
    try:
        with open(FILE_UTENTE) as f:
            return _unisci(PREDEFINITE, json.load(f))
    except (OSError, ValueError):
        return PREDEFINITE


def vietato(categoria: str, nome: str) -> bool:
    return any(v.lower() in nome.lower() for v in regole()["divieti"].get(categoria, []))
