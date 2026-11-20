"""Musica: griglia di battiti, primo battito della battuta, frasi da 8 battute, vero inizio e vera fine,
piano della base e raffiche di B-roll a tempo.

Regole (protocollo §4, 14 nov 2026 CORSET): BPM misurato e confrontato con Artlist, tagli solo a inizio
frase/battuta, scarto massimo 0,05 battiti, base con vero inizio e vera chiusura.
"""
from __future__ import annotations

import numpy as np

from .connessione import ErroreToolkit
from .regole import regole


# ---------------------------------------------------------------- analisi audio solo numpy
# librosa non si installa sui Mac Intel con Python 3.14 (numba/llvmlite senza pacchetti pronti, 20 nov 2026):
# qui gli stessi passaggi (flusso spettrale, autocorrelazione, programmazione dinamica di Ellis) in numpy.

SR = 22050


def _stft_mag(x: np.ndarray, n_fft: int, hop: int) -> np.ndarray:
    if len(x) < n_fft:
        x = np.pad(x, (0, n_fft - len(x)))
    n = 1 + (len(x) - n_fft) // hop
    finestra = np.hanning(n_fft).astype(np.float32)
    out = np.empty((n_fft // 2 + 1, n), dtype=np.float32)
    blocco = 2048
    for i in range(0, n, blocco):
        idx = np.arange(i, min(n, i + blocco))
        frames = np.stack([x[j * hop:j * hop + n_fft] for j in idx]) * finestra
        out[:, idx] = np.abs(np.fft.rfft(frames, axis=1)).T
    return out


N_FFT_ONSET = 512  # finestra corta: con 2048 i battiti escono ~35 ms in anticipo (misurato il 20 nov 2026)


def inviluppo_onset(x: np.ndarray, sr: int = SR, hop: int = 128) -> np.ndarray:
    S = np.log1p(100 * _stft_mag(x, N_FFT_ONSET, hop))
    flusso = np.maximum(0, np.diff(S, axis=1)).sum(axis=0)
    flusso = np.r_[0, flusso]
    flusso -= np.convolve(flusso, np.ones(31) / 31, mode="same")  # toglie l'andamento lento
    flusso = np.maximum(flusso, 0)
    return flusso / (flusso.max() + 1e-9)


def stima_periodo(onset: np.ndarray, sr: int, hop: int, bpm_min=60, bpm_max=200) -> float:
    o = onset - onset.mean()
    n = len(o)
    f = np.fft.rfft(o, 2 * n)
    ac = np.fft.irfft(f * np.conj(f))[:n]
    fps = sr / hop
    lag_min, lag_max = int(fps * 60 / bpm_max), int(fps * 60 / bpm_min)
    lags = np.arange(lag_min, min(lag_max, n - 1))
    bpm = 60 * fps / lags
    peso = np.exp(-0.5 * (np.log2(bpm / 120.0) / 1.0) ** 2)  # preferenza morbida attorno a 120
    k = int(np.argmax(ac[lags] * peso))
    l = lags[k]
    if 0 < k < len(lags) - 1:  # interpolazione parabolica
        y0, y1, y2 = ac[l - 1], ac[l], ac[l + 1]
        d = 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2 + 1e-12)
        return float(l + d)
    return float(l)


def traccia_battiti(onset: np.ndarray, periodo: float, stretto: float = 100.0) -> np.ndarray:
    n = len(onset)
    punteggio = onset.copy()
    precedente = -np.ones(n, dtype=int)
    p = periodo
    for t in range(n):
        a, b = int(t - 2 * p), int(t - p / 2)
        if b <= 0:
            continue
        a = max(a, 0)
        prev = np.arange(a, b)
        costo = -stretto * np.log((t - prev) / p) ** 2
        cand = punteggio[prev] + costo
        k = int(np.argmax(cand))
        punteggio[t] = onset[t] + cand[k]
        precedente[t] = prev[k]
    # ultimo battito: il migliore nell'ultimo periodo
    coda = np.arange(max(0, n - int(p)), n)
    t = int(coda[np.argmax(punteggio[coda])])
    battiti = [t]
    while precedente[t] >= 0:
        t = precedente[t]
        battiti.append(t)
    return np.array(battiti[::-1])


def _per_battito(M: np.ndarray, frame_battiti: np.ndarray, agg=np.median) -> np.ndarray:
    bordi = np.r_[frame_battiti, M.shape[1]]
    return np.stack([agg(M[:, bordi[i]:max(bordi[i] + 1, bordi[i + 1])], axis=1) for i in range(len(frame_battiti))], axis=1)


def croma_e_timbro(x: np.ndarray, sr: int, battiti_s: np.ndarray):
    hop, n_fft = 512, 4096
    S = _stft_mag(x, n_fft, hop)
    freq = np.fft.rfftfreq(n_fft, 1 / sr)
    utili = (freq > 55) & (freq < 5000)
    classe = np.zeros(len(freq), dtype=int)
    classe[utili] = (np.round(12 * np.log2(freq[utili] / 440.0)) % 12).astype(int)
    croma = np.zeros((12, S.shape[1]), dtype=np.float32)
    for c in range(12):
        croma[c] = S[utili & (classe == c)].sum(axis=0)
    croma /= croma.max(axis=0, keepdims=True) + 1e-9
    bande = np.geomspace(40, sr / 2 - 1, 21)
    timbro = np.stack([np.log1p(S[(freq >= bande[i]) & (freq < bande[i + 1])].sum(axis=0)) for i in range(20)])
    fb = np.clip((battiti_s * sr / hop).astype(int), 0, S.shape[1] - 1)
    return _per_battito(croma, fb), _per_battito(timbro, fb, np.mean)


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
    from .audio import leggi_pcm
    y, sr = leggi_pcm(file, SR)
    if len(y) < sr * 8:
        raise ErroreToolkit("Brano troppo corto per misurare il tempo.")
    hop = 128  # ~6 ms: con 512 (23 ms) il BPM esce sbagliato di 1-3 (errore del 10 nov: 123 invece di 124)
    onset = inviluppo_onset(y, sr, hop)
    periodo_frame = stima_periodo(onset, sr, hop)
    frame_b = traccia_battiti(onset, periodo_frame)
    battiti = (frame_b * hop + N_FFT_ONSET / 2) / sr  # tempo al centro della finestra
    if len(battiti) < 16:
        raise ErroreToolkit("Troppi pochi battiti rilevati: brano non adatto o file sbagliato.")
    # periodo dalla retta che passa per tutti i battiti: molto più preciso della mediana degli intervalli
    periodo = float(np.polyfit(np.arange(len(battiti)), battiti, 1)[0])
    regolarita = float(np.std(np.diff(battiti)) / periodo)
    bpm_misurato = round(60.0 / periodo, 2)
    croma, timbro = croma_e_timbro(y, sr, battiti)
    cambio = np.r_[0, np.linalg.norm(np.diff(croma, axis=1), axis=0)]
    novita = np.r_[0, np.linalg.norm(np.diff(timbro, axis=1), axis=0)]
    g = griglia_da_battiti(battiti, cambio, novita)
    finestra = int(0.05 * sr)
    n_f = len(y) // finestra
    rms = np.sqrt((y[: n_f * finestra].reshape(n_f, finestra) ** 2).mean(axis=1))
    soglia = rms.max() * 10 ** (-40 / 20)
    sopra = np.where(rms > soglia)[0]
    inizio_vero = float(sopra[0] * finestra / sr) if len(sopra) else 0.0
    fine_vera = float((sopra[-1] + 1) * finestra / sr) if len(sopra) else float(len(y) / sr)
    confronto = "NON CONFERMATO"
    if bpm_artlist:
        for mult in (1, 2, 0.5):
            if abs(bpm_misurato * mult - bpm_artlist) <= 0.5:
                confronto = f"coincide con Artlist ({bpm_artlist})" + ("" if mult == 1 else f" (misurato ×{mult})")
                break
    return {
        "esito": "ok" if "coincide" in confronto else "bpm_non_confermato",
        "bpm_misurato": bpm_misurato, "bpm_artlist": bpm_artlist, "confronto_bpm": confronto,
        "durata_battito_s": round(periodo, 4),
        "irregolarita_battiti": round(regolarita, 3),
        "battiti_s": [round(float(x), 3) for x in battiti],
        "battute_s": [round(float(battiti[i]), 3) for i in g["indici_battute"]],
        "frasi_s": [round(float(battiti[i]), 3) for i in g["indici_frasi"]],
        "inizio_vero_s": round(inizio_vero, 3), "fine_vera_s": round(fine_vera, 3),
        "nota": "Se il BPM non è confermato non tagliare finché non è chiaro (protocollo). "
                "Battute e frasi sono una stima: controllarle all'ascolto sul primo taglio.",
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
