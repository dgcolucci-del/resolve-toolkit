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


def inviluppo_db(file_audio: str):
    """Livello in dB ogni 10 ms (mono 16 kHz), da qualsiasi file con audio (wav, mov, mp4)."""
    import numpy as np
    r = subprocess.run([audio._ffmpeg(), "-v", "error", "-i", file_audio, "-vn", "-ac", "1", "-ar", "16000",
                        "-f", "s16le", "-"], capture_output=True, timeout=60)
    if r.returncode != 0 or not r.stdout:
        raise ErroreToolkit(f"Non riesco a leggere l'audio di {file_audio}.")
    a = np.frombuffer(r.stdout, np.int16).astype(np.float64) / 32768
    n = len(a) // 160
    return 20 * np.log10(np.sqrt((a[:n * 160].reshape(n, 160) ** 2).mean(axis=1)) + 1e-9), len(a) / 16000


def segmenti_calibrati(db, durata_s: float, r: dict | None = None) -> list[list[float]]:
    """Tratti di parlato con attacco e CODA intera (taglio calibrato sulle correzioni di Diego, 21 nov 2026)."""
    import numpy as np
    r = r or regole()["silenzi"]
    soglia, unisci = r["soglia_db"], r.get("pausa_min_s", 0.25)
    fondo = float(np.percentile(db, 10))
    sopra = np.where(db > soglia)[0]
    if not len(sopra):
        return []
    grezzi, ini, prec = [], sopra[0], sopra[0]
    for i in sopra[1:]:
        if i - prec > 15:
            grezzi.append([ini, prec + 1]); ini = i
        prec = i
    grezzi.append([ini, prec + 1])
    grezzi = [g for g in grezzi if g[1] - g[0] >= 5]
    if not grezzi:
        return []
    uniti = [grezzi[0]]
    for a, b in grezzi[1:]:
        if (a - uniti[-1][1]) / 100 < unisci:
            uniti[-1][1] = b
        else:
            uniti.append([a, b])
    tenuta = int(round(r.get("coda_tenuta_s", 0.08) * 100))
    limite = fondo + r.get("coda_sopra_fondo_db", 18.0)
    pre = int(round(r.get("pre_s", 0.06) * 100))
    extra = int(round(r.get("coda_extra_s", 0.0) * 100))
    out = []
    for k, (a, b) in enumerate(uniti):
        prossimo = uniti[k + 1][0] if k + 1 < len(uniti) else len(db)
        j = b
        while j < prossimo - tenuta and not (db[j:j + tenuta] < limite).all():
            j += 1
        j = min(j + extra, prossimo - 4 if k + 1 < len(uniti) else len(db))
        inizio = max(0, a - pre, out[-1][1] if out else 0)
        out.append([inizio, j])
    return [[round(a / 100, 3), round(min(b / 100, durata_s), 3)] for a, b in out]


def proposta_tagli(file_audio: str, soglia_db: float | None = None, durata_min_s: float | None = None,
                   fps: float = 25.0) -> dict:
    """Tratti da tenere misurati sull'audio vero, con le code delle parole intere (21 nov 2026).
    Accetta anche i file video (mp4/mov). Restituisce secondi e frame sorgente (fine esclusa)."""
    import math
    r = dict(regole()["silenzi"])
    if soglia_db:
        r["soglia_db"] = soglia_db
    db, durata = inviluppo_db(file_audio)
    seg = segmenti_calibrati(db, durata, r)
    frame = [[math.floor(a * fps), math.ceil(b * fps)] for a, b in seg]
    tenuto = sum(b - a for a, b in seg)
    return {"esito": "ok", "segmenti_s": seg, "segmenti_frame": frame, "fps": fps,
            "durata_originale_s": round(durata, 2), "durata_montata_s": round(tenuto, 2),
            "nota": "Code delle parole intere (calibrate sulle correzioni di Diego). Con più riprese della "
                    "stessa frase NON scegliere: timeline_alternative."}


def _testo_trascrizione(c) -> str | None:
    if hasattr(c, "GetTranscription"):
        try:
            t = c.GetTranscription()
            if isinstance(t, dict):
                if t.get("text"):
                    return t["text"]
                seg = t.get("segments") or []
                if seg:
                    return " ".join(x.get("text", "").strip() for x in seg)
            elif isinstance(t, str) and t:
                return t
        except Exception:
            pass
    v = c.GetClipProperty("Transcription")
    return v or None


def analizza_parlato(cartella_media_pool: str, cartella_wav: str = "", trascrivi: bool = True,
                     attesa_s: int = 50) -> dict:
    """UN comando per tutto il girato di un bin: tagli calibrati di ogni clip (secondi e frame) e testo
    dalla trascrizione AI di Resolve (21 nov 2026: tutto il bin in meno di 45 s, e ha sentito anche
    "per info www.simelgroup.it" che whisper aveva perso). I tempi delle parole di Resolve NON servono per
    tagliare (sbagliano di 5-20 frame): i tagli vengono dall'audio. Se la trascrizione non è pronta entro
    attesa_s risponde "in_corso": richiamare. cartella_wav (facoltativa) salva un wav unico per altri usi."""
    import numpy as np
    radice = progetto().GetMediaPool().GetRootFolder()

    def trova(folder, nome):
        if folder.GetName() == nome:
            return folder
        for sub in folder.GetSubFolderList() or []:
            f = trova(sub, nome)
            if f:
                return f
        return None
    bin_ = trova(radice, cartella_media_pool)
    if bin_ is None:
        raise ErroreToolkit(f"Bin '{cartella_media_pool}' non trovato nel media pool.")
    clip = sorted(bin_.GetClipList() or [], key=lambda c: c.GetName())
    testi, in_corso = {}, False
    if trascrivi:
        if any(_testo_trascrizione(c) is None for c in clip):
            if hasattr(bin_, "TranscribeAudio"):
                bin_.TranscribeAudio()
            t0 = time.time()
            while time.time() - t0 < attesa_s and any(_testo_trascrizione(c) is None for c in clip):
                time.sleep(3)
        testi = {c.GetName(): _testo_trascrizione(c) for c in clip}
        in_corso = any(v is None for v in testi.values())
    risultati, pezzi, mappa, cursore = [], [], [], 0.0
    for c in clip:
        path = c.GetClipProperty("File Path")
        if not path or not os.path.exists(path):
            risultati.append({"clip": c.GetName(), "errore": "file non trovato"})
            continue
        fps = float(c.GetClipProperty("FPS") or 25)
        r = proposta_tagli(path, fps=fps)
        risultati.append({"clip": c.GetName(), "durata_s": r["durata_originale_s"], "fps": fps,
                          "testo": testi.get(c.GetName()),
                          "segmenti_frame": r["segmenti_frame"], "segmenti_s": r["segmenti_s"]})
        if cartella_wav:
            g = subprocess.run([audio._ffmpeg(), "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "16000",
                                "-f", "s16le", "-"], capture_output=True, timeout=60).stdout
            a = np.frombuffer(g, np.int16)
            mappa.append({"clip": c.GetName(), "inizio_s": round(cursore, 3), "durata_s": round(len(a) / 16000, 3)})
            pezzi += [a, np.zeros(16000, np.int16)]
            cursore += len(a) / 16000 + 1.0
    out = {"esito": "in_corso" if in_corso else "ok", "clip": risultati,
           "prossimo_passo": ("trascrizione di Resolve ancora in corso: richiama tra 30 s" if in_corso else
                              "ordine delle frasi; riprese doppie in timeline_alternative (sceglie Diego); "
                              "poi monta_sequenza e fotogrammi_ai_tagli")}
    if cartella_wav and pezzi:
        import wave
        os.makedirs(cartella_wav, exist_ok=True)
        wav = os.path.join(cartella_wav, f"{cartella_media_pool}_tutte_16k.wav")
        with wave.open(wav, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes(np.concatenate(pezzi).tobytes())
        with open(wav.replace(".wav", "_mappa.json"), "w") as f:
            json.dump(mappa, f, indent=1)
        out.update({"wav_unico": wav, "mappa": mappa})
    return out


def monta_sequenza(sequenza: list[dict], nome_nuova_timeline: str, cartella: str = "") -> dict:
    """Timeline NUOVA con più clip in fila: sequenza = [{"nome_clip", "segmenti_frame": [[da, a], ...]}].
    Inserimenti verificati uno per uno (video+audio)."""
    p = progetto()
    nomi = {p.GetTimelineByIndex(i).GetName() for i in range(1, p.GetTimelineCount() + 1)}
    if nome_nuova_timeline in nomi:
        raise ErroreToolkit(f"Esiste già una timeline '{nome_nuova_timeline}'.")
    t = p.GetMediaPool().CreateEmptyTimeline(nome_nuova_timeline)
    if t is None:
        raise ErroreToolkit("Resolve non ha creato la timeline.")
    p.SetCurrentTimeline(t)
    posizione, inseriti = 0, []
    for voce in sequenza:
        for da, fino in voce["segmenti_frame"]:
            if fino <= da:
                continue
            imp = fotografia(nome_nuova_timeline)["impronta"]
            r = inserisci_clip(imp, voce["nome_clip"], int(da), int(fino), 1, posizione, "entrambi",
                               voce.get("cartella") or cartella or None, nome_nuova_timeline)
            inseriti.append({"clip": voce["nome_clip"], "sorgente": [da, fino], "posizione": posizione})
            posizione += r["durata"]
    return {"esito": "ok", "timeline": nome_nuova_timeline, "segmenti": len(inseriti), "durata_frame": posizione,
            "inseriti": inseriti, "prossimo_passo": "fotogrammi_ai_tagli, poi far vedere a Diego"}


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
