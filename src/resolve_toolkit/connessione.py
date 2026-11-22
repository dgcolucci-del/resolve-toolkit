"""Connessione a DaVinci Resolve Studio tramite l'API di scripting ufficiale."""
from __future__ import annotations

import os
import sys

PERCORSI_MAC = {
    "api": "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules",
    "lib": "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so",
}

_resolve_override = None  # usato dai test per iniettare un Resolve simulato
_connessione = None  # UNA sola connessione per processo (22 nov 2026, vedi resolve())


class ErroreToolkit(Exception):
    """Errore con messaggio in italiano, restituito così com'è a Claude."""


def imposta_resolve(oggetto) -> None:
    global _resolve_override, _connessione
    _resolve_override = oggetto
    _connessione = None


def resolve():
    """Connessione a Resolve, riusata finché risponde.

    22 nov 2026 (reel Esosomi): ogni chiamata a scriptapp() apriva una connessione NUOVA. Gli oggetti presi
    da connessioni diverse non si parlano: AppendToTimeline rifiutava la clip del media pool (inserisci_clip
    "rifiutato con tutte le convenzioni") e SetCurrentTimeline ignorava la timeline (backup_timeline lasciava
    corrente la copia). Provato sul Mac: stessa connessione = funziona, connessioni diverse = rifiutato."""
    global _connessione
    if _resolve_override is not None:
        return _resolve_override
    if _connessione is not None:
        try:
            if _connessione.GetVersionString():
                return _connessione
        except Exception:  # noqa: BLE001 - connessione caduta: se ne apre una nuova
            pass
        _connessione = None
    os.environ.setdefault("RESOLVE_SCRIPT_API", os.path.dirname(PERCORSI_MAC["api"]))
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", PERCORSI_MAC["lib"])
    if PERCORSI_MAC["api"] not in sys.path:
        sys.path.append(PERCORSI_MAC["api"])
    try:
        import DaVinciResolveScript as dvr  # type: ignore
    except ImportError as e:
        raise ErroreToolkit(f"API di Resolve non trovata ({e}). Resolve Studio è installato?")
    r = dvr.scriptapp("Resolve")
    if r is None:
        raise ErroreToolkit(
            "Resolve non risponde. Controlla che sia aperto e che in Preferenze > Generale "
            "'External scripting using' sia su Local."
        )
    _connessione = r
    return r


def progetto():
    p = resolve().GetProjectManager().GetCurrentProject()
    if p is None:
        raise ErroreToolkit("Nessun progetto aperto in Resolve.")
    return p


def timeline_corrente():
    t = progetto().GetCurrentTimeline()
    if t is None:
        raise ErroreToolkit("Nessuna timeline aperta.")
    return t


def trova_timeline(nome: str | None):
    """Timeline per nome (o la corrente se nome è vuoto). Mai indovinare: nome esatto."""
    if not nome:
        return timeline_corrente()
    p = progetto()
    trovate = []
    for i in range(1, p.GetTimelineCount() + 1):
        t = p.GetTimelineByIndex(i)
        if t.GetName() == nome:
            trovate.append(t)
    if not trovate:
        raise ErroreToolkit(f"Timeline '{nome}' non trovata. Usa elenca_timeline per i nomi esatti.")
    if len(trovate) > 1:
        raise ErroreToolkit(f"Ci sono {len(trovate)} timeline chiamate '{nome}': chiedi a Diego quale.")
    return trovate[0]
