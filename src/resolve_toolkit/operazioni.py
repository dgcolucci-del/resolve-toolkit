"""Comandi che modificano Resolve. Ognuno: lucchetto -> azione -> verifica -> confronto."""
from __future__ import annotations

import os
import time

from . import calibrazione
from .connessione import ErroreToolkit, progetto, resolve, trova_timeline
from .stato import confronta, fotografia, verifica_lucchetto

ATTESA_PAGINA_S = 2.0


# ---------------------------------------------------------------- utilità

def _clip_media_pool(nome: str, cartella: str | None = None):
    """Cerca una clip nel media pool per nome esatto. Se è ambigua si ferma."""
    radice = progetto().GetMediaPool().GetRootFolder()
    trovate = []

    def visita(folder, percorso):
        for c in folder.GetClipList() or []:
            if c.GetName() == nome:
                trovate.append((percorso, c))
        for sub in folder.GetSubFolderList() or []:
            visita(sub, f"{percorso}/{sub.GetName()}")

    visita(radice, radice.GetName())
    if cartella:
        trovate = [t for t in trovate if t[0].endswith(cartella)]
    if not trovate:
        raise ErroreToolkit(f"Clip '{nome}' non trovata nel media pool" + (f" in '{cartella}'" if cartella else "") + ".")
    if len(trovate) > 1:
        raise ErroreToolkit(
            f"Ci sono {len(trovate)} clip '{nome}' in cartelle diverse: "
            + ", ".join(p for p, _ in trovate) + ". Indica la cartella (o chiedi a Diego)."
        )
    return trovate[0][1]


def frame_a_timecode(frame: int, fps: float) -> str:
    """Timecode non drop-frame. Per 29,97/59,94 drop-frame il risultato va verificato."""
    base = round(fps)
    f = frame % base
    s = frame // base
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}:{f:02d}"


def _apri_pagina_edit():
    r = resolve()
    if r.GetCurrentPage() != "edit":
        r.OpenPage("edit")
        time.sleep(ATTESA_PAGINA_S)


# ---------------------------------------------------------------- lettura

def elenca_timeline() -> list[dict]:
    p = progetto()
    out = []
    corrente = p.GetCurrentTimeline()
    for i in range(1, p.GetTimelineCount() + 1):
        t = p.GetTimelineByIndex(i)
        out.append({
            "nome": t.GetName(),
            "fps": t.GetSetting("timelineFrameRate"),
            "inizio": t.GetStartFrame(),
            "fine": t.GetEndFrame(),
            "corrente": corrente is not None and t.GetName() == corrente.GetName(),
        })
    return out


# ---------------------------------------------------------------- inserisci clip

def inserisci_clip(impronta: str, nome_clip: str, inizio_sorgente: int, fine_sorgente: int,
                   traccia: int, posizione: int, tipo: str = "video",
                   cartella: str | None = None, nome_timeline: str | None = None) -> dict:
    """posizione = frame RELATIVI dall'inizio della timeline (0 = primo frame).
    fine_sorgente = escluso (durata = fine - inizio). tipo: video | audio | entrambi."""
    if fine_sorgente <= inizio_sorgente:
        raise ErroreToolkit("fine_sorgente deve essere maggiore di inizio_sorgente.")
    if posizione < 0:
        raise ErroreToolkit("posizione è relativa all'inizio della timeline: non può essere negativa.")
    prima = verifica_lucchetto(impronta, nome_timeline)
    t = trova_timeline(nome_timeline)
    mp = progetto().GetMediaPool()
    mpi = _clip_media_pool(nome_clip, cartella)
    inizio_tl = t.GetStartFrame()
    atteso_inizio = inizio_tl + posizione
    attesa_durata = fine_sorgente - inizio_sorgente
    media_type = {"video": 1, "audio": 2}.get(tipo)

    def prova(conv):
        info = {
            "mediaPoolItem": mpi,
            "startFrame": inizio_sorgente,
            "endFrame": fine_sorgente if conv["end_frame_escluso"] else fine_sorgente - 1,
            "trackIndex": traccia,
            "recordFrame": atteso_inizio if conv["record_frame_assoluto"] else posizione,
        }
        if media_type:
            info["mediaType"] = media_type
        return mp.AppendToTimeline([info]) or []

    conv = calibrazione.leggi()
    nuovi = prova(conv)
    if not nuovi:
        raise ErroreToolkit("Resolve ha rifiutato l'inserimento (nessuna clip creata). Niente è cambiato.")

    def misura(items):
        it = items[0]
        return it.GetStart(), it.GetDuration()

    inizio_reale, durata_reale = misura(nuovi)
    correzioni = {}
    if inizio_reale != atteso_inizio and abs(inizio_reale - atteso_inizio) == inizio_tl:
        correzioni["record_frame_assoluto"] = not conv["record_frame_assoluto"]
    if durata_reale != attesa_durata and abs(durata_reale - attesa_durata) == 1:
        correzioni["end_frame_escluso"] = not conv["end_frame_escluso"]

    if (inizio_reale, durata_reale) != (atteso_inizio, attesa_durata):
        t.DeleteClips(nuovi, False)
        if not correzioni:
            raise ErroreToolkit(
                f"Clip finita nel posto sbagliato (inizio {inizio_reale} invece di {atteso_inizio}, "
                f"durata {durata_reale} invece di {attesa_durata}) e scarto non riconosciuto: "
                "inserimento annullato."
            )
        conv.update(correzioni)
        nuovi = prova(conv)
        if not nuovi:
            raise ErroreToolkit("Secondo tentativo rifiutato da Resolve. Inserimento annullato.")
        inizio_reale, durata_reale = misura(nuovi)
        if (inizio_reale, durata_reale) != (atteso_inizio, attesa_durata):
            t.DeleteClips(nuovi, False)
            raise ErroreToolkit(
                f"Anche dopo la correzione la clip non è giusta (inizio {inizio_reale}, durata {durata_reale}). "
                "Annullato, timeline come prima."
            )
        for k, v in correzioni.items():
            calibrazione.salva(k, v)

    dopo = fotografia(nome_timeline)
    diff = confronta(prima, dopo)
    if diff["sparite"] or diff["spostate"]:
        raise ErroreToolkit(f"ATTENZIONE: l'inserimento ha toccato altre clip: {diff}. Fermati e avvisa Diego.")
    return {
        "esito": "ok",
        "inizio": inizio_reale,
        "inizio_relativo": inizio_reale - inizio_tl,
        "durata": durata_reale,
        "clip_create": len(nuovi),
        "calibrazione_corretta": correzioni or None,
        "confronto": diff,
        "impronta_nuova": dopo["impronta"],
    }


# ---------------------------------------------------------------- backup

def backup_timeline(impronta: str, nome_timeline: str | None = None) -> dict:
    """Duplica la timeline come backup. Si continua a lavorare sull'ORIGINALE:
    sulle copie via API le comp Fusion non sono modificabili (16 nov 2026)."""
    verifica_lucchetto(impronta, nome_timeline)
    t = trova_timeline(nome_timeline)
    esistenti = {x["nome"] for x in elenca_timeline()}
    n = 1
    while f"BACKUP {n:02d} - {t.GetName()}" in esistenti:
        n += 1
    nome = f"BACKUP {n:02d} - {t.GetName()}"
    copia = t.DuplicateTimeline(nome)
    if copia is None:
        raise ErroreToolkit("Duplicazione rifiutata da Resolve.")
    progetto().SetCurrentTimeline(t)  # resto sull'originale
    return {"esito": "ok", "backup": nome, "timeline_di_lavoro": t.GetName()}


# ---------------------------------------------------------------- Fusion

def salva_fusion(impronta: str, cartella_comp: str, traccia: int = 1,
                 nome_timeline: str | None = None) -> dict:
    """Le modifiche Fusion fatte via API non vengono renderizzate finché non si fa
    export + import della comp per ogni clip (16 nov 2026)."""
    verifica_lucchetto(impronta, nome_timeline)
    t = trova_timeline(nome_timeline)
    os.makedirs(cartella_comp, exist_ok=True)
    fatte, errori = [], []
    for i, item in enumerate(t.GetItemListInTrack("video", traccia) or [], start=1):
        n = item.GetFusionCompCount() or 0
        for c in range(1, n + 1):
            path = os.path.join(cartella_comp, f"V{traccia}_{i:03d}_{c}_{item.GetName()}.comp")
            if not item.ExportFusionComp(path, c):
                errori.append(f"export {item.GetName()} comp {c}")
                continue
            if not item.ImportFusionComp(path):
                errori.append(f"import {item.GetName()} comp {c}")
                continue
            fatte.append(f"{item.GetName()} comp {c}")
    return {
        "esito": "ok" if not errori else "errori",
        "comp_salvate": fatte,
        "errori": errori,
        "prossimo_passo": "render di prova breve (render_sicuro con mark_in/mark_out) e controllo dei frame",
    }


# ---------------------------------------------------------------- audio in timeline

def isolamento_voce(impronta: str, traccia: int, attivo: bool = True, quantita: int = 100,
                    nome_timeline: str | None = None) -> dict:
    verifica_lucchetto(impronta, nome_timeline)
    t = trova_timeline(nome_timeline)
    ok = t.SetVoiceIsolationState(traccia, {"isEnabled": attivo, "amount": quantita})
    letto = t.GetVoiceIsolationState(traccia) if hasattr(t, "GetVoiceIsolationState") else None
    if not ok:
        raise ErroreToolkit("Resolve ha rifiutato l'isolamento voce.")
    return {"esito": "ok", "traccia_audio": traccia, "stato_riletto": letto}


# ---------------------------------------------------------------- fotogrammi ai tagli

def fotogrammi_ai_tagli(cartella_uscita: str, traccia: int = 1, nome_timeline: str | None = None) -> dict:
    """Esporta l'ultimo frame prima e il primo dopo ogni taglio (regola 16 nov 2026)."""
    _apri_pagina_edit()
    t = trova_timeline(nome_timeline)
    p = progetto()
    p.SetCurrentTimeline(t)
    fps = float(t.GetSetting("timelineFrameRate"))
    os.makedirs(cartella_uscita, exist_ok=True)
    items = t.GetItemListInTrack("video", traccia) or []
    file = []
    for a, b in zip(items, items[1:]):
        for etichetta, frame in (("prima", a.GetEnd() - 1), ("dopo", b.GetStart())):
            tc = frame_a_timecode(frame, fps)
            if not t.SetCurrentTimecode(tc):
                raise ErroreToolkit(f"Non riesco a portare la testina a {tc}.")
            path = os.path.join(cartella_uscita, f"taglio_{len(file)//2 + 1:02d}_{etichetta}_{frame}.png")
            if not p.ExportCurrentFrameAsStill(path):
                raise ErroreToolkit(f"Export del frame {tc} fallito.")
            file.append(path)
    return {"esito": "ok", "tagli": len(items) - 1 if items else 0, "file": file,
            "da_fare": "guardare TUTTE le immagini prima di dire che i tagli sono a posto"}


# ---------------------------------------------------------------- render

def render_sicuro(cartella: str, nome_file: str, conferma_diego: str, preset: str = "H.264 Master",
                  bitrate: int = 100000, mark_in: int | None = None, mark_out: int | None = None,
                  solo_audio: bool = False, attesa_max_s: int = 1800,
                  nome_timeline: str | None = None) -> dict:
    """Export solo su richiesta esplicita di Diego: conferma_diego = le sue parole.
    Sequenza verificata (17 nov 2026): pagina Edit + 2 s, coda svuotata, job nuovo;
    se StartRendering fallisce, UN solo job nuovo. Mai il pulsante Render della coda."""
    if not conferma_diego or not conferma_diego.strip():
        raise ErroreToolkit("Export solo su richiesta esplicita di Diego: riporta le sue parole in conferma_diego.")
    return _render(cartella, nome_file, preset, bitrate, mark_in, mark_out, solo_audio, attesa_max_s, nome_timeline)


CARTELLA_PROVE = os.path.expanduser("~/Library/Application Support/ResolveToolkit/temp/render_prova")


def render_di_prova(mark_in: int, mark_out: int, solo_audio: bool = False, nome_timeline: str | None = None) -> dict:
    """Render di CONTROLLO (non una consegna): tratto breve in 1080p nella cartella temporanea del toolkit.
    Serve a verificare effetti Fusion, grafiche, tagli e audio della timeline attuale."""
    if mark_out <= mark_in:
        raise ErroreToolkit("mark_out deve essere dopo mark_in.")
    nome = f"prova_{time.strftime('%Y%m%d-%H%M%S')}"
    r = _render(CARTELLA_PROVE, nome, "H.264 Master", 40000, mark_in, mark_out, solo_audio, 900, nome_timeline)
    from .lavoro import registra_file
    registra_file(r["file"], "render di prova")
    return r


def _render(cartella, nome_file, preset, bitrate, mark_in, mark_out, solo_audio, attesa_max_s, nome_timeline):
    p = progetto()
    t = trova_timeline(nome_timeline)
    p.SetCurrentTimeline(t)
    _apri_pagina_edit()
    p.DeleteAllRenderJobs()
    if not p.LoadRenderPreset(preset):
        raise ErroreToolkit(f"Preset '{preset}' non trovato.")
    impostazioni = {"TargetDir": cartella, "CustomName": nome_file, "SelectAllFrames": True}
    if solo_audio:
        p.SetCurrentRenderFormatAndCodec("mov", "H264")  # formato contenitore; il video viene escluso
        impostazioni.update({"ExportVideo": False, "ExportAudio": True, "AudioCodec": "lpcm"})
    else:
        impostazioni["VideoQuality"] = int(bitrate)  # "Best" viene rifiutato (15 nov 2026)
    if mark_in is not None and mark_out is not None:
        inizio = t.GetStartFrame()
        impostazioni.update({"SelectAllFrames": False, "MarkIn": inizio + mark_in, "MarkOut": inizio + mark_out})
    if not p.SetRenderSettings(impostazioni):
        raise ErroreToolkit(f"Impostazioni di render rifiutate: {impostazioni}")

    job = p.AddRenderJob()
    partito = bool(job) and p.StartRendering([job])
    tentativi = 1
    if not partito:
        p.DeleteAllRenderJobs()
        job = p.AddRenderJob()
        partito = bool(job) and p.StartRendering([job])
        tentativi = 2
    if not partito:
        raise ErroreToolkit("Il render non parte nemmeno con un job nuovo. Non premere Render nella coda: avvisa Diego.")

    t0 = time.time()
    while p.IsRenderingInProgress():
        if time.time() - t0 > attesa_max_s:
            raise ErroreToolkit(f"Render ancora in corso dopo {attesa_max_s} s.")
        time.sleep(2)
    stato = p.GetRenderJobStatus(job) or {}
    estensione = ".mov" if solo_audio else ""
    candidati = [f for f in os.listdir(cartella) if f.startswith(nome_file)] if os.path.isdir(cartella) else []
    if stato.get("JobStatus") != "Complete" or not candidati:
        raise ErroreToolkit(f"Render non completato: stato {stato}, file trovati {candidati}.")
    file = os.path.join(cartella, sorted(candidati)[-1])
    return {"esito": "ok", "file": file, "byte": os.path.getsize(file), "tentativi": tentativi,
            "stato": stato, "nota": estensione and "solo audio in mov/lpcm",
            "prossimo_passo": "controllo_consegna sul file (numeri veri, non le impostazioni)"}
