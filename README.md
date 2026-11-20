# Resolve Toolkit 0.2

Collegamento tra Claude e DaVinci Resolve Studio, fatto per Diego Colucci. Le operazioni ripetute hanno dentro le regole e le verifiche, così non dipendono più dalla memoria di Claude.

## Principi

- **Lucchetto:** ogni comando che modifica vuole l'impronta letta con `stato_timeline`. Se Diego ha cambiato la timeline, il comando risponde "BLOCCATO".
- **Verifica dentro il comando:** dopo ogni modifica rilegge e confronta il prima e il dopo. Se qualcosa non torna, annulla.
- **Cancelli:** color, audio e consegna si chiudono solo con prove registrate (scope letti, misure Fairlight, numeri sul file).
- **Nessuno stile fisso:** grafiche, effetti e sottotitoli sono nuovi per ogni reel. `controlla_novita` avvisa se si ricicla.
- **Regole in un posto solo:** `regole.py`, sovrascrivibile da `~/Library/Application Support/ResolveToolkit/regole.json`.
- **Autocalibrazione e sondaggio:** convenzioni dell'API misurate al primo uso, funzioni disponibili controllate su ogni Mac.
- **Registro e passaggi:** ogni comando finisce in `~/Library/Logs/ResolveToolkit/`. A fine fase `scrivi_passaggio` lascia lo stato per la chat successiva.

## Comandi (52)

| Area | Comandi |
|---|---|
| Avvio | `avvio_reel`, `sondaggio_api`, `regole_diego`, `elenca_timeline`, `stato_timeline` |
| Montaggio | `inserisci_clip`, `sostituisci_clip`, `backup_timeline`, `proposta_tagli`, `monta_parlato`, `timeline_alternative`, `trascrivi`, `fotogrammi_ai_tagli` |
| Color | `stato_color`, `uniformita_color`, `registra_controllo_scope`, `segna_modifica_color`, `color_completa`, `assegna_gruppo_colore` |
| Grafiche | `mappa_zone`, `piano_sottotitoli`, `crea_titolo_fusion`, `controllo_grafiche`, `verifica_font` |
| Effetti | `applica_effetto` (punch_in, shake, flash, whip, blur, glow, speed_ramp), `transizione` (whip, flash, zoom, blur), `salva_fusion`, `clip_orizzontali`, `smart_reframe` |
| Musica | `analizza_brano`, `verifica_taglio_musica`, `piano_base`, `piano_raffica` |
| Audio | `isolamento_voce`, `misura_loudness`, `trova_silenzi`, `livelli_nei_punti`, `registra_misure_audio`, `chiudi_audio` |
| Verifica | `render_di_prova`, `verifica_render_prova`, `controllo_consegna` |
| Export | `render_sicuro` (solo con le parole di Diego; formato/codec/risoluzione, es. MP4 4K 2160x3840), `stato_render` |
| Lavoro | `elenca_file_creati`, `sposta_nel_cestino`, `importa_asset`, `salva_progetto`, `scrivi_passaggio`, `leggi_passaggio`, `controlla_novita`, `registra_stile` |

## Novità 0.2.3 (20 nov 2026, dopo REEL 003 Piero Angela)

- `render_sicuro`: Export Video e Export Audio sempre impostati (prima il Deliver ricordava "video spento" dall'ultimo render audio e uscivano file solo audio); parametri formato, codec, larghezza, altezza per il 4K MP4; i render lunghi rispondono "in_corso" entro ~55 s e si seguono con `stato_render` (prima superavano il limite di 80 s del collegamento); se non parte riprova da Edit con un job nuovo.
- `inserisci_clip`: la fine viene troncata alla lunghezza vera della clip; se Resolve rifiuta, prova le altre convenzioni prima di arrendersi.
- `sostituisci_clip`: nuova versione di un overlay nella stessa traccia e posizione.
- `trascrivi`: whisper gira in background; si richiama con lo stesso file finché dà il testo; accetta anche mov/mp4.
- `uniformita_color`: misura ogni clip in un punto dove è davvero visibile (non sotto un B-roll); le clip coperte del tutto sono elencate a parte. Restituisce etichette e id.
- `registra_controllo_scope` / `segna_modifica_color`: accettano id, etichetta `V1_003_nome` o nome (con nomi doppi le registra tutte e avvisa).
- `importa_asset`: anche dalle cartelle dei progetti (overlay in `REEL xxx/_claude`).
- Export dei frame: secondo tentativo da Edit.
- `stato_color`: avviso sui progetti YRGB non gestiti (esposizione con Offset in "Use timeline", non Gain in Linear).

## Cosa resta nella UI di Resolve (non esiste nell'API)

- Lettura degli scope; ruote, curve, qualifier, riduzione rumore: pagina Color, controllo dello schermo, poi `registra_controllo_scope`.
- Transizioni native di Resolve.
- Fader delle tracce e Loudness Meter di Fairlight; AI Audio Assistant.

## Installazione

1. Scarica `ResolveToolkit-x.y.z.pkg` da Releases (o dagli Artifacts di GitHub Actions).
2. Il pacchetto non è firmato: tasto destro sul file > Apri > Apri.
3. Riavvia Claude Desktop: compare `resolve-toolkit`.
4. Log: `~/Library/Logs/ResolveToolkit/installazione.log`.

Requisiti: Resolve Studio aperto, Preferenze > Generale > "External scripting using" = Local, Python 3.10+, ffmpeg (vendor di Tokiro 01, Homebrew, `/usr/local/bin` o `RESOLVE_TOOLKIT_FFMPEG`).

## Primo collaudo dal vivo

1. `sondaggio_api`, poi `avvio_reel` su un progetto di prova.
2. `inserisci_clip` di una clip corta (si calibra da solo), controllo a schermo.
3. `applica_effetto` punch_in + `render_di_prova` + `verifica_render_prova`: l'effetto si vede nel render?
4. `mappa_zone`: rileva visi e scritte? Apple Vision attivo?
5. `stato_color`: legge nodi ed etichette?
6. `analizza_brano` su una base Artlist col BPM noto.

## Sviluppo

```
pip install "mcp>=1.2" numpy pillow librosa soundfile opencv-python-headless pytest
python -m pytest -q tests
```
