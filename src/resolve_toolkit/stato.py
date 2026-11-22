"""Fotografia della timeline, impronta (il "lucchetto") e confronto prima/dopo.

Regola di Diego (18 nov 2026): lui modifica la timeline mentre lavoro. Ogni comando che
modifica riceve l'impronta letta prima: se non coincide con quella attuale, si rifiuta.
"""
from __future__ import annotations

import hashlib
import json

from .connessione import ErroreToolkit, trova_timeline

TIPI_TRACCIA = ("video", "audio", "subtitle")


def _clip(item, tipo: str, traccia: int, indice: int) -> dict:
    mpi = item.GetMediaPoolItem() if hasattr(item, "GetMediaPoolItem") else None
    return {
        "tipo": tipo,
        "traccia": traccia,
        "indice": indice,
        "nome": item.GetName(),
        "id": item.GetUniqueId() if hasattr(item, "GetUniqueId") else None,
        "inizio": item.GetStart(),
        "fine": item.GetEnd(),
        "durata": item.GetDuration(),
        "offset_sorgente": item.GetLeftOffset(),
        "file": mpi.GetClipProperty("File Path") if mpi else None,
    }


def fotografia(nome_timeline: str | None = None) -> dict:
    t = trova_timeline(nome_timeline)
    inizio = t.GetStartFrame()
    clip = []
    tracce = {}
    for tipo in TIPI_TRACCIA:
        n = t.GetTrackCount(tipo) or 0
        tracce[tipo] = n
        for tr in range(1, n + 1):
            for i, item in enumerate(t.GetItemListInTrack(tipo, tr) or [], start=1):
                c = _clip(item, tipo, tr, i)
                c["inizio_relativo"] = c["inizio"] - inizio
                clip.append(c)
    foto = {
        "timeline": t.GetName(),
        "fps": t.GetSetting("timelineFrameRate"),
        "inizio_timeline": inizio,
        "fine_timeline": t.GetEndFrame(),
        "tracce": tracce,
        "numero_clip": len(clip),
        "clip": clip,
    }
    foto["impronta"] = impronta(foto)
    return foto


def impronta(foto: dict) -> str:
    dati = {k: foto[k] for k in ("timeline", "fps", "inizio_timeline", "tracce")}
    dati["clip"] = [
        (c["tipo"], c["traccia"], c["nome"], c["inizio"], c["fine"], c["offset_sorgente"])
        for c in foto["clip"]
    ]
    return hashlib.sha256(json.dumps(dati, sort_keys=True).encode()).hexdigest()[:12]


def verifica_lucchetto(impronta_attesa: str, nome_timeline: str | None) -> dict:
    """Restituisce la fotografia attuale se coincide, altrimenti blocca."""
    attuale = fotografia(nome_timeline)
    if not impronta_attesa:
        raise ErroreToolkit(
            "Manca l'impronta: chiama prima stato_timeline e passa la sua impronta."
        )
    if attuale["impronta"] != impronta_attesa:
        raise ErroreToolkit(
            "BLOCCATO: la timeline è cambiata dall'ultima lettura (probabilmente l'ha modificata Diego). "
            f"Impronta attesa {impronta_attesa}, attuale {attuale['impronta']}. "
            "Rileggi con stato_timeline e riparti dalla versione attuale."
        )
    return attuale


def confronta(prima: dict, dopo: dict) -> dict:
    # Per id unico: col nome due clip uguali sulla stessa traccia (stesso SFX due volte, overlay e sua copia)
    # si sovrascrivevano e una clip nuova risultava "spostata" (22 nov 2026). Senza id: chiave di prima.
    def chiave(c):
        return c.get("id") or (c["tipo"], c["traccia"], c["nome"], c["offset_sorgente"])
    a = {chiave(c): c for c in prima["clip"]}
    b = {chiave(c): c for c in dopo["clip"]}
    sparite = [a[k] for k in a if k not in b]
    nuove = [b[k] for k in b if k not in a]
    spostate = [
        {"nome": b[k]["nome"], "traccia": f'{b[k]["tipo"]} {b[k]["traccia"]}',
         "prima": [a[k]["inizio"], a[k]["fine"]], "dopo": [b[k]["inizio"], b[k]["fine"]]}
        for k in a if k in b and (a[k]["inizio"], a[k]["fine"]) != (b[k]["inizio"], b[k]["fine"])
    ]
    return {
        "clip_prima": prima["numero_clip"],
        "clip_dopo": dopo["numero_clip"],
        "sparite": [f'{c["nome"]} ({c["tipo"]} {c["traccia"]}, {c["inizio"]}-{c["fine"]})' for c in sparite],
        "nuove": [f'{c["nome"]} ({c["tipo"]} {c["traccia"]}, {c["inizio"]}-{c["fine"]})' for c in nuove],
        "spostate": spostate,
    }
