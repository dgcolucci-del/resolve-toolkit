import os

import pytest

from resolve_toolkit import audio, calibrazione, operazioni, connessione
from resolve_toolkit.connessione import ErroreToolkit
from resolve_toolkit.stato import fotografia
from finto_resolve import FintaTimeline, FintoItem, FintoResolve


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(calibrazione, "FILE", str(tmp_path / "calibrazione.json"))
    monkeypatch.setattr(operazioni, "ATTESA_PAGINA_S", 0)

    def crea(**kw):
        r = FintoResolve(**kw)
        t = r.p._aggiungi(FintaTimeline("REEL 016"))
        t.tracce["video"][0].append(FintoItem("C6594.MP4", 90000, 90050, 10))
        connessione.imposta_resolve(r)
        return r, t
    yield crea
    connessione.imposta_resolve(None)


def test_lucchetto_blocca_se_diego_ha_modificato(ambiente):
    r, t = ambiente()
    imp = fotografia()["impronta"]
    t.tracce["video"][0][0].fine = 90040  # Diego accorcia una clip mentre lavoro
    with pytest.raises(ErroreToolkit, match="BLOCCATO"):
        operazioni.inserisci_clip(imp, "C7001.MP4", 0, 25, 1, 50)


def test_inserisci_clip_posizione_relativa(ambiente):
    r, t = ambiente()
    out = operazioni.inserisci_clip(fotografia()["impronta"], "C7001.MP4", 100, 125, 1, 50, tipo="video")
    assert out["inizio"] == 90050 and out["durata"] == 25 and out["inizio_relativo"] == 50
    assert out["confronto"]["sparite"] == [] and len(out["confronto"]["nuove"]) == 1


@pytest.mark.parametrize("assoluto,escluso", [(False, True), (True, False), (False, False)])
def test_autocalibrazione_convenzioni_api(ambiente, assoluto, escluso):
    """Se l'API usa una convenzione diversa da quella attesa, annulla, corregge e salva."""
    r, t = ambiente(record_assoluto=assoluto, end_escluso=escluso)
    out = operazioni.inserisci_clip(fotografia()["impronta"], "C7001.MP4", 100, 125, 1, 50, tipo="video")
    assert (out["inizio"], out["durata"]) == (90050, 25)
    assert len(t.tracce["video"][0]) == 2  # il tentativo sbagliato è stato rimosso
    conv = calibrazione.leggi()
    assert conv["record_frame_assoluto"] == assoluto and conv["end_frame_escluso"] == escluso
    # secondo inserimento: giusto al primo colpo
    out2 = operazioni.inserisci_clip(out["impronta_nuova"], "C7001.MP4", 200, 210, 1, 75, tipo="video")
    assert out2["calibrazione_corretta"] is None and out2["inizio"] == 90075


def test_clip_ambigua_si_ferma(ambiente):
    r, t = ambiente()
    r.p.radice.sotto[0].clip.append(r.p.radice.clip[0])  # stessa clip in due cartelle
    with pytest.raises(ErroreToolkit, match="cartelle diverse"):
        operazioni.inserisci_clip(fotografia()["impronta"], "C6594.MP4", 0, 10, 2, 0)


def test_render_sequenza_sicura(ambiente, tmp_path):
    r, t = ambiente()
    r.p.jobs = ["vecchio1", "vecchio2"]  # job vecchi in coda, pagina Color: la trappola del 17 nov
    with pytest.raises(ErroreToolkit, match="richiesta esplicita"):
        operazioni.render_sicuro(str(tmp_path), "REEL", "")
    out = operazioni.render_sicuro(str(tmp_path / "out"), "REEL 016", "Diego: esporta")
    assert out["esito"] == "ok" and out["tentativi"] == 1 and r.pagina == "edit"
    assert r.p.render_impostazioni["VideoQuality"] == 100000


def test_salva_fusion_export_import(ambiente, tmp_path):
    r, t = ambiente()
    t.tracce["video"][0][0].comp = 2
    out = operazioni.salva_fusion(fotografia()["impronta"], str(tmp_path / "comp"))
    assert len(out["comp_salvate"]) == 2 and t.tracce["video"][0][0].import_fatti == 2


def test_fotogrammi_ai_tagli(ambiente, tmp_path):
    r, t = ambiente()
    t.tracce["video"][0].append(FintoItem("C7001.MP4", 90050, 90100, 0))
    out = operazioni.fotogrammi_ai_tagli(str(tmp_path / "tagli"))
    assert out["tagli"] == 1 and len(out["file"]) == 2
    assert "90049" in out["file"][0] and "90050" in out["file"][1]


def test_backup_resta_su_originale(ambiente):
    r, t = ambiente()
    out = operazioni.backup_timeline(fotografia()["impronta"])
    assert out["backup"] == "BACKUP 01 - REEL 016" and r.p.corrente is t


def test_timecode():
    assert operazioni.frame_a_timecode(90068, 25) == "01:00:02:18"


def test_parser_ebur128_e_silenzi():
    testo = """[Parsed_ebur128_0] Summary:
  Integrated loudness:
    I:         -14.2 LUFS
    Threshold: -24.5 LUFS
  Loudness range:
    LRA:         5.1 LU
  True peak:
    Peak:       -1.3 dBFS"""
    assert audio.analizza_ebur128(testo) == {"lufs_integrati": -14.2, "lra": 5.1, "true_peak_dbtp": -1.3}
    s = "silence_start: 1.5\nsilence_end: 2.1 | silence_duration: 0.6\nsilence_start: 9.0\n"
    out = audio.analizza_silenzi(s)
    assert out[0] == {"inizio_s": 1.5, "fine_s": 2.1, "durata_s": 0.6} and out[1]["fine_s"] is None


def test_ffmpeg_reale_su_file_generato(tmp_path):
    import shutil, subprocess
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg assente")
    f = tmp_path / "prova.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=2",
                    "-f", "lavfi", "-i", "anullsrc=d=1", "-filter_complex",
                    "[0][1]concat=n=2:v=0:a=1,volume=-6dB", str(f)], check=True)
    l = audio.misura_loudness(str(f))
    assert l["lufs_integrati"] is not None and l["true_peak_dbtp"] < 0
    s = audio.trova_silenzi(str(f))
    assert s["numero"] == 1 and abs(s["silenzi"][0]["inizio_s"] - 2.0) < 0.05


@pytest.mark.senza_video
def test_render_uscito_solo_audio_viene_fermato(ambiente, tmp_path, monkeypatch):
    r, t = ambiente()
    monkeypatch.setattr(operazioni.audio, "formato", lambda path: {"codec_video": None, "codec_audio": "aac"})
    with pytest.raises(ErroreToolkit, match="NON ha la traccia video"):
        operazioni.render_sicuro(str(tmp_path / "out"), "REEL 016", "Diego: esporta")
