"""Server MCP "resolve-toolkit": espone a Claude solo comandi con verifiche integrate.

Ogni risposta è un dizionario con "esito". Gli errori tornano come esito "bloccato" con il
motivo in italiano: Claude deve riportarlo a Diego, non aggirarlo.
"""
from __future__ import annotations

import functools
import traceback

try:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from . import (audio, avvio, color, config, effetti, grafiche, lavoro, montaggio, musica, operazioni,
               registro, regole, stato)
from .connessione import ErroreToolkit

ISTRUZIONI = (
    "Toolkit di Diego per DaVinci Resolve. Regole: 0) ogni reel parte da avvio_reel. "
    "1) Prima di ogni modifica chiama stato_timeline e passa la sua impronta; se un comando risponde "
    "BLOCCATO, rileggi e riparti dalla versione attuale. 2) Mai dire 'fatto' senza l'output di un comando "
    "di verifica (confronto, render_di_prova + verifica_render_prova, fotogrammi_ai_tagli, color_completa, "
    "chiudi_audio, controllo_consegna) e senza aver GUARDATO i frame. 3) Export solo su richiesta esplicita "
    "di Diego. 4) Color: si corregge solo nella pagina Color guardando gli scope sul PHL; dopo ogni ritocco "
    "segna_modifica_color, dopo ogni controllo registra_controllo_scope. 5) Nessuno stile fisso: grafiche, "
    "effetti e sottotitoli nuovi per ogni reel (controlla_novita). 6) A fine fase scrivi_passaggio. "
    "Rispondi a Diego sempre in italiano."
)

app = _Server("resolve-toolkit", instructions=ISTRUZIONI)


def comando(fn):
    @functools.wraps(fn)
    def avvolto(*args, **kwargs):
        try:
            esito = fn(*args, **kwargs)
        except ErroreToolkit as e:
            esito = {"esito": "bloccato", "motivo": str(e)}
        except Exception as e:  # errore imprevisto: mai inventare un risultato
            esito = {"esito": "errore", "motivo": f"{type(e).__name__}: {e}",
                     "dettaglio": traceback.format_exc(limit=3)}
        registro.scrivi(fn.__name__, kwargs, esito)
        return esito
    return app.tool()(avvolto)


@comando
def stato_timeline(nome_timeline: str = "") -> dict:
    """Legge tutte le tracce (video, audio, sottotitoli) e restituisce clip, offset e IMPRONTA.
    Da chiamare prima di ogni modifica: l'impronta serve agli altri comandi."""
    return {"esito": "ok", **stato.fotografia(nome_timeline or None)}


@comando
def elenca_timeline() -> dict:
    """Tutte le timeline del progetto con fps, inizio e fine."""
    return {"esito": "ok", "timeline": operazioni.elenca_timeline()}


@comando
def inserisci_clip(impronta: str, nome_clip: str, inizio_sorgente: int, fine_sorgente: int,
                   traccia: int, posizione: int, tipo: str = "video", cartella: str = "",
                   nome_timeline: str = "") -> dict:
    """Inserisce una clip del media pool. posizione = frame RELATIVI all'inizio timeline (0 = inizio).
    fine_sorgente escluso. Verifica da sola posizione e durata, annulla se sbagliate, e controlla
    che nessun'altra clip sia stata toccata. tipo: video | audio | entrambi."""
    return operazioni.inserisci_clip(impronta, nome_clip, inizio_sorgente, fine_sorgente, traccia,
                                     posizione, tipo, cartella or None, nome_timeline or None)


@comando
def backup_timeline(impronta: str, nome_timeline: str = "") -> dict:
    """Copia di sicurezza numerata (BACKUP nn). Si resta a lavorare sull'originale."""
    return operazioni.backup_timeline(impronta, nome_timeline or None)


@comando
def salva_fusion(impronta: str, cartella_comp: str, traccia: int = 1, nome_timeline: str = "") -> dict:
    """Dopo modifiche Fusion via API: export + import di ogni comp, altrimenti NON vengono renderizzate."""
    return operazioni.salva_fusion(impronta, cartella_comp, traccia, nome_timeline or None)


@comando
def isolamento_voce(impronta: str, traccia: int, attivo: bool = True, quantita: int = 100,
                    nome_timeline: str = "") -> dict:
    """Attiva o disattiva Voice Isolation su una traccia audio."""
    return operazioni.isolamento_voce(impronta, traccia, attivo, quantita, nome_timeline or None)


@comando
def fotogrammi_ai_tagli(cartella_uscita: str, traccia: int = 1, nome_timeline: str = "") -> dict:
    """Esporta ultimo frame prima e primo frame dopo ogni taglio della traccia video, da guardare tutti."""
    return operazioni.fotogrammi_ai_tagli(cartella_uscita, traccia, nome_timeline or None)


@comando
def render_sicuro(cartella: str, nome_file: str, conferma_diego: str, preset: str = "H.264 Master",
                  bitrate: int = 100000, mark_in: int = -1, mark_out: int = -1,
                  solo_audio: bool = False, nome_timeline: str = "") -> dict:
    """Render con la sequenza verificata. SOLO su richiesta esplicita: conferma_diego = sue parole.
    mark_in/mark_out in frame relativi (-1 = tutta la timeline)."""
    return operazioni.render_sicuro(cartella, nome_file, conferma_diego, preset, bitrate,
                                    None if mark_in < 0 else mark_in, None if mark_out < 0 else mark_out,
                                    solo_audio, nome_timeline=nome_timeline or None)


@comando
def misura_loudness(file: str) -> dict:
    """LUFS integrati, LRA e true peak misurati con ffmpeg sul file."""
    return {"esito": "ok", "file": file, **audio.misura_loudness(file)}


@comando
def trova_silenzi(file: str, soglia_db: float = -30.0, durata_min_s: float = 0.15) -> dict:
    """Pause nell'audio vero (silencedetect): da usare per tagliare tutti i silenzi dei parlati."""
    return {"esito": "ok", "file": file, **audio.trova_silenzi(file, soglia_db, durata_min_s)}


@comando
def controllo_consegna(file: str, larghezza: int = 1080, altezza: int = 1920,
                       lufs_obiettivo: float = -14.0, true_peak_max: float = -1.0) -> dict:
    """Controllo finale sul file esportato: risoluzione, fps, durata, LUFS, true peak, con esito per voce."""
    r = audio.controllo_consegna(file, larghezza, altezza, lufs_obiettivo, 1.0, true_peak_max)
    return {"esito": "ok" if r["tutto_ok"] else "da_correggere", **r}


# ================================================================ avvio, configurazione, regole

@comando
def avvio_reel(cliente: str = "") -> dict:
    """PRIMO comando di ogni reel: fps timeline/girato, cartella media, progetto salvato, skill da
    caricare, file cliente, passaggio della chat precedente. Finché ci sono problemi non montare."""
    return avvio.avvio_reel(cliente)


@comando
def sondaggio_api() -> dict:
    """Controlla quali funzioni dell'API esistono davvero su questo Mac e versione di Resolve."""
    return {"esito": "ok", **config.sondaggio()}


@comando
def regole_diego() -> dict:
    """Tutte le regole usate dai comandi (safe zone, LUFS, divieti, musica, silenzi)."""
    return {"esito": "ok", "regole": regole.regole(), "file_utente": regole.FILE_UTENTE}


# ================================================================ color

@comando
def stato_color(nome_timeline: str = "") -> dict:
    """Per clip: nodi, etichette, LUT, gruppo colore e dati sorgente; avvisa se la catena non è adatta alla sorgente."""
    return color.stato_color(nome_timeline or None)


@comando
def uniformita_color(nome_timeline: str = "") -> dict:
    """Misure su un frame per clip e clip fuori dalla mediana. Solo per sapere DOVE guardare gli scope."""
    return color.uniformita(nome_timeline or None)


@comando
def registra_controllo_scope(nome_clip: str, parade: str, waveform: str, vectorscope: str, esito: str,
                             pelle: str = "", rumore: str = "", screenshot: str = "", nome_timeline: str = "") -> dict:
    """Dopo aver GUARDATO gli scope di Resolve sul PHL per quella clip: scrivi i valori letti. esito: ok | da_correggere."""
    return color.registra_controllo_scope(nome_clip, parade, waveform, vectorscope, esito, pelle, rumore,
                                          screenshot, nome_timeline or None)


@comando
def segna_modifica_color(nome_clip: str, nome_timeline: str = "") -> dict:
    """Dopo OGNI ritocco a una clip in pagina Color: annulla il controllo scope precedente di quella clip."""
    return color.segna_modifica_color(nome_clip, nome_timeline or None)


@comando
def color_completa(nome_timeline: str = "") -> dict:
    """Cancello: la color è chiusa solo se ogni clip ha un controllo scope valido con esito ok."""
    return color.color_completa(nome_timeline or None)


@comando
def assegna_gruppo_colore(impronta: str, nome_gruppo: str, clip: list[str], crea_se_manca: bool = False,
                          nome_timeline: str = "") -> dict:
    """Assegna clip a un gruppo colore (per lavorare sul nodo Group Post-Clip)."""
    return color.assegna_gruppo_colore(impronta, nome_gruppo, clip, crea_se_manca, nome_timeline or None)


# ================================================================ grafiche e sottotitoli

@comando
def mappa_zone(nome_timeline: str = "", campioni_per_clip: int = 3, traccia: int = 1) -> dict:
    """Visi e scritte su frame reali della timeline (zoom compresi), fasce libere nella safe zone, anteprime da guardare."""
    return grafiche.mappa_zone(nome_timeline or None, campioni_per_clip, traccia)


@comando
def piano_sottotitoli(parole: list[dict], stile: dict, zone: dict, altezza_testo_px: float,
                      max_caratteri: int = 22) -> dict:
    """Righe, tempi e posizione dei sottotitoli (stessa altezza, di lato se c'è un viso/logo). stile obbligatorio."""
    return grafiche.piano_sottotitoli(parole, stile, zone, altezza_testo_px, max_caratteri)


@comando
def controllo_grafiche(frame: list[str]) -> dict:
    """Su frame del render di prova: testi dentro la safe zone e mai sopra i visi."""
    return grafiche.controllo_grafiche(frame)


@comando
def verifica_font(nome: str) -> dict:
    """Il font è installato sul Mac?"""
    return grafiche.verifica_font(nome)


@comando
def crea_titolo_fusion(impronta: str, indice_clip: int, testo: str, stile: dict, centro_px: list[float],
                       traccia: int = 1, nome_timeline: str = "") -> dict:
    """Text+ con Merge nella comp della clip, dentro la safe zone, comp salvata per il render."""
    return grafiche.crea_titolo_fusion(impronta, indice_clip, testo, stile, centro_px, traccia, nome_timeline or None)


# ================================================================ effetti, transizioni, reframe

@comando
def applica_effetto(impronta: str, indice_clip: int, effetto: str, parametri: dict, traccia: int = 1,
                    visi: list[dict] | None = None, nome_timeline: str = "") -> dict:
    """Effetto Fusion su una clip: punch_in (con controllo testa), shake, flash, whip, blur, glow, speed_ramp.
    Frame relativi alla clip. Comp salvata automaticamente. Drop Warp vietato."""
    return effetti.applica_effetto(impronta, indice_clip, effetto, parametri, traccia, visi, nome_timeline or None)


@comando
def transizione(impronta: str, indice_taglio: int, tipo: str, durata_frame: int = 8, traccia: int = 1,
                parametri: dict | None = None, nome_timeline: str = "") -> dict:
    """Transizione costruita in Fusion sulle due clip del taglio: whip, flash, zoom, blur."""
    return effetti.transizione(impronta, indice_taglio, tipo, durata_frame, traccia, parametri, nome_timeline or None)


@comando
def clip_orizzontali(nome_timeline: str = "") -> dict:
    """Clip orizzontali presenti: vanno adattate a pieno schermo verticale."""
    return effetti.clip_orizzontali(nome_timeline or None)


@comando
def smart_reframe(impronta: str, indici: list[int], traccia: int = 1, nome_timeline: str = "") -> dict:
    """Smart Reframe sulle clip indicate (poi mappa_zone per la testa)."""
    return effetti.smart_reframe(impronta, indici, traccia, nome_timeline or None)


@comando
def render_di_prova(mark_in: int, mark_out: int, solo_audio: bool = False, nome_timeline: str = "") -> dict:
    """Render di CONTROLLO di un tratto (frame relativi) nella cartella temporanea. Non è una consegna."""
    return operazioni.render_di_prova(mark_in, mark_out, solo_audio, nome_timeline or None)


@comando
def verifica_render_prova(file: str, tempi_s: list[float] | None = None) -> dict:
    """Frame neri/fermi e fotogrammi estratti ai tempi indicati, da guardare."""
    return audio.verifica_render_prova(file, tempi_s)


# ================================================================ parlato e musica

@comando
def proposta_tagli(file_audio: str, soglia_db: float = 0, durata_min_s: float = 0) -> dict:
    """Tratti parlati da tenere, misurati sull'audio vero (tutte le pause tolte). Da mostrare a Diego."""
    return montaggio.proposta_tagli(file_audio, soglia_db or None, durata_min_s or None)


@comando
def monta_parlato(nome_clip: str, segmenti_s: list[list[float]], nome_nuova_timeline: str,
                  traccia: int = 1, cartella: str = "") -> dict:
    """Timeline NUOVA con i soli tratti parlati, sui file originali, ogni inserimento verificato."""
    return montaggio.monta_parlato(nome_clip, segmenti_s, nome_nuova_timeline, traccia, cartella)


@comando
def timeline_alternative(riprese: list[dict], nome_timeline: str) -> dict:
    """Più riprese della stessa frase in fila con marker, per far scegliere Diego."""
    return montaggio.timeline_alternative(riprese, nome_timeline)


@comando
def trascrivi(file_audio: str, lingua: str = "it") -> dict:
    """whisper.cpp large-v3 sul Mac: parole con tempi (da correggere sull'audio e far rileggere a Diego)."""
    return montaggio.trascrivi(file_audio, lingua)


@comando
def analizza_brano(file: str, bpm_artlist: float = 0) -> dict:
    """BPM (confrontato con Artlist), battiti, primo battito della battuta, frasi da 8, vero inizio e vera fine."""
    return musica.analizza_brano(file, bpm_artlist or None)


@comando
def verifica_taglio_musica(griglia: dict, tempo_s: float, livello: str = "frase") -> dict:
    """Scarto di un taglio dalla griglia (frase | battuta | battito). Oltre 0,05 battiti: fuori tempo."""
    return musica.verifica_taglio(griglia, tempo_s, livello)


@comando
def piano_base(griglia: dict, durata_reel_s: float) -> dict:
    """Base con vero inizio e vera chiusura; se serve un salto, solo da inizio frase a inizio frase."""
    return musica.piano_base(griglia, durata_reel_s)


@comando
def piano_raffica(griglia: dict, da_s: float, a_s: float, clip: list[dict], battiti_per_clip: int = 1) -> dict:
    """B-roll a raffica sui battiti: mai ripetute, mai orizzontali, mai lunghe."""
    return musica.piano_raffica(griglia, da_s, a_s, clip, battiti_per_clip)


@comando
def livelli_nei_punti(file: str, tempi_s: list[float], finestra_s: float = 0.2) -> dict:
    """Picco e RMS attorno ai colpi (SFX contro musica)."""
    return audio.livelli_nei_punti(file, tempi_s, finestra_s)


@comando
def registra_misure_audio(voce_lufs: float, voce_pulita: bool, fonte: str, musica_lufs: float = 0,
                          sfx_lufs: float = 0) -> dict:
    """Numeri letti sul Loudness Meter Fairlight (Absolute Scale) traccia per traccia in solo."""
    return lavoro.registra_misure_audio(voce_lufs, musica_lufs or None, sfx_lufs or None, fonte, voce_pulita)


@comando
def chiudi_audio(file_mix: str) -> dict:
    """Cancello audio: misure Fairlight registrate, voce pulita, mix −14 LUFS / −1 dBTP misurato sul file."""
    return lavoro.chiudi_audio(audio.misura_loudness(file_mix))


# ================================================================ file, passaggi, stili

@comando
def elenca_file_creati() -> dict:
    """File di prova creati dal toolkit, da mostrare a Diego prima di qualsiasi pulizia."""
    return lavoro.elenca_file_creati()


@comando
def sposta_nel_cestino(file: list[str], conferma_diego: str) -> dict:
    """Sposta nel Cestino (recuperabile) solo file creati dal toolkit e solo col via di Diego."""
    return lavoro.sposta_nel_cestino(file, conferma_diego)


@comando
def importa_asset(percorsi: list[str], cartella_media_pool: str = "") -> dict:
    """Importa nel media pool asset scaricati da Diego, solo dall'archivio Tokiro 01/SFX."""
    return lavoro.importa_asset(percorsi, cartella_media_pool)


@comando
def salva_progetto(nome_deciso_da_diego: str) -> dict:
    """Salva il progetto aperto solo se ha già il nome deciso da Diego."""
    return lavoro.salva_progetto(nome_deciso_da_diego)


@comando
def scrivi_passaggio(fase: str, fatto: list[str], verificato: list[str], non_verificato: list[str],
                     manca: list[str], impronta: str = "") -> dict:
    """A fine fase: stato per la chat successiva (fatto, verificato, non verificato, manca)."""
    return lavoro.scrivi_passaggio(fase, fatto, verificato, non_verificato, manca, impronta)


@comando
def leggi_passaggio(nome_progetto: str = "") -> dict:
    """Ultimo passaggio scritto per il progetto aperto (o quello indicato)."""
    return {"esito": "ok", "passaggio": lavoro.leggi_passaggio(nome_progetto or None)}


@comando
def controlla_novita(sottotitoli: str, effetti: list[str], transizioni: list[str]) -> dict:
    """Avvisa se lo stile proposto somiglia a un reel già fatto (ogni reel è nuovo)."""
    return lavoro.controlla_novita(sottotitoli, effetti, transizioni)


@comando
def registra_stile(cliente: str, reel: str, sottotitoli: str, effetti: list[str], transizioni: list[str]) -> dict:
    """A reel consegnato: registra stile sottotitoli, effetti e transizioni usati."""
    return lavoro.registra_stile(cliente, reel, sottotitoli, effetti, transizioni)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
