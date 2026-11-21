"""Comandi che modificano Resolve. Ognuno: lucchetto -> azione -> verifica -> confronto."""
from __future__ import annotations

import os
import time

from . import audio, calibrazione
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


def _apri_pagina_edit(forza: bool = False):
    """Il render e l'export dei frame falliscono se Resolve è in Color/Deliver (20 nov 2026):
    si passa sempre da Edit e si aspetta che la pagina sia davvero cambiata."""
    r = resolve()
    if forza or r.GetCurrentPage() != "edit":
        r.OpenPage("edit")
        for _ in range(10):
            time.sleep(ATTESA_PAGINA_S / 2)
            if r.GetCurrentPage() == "edit":
                break
        time.sleep(ATTESA_PAGINA_S / 2)


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
    try:
        lunghezza = int(str(mpi.GetClipProperty("Frames") or "0").strip() or 0)
    except (ValueError, TypeError):
        lunghezza = 0
    if lunghezza and fine_sorgente > lunghezza:
        fine_sorgente = lunghezza  # 20 nov 2026: overlay da 1007 frame rifiutato con fine oltre la clip
    if fine_sorgente <= inizio_sorgente:
        raise ErroreToolkit(f"La clip dura {lunghezza} frame: inizio_sorgente {inizio_sorgente} è oltre la fine.")
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
    rifiuto_superato = None
    _apri_pagina_edit()
    nuovi = prova(conv)
    if not nuovi:
        # 20 nov 2026: rifiuto con endFrame = lunghezza clip e recordFrame assoluto. Si provano le altre
        # convenzioni una alla volta; la posizione viene comunque verificata subito dopo.
        for alt in ({"end_frame_escluso": not conv["end_frame_escluso"]},
                    {"record_frame_assoluto": not conv["record_frame_assoluto"]},
                    {"end_frame_escluso": not conv["end_frame_escluso"],
                     "record_frame_assoluto": not conv["record_frame_assoluto"]}):
            nuovi = prova({**conv, **alt})
            if nuovi:
                conv = {**conv, **alt}
                rifiuto_superato = alt
                break
    if not nuovi:
        raise ErroreToolkit("Resolve ha rifiutato l'inserimento con tutte le convenzioni (nessuna clip creata). "
                            "Controlla che la traccia esista e non sia bloccata. Niente è cambiato.")

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
    elif rifiuto_superato:
        for k, v in rifiuto_superato.items():
            calibrazione.salva(k, v)
        correzioni = rifiuto_superato

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


def sostituisci_clip(impronta: str, id_clip: str, nome_clip_nuova: str, cartella: str | None = None,
                     nome_timeline: str | None = None) -> dict:
    """Sostituisce una clip (es. overlay sottotitoli v02 → v03) nella STESSA traccia e posizione.
    Durata: quella della clip nuova, ma mai oltre la vecchia se dopo c'è un'altra clip sulla traccia."""
    t = trova_timeline(nome_timeline)
    verifica_lucchetto(impronta, nome_timeline)
    trovata = None
    for tipo in ("video", "audio"):
        for tr in range(1, (t.GetTrackCount(tipo) or 0) + 1):
            items = t.GetItemListInTrack(tipo, tr) or []
            for k, it in enumerate(items):
                if it.GetUniqueId() == id_clip:
                    successiva = items[k + 1].GetStart() if k + 1 < len(items) else None
                    trovata = (tipo, tr, it, successiva)
    if not trovata:
        raise ErroreToolkit(f"Clip con id {id_clip} non trovata nella timeline.")
    tipo, tr, vecchia, successiva = trovata
    nome_vecchia, inizio = vecchia.GetName(), vecchia.GetStart()
    posizione = inizio - t.GetStartFrame()
    mpi = _clip_media_pool(nome_clip_nuova, cartella)
    try:
        lunghezza = int(str(mpi.GetClipProperty("Frames") or "0").strip() or 0)
    except (ValueError, TypeError):
        lunghezza = 0
    if not lunghezza:
        raise ErroreToolkit(f"Non leggo la durata di '{nome_clip_nuova}'.")
    if successiva is not None:
        lunghezza = min(lunghezza, successiva - inizio)
    if not t.DeleteClips([vecchia], False):
        raise ErroreToolkit("Resolve non ha tolto la clip vecchia: niente è cambiato.")
    dopo_delete = fotografia(nome_timeline)["impronta"]
    try:
        r = inserisci_clip(dopo_delete, nome_clip_nuova, 0, lunghezza, tr, posizione,
                           tipo="video" if tipo == "video" else "audio", cartella=cartella,
                           nome_timeline=nome_timeline)
    except ErroreToolkit as e:
        raise ErroreToolkit(f"Clip vecchia '{nome_vecchia}' TOLTA ma la nuova non è entrata: {e}. "
                            f"Rimettila con inserisci_clip in traccia {tr}, posizione {posizione}. Avvisa Diego.")
    r.update({"sostituita": nome_vecchia, "con": nome_clip_nuova, "traccia": tr,
              "nota": "La clip vecchia resta nel media pool: si cancella solo col via di Diego."})
    return r


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

ATTESA_IN_CHIAMATA_S = 55  # il ponte col Mac chiude a 80 s: oltre si torna "in_corso" e si usa stato_render


def render_sicuro(cartella: str, nome_file: str, conferma_diego: str, preset: str = "H.264 Master",
                  bitrate: int = 100000, mark_in: int | None = None, mark_out: int | None = None,
                  solo_audio: bool = False, formato: str = "", codec: str = "",
                  larghezza: int = 0, altezza: int = 0, nome_timeline: str | None = None) -> dict:
    """Export solo su richiesta esplicita di Diego: conferma_diego = le sue parole.
    formato/codec (es. mp4 + H264 o H265), larghezza/altezza (es. 2160x3840 per il 4K verticale).
    Se il render dura più di ~55 s risponde "in_corso": poi stato_render(job_id)."""
    if not conferma_diego or not conferma_diego.strip():
        raise ErroreToolkit("Export solo su richiesta esplicita di Diego: riporta le sue parole in conferma_diego.")
    return _render(cartella, nome_file, preset, bitrate, mark_in, mark_out, solo_audio, nome_timeline,
                   formato=formato, codec=codec, larghezza=larghezza, altezza=altezza)


CARTELLA_PROVE = os.path.expanduser("~/Library/Application Support/ResolveToolkit/temp/render_prova")


def render_di_prova(mark_in: int, mark_out: int, solo_audio: bool = False, nome_timeline: str | None = None) -> dict:
    """Render di CONTROLLO (non una consegna): tratto in 1080p nella cartella temporanea del toolkit."""
    if mark_out <= mark_in:
        raise ErroreToolkit("mark_out deve essere dopo mark_in.")
    nome = f"prova_{time.strftime('%Y%m%d-%H%M%S')}"
    r = _render(CARTELLA_PROVE, nome, "H.264 Master", 40000, mark_in, mark_out, solo_audio, nome_timeline,
                larghezza=1080, altezza=1920)
    if r.get("file"):
        from .lavoro import registra_file
        registra_file(r["file"], "render di prova")
    return r


def _avvia(p):
    job = p.AddRenderJob()
    return job, bool(job) and p.StartRendering([job])


def _render(cartella, nome_file, preset, bitrate, mark_in, mark_out, solo_audio, nome_timeline,
            formato="", codec="", larghezza=0, altezza=0):
    p = progetto()
    t = trova_timeline(nome_timeline)
    p.SetCurrentTimeline(t)
    _apri_pagina_edit(forza=True)
    p.DeleteAllRenderJobs()
    if not p.LoadRenderPreset(preset):
        raise ErroreToolkit(f"Preset '{preset}' non trovato.")
    if solo_audio:
        p.SetCurrentRenderFormatAndCodec("mov", "H264")  # contenitore; il video viene escluso
    elif formato or codec:
        if not p.SetCurrentRenderFormatAndCodec(formato or "mp4", codec or "H264"):
            raise ErroreToolkit(f"Formato/codec rifiutati: {formato or 'mp4'} / {codec or 'H264'}.")
    impostazioni = {"TargetDir": cartella, "CustomName": nome_file, "SelectAllFrames": True}
    if solo_audio:
        impostazioni.update({"ExportVideo": False, "ExportAudio": True, "AudioCodec": "lpcm"})
    else:
        # Sempre esplicito: il Deliver ricorda "Export Video" spento dall'ultimo render audio (20 nov 2026)
        impostazioni.update({"ExportVideo": True, "ExportAudio": True,
                             "VideoQuality": int(bitrate)})  # "Best" viene rifiutato (15 nov 2026)
        if (formato or "").lower() == "mp4":
            impostazioni["AudioCodec"] = "aac"
    if larghezza and altezza:
        impostazioni.update({"FormatWidth": int(larghezza), "FormatHeight": int(altezza)})
    if mark_in is not None and mark_out is not None:
        inizio = t.GetStartFrame()
        impostazioni.update({"SelectAllFrames": False, "MarkIn": inizio + mark_in, "MarkOut": inizio + mark_out})
    if not p.SetRenderSettings(impostazioni):
        raise ErroreToolkit(f"Impostazioni di render rifiutate: {impostazioni}")

    job, partito = _avvia(p)
    tentativi = 1
    if not partito:
        # 20 nov 2026: dopo la pagina Color il primo StartRendering fallisce; Edit di nuovo + job nuovo
        p.DeleteAllRenderJobs()
        _apri_pagina_edit(forza=True)
        time.sleep(1.5)
        job, partito = _avvia(p)
        tentativi = 2
    if not partito:
        raise ErroreToolkit("Il render non parte nemmeno con un job nuovo. Non premere Render nella coda: avvisa Diego.")

    lavoro_info = {"job_id": job, "cartella": cartella, "nome_file": nome_file, "solo_audio": solo_audio,
                   "atteso": {"larghezza": larghezza or None, "altezza": altezza or None}}
    _salva_job(lavoro_info)
    t0 = time.time()
    while p.IsRenderingInProgress():
        if time.time() - t0 > ATTESA_IN_CHIAMATA_S:
            st = p.GetRenderJobStatus(job) or {}
            return {"esito": "in_corso", "job_id": job, "tentativi": tentativi,
                    "percentuale": st.get("CompletionPercentage"),
                    "mancano_s": round((st.get("EstimatedTimeRemainingInMs") or 0) / 1000),
                    "prossimo_passo": "stato_render(job_id) tra qualche minuto; non avviare un altro render"}
        time.sleep(2)
    return stato_render(job, tentativi)


def _file_jobs():
    return os.path.expanduser("~/Library/Application Support/ResolveToolkit/render_jobs.json")


def _salva_job(info):
    import json
    try:
        with open(_file_jobs()) as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d[info["job_id"]] = info
    os.makedirs(os.path.dirname(_file_jobs()), exist_ok=True)
    with open(_file_jobs(), "w") as f:
        json.dump(d, f)


def stato_render(job_id: str, tentativi: int | None = None) -> dict:
    """Stato di un render avviato da render_sicuro/render_di_prova; a fine render trova il file."""
    import json
    p = progetto()
    try:
        with open(_file_jobs()) as f:
            info = json.load(f).get(job_id)
    except (OSError, ValueError):
        info = None
    if not info:
        raise ErroreToolkit(f"Job {job_id} non avviato dal toolkit.")
    st = p.GetRenderJobStatus(job_id) or {}
    if st.get("JobStatus") in ("Rendering", "Ready") or p.IsRenderingInProgress():
        return {"esito": "in_corso", "job_id": job_id, "percentuale": st.get("CompletionPercentage"),
                "mancano_s": round((st.get("EstimatedTimeRemainingInMs") or 0) / 1000)}
    cartella, nome_file = info["cartella"], info["nome_file"]
    candidati = [f for f in os.listdir(cartella) if f.startswith(nome_file)] if os.path.isdir(cartella) else []
    if st.get("JobStatus") != "Complete" or not candidati:
        raise ErroreToolkit(f"Render non completato: stato {st}, file trovati {candidati}.")
    file = os.path.join(cartella, sorted(candidati, key=lambda f: os.path.getmtime(os.path.join(cartella, f)))[-1])
    if not info.get("solo_audio"):
        # 21 nov 2026: un render "Complete" uscito SOLO AUDIO (Export Video rimasto spento nel Deliver)
        try:
            fmt = audio.formato(file)
        except Exception:  # noqa: BLE001
            fmt = {}
        if not fmt.get("codec_video"):
            raise ErroreToolkit(f"Render finito ma {os.path.basename(file)} NON ha la traccia video: nel Deliver "
                                "'Export Video' è rimasto spento. Spuntarlo (pagina Deliver) e rifare il render.")
    out = {"esito": "ok", "file": file, "byte": os.path.getsize(file), "stato": st,
           "nota": "solo audio in mov/lpcm" if info.get("solo_audio") else "",
           "prossimo_passo": "controllo_consegna sul file (numeri veri, non le impostazioni)"}
    if tentativi:
        out["tentativi"] = tentativi
    return out
