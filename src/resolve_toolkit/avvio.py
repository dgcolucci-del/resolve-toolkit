"""Avvio reel: i controlli che vanno fatti prima di toccare la timeline (protocollo §1)."""
from __future__ import annotations

from . import config, lavoro
from .connessione import progetto, resolve
from .regole import regole

NOMI_NON_SALVATI = {"Untitled Project", "Progetto senza titolo"}


def _fps_sorgenti(t) -> dict:
    conteggio = {}
    for tipo in ("video",):
        for tr in range(1, (t.GetTrackCount(tipo) or 0) + 1):
            for item in t.GetItemListInTrack(tipo, tr) or []:
                mpi = item.GetMediaPoolItem()
                if mpi is None:
                    continue
                fps = mpi.GetClipProperty("FPS")
                if fps:
                    conteggio[str(fps)] = conteggio.get(str(fps), 0) + 1
    return conteggio


def _uguali(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) < 0.01
    except (TypeError, ValueError):
        return False


def avvio_reel(cliente: str = "") -> dict:
    p = progetto()
    problemi, controlli = [], {}

    nome = p.GetName()
    controlli["progetto"] = nome
    if nome in NOMI_NON_SALVATI:
        problemi.append("Progetto mai salvato: nome e cartella li decide Diego prima di salvare.")

    impostazioni = p.GetSetting() or {}
    cartelle = {k: v for k, v in impostazioni.items() if "media" in k.lower() and ("location" in k.lower() or "path" in k.lower())}
    controlli["cartelle_media"] = cartelle or "NON CONFERMATO (chiave non trovata nelle impostazioni)"
    if cartelle:
        problemi.append("Controlla con Diego la cartella media del progetto: eredita quella dell'ultimo progetto (13 nov).")

    timeline = []
    for i in range(1, p.GetTimelineCount() + 1):
        t = p.GetTimelineByIndex(i)
        fps_tl = t.GetSetting("timelineFrameRate")
        sorgenti = _fps_sorgenti(t)
        diversi = [f for f in sorgenti if not _uguali(f, fps_tl)]
        timeline.append({"nome": t.GetName(), "fps": fps_tl, "fps_sorgenti": sorgenti, "fps_diversi": diversi})
        if diversi:
            problemi.append(f"Timeline '{t.GetName()}' a {fps_tl} fps con clip a {diversi} fps: frame persi (test 13 nov).")
    controlli["timeline"] = timeline
    corrente = p.GetCurrentTimeline()
    controlli["timeline_corrente"] = corrente.GetName() if corrente else None
    controlli["pagina"] = resolve().GetCurrentPage()

    sondato = config.leggi().get("api_disponibili")
    if not sondato:
        problemi.append("API non ancora sondata su questo Mac: esegui sondaggio_api.")

    passaggio = lavoro.leggi_passaggio(nome)
    return {
        "esito": "ok" if not problemi else "da_risolvere",
        "problemi": problemi,
        "controlli": controlli,
        "skill_da_caricare": regole()["skill_avvio"],
        "file_cliente": f"/areas/{cliente}.md" if cliente else "identificare il cliente dal progetto e leggere /areas/<cliente>.md",
        "da_fare_a_schermo": ["scope agganciati nella pagina Color sul PHL (mai flottanti)",
                              "partire dalla timeline già montata da Diego, non dal girato completo"],
        "passaggio_precedente": passaggio,
    }
