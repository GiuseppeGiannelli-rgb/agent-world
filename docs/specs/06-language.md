# Spec 06 — Lingua globale (cinque lingue, inglese di default)

**In breve.** Si sceglie la lingua dell'app una volta sola: inglese (il default), italiano, spagnolo, francese o tedesco. All'inizio erano solo italiano e inglese, con l'italiano di default; l'estensione è nel §8. La scelta cambia:
- l'interfaccia, subito e senza ricaricare la pagina;
- la voce, cioè la sintesi vocale e la dettatura;
- la lingua in cui gli agenti ragionano, scrivono i log e rispondono;
- i messaggi di sistema che il backend manda via SSE.

Si salva in `config/local.json` come `ui.language` e vale fra una sessione e l'altra. Ogni run riceve la lingua nel payload e la tiene ferma fino alla fine.

Decisioni D1–D6 approvate dall'utente il 15/10/2026.

**Stato: fatta.** Backend, frontend e test ci sono tutti. Alla chiusura ho sistemato tre difetti trovati dalle verifiche, nessuno della lingua (§6, "Chiusura"). I risultati delle suite sono nel §7. Resta aperto il ticket N13; N14, N15 e N16 sono chiusi (§5).

## 1. Decisioni

| # | Decisione |
|---|---|
| D1 | La lingua si salva in `ui.language`, dentro `config/local.json` (con `POST /api/config`). `POST /api/runs` la riceve come `language` e la salva in `run.data["language"]`: cambiarla durante un run non tocca il run in corso. |
| D2 | La UI non ha un'opzione "Auto". Con `language` assente o `None`, i prompt tengono la regola di prima (la lingua del GOAL); è solo un fallback interno. |
| D3 | Le etichette dei team si traducono con un dizionario del frontend, indicizzato per id del team. Se un team non è nel dizionario, si usa `label` di config. |
| D4 | I messaggi di sistema e i log di `run.py` mandati via SSE si traducono: messaggi, testi dei fumetti, errori di task e workstream, titoli delle note del Brain (`Missione ·`, `Lezione ·`), feedback automatici. Gli errori HTTP restano in italiano: ticket **N13**. |
| D5 | I testi del provider demo (`router/mock.py`) non si toccano: in inglese la demo resta in italiano. Ticket **N14**, chiuso dopo: ora la demo parla la lingua della run (§5). |
| D6 | Branch `feat/spec06-language`, da `fix/start-port-message` (`809e0cb`). |

## 2. Contratto backend

**Lingue.** `backend/backend/i18n.py` contiene `LANGUAGES = {"it": "Italian", "en": "English"}`, il default `it`, `tr(lang, key, **vars)`, le tabelle `MESSAGES` per `it` ed `en` (stesse chiavi e stessi segnaposto) e `team_label(cfg, team, lang)`.

**Prompt.** `prompts.language_rule(lang)` sostituisce la costante `LANGUAGE`. Tutti i builder hanno il parametro `language=None`:
- `ceo_plan_prompt`
- `lead_plan_prompt`
- `advisor_prompt`
- `rescue_prompt`
- `librarian_prompt` (prima non aveva nessuna regola)
- `prompt_eng_prompt`
- `tasker_system`, che vale per worker e sub-agenti
- `judge_prompt`
- `synth_prompt`
- `chat_prompt` (prima: "nella lingua che usa l'utente")

Con una lingua scelta, la regola chiede di usare quella lingua per pensieri, messaggi, sintesi, report e testi consegnati, in qualunque lingua siano il GOAL o gli input. Le chiavi JSON, i valori fissi (`pass`, `revise`, `retry`, `skip`…) e i nomi dei tool restano come sono scritti: il parsing e il provider demo non cambiano. Una lingua sconosciuta solleva `ValueError`.

**Route.**
- `POST /api/runs`: `language` è opzionale. Un valore assente o `null` prende `ui.language` di config. Un valore fuori da `LANGUAGES` dà 400 (`"Lingua non supportata: …"`, in italiano, vedi N13).
- `POST /api/chat/:id`: usa la lingua del run attivo, se c'è, altrimenti `ui.language`.
- `POST /api/config`: `ui` è fra le chiavi modificabili (`EDITABLE`), e `/api/state` e `/api/config` la espongono. Dà 400 (`"Lingua non supportata: …"`) e non scrive niente se `ui` non è un oggetto o se `ui.language` non è una stringa di `LANGUAGES`.

**Run.** `Run(options={"language": …})` salva la lingua in `data["language"]` e la passa a ogni builder e a ogni `tr()`.

## 3. Frontend

- `public/js/i18n.js` contiene i dizionari `it`/`en`, `t(key, vars)`, `LOCALE = {it: 'it-IT', en: 'en-US'}` e le etichette dei team.
- Il selettore della lingua sta nella modale Impostazioni e, in forma compatta, nella topbar.
- Quando la lingua cambia:
  - si salva con `POST /api/config` (`{ui: {language}}`);
  - `<html lang>` si aggiorna;
  - si chiama `invalidate(...ALL)`;
  - i testi statici di `index.html` (marcati con `data-i18n`) si riscrivono.
- `say()`, `listen()` e le date usano `LOCALE[lang]`.
- `POST /api/runs` manda `language`.

## 4. Test (scritti prima del codice, visti rossi)

**Python**
- `test_prompts.py`: in ogni builder e in entrambe le lingue, il system prompt contiene la regola; con `None` resta la regola di prima; una lingua sconosciuta dà errore; il mock legge ancora i prompt.
- `test_i18n.py`: `it` ed `en` hanno le stesse chiavi e gli stessi segnaposto.
- `test_runs.py`: `language` arriva nelle options; senza `language` vale quella di config; un valore non valido dà 400; la chat usa la lingua giusta.
- `test_config.py`: `ui.language` si salva in `local.json` ed è pubblica.
- `test_run.py`: un run demo in `en` manda la regola "English" in **ogni** chiamata al modello. Nessun messaggio, fumetto, errore o titolo del Brain contiene i pezzi fissi dei testi italiani di `MESSAGES["it"]`.

**Node/browser**
- Il cambio di lingua aggiorna la UI senza reload.
- Il payload del run contiene `language`.
- `utterance.lang` vale `en-US`.
- La scelta resta dopo un reload.

## 5. Ticket aperti

- **N13**: errori HTTP del backend ancora in italiano.
- **N14**: testi del provider demo solo in italiano.
  - **Chiuso il 16/10/2026** (branch `feat/n14-demo-language`, decisioni D1–D3 dell'utente).
    - **D1, la lingua dalla regola.** `mock.language_of()` legge il nome della lingua dalla regola che `language_rule()` mette in ogni system prompt. Il pezzo di regola prima del nome lo prende da `prompts.py`, così se il testo cambia il mock lo segue. Ai modelli veri non arriva niente di nuovo.
    - **D2, inglese di riserva.** Con la regola di prima (nessuna lingua scelta) il mock risponde in inglese, il default del progetto.
    - **D3, cinque lingue.** I testi stanno in `router/mock_texts.py`: una tabella per lingua, con la forma di quella inglese. La tabella italiana ha esattamente i testi di prima. Forme JSON, nomi dei tool, percorsi dei file e hash (che decidono revisioni, domande al lead e lezioni) sono uguali in ogni lingua.
    - **Le parole chiave della missione.** `ceo_plan()` capisce dalle parole del GOAL se è un sito o un documento, se è semplice o complesso, se servono immagini e voce. Prima conosceva solo le parole italiane e qualcuna inglese, ora quelle delle cinque lingue: lo stesso GOAL dà lo stesso piano in ogni lingua. Resta la regola della lunghezza (oltre 80 caratteri è complesso), quindi un GOAL tedesco, più lungo, può diventare complesso prima.
    - **La pagina** generata dichiara la lingua della run in `<html lang>` (prima sempre `it`), e le ancore sono `#services` e `#contact` invece di `#servizi` e `#contatti`.
    - **Resta in inglese** il prompt per le immagini: lo legge il modello di immagini, non l'utente.
    - **Test, visti rossi prima del codice:**
      - `test_mock_language.py` (31 test). Le tabelle hanno tutte la stessa forma e sono tradotte davvero: al massimo il 15% dei testi uguali all'inglese. `language_of()` riconosce ogni lingua, e con la regola di prima dà `None`. Lo stesso GOAL scritto nelle cinque lingue dà lo stesso piano, in quattro tipi di missione; uno di questi è un GOAL corto, complesso solo per la parola "completo". Ogni ruolo risponde nella lingua della run. La pagina dichiara la sua lingua. La tabella inglese non contiene italiano.
      - `test_prompts.py`: il mock legge la lingua dal system prompt di ogni builder, nelle cinque lingue e con `None`.
      - `test_run.py`, `TestDemoRunInEveryLanguage`: una missione demo intera per lingua. Ogni chiamata porta la regola della run. Messaggi, fumetti, storie dei task, note del Brain, report, piano e file `.md` e `.html` non contengono pezzi fissi (di almeno 12 caratteri) delle altre lingue, né di `MESSAGES` né di `MOCK_TEXTS`. Prima di N14 il test doveva togliere le parole del modello (§6). Il report di `test_demo_run_completes_end_to_end` ora comincia con `# Final report`.
    - **Mutazioni.** I test diventano rossi in ognuno di questi casi:
      - `language_of()` ignorato;
      - pensieri dei worker, feedback del judge, file markdown o piano del lead sempre in italiano;
      - `<html lang="it">` fisso;
      - `compl[eèé]t` ridotto a `complet`, `komplett` o `\bbild` tolti;
      - l'inizio della regola cambiato.
- **N15**: `test_state.py::test_api_config_post_updates_and_emits` scrive nel vero `config/local.json` (per questo lì c'è `limits.maxParallel = 3`). Va isolato su una cartella temporanea. È un problema preesistente, fuori da questa spec. Lo fanno anche i due test di `test_events.py` che chiamano `POST /api/config` (`maxParallel` 1…5): `live_server` crea l'app con il `Config` del repo.
  - **Chiuso il 16/10/2026** (branch `fix/n15-test-isolation`, decisioni D1–D3 dell'utente).
    - **Le fonti misurate erano quattro:**
      1. `test_state.py` (fixture con `Config(ROOT / "config")` e `POST /api/config`);
      2. `test_events.py` (`create_app()` senza `config=`);
      3. `test_runs.py` (6 log del router in `data/calls/` del repo, perché `AGENT_WORLD_HOME` non era impostato);
      4. il lifespan, che su un clone nuovo faceva `git clone` delle `skills.repos` in `skills/vendor/`.

      Al contrario, i test leggevano anche le preferenze dell'utente.
    - **Soluzione: i default distribuiti restano nel repo, le preferenze si spostano.**
      - `Config(dir, local_file=None)` cerca il file in quest'ordine: `local_file`, poi `AGENT_WORLD_LOCAL_CONFIG`, poi `dir/local.json`. In produzione non cambia niente.
      - `AGENT_WORLD_SKILL_REPOS=0` salta il clone all'avvio.
      - `conftest.py` imposta per ogni test (fixture autouse) un file di preferenze vuoto e una `AGENT_WORLD_HOME` sua, e per tutta la sessione `AGENT_WORLD_SKILL_REPOS=0`.
      - `demoEnv()` fa lo stesso per i server degli script Node e rifiuta di partire senza `AGENT_WORLD_HOME`.
    - **Test, visti rossi prima della correzione:**
      - la guardia di sessione in `conftest.py` fotografa `config/local.json`, `data/` e `skills/vendor/` e fa fallire la suite se un test li tocca. Prima della correzione elencava `local.json` e i 6 log;
      - `test_isolation.py` ha 9 test: 7 rossi, uno per fonte, più la precedenza;
      - `scripts/launcher-test.js`, in `npm test`: un server avviato con `demoEnv()` aveva scritto `maxParallel: 7` nel file dell'utente;
      - fase browser `language`, L9: il file dell'utente non viene mai scritto. La fase non salva più né ripristina `config/local.json`, e L1 verifica sempre il default inglese.
    - **Mutazioni:** con ognuna delle quattro difese tolta, i test diventano rossi. Per le tre sull'isolamento si accende anche la guardia; per l'interruttore del clone basta il suo test, che usa un `vendor/` temporaneo.
    - **Limite noto:** la guardia vede anche le scritture dell'app, se l'app gira dalla stessa cartella mentre passano i test.
- **N16**: test che passano solo su Windows. Su Linux sono rossi anche su `main`, quindi non c'entrano con questa spec.
  - `test_static.py::test_traversal_forbidden[/..\..\server\index.js]` e `test_tools.py::TestWorkspace::test_resolve_keeps_paths_inside_the_root` (`..\..\x`, `C:/Windows/x`). Su Linux `\` non separa i percorsi e `C:` non è un drive: `..\..\x` è il nome di un file dentro la cartella del progetto, quindi niente esce dalla radice. Il contenimento regge, ma i test si aspettano il rifiuto che fa Windows. Strade possibili: rifiutare `\` e `X:` su ogni sistema, così la regola è una sola e i workspace restano portabili; oppure separare le attese per piattaforma.
  - `temp-test.js` C3, "a killed smoke leaves its folder": uccide lo smoke con `taskkill /PID … /F`, che su Linux non esiste. Lo smoke non viene ucciso, finisce da solo e pulisce la sua cartella (`leftByTheKill: false`). Fuori da Windows serve un kill forzato equivalente (`SIGKILL`).
  - Altre ipotesi di Windows trovate qui: `scripts/lib/backend-launcher.js` cerca solo `backend/.venv/Scripts/python.exe` (su Linux e macOS è `.venv/bin/python`), e `scripts/browser/headless.js` trova solo Edge o Chrome installati. Per le verifiche del §7 ho usato un symlink dentro `.venv` (ignorato da git) e `BROWSER` puntato a Chromium con `--no-sandbox`.
  - **Chiuso il 16/10/2026** (branch `fix/n16-cross-platform`, decisioni D1–D4 dell'utente). Erano test e codice che davano Windows per scontato: passavano su Windows e fallivano su Linux e macOS.
    - **Percorsi (D1, D2 opzione b): una regola sola su ogni sistema**, in `backend/backend/paths.py`, usata da `Workspace.resolve()` e dalle route statiche.
      - `\` separa come `/`;
      - le `/` iniziali si tolgono, quindi `/etc/passwd` resta dentro (il contratto di Node);
      - un drive (`C:/x`, `c:x`) è "fuori dalla cartella del progetto";
      - ogni altro `:` è rifiutato con un messaggio che dice all'agente cosa cambiare. Su Windows era uno stream NTFS nascosto, e un nome con `:` non si copia su Windows;
      - un byte NUL è rifiutato. Prima `pathlib` sollevava un `ValueError` qualunque, e le route statiche rispondevano 500 (succedeva già prima di N16);
      - il contenimento si controlla per parti del percorso (`is_relative_to`), non con il prefisso della stringa.

      Prima la regola la decideva `pathlib`, cioè il sistema: lo stesso output dell'agente faceva cartelle diverse (`a\b.md` annidato su Windows, un nome strano altrove). È la stessa regola di `downloads.safe_relpath()`, che c'era già.
    - **Kill forzato.** `hardKill()` in `scripts/lib/temp.js` fa `taskkill /F` su Windows (con `/T` per l'albero) e `SIGKILL` altrove. Lo usano `temp-test`, `browser-test` e `headless.js`, che avevano ognuno la sua versione; `temp-test` chiamava `taskkill` ovunque, anche nel limite di tempo di `runScript`.
    - **Server orfano (D3).** Trovato correggendo C3. Il server di test era legato al suo script solo dalla pipe di stdout: moriva alla prima scrittura dopo la morte dello script.
      - Ucciso durante l'avvio, moriva sulla riga di pronto, ma su Linux rispondeva ancora una volta a +1,7 s. C3 guardava a +0,5 s: passava per tempismo.
      - Ucciso a server pronto, non moriva più: dopo 15 s teneva ancora la porta 4399 e scriveva nella cartella che il test successivo cancella.

      Ora `spawnBackend()` (`scripts/lib/backend-launcher.js`) avvia il server per tutti e sei gli script, con uno stdin a pipe e `AGENT_WORLD_EXIT_WITH_PARENT=1`. Il server si chiude in modo pulito quando la pipe si chiude, cosa che il sistema fa alla morte dello script, comunque venga ucciso. Con il flag ma senza pipe il server non parte, invece di riportare gli orfani in silenzio. `npm start` non lo imposta.
    - **Launcher (D4).** `.venv/Scripts/python.exe` su Windows, `.venv/bin/python` altrove. Il symlink del §7 non serve più ed è stato tolto. `headless.js` resta com'è: cerca già i percorsi standard di macOS e Linux, e accetta `BROWSER`.
    - **Test, visti rossi su Linux prima della correzione:**
      - `test_paths.py`: una tabella di casi con le stesse attese su ogni sistema, contro tutti e due i chiamanti;
      - `test_static.py`: un URL con `\` serve il file, un `:` o un NUL dà 403. I due test N16 di `test_static.py` e `test_tools.py` diventano verdi senza modifiche;
      - `test_main.py`: un server con il flag si chiude quando si chiude il suo stdin; senza il flag non cambia niente; il flag senza pipe è rifiutato;
      - `launcher-test.js`: il Python del venv di questo sistema, e `spawnBackend()` che lega il server allo script;
      - `temp-test.js`: un test oltre il suo limite di tempo viene davvero terminato; C3 guarda il server per una finestra di 5 s invece che in un istante; il nuovo C4 uccide uno smoke a server pronto e non deve restare nessun server.
    - **Mutazioni.** I test diventano rossi in ognuno di questi casi:
      - il separatore `\`, il controllo del drive, quello dei `:` o il contenimento tolti;
      - `hardKill` senza `SIGKILL`;
      - il server che non guarda lo stdin;
      - `spawnBackend` senza pipe;
      - il percorso del venv solo Windows;
      - il controllo della pipe sempre vero.

      Con il server che non guarda lo stdin diventa rosso solo C4: un server ucciso all'avvio muore comunque sulla riga di pronto.
    - **Verifica su Windows:** non l'ho fatta, va fatta sulla macchina di riferimento.

## 6. Scostamenti

**Backend (15/10/2026)**
- `run.data` ha un campo nuovo, `language`. Quindi la forma "Node" del run, controllata da `TestDataShape`, ora ha una chiave in più.
- D3 vale anche per il backend: `i18n.TEAM_LABELS` traduce in inglese le etichette dei team negli elenchi che `run.py` scrive (piano, richiesta di approvazione). Se un team non è nella tabella, si usa `label` di config, come nel frontend.
- `POST /api/config` rifiuta con 400 un `ui.language` non supportato, prima di scrivere `local.json`.
- Il tag `missione` delle note del Brain resta così: è un identificativo, non un testo da mostrare.
- Il test anti-italiano del run in inglese prima toglie dai testi quello che ha scritto il modello, cioè il provider demo (D5): controlla solo le parole del backend. Con N14 il taglio non serve più: il test controlla tutto, in ogni lingua (§5). Ho provato che può fallire con due mutazioni:
  - `"Consegnato!"` rimesso come testo fisso;
  - `language` tolto dalla chiamata del judge.

  In entrambi i casi il test è diventato rosso.
- La demo non passa da `rescue` e da `advise`: per quei due builder la regola della lingua è coperta dai test dei prompt, non dal run end-to-end.

**Frontend (15/10/2026)**
- Quando cambia la lingua, `world.build()` non viene chiamato, perché ricostruirebbe la scena e riporterebbe ogni agente alla scrivania a metà run. Al suo posto c'è `World.relabel()`, che cambia solo i testi delle etichette delle stanze e del Brain.
- La lingua si applica a ogni evento `config`: una scelta fatta in un'altra scheda arriva anche a questa.
- Il selettore delle Impostazioni manda `ui.language` insieme alle altre impostazioni. Quello della topbar la salva subito.
- Fase browser `language` (L1–L7) in `scripts/browser-test.js`:
  - il server di prova legge il `config/` del repo, quindi la fase salva `config/local.json` e alla fine lo rimette identico (verificato con `diff`);
  - la richiesta del run e la voce sono simulate dentro la pagina: non parte nessuna missione e nessun audio;
  - ho provato che i controlli possono fallire con tre mutazioni: senza `language` nel payload diventa rosso L4, con `u.lang = 'it-IT'` diventa rosso L5, senza `relabel()` diventa rosso L2. In ogni caso è diventato rosso solo il controllo atteso.
- `brief` e `title` dei team sono già in inglese in `default.json` e restano come sono. Il titolo del CEO (`ceo.title`, "CEO · Regia") si traduce come le etichette dei team (D3): la chiave `team.ceo.title` c'è solo in inglese, e in italiano si usa il valore di config.

**Chiusura (15/10/2026).** Tre difetti trovati dalle verifiche, nessuno della lingua. Ognuno ha il suo commit con il test visto rosso prima della correzione.
- `df7ef3c` — `test_events.py::test_config_post_produces_sse_frame` voleva il frame `config` subito dopo `retry`, con `seq` 1. La reindicizzazione dello Skill Hub all'avvio però emette `skills` sullo stesso bus, e su una macchina veloce arriva prima. Era rosso anche su `main`. Ora il test salta gli altri frame, come già faceva `test_ping_on_idle`, e controlla che `seq` cresca. Con l'evento `config` rinominato diventa rosso in circa 6 s, invece di restare appeso ad aspettare i ping da 15 s.
- `ca94b53` — due difetti del controllo della porta occupata (`809e0cb`), visti su Linux, dove `flows-test.js` falliva con "fetch failed" subito dopo `backend-boot-test.js` (stessa porta, 4398):
  - il bind di prova non usava `SO_REUSEADDR`, quindi le connessioni in TIME_WAIT di un server appena chiuso risultavano "occupate", mentre uvicorn avrebbe fatto il bind senza problemi. Ora il bind di prova fa come uvicorn. Su Windows `SO_REUSEADDR` resta spento, perché lì permetterebbe di fare il bind sopra un listener vivo;
  - il messaggio cominciava con `Agent World  →`, cioè la riga di avvio che gli script aspettano su stdout, e così i test andavano avanti contro un server mai partito. Ora va su stderr e senza quel prefisso.
- `402896d` — `POST /api/config` con `ui.language` lista o oggetto: `x in LANGUAGES` sollevava `TypeError` e la risposta era 500. Ora si controlla prima il tipo, come faceva già `POST /api/runs`, e la risposta è 400.

## 7. Verifiche finali (15/10/2026)

Fatte su Linux (container cloud), quindi non sulla macchina Windows di riferimento. Per ogni rosso ho rifatto lo stesso controllo su `main`, nello stesso ambiente.

| Suite | Risultato | I rossi |
|---|---|---|
| `pytest` | 355 passati, 3 saltati, 2 rossi | i 2 test di percorsi Windows (N16), rossi anche su `main`. I saltati: `aw_core` non compilato (×2) e il clash di maiuscole, che esiste solo su volumi case-insensitive |
| `world-test`, `backend-boot-test`, `smoke`, `flows-test`, `secret-scan-test` | tutti `ALL OK` / `OK` | — |
| `temp-test` | 1 rosso | C3 (N16), rosso anche su `main` |
| `browser-test`, completo | 234 ok, 8 rossi | vedi sotto |
| `browser-test --only language`, dopo le correzioni della chiusura | `ALL OK` (L1–L7) | — |

**Gli 8 rossi della suite browser:**
- `views` ×4 ("floor under the UI", a 2560×1440 e 1440×900, con i pannelli LR e -R);
- `input` ×2 ("a real drag…", "a real click on an agent…");
- D8 ("painted bay text covered at most 27%": 30,9%);
- A10 (ticket N12, chiuso dopo con la correzione in `world.js`: vedi spec 05, §6).

Con `--only views,input,labels`, su `main` sono rossi gli stessi 7 controlli (tutti tranne A10, che sta nella fase `run`), con valori vicini. Quindi dipendono dall'ambiente (Chromium headless con SwiftShader a circa 3 fps, font di Linux) e non da questa spec. Il riferimento resta `npm run test:browser` su Windows.

## 8. Estensione: cinque lingue, inglese di default (15/10/2026)

Richiesta dall'utente dopo il merge in `main`: spagnolo, francese e tedesco, e il sito in inglese di default.

**Backend**
- `i18n.py`: `LANGUAGES = {"en", "it", "es", "fr", "de"}`, con l'inglese primo; `DEFAULT = "en"`. Le tabelle `MESSAGES` es/fr/de hanno le chiavi e i segnaposto dell'inglese, che è il riferimento. `TEAM_LABELS` ha en/es/fr/de; l'italiano non ce l'ha, perché le etichette di `default.json` sono già in italiano (D3).
- `config/default.json` passa a `"ui": {"language": "en"}`, e `config.py` prende il default da `i18n.DEFAULT`.
- Un run senza lingua (`None`) scrive i suoi messaggi in inglese. I prompt, invece, tengono la regola di prima (la lingua del GOAL, D2).
- `language_rule()` non è cambiata: legge il nome da `LANGUAGES` ("Spanish", "French", "German").

**Frontend**
- `i18n.js`: `LANGS` (en, it, es, fr, de, ognuna nel suo nome), `DEFAULT_LANG = 'en'`, voci `es-ES`, `fr-FR`, `de-DE`. Il fallback di `t()` e `label()` è l'inglese.
- Il selettore della topbar si costruisce da `LANGS` (EN, IT, ES, FR, DE, con il nome come tooltip); quello delle Impostazioni lo faceva già.
- `index.html` ha `lang="en"` e i testi statici in inglese: prima che `main.js` parta non si vede l'italiano.
- La barra delle tab ora va a capo (`flex-wrap`), e il padding orizzontale delle tab scende da 9 a 5 px. Con lo scroll orizzontale e la scrollbar nascosta, una lingua più lunga nascondeva l'ultima tab: con i font di Linux succedeva già in italiano (18 px) e in inglese (42 px). Adesso en, it, es e fr stanno su una riga; il tedesco va su due, con "Output" da solo.

**`config/local.json`.** Non si tocca: contiene solo le scelte dell'utente. Chi aveva già salvato `"ui": {"language": "it"}` resta in italiano finché non cambia lingua.

**Test**
- `test_i18n.py`: le cinque lingue, l'inglese come default; chiavi e segnaposto uguali in ogni tabella; ogni tabella tradotta davvero (al massimo 3 testi uguali all'inglese); `TEAM_LABELS` completo; e il controllo incrociato: i codici di `LANGS` in `i18n.js` sono quelli di `LANGUAGES`, nello stesso ordine.
- Aggiornati per il default inglese e per `fr`, che ora è valido (al suo posto `xx`): `test_config.py`, `test_run.py`, `test_prompts.py` (la regola in tutte e cinque le lingue), `test_runs.py`, `test_state.py`.
- `flows-test.js`: il run rifiutato ora passa `language: 'en'` e si aspetta "Plan rejected". Prima ereditava la lingua di config, quindi l'esito dipendeva dal `local.json` di chi lancia i test.
- Nuovo `scripts/i18n-test.js`, dentro `npm test`. Controlla le chiavi e i segnaposto di ogni dizionario contro l'inglese, una traduzione vera (al massimo il 15% dei testi uguali all'inglese), una voce `xx-XX` per lingua, il fallback all'inglese, e che `index.html` porti le parole inglesi del dizionario. Ho provato tre mutazioni (una chiave tedesca tolta, un segnaposto francese cambiato, il pulsante di `index.html` rimesso in italiano): ognuna fa diventare rosso solo il suo controllo.
- Fase browser `language`, riscritta per le cinque lingue. I valori attesi li legge dai dizionari della pagina.
  - L1: il default è l'inglese (o la lingua di `config/local.json`) e il selettore elenca le cinque lingue.
  - L2: ogni lingua riscrive la UI, le etichette 3D e la lavagna senza reload.
  - L3: la scelta resta dopo un reload.
  - L4: il payload del run porta la lingua.
  - L5: la voce usa `de-DE`.
  - L6: l'italiano riporta le etichette di config.
  - L7: il selettore delle Impostazioni elenca le cinque lingue.
  - L8 (nuovo): in ogni lingua ogni tab è tutta visibile e la topbar non va in overflow, a 1920×1080 e 1440×900. Senza la correzione del CSS L8 è rosso (1–2 tab tagliate in ogni lingua).

**Restano aperti:** N13 (errori HTTP in italiano). N14 (simulatore demo in italiano) è chiuso il 16/10/2026: la demo parla la lingua della run, e senza lingua l'inglese (§5).

