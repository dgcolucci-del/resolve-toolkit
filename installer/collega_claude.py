"""Aggiunge (o aggiorna) la voce resolve-toolkit in claude_desktop_config.json senza toccare il resto."""
import json
import sys


def collega(conf_path: str, comando: str) -> dict:
    try:
        with open(conf_path) as f:
            conf = json.load(f)
    except FileNotFoundError:
        conf = {}
    conf.setdefault("mcpServers", {})["resolve-toolkit"] = {"command": comando, "args": []}
    with open(conf_path, "w") as f:
        json.dump(conf, f, indent=2, ensure_ascii=False)
    return conf


if __name__ == "__main__":
    collega(sys.argv[1], sys.argv[2])
    print("collegato:", sys.argv[2])
