"""Registro di ogni comando eseguito: cosa, quando, esito. Serve a Diego e a me per ricostruire."""
from __future__ import annotations

import json
import os
import time

CARTELLA = os.path.expanduser("~/Library/Logs/ResolveToolkit")


def scrivi(comando: str, parametri: dict, esito: dict | str) -> None:
    try:
        os.makedirs(CARTELLA, exist_ok=True)
        riga = {"ora": time.strftime("%Y-%m-%d %H:%M:%S"), "comando": comando,
                "parametri": parametri, "esito": esito}
        with open(os.path.join(CARTELLA, time.strftime("%Y-%m-%d") + ".jsonl"), "a") as f:
            f.write(json.dumps(riga, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass  # il registro non deve mai bloccare il lavoro
