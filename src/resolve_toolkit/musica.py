"""Musica: griglia di battiti, primo battito della battuta, frasi da 8 battute, vero inizio e vera fine,
piano della base e raffiche di B-roll a tempo.

Regole (protocollo §4, 14 nov 2026 CORSET): BPM misurato e confrontato con Artlist, tagli solo a inizio
frase/battuta, scarto massimo 0,05 battiti, base con vero inizio e vera chiusura.
"""
from __future__ import annotations

import numpy as np

from .connessione import ErroreToolkit
from .regole import regole


def _librosa():
    try:
        import librosa  # type: ignore
        return librosa
    except ImportError:
        raise ErroreToolkit("librosa non installato nel toolkit (pip install librosa).")


def griglia_da_battiti(battiti_s: np.ndarray, cambio_armonico: np.ndarray, novita_timbrica: np.ndarray) -> dict:
    """Logica pura (testabile): fase del primo battito della battuta e inizio delle frasi."""
    r = regole()["musica"]
    bpb, fr = r["battiti_per_battuta"], r["battute_per_frase"]
    n = len(battiti_s)
    fasi = [float(np.mean(cambio_armonico[k::bpb])) if len(cambio_armonico[k::bpb]) else 0 for k in range(bpb)]
    fase = int(np.argmax(fasi))
    battute = list(range(fase, n, bpb))
    passo = bpb * fr
    candidati = []
    for off in range(fr):
        idx = list(range(fase + off * bpb, n, passo))
        candidati.append(float(np.mean(novita_timbrica[idx])) if idx else 0)
    offset = int(np.argmax(candidati))
    frasi = list(range(fase + offset * bpb, n, passo))
    return {"fase_primo_battito": fase, "indici_battute": battute, "indici_frasi": frasi,
            "forza_fasi": [round(x, 4) for x in fasi]}


def analizza_brano(file: str, bpm_artlist: float | None = None) -> dict:
    lb = _librosa()
    y, sr = lb.load(file, sr=22050, mono=True)
    hop_fine = 128  # ~6 ms: con 512 (23 ms) il BPM esce sbagliato di 1-3 (errore del 10 nov: 123 invece di 124)
    onset = lb.onset.onset_strength(y=y, sr=sr, hop_length=hop_fine)
    tempo, frames_fini = lb.beat.beat_track(onset_envelope=onset, sr=sr, hop_length=hop_fine, units="frames")
    tempo = float(np.atleast_1d(tempo)[0])
    battiti = lb.frames_to_time(frames_fini, sr=sr, hop_length=hop_fine)
    if len(battiti) < 16:
        raise ErroreToolkit("Troppi pochi battiti rilevati: brano non adatto o file sbagliato.")
    # periodo dalla retta che passa per tutti i battiti: molto più preciso della mediana degli intervalli
    periodo = float(np.polyfit(np.arange(len(battiti)), battiti, 1)[0])
    regolarita = float(np.std(np.diff(battiti)) / periodo)
    bpm_misurato = round(60.0 / periodo, 2)
    frames = lb.time_to_frames(battiti, sr=sr, hop_length=512)
    chroma = lb.util.sync(lb.feature.chroma_cqt(y=y, sr=sr), frames, aggregate=np.median)
    mfcc = lb.util.sync(lb.feature.mfcc(y=y, sr=sr, n_mfcc=13), frames, aggregate=np.mean)
    cambio = np.r_[0, np.linalg.norm(np.diff(chroma, axis=1), axis=0)][: len(battiti)]
    novita = np.r_[0, np.linalg.norm(np.diff(mfcc, axis=1), axis=0)][: len(battiti)]
    g = griglia_da_battiti(battiti, cambio, novita)
    rms = lb.feature.rms(y=y)[0]
    t_rms = lb.frames_to_time(np.arange(len(rms)), sr=sr)
    soglia = rms.max() * 10 ** (-40 / 20)
    sopra = np.where(rms > soglia)[0]
    inizio_vero = float(t_rms[sopra[0]]) if len(sopra) else 0.0
    fine_vera = float(t_rms[sopra[-1]]) if len(sopra) else float(len(y) / sr)
    confronto = "NON CONFERMATO"
    if bpm_artlist:
        for mult in (1, 2, 0.5):
            if abs(bpm_misurato * mult - bpm_artlist) <= 0.5:
                confronto = f"coincide con Artlist ({bpm_artlist})" + ("" if mult == 1 else f" (misurato ×{mult})")
                break
    return {
        "esito": "ok" if "coincide" in confronto else "bpm_non_confermato",
        "bpm_misurato": bpm_misurato, "bpm_librosa": round(tempo, 2), "bpm_artlist": bpm_artlist, "confronto_bpm": confronto,
        "durata_battito_s": round(periodo, 4),
        "irregolarita_battiti": round(regolarita, 3),
        "battiti_s": [round(float(x), 3) for x in battiti],
        "battute_s": [round(float(battiti[i]), 3) for i in g["indici_battute"]],
        "frasi_s": [round(float(battiti[i]), 3) for i in g["indici_frasi"]],
        "inizio_vero_s": round(inizio_vero, 3), "fine_vera_s": round(fine_vera, 3),
        "nota": "Se il BPM non è confermato non tagliare finché non è chiaro (protocollo).",
    }


def verifica_taglio(griglia: dict, tempo_s: float, livello: str = "frase") -> dict:
    punti = griglia["frasi_s"] if livello == "frase" else griglia["battute_s"] if livello == "battuta" else griglia["battiti_s"]
    if not punti:
        raise ErroreToolkit("Griglia vuota.")
    vicino = min(punti, key=lambda p: abs(p - tempo_s))
    scarto_s = tempo_s - vicino
    scarto_battiti = scarto_s / griglia["durata_battito_s"]
    ok = abs(scarto_battiti) <= regole()["musica"]["scarto_max_battiti"]
    return {"esito": "ok" if ok else "fuori_tempo", "punto_griglia_s": vicino, "scarto_ms": round(scarto_s * 1000, 1),
            "scarto_battiti": round(scarto_battiti, 3), "livello": livello}


def piano_base(griglia: dict, durata_reel_s: float) -> dict:
    """Vero inizio + vera chiusura. Se il brano è troppo lungo, UN salto da inizio frase a inizio frase."""
    inizio, fine = griglia["inizio_vero_s"], griglia["fine_vera_s"]
    if fine - inizio <= durata_reel_s + 0.05:
        return {"esito": "ok", "tratti_s": [[inizio, fine]], "durata_s": round(fine - inizio, 3), "salto": None}
    frasi = [f for f in griglia["frasi_s"] if inizio < f < fine]
    migliore = None
    for i, a in enumerate(frasi):
        for b in frasi[i + 1:]:
            durata = (a - inizio) + (fine - b)
            scarto = abs(durata - durata_reel_s)
            if migliore is None or scarto < migliore[0]:
                migliore = (scarto, a, b, durata)
    if migliore is None:
        raise ErroreToolkit("Nessuna coppia di inizi frase utile: scegliere con Diego un'altra base o un'altra durata.")
    _, a, b, durata = migliore
    return {"esito": "ok", "tratti_s": [[inizio, a], [b, fine]], "durata_s": round(durata, 3),
            "salto": {"da_s": a, "a_s": b, "tipo": "inizio frase -> inizio frase"},
            "scarto_da_durata_reel_s": round(durata - durata_reel_s, 3)}


def piano_raffica(griglia: dict, da_s: float, a_s: float, clip: list[dict], battiti_per_clip: int = 1) -> dict:
    """clip: [{"nome","orientamento","durata_s"}]. Una clip per gruppo di battiti, mai ripetute, mai orizzontali."""
    if battiti_per_clip > regole()["broll"]["battiti_max_per_clip"]:
        raise ErroreToolkit("B-roll troppo lunghi: le raffiche vanno a tempo, non clip lunghe.")
    nomi = [c["nome"] for c in clip]
    doppie = {n for n in nomi if nomi.count(n) > 1}
    if doppie:
        raise ErroreToolkit(f"Clip ripetute nello stesso reel: {sorted(doppie)}.")
    orizz = [c["nome"] for c in clip if c.get("orientamento") == "orizzontale"]
    if orizz:
        raise ErroreToolkit(f"Clip orizzontali: adattarle a pieno schermo verticale prima ({orizz}).")
    battiti = [b for b in griglia["battiti_s"] if da_s - 1e-6 <= b < a_s]
    punti = battiti[::battiti_per_clip] + [a_s]
    posti = len(punti) - 1
    if posti > len(clip):
        raise ErroreToolkit(f"Servono {posti} clip diverse, ne hai {len(clip)}: non ripeto clip.")
    piano = []
    for k in range(posti):
        durata = punti[k + 1] - punti[k]
        c = clip[k]
        if c.get("durata_s") is not None and c["durata_s"] < durata:
            raise ErroreToolkit(f"{c['nome']} è più corta del suo spazio ({durata:.2f} s).")
        piano.append({"clip": c["nome"], "inizio_s": round(punti[k], 3), "durata_s": round(durata, 3)})
    return {"esito": "ok", "piano": piano, "clip_usate": posti, "clip_avanzate": [c["nome"] for c in clip[posti:]]}
