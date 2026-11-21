"""Correzioni 0.2.3 (20 nov 2026, REEL 003 Piero Angela)."""
import pytest

from resolve_toolkit import calibrazione, color, connessione, immagini, lavoro, operazioni
from resolve_toolkit.connessione import ErroreToolkit
from resolve_toolkit.stato import fotografia
from finto_resolve import FintaTimeline, FintoItem, FintoMPI, FintoResolve


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(calibrazione, "FILE", str(tmp_path / "calibrazione.json"))
    monkeypatch.setattr(operazioni, "ATTESA_PAGINA_S", 0)
    monkeypatch.setattr(operazioni, "_file_jobs", lambda: str(tmp_path / "jobs.json"))

    def crea(**kw):
        r = FintoResolve(**kw)
        t = r.p._aggiungi(FintaTimeline("REEL 003"))
        t.tracce["video"][0].append(FintoItem("C7002.MP4", 90000, 90100, 0))
        connessione.imposta_resolve(r)
        return r, t
    yield crea
    connessione.imposta_resolve(None)


def test_render_imposta_sempre_export_video(ambiente, tmp_path):
    r, t = ambiente()
    r.p.render_impostazioni["ExportVideo"] = False  # rimasto spento dall'ultimo render audio
    out = operazioni.render_sicuro(str(tmp_path / "o"), "PA003_4K", "Diego: esporta in mp4 4K",
                                   bitrate=160000, formato="mp4", codec="H264", larghezza=2160, altezza=3840)
    s = r.p.render_impostazioni
    assert out["esito"] == "ok"
    assert s["ExportVideo"] is True and s["ExportAudio"] is True
    assert (s["FormatWidth"], s["FormatHeight"]) == (2160, 3840) and s["AudioCodec"] == "aac"


def test_render_lungo_risponde_in_corso(ambiente, tmp_path, monkeypatch):
    r, t = ambiente()
    monkeypatch.setattr(operazioni, "ATTESA_IN_CHIAMATA_S", 0)
    r.p.IsRenderingInProgress = lambda: True
    r.p.GetRenderJobStatus = lambda j: {"JobStatus": "Rendering", "CompletionPercentage": 12,
                                        "EstimatedTimeRemainingInMs": 300000}
    out = operazioni.render_sicuro(str(tmp_path / "o"), "PA", "Diego: esporta")
    assert out["esito"] == "in_corso" and out["percentuale"] == 12 and out["mancano_s"] == 300
    r.p.IsRenderingInProgress = lambda: False
    r.p.GetRenderJobStatus = lambda j: {"JobStatus": "Complete", "CompletionPercentage": 100}
    fine = operazioni.stato_render(out["job_id"])
    assert fine["esito"] == "ok" and fine["file"].endswith("PA.mp4")


def test_inserisci_clip_tronca_alla_lunghezza(ambiente):
    r, t = ambiente()
    mpi = FintoMPI("PA003_sottotitoli_v03.mov")
    mpi.props["Frames"] = "1007"
    r.p.radice.clip.append(mpi)
    out = operazioni.inserisci_clip(fotografia()["impronta"], "PA003_sottotitoli_v03.mov", 0, 1200, 3, 0, tipo="video")
    assert out["durata"] == 1007 and out["inizio_relativo"] == 0


def test_inserisci_clip_riprova_se_rifiutata(ambiente):
    r, t = ambiente()
    originale = r.p.mp.AppendToTimeline

    def rifiuta_assoluto(infos):  # come il 20 nov: recordFrame assoluto rifiutato
        if infos[0]["recordFrame"] >= 90000:
            return []
        return originale(infos)
    r.p.mp.record_assoluto = False
    r.p.mp.AppendToTimeline = rifiuta_assoluto
    out = operazioni.inserisci_clip(fotografia()["impronta"], "C7001.MP4", 0, 25, 2, 10, tipo="video")
    assert out["inizio_relativo"] == 10 and calibrazione.leggi()["record_frame_assoluto"] is False


def test_sostituisci_clip(ambiente):
    r, t = ambiente()
    for n in ("sub_v02.mov", "sub_v03.mov"):
        m = FintoMPI(n); m.props["Frames"] = "50"; r.p.radice.clip.append(m)
    operazioni.inserisci_clip(fotografia()["impronta"], "sub_v02.mov", 0, 50, 3, 20, tipo="video")
    vecchia = t.tracce["video"][2][0]
    out = operazioni.sostituisci_clip(fotografia()["impronta"], vecchia.GetUniqueId(), "sub_v03.mov")
    nuova = t.tracce["video"][2]
    assert len(nuova) == 1 and nuova[0].GetName() == "sub_v03.mov" and out["inizio_relativo"] == 20


def test_uniformita_salta_le_clip_coperte(ambiente, tmp_path, monkeypatch):
    r, t = ambiente()
    t.tracce["video"].append([FintoItem("BROLL.MP4", 90000, 90060, 0)])  # copre i primi 60 frame
    t.tracce["video"].append([FintoItem("PA003_sottotitoli.mov", 90000, 90100, 0)])  # overlay: non conta
    t.tracce["video"][0].append(FintoItem("C7002.MP4", 90100, 90150, 0))
    t.tracce["video"][1].append(FintoItem("BROLL2.MP4", 90100, 90150, 0))  # copre tutta la seconda
    presi = []
    monkeypatch.setattr(immagini, "esporta_frame", lambda tl, f, p: presi.append(f) or p)
    monkeypatch.setattr(immagini, "carica_rgb", lambda p: None)
    monkeypatch.setattr(immagini, "analizza_colore", lambda rgb: {"pelle": 0})
    monkeypatch.setattr(immagini, "fuori_media", lambda m: [])
    monkeypatch.setattr(color, "registra_file", lambda *a: None)
    out = color.uniformita(cartella=str(tmp_path))
    assert "V1_002_C7002.MP4" in out["coperte_interamente"]
    assert presi[0] == 90080  # metà del tratto visibile 90060-90100, non 90050
    assert out["id"]["V1_001_C7002.MP4"]


def test_scope_per_etichetta_e_nomi_doppi(ambiente, monkeypatch, tmp_path):
    r, t = ambiente()
    t.tracce["video"][0].append(FintoItem("C7002.MP4", 90100, 90150, 0))
    monkeypatch.setattr(color, "_registro", lambda: str(tmp_path / "scope.json"))
    valori = dict(parade="RGB allineati a 720", waveform="pelle 560-610", vectorscope="pelle sulla linea")
    out = color.registra_controllo_scope("V1_002_C7002.MP4", esito="ok", **valori)
    assert out["clip_registrate"] == 1
    out = color.registra_controllo_scope("C7002.MP4", esito="ok", **valori)
    assert out["clip_registrate"] == 2 and "attenzione" in out
    with pytest.raises(ErroreToolkit, match="timeline è cambiata"):
        color.registra_controllo_scope("V1_002_ALTRA.MP4", esito="ok", **valori)
    assert color.segna_modifica_color("V1_001_C7002.MP4")["controlli_annullati"] == 1


def test_importa_asset_dalla_cartella_progetto(ambiente, monkeypatch, tmp_path):
    r, t = ambiente()
    f = tmp_path / "REEL 003" / "_claude" / "sub.mov"
    f.parent.mkdir(parents=True); f.write_bytes(b"x")
    monkeypatch.setattr(lavoro, "regole", lambda: {"archivio_asset": "/Volumes/Tokiro 01/SFX",
                                                   "cartella_progetti": str(tmp_path)})
    r.p.mp.ImportMedia = lambda ps: [FintoMPI("sub.mov")]
    assert lavoro.importa_asset([str(f)])["esito"] == "ok"
    with pytest.raises(ErroreToolkit, match="Fuori"):
        lavoro.importa_asset(["/Users/mac/Desktop/x.mov"])


def test_tagli_tengono_la_coda_delle_parole():
    """21 nov 2026: le code sotto -30 dB vanno tenute fino al fondo stanza (+18 dB), le pause tolte."""
    import numpy as np
    from resolve_toolkit import montaggio
    db = np.full(300, -70.0)          # 3 s di fondo stanza a -70 dB
    db[50:120] = -20                  # parola 1: 0,50-1,20 s
    db[120:150] = np.linspace(-35, -60, 30)  # coda che decade sotto -30 dB
    db[200:260] = -20                 # parola 2 dopo una pausa vera
    seg = montaggio.segmenti_calibrati(db, 3.0)
    assert len(seg) == 2
    assert seg[0][0] == 0.44 and seg[0][1] >= 1.40   # coda tenuta (la vecchia regola tagliava a 1,25)
    assert seg[1][0] == 1.94 and seg[1][1] <= 2.75   # pausa tolta


def test_analizza_parlato_bin_intero(ambiente, tmp_path, monkeypatch):
    """Un solo comando: tagli di ogni clip del bin + wav unico con la mappa per una sola trascrizione."""
    import json, subprocess
    from resolve_toolkit import audio, montaggio
    r, t = ambiente()
    f = tmp_path / "C7001.mp4"
    subprocess.run([audio._ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "sine=f=300:d=1",
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono:d=1", "-filter_complex",
                    "[0][1]concat=n=2:v=0:a=1,volume=0.5", str(f)], check=True)
    r.p.radice.sotto[0].clip[0].props["File Path"] = str(f)
    out = montaggio.analizza_parlato("B-ROLL", str(tmp_path / "wav"), trascrivi=True, attesa_s=0)
    assert out["esito"] == "in_corso"  # nel finto non c'è trascrizione
    r.p.radice.sotto[0].clip[0].props["Transcription"] = "Simel ti aspetta"
    out = montaggio.analizza_parlato("B-ROLL", str(tmp_path / "wav"))
    assert out["esito"] == "ok" and out["clip"][0]["testo"] == "Simel ti aspetta"
    c = out["clip"][0]
    assert c["clip"] == "C7001.MP4" and len(c["segmenti_frame"]) == 1
    assert out["mappa"][0]["inizio_s"] == 0 and abs(out["mappa"][0]["durata_s"] - 2.0) < 0.05
    assert json.load(open(out["wav_unico"].replace(".wav", "_mappa.json")))[0]["clip"] == "C7001.MP4"
