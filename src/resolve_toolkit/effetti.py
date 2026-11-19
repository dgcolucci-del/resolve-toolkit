"""Effetti su clip e transizioni costruiti in Fusion, con parametri scelti per ogni reel.

Le transizioni native di Resolve NON si inseriscono via API: qui si costruiscono come effetti Fusion
sulle due clip ai lati del taglio. Ogni effetto: costruzione -> export+import comp (sennò non si
renderizza, 16 nov) -> render di prova -> controllo frame.
"""
from __future__ import annotations

import math
import os
import time

from .connessione import ErroreToolkit, progetto, trova_timeline
from .lavoro import registra_file
from .regole import regole, vietato
from .stato import verifica_lucchetto

CARTELLA_COMP = os.path.expanduser("~/Library/Application Support/ResolveToolkit/comp")


# ---------------------------------------------------------------- comp

def comp_della_clip(t, traccia: int, indice: int):
    items = t.GetItemListInTrack("video", traccia) or []
    if not 1 <= indice <= len(items):
        raise ErroreToolkit(f"Clip {indice} non esiste sulla traccia video {traccia} ({len(items)} clip).")
    item = items[indice - 1]
    comp = item.GetFusionCompByIndex(1) if (item.GetFusionCompCount() or 0) > 0 else item.AddFusionComp()
    if comp is None:
        raise ErroreToolkit(f"Non riesco ad aprire o creare la comp Fusion di {item.GetName()}.")
    return item, comp


def _strumento(comp, nome):
    s = comp.FindTool(nome)
    if s is None:
        raise ErroreToolkit(f"Nella comp manca {nome}.")
    return s


def inserisci_prima_di_mediaout(comp, tool, ingresso: str = "Input"):
    """Mette tool tra l'ultimo nodo della catena e MediaOut1, senza perdere gli effetti già presenti."""
    out = _strumento(comp, "MediaOut1")
    precedente = None
    try:
        conn = out.Input.GetConnectedOutput()
        precedente = conn.GetTool() if conn else None
    except AttributeError:
        precedente = None
    precedente = precedente or _strumento(comp, "MediaIn1")
    tool.ConnectInput(ingresso, precedente)
    out.ConnectInput("Input", tool)
    return tool


def inizio_comp(comp) -> int:
    """Primo frame della comp: le chiavi si danno in frame relativi alla clip e si sommano a questo."""
    attr = comp.GetAttrs() or {}
    return int(attr.get("COMPN_RenderStart", attr.get("COMPN_GlobalStart", 0)) or 0)


def chiave(tool, ingresso: str, valori: list[tuple[int, object]], base: int) -> None:
    tool.AddModifier(ingresso, "BezierSpline")
    for frame, v in valori:
        tool.SetInput(ingresso, v, base + frame)


def salva_comp_clip(item) -> list[str]:
    os.makedirs(CARTELLA_COMP, exist_ok=True)
    salvate = []
    for c in range(1, (item.GetFusionCompCount() or 0) + 1):
        path = os.path.join(CARTELLA_COMP, f"{item.GetUniqueId()}_{c}_{time.strftime('%H%M%S')}.comp")
        if not item.ExportFusionComp(path, c) or not item.ImportFusionComp(path):
            raise ErroreToolkit(f"Export/import comp {c} di {item.GetName()} fallito: l'effetto non verrebbe renderizzato.")
        registra_file(path, "comp Fusion salvata")
        salvate.append(path)
    return salvate


# ---------------------------------------------------------------- punch-in sicuro

def scala_massima(visi: list[dict], centro_px: tuple[float, float], H: int, W: int, margine_px: float) -> float:
    """Zoom massimo attorno a centro che lascia la testa intera (testa ≈ viso + 35% sopra)."""
    cx, cy = centro_px
    limite = 8.0
    for v in visi:
        testa_y = v["y"] - 0.35 * v["h"]
        dy = cy - testa_y
        if dy > 0:
            limite = min(limite, (cy - margine_px) / dy)
        for x in (v["x"], v["x"] + v["w"]):
            if x > cx:
                limite = min(limite, (W - cx) / (x - cx))
            elif x < cx:
                limite = min(limite, cx / (cx - x))
    return max(1.0, round(limite, 3))


# ---------------------------------------------------------------- effetti

def _controlla_nome(nome: str):
    if vietato("effetti", nome):
        raise ErroreToolkit(f"'{nome}' è vietato da Diego (12 nov 2026: l'effetto onda/Drop Warp non gli piace).")


def applica_effetto(impronta: str, indice_clip: int, effetto: str, parametri: dict, traccia: int = 1,
                    visi: list[dict] | None = None, nome_timeline: str | None = None) -> dict:
    """effetto: punch_in | shake | flash | whip | blur | glow | speed_ramp.
    I frame nei parametri sono relativi all'inizio della clip."""
    _controlla_nome(effetto)
    _controlla_nome(str(parametri))
    verifica_lucchetto(impronta, nome_timeline)
    t = trova_timeline(nome_timeline)
    item, comp = comp_della_clip(t, traccia, indice_clip)
    base = inizio_comp(comp)
    f = regole()["formato"]
    W, H = f["larghezza"], f["altezza"]
    da, a = int(parametri.get("da", 0)), int(parametri.get("a", item.GetDuration() - 1))
    if not 0 <= da < a <= item.GetDuration():
        raise ErroreToolkit(f"Intervallo {da}-{a} fuori dalla clip (durata {item.GetDuration()}).")

    if effetto == "punch_in":
        scala = float(parametri["scala"])
        centro = parametri.get("centro_px", [W / 2, H / 2])
        if visi is None:
            raise ErroreToolkit("Per il punch-in servono i visi della clip (da mappa_zone): il margine sopra la testa si calcola PRIMA.")
        massimo = scala_massima([v for v in visi if v.get("tipo", "viso") == "viso"], tuple(centro), H, W,
                                regole()["punch_in"]["margine_testa_px"])
        if scala > massimo:
            raise ErroreToolkit(f"Zoom {scala} taglia la testa: massimo {massimo} con questo centro.")
        tool = inserisci_prima_di_mediaout(comp, comp.AddTool("Transform"))
        tool.SetInput("Pivot", {1: centro[0] / W, 2: 1 - centro[1] / H})
        tool.SetInput("Center", {1: centro[0] / W, 2: 1 - centro[1] / H})
        chiave(tool, "Size", [(da, 1.0), (a, scala)], base)
        dettaglio = {"scala": scala, "scala_massima": massimo}
    elif effetto == "shake":
        amp = float(parametri.get("ampiezza_px", 12))
        tool = inserisci_prima_di_mediaout(comp, comp.AddTool("Transform"))
        tool.SetInput("Size", float(parametri.get("scala_copertura", 1.05)))  # niente bordi neri
        punti = []
        for k, fr in enumerate(range(da, a + 1, max(1, int(parametri.get("passo", 2))))):
            ang = k * 2.399
            punti.append((fr, {1: 0.5 + amp * math.cos(ang) / W, 2: 0.5 + amp * math.sin(ang * 1.3) / H}))
        punti.append((a, {1: 0.5, 2: 0.5}))
        chiave(tool, "Center", punti, base)
        dettaglio = {"ampiezza_px": amp}
    elif effetto == "flash":
        tool = inserisci_prima_di_mediaout(comp, comp.AddTool("BrightnessContrast"))
        picco = float(parametri.get("gain", 3.0))
        meta = (da + a) // 2
        chiave(tool, "Gain", [(da, 1.0), (meta, picco), (a, 1.0)], base)
        dettaglio = {"gain_picco": picco}
    elif effetto == "whip":
        direzione = parametri.get("direzione", "sinistra")
        segno = -1 if direzione == "sinistra" else 1
        blur = inserisci_prima_di_mediaout(comp, comp.AddTool("DirectionalBlur"))
        chiave(blur, "Length", [(da, 0.0), ((da + a) // 2, float(parametri.get("blur", 0.15))), (a, 0.0)], base)
        tr = inserisci_prima_di_mediaout(comp, comp.AddTool("Transform"))
        chiave(tr, "Center", [(da, {1: 0.5, 2: 0.5}), (a, {1: 0.5 + segno * float(parametri.get("spostamento", 0.3)), 2: 0.5})], base)
        dettaglio = {"direzione": direzione}
    elif effetto == "blur":
        tool = inserisci_prima_di_mediaout(comp, comp.AddTool("Blur"))
        chiave(tool, "XBlurSize", [(da, float(parametri.get("da_valore", 0))), (a, float(parametri.get("a_valore", 20)))], base)
        dettaglio = {}
    elif effetto == "glow":
        tool = inserisci_prima_di_mediaout(comp, comp.AddTool("SoftGlow"))
        tool.SetInput("Gain", float(parametri.get("gain", 1.0)))
        tool.SetInput("Threshold", float(parametri.get("soglia", 0.7)))
        dettaglio = {}
    elif effetto == "speed_ramp":
        punti = parametri.get("punti")  # [[frame_clip, frame_sorgente], ...]
        if not punti or len(punti) < 2:
            raise ErroreToolkit("speed_ramp vuole almeno due punti [frame_clip, frame_sorgente].")
        tool = inserisci_prima_di_mediaout(comp, comp.AddTool("TimeStretcher"))
        chiave(tool, "SourceTime", [(int(fc), float(base + fs)) for fc, fs in punti], base)
        dettaglio = {"punti": punti}
    else:
        raise ErroreToolkit(f"Effetto '{effetto}' non previsto. Disponibili: punch_in, shake, flash, whip, blur, glow, speed_ramp.")

    salvate = salva_comp_clip(item)
    return {"esito": "ok", "clip": item.GetName(), "effetto": effetto, "dettaglio": dettaglio,
            "frame_comp_base": base, "comp_salvate": salvate,
            "prossimo_passo": "render_di_prova sul tratto + verifica_render_prova + guardare i frame"}


def transizione(impronta: str, indice_taglio: int, tipo: str, durata_frame: int = 8, traccia: int = 1,
                parametri: dict | None = None, nome_timeline: str | None = None) -> dict:
    """Transizione costruita come effetti sulle due clip del taglio (indice_taglio = taglio tra clip n e n+1)."""
    _controlla_nome(tipo)
    parametri = parametri or {}
    t = trova_timeline(nome_timeline)
    items = t.GetItemListInTrack("video", traccia) or []
    if not 1 <= indice_taglio < len(items):
        raise ErroreToolkit(f"Taglio {indice_taglio} non esiste ({len(items)} clip).")
    a_item, b_item = items[indice_taglio - 1], items[indice_taglio]
    if a_item.GetEnd() != b_item.GetStart():
        raise ErroreToolkit("Tra le due clip c'è un buco o una sovrapposizione: sistemare il montaggio prima.")
    mezzo = max(1, durata_frame // 2)
    combinazioni = {
        "whip": [("whip", {"direzione": parametri.get("direzione", "sinistra")}),
                 ("whip", {"direzione": parametri.get("direzione", "sinistra")})],
        "flash": [("flash", {"gain": parametri.get("gain", 3.0)}), ("flash", {"gain": parametri.get("gain", 3.0)})],
        "zoom": [("punch_in", {"scala": parametri.get("scala", 1.3)}), ("blur", {"da_valore": 15, "a_valore": 0})],
        "blur": [("blur", {"da_valore": 0, "a_valore": 20}), ("blur", {"da_valore": 20, "a_valore": 0})],
    }
    if tipo not in combinazioni:
        raise ErroreToolkit(f"Transizione '{tipo}' non prevista: {sorted(combinazioni)}. Le transizioni native di Resolve si mettono a mano.")
    (eff_a, par_a), (eff_b, par_b) = combinazioni[tipo]
    par_a = {**par_a, "da": a_item.GetDuration() - mezzo, "a": a_item.GetDuration() - 1 if a_item.GetDuration() > mezzo else a_item.GetDuration()}
    par_b = {**par_b, "da": 0, "a": mezzo}
    r1 = applica_effetto(impronta, indice_taglio, eff_a, par_a, traccia, parametri.get("visi_a"), nome_timeline)
    from .stato import fotografia
    imp2 = fotografia(nome_timeline)["impronta"]
    r2 = applica_effetto(imp2, indice_taglio + 1, eff_b, par_b, traccia, parametri.get("visi_b"), nome_timeline)
    return {"esito": "ok", "tipo": tipo, "uscita": r1, "entrata": r2,
            "prossimo_passo": "render_di_prova attorno al taglio e controllo frame per frame"}


# ---------------------------------------------------------------- reframe verticale

def orientamento(mpi) -> str:
    res = (mpi.GetClipProperty("Resolution") or "") if mpi else ""
    try:
        w, h = (int(x) for x in res.lower().split("x"))
    except ValueError:
        return "sconosciuto"
    return "orizzontale" if w > h else "verticale"


def clip_orizzontali(nome_timeline: str | None = None) -> dict:
    t = trova_timeline(nome_timeline)
    out = []
    for tr in range(1, (t.GetTrackCount("video") or 0) + 1):
        for i, it in enumerate(t.GetItemListInTrack("video", tr) or [], start=1):
            if orientamento(it.GetMediaPoolItem()) == "orizzontale":
                out.append({"traccia": tr, "indice": i, "nome": it.GetName()})
    return {"esito": "ok" if not out else "da_adattare", "orizzontali": out,
            "regola": "niente clip orizzontali dentro il verticale, neanche su fondo sfocato: pieno schermo verticale"}


def smart_reframe(impronta: str, indici: list[int], traccia: int = 1, nome_timeline: str | None = None) -> dict:
    verifica_lucchetto(impronta, nome_timeline)
    t = trova_timeline(nome_timeline)
    items = t.GetItemListInTrack("video", traccia) or []
    fatte, errori = [], []
    for i in indici:
        it = items[i - 1]
        if not hasattr(it, "SmartReframe"):
            raise ErroreToolkit("SmartReframe non disponibile su questa versione dell'API (vedi sondaggio_api).")
        (fatte if it.SmartReframe() else errori).append(it.GetName())
    return {"esito": "ok" if not errori else "parziale", "fatte": fatte, "errori": errori,
            "prossimo_passo": "mappa_zone per controllare che la testa sia intera in ogni clip adattata"}
