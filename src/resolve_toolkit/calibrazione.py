"""Convenzioni dell'API scoperte sul campo, salvate su disco.

Esempio: AppendToTimeline vuole recordFrame assoluto o relativo? endFrame è incluso o escluso?
Invece di affidarsi alla memoria, il comando prova, misura il risultato e se sbaglia di uno
scarto riconoscibile annulla, corregge, riprova una volta e salva la convenzione giusta.
"""
from __future__ import annotations

import json
import os

FILE = os.path.expanduser("~/Library/Application Support/ResolveToolkit/calibrazione.json")

PREDEFINITE = {
    # API ufficiale: recordFrame nel sistema di frame della timeline (assoluto). NON CONFERMATO
    # sulla macchina di Diego: si calibra da solo al primo inserimento.
    "record_frame_assoluto": True,
    # endFrame escluso (durata = end - start). NON CONFERMATO: si calibra da solo.
    "end_frame_escluso": True,
}


def leggi() -> dict:
    dati = dict(PREDEFINITE)
    try:
        with open(FILE) as f:
            dati.update(json.load(f))
    except (OSError, ValueError):
        pass
    return dati


def salva(chiave: str, valore) -> None:
    dati = leggi()
    dati[chiave] = valore
    os.makedirs(os.path.dirname(FILE), exist_ok=True)
    with open(FILE, "w") as f:
        json.dump(dati, f, indent=2)
