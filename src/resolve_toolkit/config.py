"""Configurazione per ogni Mac e sondaggio dell'API realmente disponibile.

Su due Mac diversi cambiano percorsi, versione di Resolve, monitor, ffmpeg. Il sondaggio registra
quali funzioni dell'API esistono davvero, così non si chiamano comandi inventati.
"""
from __future__ import annotations

import json
import os
import platform
import socket

from .connessione import progetto, resolve, timeline_corrente

CARTELLA = os.path.expanduser("~/Library/Application Support/ResolveToolkit")

METODI_DA_SONDARE = {
    "resolve": ["GetVersionString", "OpenPage", "GetCurrentPage"],
    "progetto": ["GetRenderJobStatus", "ExportCurrentFrameAsStill", "AddColorGroup", "GetColorGroupsList",
                 "SetCurrentRenderFormatAndCodec", "GetSetting"],
    "timeline": ["SetVoiceIsolationState", "GetVoiceIsolationState", "DuplicateTimeline", "SetCurrentTimecode",
                 "DeleteClips", "CreateSubtitlesFromAudio", "DetectSceneCuts"],
    "item": ["GetNodeGraph", "AssignToColorGroup", "GetColorGroup", "SmartReframe", "AddFusionComp",
             "GetFusionCompByIndex", "ExportFusionComp", "ImportFusionComp", "SetCDL"],
    "grafo": ["GetNumNodes", "GetNodeLabel", "GetLUT", "GetToolsInNode", "SetNodeEnabled"],
}


def nome_mac() -> str:
    return socket.gethostname().split(".")[0]


def file_config() -> str:
    return os.path.join(CARTELLA, f"config-{nome_mac()}.json")


def leggi() -> dict:
    try:
        with open(file_config()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def scrivi(dati: dict) -> None:
    os.makedirs(CARTELLA, exist_ok=True)
    with open(file_config(), "w") as f:
        json.dump(dati, f, indent=2, ensure_ascii=False)


def sondaggio() -> dict:
    r = resolve()
    oggetti = {"resolve": r}
    try:
        p = progetto()
        oggetti["progetto"] = p
        t = timeline_corrente()
        oggetti["timeline"] = t
        items = t.GetItemListInTrack("video", 1) or []
        if items:
            oggetti["item"] = items[0]
            if hasattr(items[0], "GetNodeGraph"):
                g = items[0].GetNodeGraph()
                if g:
                    oggetti["grafo"] = g
    except Exception:
        pass
    disponibili, mancanti, non_sondati = {}, {}, []
    for nome, metodi in METODI_DA_SONDARE.items():
        o = oggetti.get(nome)
        if o is None:
            non_sondati.append(nome)
            continue
        disponibili[nome] = [m for m in metodi if hasattr(o, m)]
        mancanti[nome] = [m for m in metodi if not hasattr(o, m)]
    dati = leggi()
    dati.update({
        "mac": nome_mac(),
        "sistema": platform.platform(),
        "resolve": r.GetVersionString() if hasattr(r, "GetVersionString") else "NON CONFERMATO",
        "api_disponibili": disponibili,
        "api_mancanti": mancanti,
        "non_sondati": non_sondati,
    })
    scrivi(dati)
    return dati


def api_presente(oggetto: str, metodo: str) -> bool | None:
    """True/False se sondato, None se non ancora sondato su questo Mac."""
    d = leggi()
    if oggetto in d.get("api_disponibili", {}):
        return metodo in d["api_disponibili"][oggetto]
    return None
