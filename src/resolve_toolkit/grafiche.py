"""Motion graphic e sottotitoli: zone libere, piano dei sottotitoli, controllo grafiche, Text+ in Fusion.

Regole (preferenze Diego + regole-motion-diego):
- mai sopra visi, loghi o scritte in inquadratura (anche ricamati sui vestiti, anche nei tratti zoomati);
- safe zone: niente testo sopra 250 px e sotto 1470 px, margini laterali;
- sottotitoli tutti alla stessa altezza, poco sopra la safe zone inferiore; interlinea stretta;
- nessuno stile predefinito: ogni reel ha il suo stile, scelto con Diego su 2-3 proposte su frame reali.
"""
from __future__ import annotations

import glob
import os
import time

from PIL import Image, ImageDraw

from . import immagini, visione
from .connessione import ErroreToolkit, progetto, trova_timeline
from .lavoro import registra_file
from .regole import regole
from .stato import verifica_lucchetto


# ---------------------------------------------------------------- geometria

def _scala_box(boxes, w_img, h_img, W, H):
    sx, sy = W / w_img, H / h_img
    return [{**b, "x": b["x"] * sx, "y": b["y"] * sy, "w": b["w"] * sx, "h": b["h"] * sy} for b in boxes]


def fasce_libere(boxes: list[dict], H: int | None = None, margine: float | None = None) -> list[list[float]]:
    """Fasce orizzontali libere dentro la safe zone, tolti visi e scritte (+ margine)."""
    sz = regole()["safe_zone"]
    margine = regole()["sottotitoli"]["margine_viso_px"] if margine is None else margine
    libere = [[float(sz["alto_px"]), float(sz["basso_px"])]]
    for b in boxes:
        a, z = b["y"] - margine, b["y"] + b["h"] + margine
        nuove = []
        for s, e in libere:
            if z <= s or a >= e:
                nuove.append([s, e])
                continue
            if a > s:
                nuove.append([s, a])
            if z < e:
                nuove.append([z, e])
        libere = nuove
    return [f for f in libere if f[1] - f[0] >= 40]


def intersezione_fasce(liste: list[list[list[float]]]) -> list[list[float]]:
    if not liste:
        return []
    comuni = liste[0]
    for altra in liste[1:]:
        nuove = []
        for s1, e1 in comuni:
            for s2, e2 in altra:
                s, e = max(s1, s2), min(e1, e2)
                if e - s >= 40:
                    nuove.append([s, e])
        comuni = nuove
    return comuni


def _anteprima(path_frame, boxes, W, H, out):
    img = Image.open(path_frame).convert("RGB").resize((W, H))
    d = ImageDraw.Draw(img, "RGBA")
    sz = regole()["safe_zone"]
    d.rectangle([0, 0, W, sz["alto_px"]], fill=(255, 0, 0, 70))
    d.rectangle([0, sz["basso_px"], W, H], fill=(255, 0, 0, 70))
    d.rectangle([0, 0, sz["lato_sinistro_px"], H], fill=(255, 0, 0, 40))
    d.rectangle([W - sz["lato_destro_px"], 0, W, H], fill=(255, 0, 0, 40))
    for b in boxes:
        colore = (255, 200, 0, 255) if b["tipo"] == "viso" else (0, 200, 255, 255)
        d.rectangle([b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]], outline=colore, width=5)
    img.save(out)
    return out


# ---------------------------------------------------------------- mappa delle zone

def mappa_zone(nome_timeline: str | None = None, campioni_per_clip: int = 3, traccia: int = 1) -> dict:
    """Fotogrammi della timeline (quindi con zoom e reframe già applicati), visi e scritte per clip,
    fasce libere per clip e fascia comune per tutti i sottotitoli."""
    t = trova_timeline(nome_timeline)
    progetto().SetCurrentTimeline(t)
    f = regole()["formato"]
    W, H = f["larghezza"], f["altezza"]
    cartella = os.path.join(immagini.CARTELLA_TEMP, "zone", time.strftime("%Y%m%d-%H%M%S"))
    per_clip, tutte, motori = [], [], set()
    for i, item in enumerate(t.GetItemListInTrack("video", traccia) or [], start=1):
        a, b = item.GetStart(), item.GetEnd()
        frames = sorted({a + (b - a) * (k + 1) // (campioni_per_clip + 1) for k in range(campioni_per_clip)})
        boxes_clip, fasce_clip, anteprime = [], [], []
        for fr in frames:
            p = immagini.esporta_frame(t, fr, os.path.join(cartella, f"{i:03d}_{fr}.png"))
            registra_file(p, "frame per mappa zone")
            w_img, h_img = Image.open(p).size
            r = visione.rileva(p)
            motori.add(r["motore"])
            bx = _scala_box(r["box"], w_img, h_img, W, H)
            boxes_clip += [{**x, "frame": fr} for x in bx]
            fasce_clip.append(fasce_libere(bx))
            ant = _anteprima(p, bx, W, H, p.replace(".png", "_zone.png"))
            registra_file(ant, "anteprima zone")
            anteprime.append(ant)
        libere = intersezione_fasce(fasce_clip)
        tutte.append(libere)
        per_clip.append({"indice": i, "nome": item.GetName(), "inizio": a, "fine": b, "box": boxes_clip,
                         "fasce_libere": libere, "anteprime": anteprime})
    comune = intersezione_fasce(tutte)
    testo_ok = "Apple Vision" in motori
    return {
        "esito": "ok",
        "fps": t.GetSetting("timelineFrameRate"),
        "inizio_timeline": t.GetStartFrame(),
        "motore": sorted(motori),
        "fascia_comune": comune,
        "clip": per_clip,
        "da_confermare_a_occhio": "loghi ricamati e scritte piccole" if testo_ok else
                                  "SCRITTE E LOGHI NON RILEVATI (manca Apple Vision): guardare tutte le anteprime",
    }


# ---------------------------------------------------------------- piano sottotitoli

def piano_sottotitoli(parole: list[dict], stile: dict, zone: dict, altezza_testo_px: float,
                      max_caratteri: int = 22, pausa_a_capo_s: float = 0.35) -> dict:
    """parole: [{"testo","inizio_s","fine_s"}] da trascrizione corretta sull'audio vero.
    stile: OBBLIGATORIO, scelto con Diego per questo reel (font, colori, animazione)."""
    if not stile or not stile.get("font"):
        raise ErroreToolkit("Manca lo stile di questo reel: niente stili fissi, sceglierlo con Diego (2-3 proposte su frame reali).")
    if stile.get("interlinea", 1.0) > regole()["sottotitoli"]["interlinea_max"]:
        raise ErroreToolkit("Interlinea troppo larga: Diego la vuole stretta.")
    sz0 = regole()["safe_zone"]
    # altezza unica: poco sopra la safe zone inferiore (scelta del 9 nov 2026)
    y_centro = sz0["basso_px"] - 10 - altezza_testo_px / 2
    fps = float(zone.get("fps") or 25)
    inizio_tl = zone.get("inizio_timeline") or 0

    gruppi, corrente = [], []
    for p in parole:
        testo = " ".join(w["testo"] for w in corrente + [p]).strip()
        pausa = corrente and p["inizio_s"] - corrente[-1]["fine_s"] > pausa_a_capo_s
        if corrente and (len(testo) > max_caratteri or pausa or corrente[-1]["testo"].rstrip()[-1:] in ".?!"):
            gruppi.append(corrente)
            corrente = []
        corrente.append(p)
    if corrente:
        gruppi.append(corrente)

    W = regole()["formato"]["larghezza"]
    sz = regole()["safe_zone"]
    m = regole()["sottotitoli"]["margine_viso_px"]
    a_fascia, z_fascia = y_centro - altezza_testo_px / 2 - m, y_centro + altezza_testo_px / 2 + m
    piano, da_decidere = [], []
    for g in gruppi:
        inizio, fine = g[0]["inizio_s"], g[-1]["fine_s"]
        lati_occupati = set()
        for c in zone.get("clip", []):
            c_in, c_out = (c["inizio"] - inizio_tl) / fps, (c["fine"] - inizio_tl) / fps
            if c_out <= inizio or c_in >= fine:
                continue
            for b in c["box"]:
                if b["y"] < z_fascia and b["y"] + b["h"] > a_fascia:
                    if b["x"] < W / 2:
                        lati_occupati.add("sinistra")
                    if b["x"] + b["w"] > W / 2:
                        lati_occupati.add("destra")
        if not lati_occupati:
            x = "centro"
        elif len(lati_occupati) == 1:
            x = "destra" if "sinistra" in lati_occupati else "sinistra"
        else:
            x = "da_decidere"
        riga = {"testo": " ".join(w["testo"] for w in g), "inizio_s": inizio, "fine_s": fine,
                "parole": g, "y_centro_px": round(y_centro), "allineamento": x}
        if x == "da_decidere":
            da_decidere.append(riga["testo"])
        piano.append(riga)
    return {"esito": "ok" if not da_decidere else "da_decidere_con_diego", "da_decidere": da_decidere,
            "stile": stile, "y_centro_px": round(y_centro), "righe": piano,
            "margini_laterali_px": [sz["lato_sinistro_px"], W - sz["lato_destro_px"]],
            "nota": "Stessa altezza per tutte le righe. Se 'allineamento' non è centro, c'è un viso o logo nella fascia: testo spostato di lato."}


# ---------------------------------------------------------------- controllo grafiche sul render

def controllo_grafiche(frame: list[str]) -> dict:
    """Su frame del render di prova: ogni testo dentro la safe zone e lontano dai visi."""
    f = regole()["formato"]
    sz = regole()["safe_zone"]
    W, H = f["larghezza"], f["altezza"]
    risultati, problemi, motore = [], [], set()
    for path in frame:
        w_img, h_img = Image.open(path).size
        r = visione.rileva(path)
        motore.add(r["motore"])
        bx = _scala_box(r["box"], w_img, h_img, W, H)
        visi = [b for b in bx if b["tipo"] == "viso"]
        testi = [b for b in bx if b["tipo"] == "testo"]
        for tb in testi:
            if tb["y"] < sz["alto_px"] or tb["y"] + tb["h"] > sz["basso_px"] \
                    or tb["x"] < sz["lato_sinistro_px"] or tb["x"] + tb["w"] > W - sz["lato_destro_px"]:
                problemi.append(f"{os.path.basename(path)}: '{tb['testo']}' fuori safe zone")
            for v in visi:
                if not (tb["x"] + tb["w"] < v["x"] or tb["x"] > v["x"] + v["w"]
                        or tb["y"] + tb["h"] < v["y"] or tb["y"] > v["y"] + v["h"]):
                    problemi.append(f"{os.path.basename(path)}: '{tb['testo']}' sopra un viso")
        risultati.append({"frame": path, "testi": len(testi), "visi": len(visi)})
    affidabile = "Apple Vision" in motore
    return {"esito": ("ok" if not problemi else "da_correggere") if affidabile else "non_verificabile",
            "problemi": problemi, "frame": risultati, "motore": sorted(motore),
            "nota": None if affidabile else "Senza Apple Vision il testo non si rileva: controllo a occhio obbligatorio."}


def verifica_font(nome: str) -> dict:
    cartelle = [os.path.expanduser("~/Library/Fonts"), "/Library/Fonts", "/System/Library/Fonts"]
    trovati = [p for c in cartelle for p in glob.glob(os.path.join(c, "**", "*"), recursive=True)
               if nome.lower().replace(" ", "") in os.path.basename(p).lower().replace(" ", "").replace("-", "")]
    return {"esito": "ok" if trovati else "non_trovato", "font": nome, "file": trovati[:10],
            "nota": "Se è installato, controllare anche che compaia nell'elenco del Text+ in Resolve."}


# ---------------------------------------------------------------- Text+ in Fusion

def crea_titolo_fusion(impronta: str, indice_clip: int, testo: str, stile: dict, centro_px: list[float],
                       traccia: int = 1, nome_timeline: str | None = None) -> dict:
    """Aggiunge un Text+ (con Merge) alla comp della clip. stile: font, stile_font, size_fusion,
    colore [r,g,b] 0-1, interlinea. La dimensione in Fusion va verificata sul render di prova."""
    from .effetti import comp_della_clip, inserisci_prima_di_mediaout, salva_comp_clip
    if not stile or not stile.get("font"):
        raise ErroreToolkit("Manca lo stile di questo reel (nessuno stile fisso).")
    if stile.get("interlinea", 1.0) > regole()["sottotitoli"]["interlinea_max"]:
        raise ErroreToolkit("Interlinea troppo larga: Diego la vuole stretta.")
    sz, f = regole()["safe_zone"], regole()["formato"]
    x, y = centro_px
    if not (sz["lato_sinistro_px"] <= x <= f["larghezza"] - sz["lato_destro_px"] and sz["alto_px"] <= y <= sz["basso_px"]):
        raise ErroreToolkit(f"Centro {centro_px} fuori dalla safe zone.")
    verifica_lucchetto(impronta, nome_timeline)
    t = trova_timeline(nome_timeline)
    item, comp = comp_della_clip(t, traccia, indice_clip)
    txt = comp.AddTool("TextPlus")
    txt.SetInput("StyledText", testo)
    txt.SetInput("Font", stile["font"])
    if stile.get("stile_font"):
        txt.SetInput("Style", stile["stile_font"])
    if stile.get("size_fusion"):
        txt.SetInput("Size", float(stile["size_fusion"]))
    txt.SetInput("LineSpacing", float(stile.get("interlinea", 0.9)))
    txt.SetInput("Center", {1: x / f["larghezza"], 2: 1 - y / f["altezza"]})
    if stile.get("colore"):
        for canale, v in zip(("Red1", "Green1", "Blue1"), stile["colore"]):
            txt.SetInput(canale, float(v))
    merge = comp.AddTool("Merge")
    inserisci_prima_di_mediaout(comp, merge, ingresso="Background")
    merge.ConnectInput("Foreground", txt)
    salvato = salva_comp_clip(item)
    return {"esito": "ok", "clip": item.GetName(), "comp_salvata": salvato,
            "prossimo_passo": "render_di_prova sul tratto e controllo_grafiche sui frame"}
