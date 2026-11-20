import numpy as np
import pytest

from resolve_toolkit import (avvio, calibrazione, color, connessione, effetti, grafiche, immagini, lavoro,
                             montaggio, musica, operazioni, regole)
from resolve_toolkit.connessione import ErroreToolkit
from resolve_toolkit.stato import fotografia
from finto_resolve import FintaTimeline, FintoItem, FintoMPI, FintoResolve


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(calibrazione, "FILE", str(tmp_path / "cal.json"))
    monkeypatch.setattr(lavoro, "CARTELLA", str(tmp_path / "tk"))
    monkeypatch.setattr(effetti, "CARTELLA_COMP", str(tmp_path / "comp"))
    monkeypatch.setattr(immagini, "CARTELLA_TEMP", str(tmp_path / "temp"))
    monkeypatch.setattr(operazioni, "ATTESA_PAGINA_S", 0)
    monkeypatch.setattr(regole, "FILE_UTENTE", str(tmp_path / "nessuno.json"))
    r = FintoResolve()
    t = r.p._aggiungi(FintaTimeline("REEL 016"))
    mpi = r.p.radice.clip[0]
    t.tracce["video"][0] += [FintoItem("C6594.MP4", 90000, 90050, 10, mpi), FintoItem("C6595.MP4", 90050, 90100, 0, mpi)]
    connessione.imposta_resolve(r)
    yield r, t
    connessione.imposta_resolve(None)


# ---------------------------------------------------------------- avvio

def test_avvio_segnala_fps_diversi(ambiente):
    r, t = ambiente
    t.tracce["video"][0][0].mpi = FintoMPI("X.MP4", fps="24")
    out = avvio.avvio_reel("prato-pescheria")
    assert out["esito"] == "da_risolvere"
    assert any("24" in p and "frame persi" in p for p in out["problemi"])
    assert "protocollo-reel-diego" in out["skill_da_caricare"]


# ---------------------------------------------------------------- color

def test_stato_color_catena_non_adatta(ambiente):
    r, t = ambiente
    t.tracce["video"][0][1].mpi = FintoMPI("DJI.MP4", gamma="D-Log M")
    out = color.stato_color()
    assert out["esito"] == "da_verificare"
    assert any("NON adatta" in a and "C6595" in a for a in out["avvisi"])


def test_cancello_scope(ambiente):
    r, t = ambiente
    assert color.color_completa()["esito"] == "aperta"
    with pytest.raises(ErroreToolkit, match="davvero"):
        color.registra_controllo_scope("C6594.MP4", "ok", "ok", "ok", "ok")
    for n in ("C6594.MP4", "C6595.MP4"):
        color.registra_controllo_scope(n, "bianchi R=G=B a 890", "picchi a 920, neri a 64", "pelle sulla linea", "ok")
    assert color.color_completa()["esito"] == "completa"
    color.segna_modifica_color("C6595.MP4")
    out = color.color_completa()
    assert out["esito"] == "aperta" and out["senza_controllo_scope"] == ["C6595.MP4"]
    # nodi cambiati via script dopo il controllo -> il controllo non vale
    color.registra_controllo_scope("C6595.MP4", "bianchi R=G=B a 890", "picchi a 920, neri a 64", "pelle ok sulla linea", "ok")
    t.tracce["video"][0][0].grafo.etichette.append("Nuovo nodo")
    assert "nodi cambiati" in color.color_completa()["senza_controllo_scope"][0]


def test_gruppo_colore(ambiente):
    r, t = ambiente
    imp = fotografia()["impronta"]
    with pytest.raises(ErroreToolkit, match="non esiste"):
        color.assegna_gruppo_colore(imp, "Pelle", ["C6594.MP4"])
    out = color.assegna_gruppo_colore(imp, "Pelle", ["C6594.MP4", "MANCA.MP4"], crea_se_manca=True)
    assert out["assegnate"] == ["C6594.MP4"] and out["non_trovate"] == ["MANCA.MP4"]


def test_analisi_colore_dominante():
    img = np.full((100, 100, 3), 60, np.float32)
    img[:10, :10] = [200, 210, 245]  # bianchi bluastri
    m = immagini.analizza_colore(img)
    assert m["dominante_bianchi"] > 40
    neutro = immagini.analizza_colore(np.full((50, 50, 3), 128, np.float32))
    f = immagini.fuori_media({"a": m, "b": neutro, "c": neutro})
    assert any(x["clip"] == "a" for x in f)


# ---------------------------------------------------------------- grafiche

def test_fasce_libere_tolgono_visi():
    f = grafiche.fasce_libere([{"x": 300, "y": 500, "w": 400, "h": 400, "tipo": "viso"}], margine=30)
    assert f == [[250.0, 470.0], [930.0, 1470.0]]


def test_piano_sottotitoli_stile_obbligatorio_e_lato(ambiente):
    parole = [{"testo": "Ciao", "inizio_s": 0.0, "fine_s": 0.3}, {"testo": "a", "inizio_s": 0.3, "fine_s": 0.4},
              {"testo": "tutti.", "inizio_s": 0.4, "fine_s": 0.8}, {"testo": "Oggi", "inizio_s": 2.5, "fine_s": 2.8}]
    zone = {"fps": "25", "inizio_timeline": 90000, "clip": [
        {"inizio": 90000, "fine": 90050, "box": []},
        {"inizio": 90050, "fine": 90100, "box": [{"x": 650, "y": 1350, "w": 200, "h": 150, "tipo": "testo"}]}]}
    with pytest.raises(ErroreToolkit, match="stile"):
        grafiche.piano_sottotitoli(parole, {}, zone, 80)
    with pytest.raises(ErroreToolkit, match="Interlinea"):
        grafiche.piano_sottotitoli(parole, {"font": "X", "interlinea": 1.4}, zone, 80)
    out = grafiche.piano_sottotitoli(parole, {"font": "X", "interlinea": 0.85}, zone, 80)
    righe = out["righe"]
    assert righe[0]["testo"] == "Ciao a tutti." and righe[0]["allineamento"] == "centro"
    assert righe[1]["allineamento"] == "sinistra"  # logo a destra nella fascia durante la clip 2
    assert len({r["y_centro_px"] for r in righe}) == 1  # tutti alla stessa altezza


def test_titolo_fuori_safe_zone(ambiente):
    with pytest.raises(ErroreToolkit, match="safe zone"):
        grafiche.crea_titolo_fusion(fotografia()["impronta"], 1, "X", {"font": "A"}, [540, 1700])
    out = grafiche.crea_titolo_fusion(fotografia()["impronta"], 1, "X", {"font": "A", "interlinea": 0.9}, [540, 1300])
    assert out["esito"] == "ok" and out["comp_salvata"]


# ---------------------------------------------------------------- effetti

def test_scala_massima_testa():
    viso = [{"x": 440, "y": 300, "w": 200, "h": 260}]
    s = effetti.scala_massima(viso, (540, 960), 1920, 1080, 40)
    testa = 300 - 0.35 * 260
    assert 960 + (testa - 960) * s == pytest.approx(40, abs=1)


def test_punch_in_e_divieti(ambiente):
    r, t = ambiente
    visi = [{"x": 440, "y": 300, "w": 200, "h": 260, "tipo": "viso"}]
    imp = fotografia()["impronta"]
    with pytest.raises(ErroreToolkit, match="taglia la testa"):
        effetti.applica_effetto(imp, 1, "punch_in", {"scala": 1.8, "da": 0, "a": 20}, visi=visi)
    with pytest.raises(ErroreToolkit, match="servono i visi"):
        effetti.applica_effetto(imp, 1, "punch_in", {"scala": 1.1})
    out = effetti.applica_effetto(imp, 1, "punch_in", {"scala": 1.15, "da": 0, "a": 20}, visi=visi)
    assert out["esito"] == "ok" and out["comp_salvate"]
    with pytest.raises(ErroreToolkit, match="vietato"):
        effetti.applica_effetto(imp, 1, "Drop Warp", {})
    out = effetti.transizione(imp, 1, "whip", 8)
    assert out["uscita"]["clip"] == "C6594.MP4" and out["entrata"]["clip"] == "C6595.MP4"


def test_catena_fusion_non_perde_effetti(ambiente):
    r, t = ambiente
    item, comp = effetti.comp_della_clip(t, 1, 1)
    a = effetti.inserisci_prima_di_mediaout(comp, comp.AddTool("Transform"))
    comp.FindTool("MediaOut1").Input = type("I", (), {"GetConnectedOutput": lambda s: type("O", (), {"GetTool": lambda s: a})()})()
    b = effetti.inserisci_prima_di_mediaout(comp, comp.AddTool("Blur"))
    assert b.collegati["Input"] is a and comp.FindTool("MediaOut1").collegati["Input"] is b


def test_clip_orizzontali(ambiente):
    r, t = ambiente
    t.tracce["video"][0][1].mpi = FintoMPI("H.MP4", res="3840x2160")
    assert effetti.clip_orizzontali()["orizzontali"][0]["nome"] == "C6595.MP4"


# ---------------------------------------------------------------- parlato

def test_segmenti_parlato():
    sil = [{"inizio_s": 1.0, "fine_s": 1.6, "durata_s": 0.6}, {"inizio_s": 3.0, "fine_s": 3.4, "durata_s": 0.4}]
    assert montaggio.segmenti_parlato(sil, 5.0, margine_s=0.05) == [[0.0, 1.05], [1.55, 3.05], [3.35, 5.0]]


def test_monta_parlato(ambiente):
    r, t = ambiente
    out = montaggio.monta_parlato("C6594.MP4", [[0.0, 1.0], [1.6, 2.0]], "REEL 016 parlato")
    assert out["segmenti"] == 2 and out["durata_frame"] == 35
    nuova = r.p.GetCurrentTimeline()
    v = nuova.GetItemListInTrack("video", 1)
    assert [(i.GetStart(), i.GetEnd()) for i in v] == [(90000, 90025), (90025, 90035)]
    with pytest.raises(ErroreToolkit, match="Esiste già"):
        montaggio.monta_parlato("C6594.MP4", [[0, 1]], "REEL 016 parlato")


# ---------------------------------------------------------------- musica

def test_griglia_fase_e_frasi():
    n = 96
    battiti = np.arange(n) * 0.5
    cambio = np.array([1.0 if (i - 1) % 4 == 0 else 0.1 for i in range(n)])  # primo battito alla fase 1
    novita = np.array([1.0 if (i - 9) % 32 == 0 else 0.1 for i in range(n)])  # frasi da 9
    g = musica.griglia_da_battiti(battiti, cambio, novita)
    assert g["fase_primo_battito"] == 1 and g["indici_frasi"][:2] == [9, 41]


def _griglia():
    b = [round(i * 0.5, 3) for i in range(160)]
    return {"battiti_s": b, "battute_s": b[::4], "frasi_s": b[::32], "durata_battito_s": 0.5,
            "inizio_vero_s": 0.0, "fine_vera_s": 80.0}


def test_verifica_taglio_e_piano_base():
    g = _griglia()
    assert musica.verifica_taglio(g, 16.01)["esito"] == "ok"
    assert musica.verifica_taglio(g, 16.1)["esito"] == "fuori_tempo"
    pb = musica.piano_base(g, 30.0)
    (a0, a1), (b0, b1) = pb["tratti_s"]
    assert a0 == 0.0 and b1 == 80.0 and a1 in g["frasi_s"] and b0 in g["frasi_s"]
    assert abs(pb["durata_s"] - 30.0) <= 8


def test_piano_raffica_regole():
    g = _griglia()
    clip = [{"nome": f"B{i}", "orientamento": "verticale", "durata_s": 2} for i in range(4)]
    out = musica.piano_raffica(g, 10.0, 12.0, clip)
    assert [p["clip"] for p in out["piano"]] == ["B0", "B1", "B2", "B3"]
    with pytest.raises(ErroreToolkit, match="ripetute"):
        musica.piano_raffica(g, 10, 12, clip + [clip[0]])
    with pytest.raises(ErroreToolkit, match="orizzontali"):
        musica.piano_raffica(g, 10, 12, [{"nome": "H", "orientamento": "orizzontale"}])
    with pytest.raises(ErroreToolkit, match="diverse"):
        musica.piano_raffica(g, 10, 14, clip)


def _scrivi_wav(path, y, sr):
    import wave
    pcm = (np.clip(y, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm.tobytes())


def _brano_sintetico(bpm, battute=40, sr=22050, partenza_s=0.8):
    """Cassa su ogni battito, accordo che cambia a ogni battuta, timbro che cambia ogni 8 battute."""
    periodo = 60 / bpm
    durata = partenza_s + battute * 4 * periodo + 2
    t_tot = np.arange(int(durata * sr)) / sr
    y = np.zeros_like(t_tot, dtype=np.float32)
    accordi = [(220, 277, 330), (196, 247, 294), (175, 220, 262), (165, 208, 247)]
    for k in range(battute * 4):
        t0 = partenza_s + k * periodo
        i = int(t0 * sr)
        n = int(0.12 * sr)
        tt = np.arange(n) / sr
        y[i:i + n] += 0.6 * np.sin(2 * np.pi * 60 * tt) * np.exp(-tt * 30)
        if k % 4 == 0:  # nuova battuta: nuovo accordo
            n2 = int(4 * periodo * sr)
            tt2 = np.arange(n2) / sr
            acc = accordi[(k // 4) % 4]
            seg = sum(np.sin(2 * np.pi * f * tt2) for f in acc) * 0.06
            if (k // 32) % 2 == 1:  # frase B: timbro più brillante
                seg = seg + 0.05 * np.sign(np.sin(2 * np.pi * acc[0] * 4 * tt2))
            y[i:i + n2] += seg[: len(y) - i]
    return y, sr, partenza_s, periodo


@pytest.mark.parametrize("bpm", [107.67, 124.0, 93.5])
def test_analizza_brano_numpy(tmp_path, bpm):
    y, sr, partenza, periodo = _brano_sintetico(bpm)
    path = tmp_path / "brano.wav"
    _scrivi_wav(path, y, sr)
    out = musica.analizza_brano(str(path), bpm_artlist=bpm)
    assert abs(out["bpm_misurato"] - bpm) < 0.1, out["bpm_misurato"]
    assert out["confronto_bpm"].startswith("coincide")
    # le battute devono cadere sui veri primi battiti (multipli di 4 battiti dalla partenza)
    for b in out["battute_s"][:6]:
        k = (b - partenza) / periodo
        assert abs(k - round(k / 4) * 4) < 0.15, (b, k)
    # almeno una frase rilevata su un vero inizio frase (ogni 32 battiti)
    assert any(abs(((f - partenza) / periodo) % 32) < 0.2 or abs(((f - partenza) / periodo) % 32 - 32) < 0.2
               for f in out["frasi_s"]), out["frasi_s"]
    assert abs(out["inizio_vero_s"] - partenza) < 0.1


# ---------------------------------------------------------------- lavoro

def test_passaggio_novita_audio(ambiente):
    lavoro.scrivi_passaggio("montaggio", ["tagli"], ["fotogrammi ai tagli"], ["color"], ["musica"], "abc")
    assert lavoro.leggi_passaggio()["ultima"]["fase"] == "montaggio"
    lavoro.registra_stile("prato", "016", "Anton bold giallo pop", ["punch_in", "flash"], ["whip"])
    assert lavoro.controlla_novita("Anton bold giallo pop", ["punch_in", "flash"], ["whip"])["esito"] == "troppo_simile"
    assert lavoro.controlla_novita("serif corsivo bianco fade", ["glow"], ["blur"])["esito"] == "ok"
    assert lavoro.chiudi_audio({"lufs_integrati": -14.1, "true_peak_dbtp": -1.2})["esito"] == "aperto"
    lavoro.registra_misure_audio(-16.0, -22.0, -18.0, "Fairlight Absolute Scale", voce_pulita=True)
    assert lavoro.chiudi_audio({"lufs_integrati": -14.1, "true_peak_dbtp": -1.2})["esito"] == "ok"
    assert lavoro.chiudi_audio({"lufs_integrati": -11.0, "true_peak_dbtp": -0.2})["esito"] == "aperto"


def test_cestino_solo_file_del_toolkit(ambiente):
    with pytest.raises(ErroreToolkit, match="via di Diego"):
        lavoro.sposta_nel_cestino(["/x"], "")
    with pytest.raises(ErroreToolkit, match="non li ha creati"):
        lavoro.sposta_nel_cestino(["/Volumes/Tokiro 01/girato.mov"], "Diego: cancella")
