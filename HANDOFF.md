# HANDOFF — Agent World

*Aggiornato il 2026-10-18, sera. In breve:*
- *`main` = `67f98c7`: la PR #6 (spec 09) è unita. Le spec 01–09 sono chiuse (la 03 congelata dopo T2).*
- *Branch `claude/tech-debt-i18n-browser-docs-519081`, da `main`, per il debito tecnico rimasto:*
  - *N13 chiuso: gli errori HTTP seguono la lingua dell'app;*
  - *i rossi di `views` e `input` del runner del browser venivano dalle attese a tempo fisso: ora contano i frame;*
  - *questo file e il README descrivono il sistema di oggi.*
- *Da decidere per l'utente: `npm run scan:secrets` trova l'identità vera nei 5 commit di merge che GitHub ha creato per le PR (sezione 1).*
- *Lo stato dettagliato e le verifiche sono in fondo, in "Stato al 18/10/2026, sera".*

## 1. Stato

- **Repo:** questa cartella (`agent-world/`), remote `origin` su GitHub. L'indirizzo è in `git remote -v`; qui non si scrive il nome dell'account. `../Claudio` è un altro repo e non va toccato.
- **Il sistema di oggi:**
  - backend FastAPI (Python 3.13, uv, un solo processo uvicorn) in `backend/`;
  - acceleratore Rust opzionale in `crates/aw_core` (PyO3);
  - front-end three.js senza build in `public/`.
  
  Il server Node (`server/`) non c'è più dalla P7 della spec 04.
- **Spec chiuse e unite in `main`**, tutte con i documenti in `docs/specs/`:
  - 01 inquadratura dell'ufficio;
  - 02 sovrapposizioni della UI;
  - 03 stabilità della memoria (congelata dopo T2);
  - 04 porting del backend;
  - 05 RAG ibrido e Skiller;
  - 06 lingue;
  - 07 sicurezza;
  - 08 router, RAG e media;
  - 09 file del proprietario, dialogo, ripresa e failover.
- **Rust:** `aw_core` non è compilato su questa macchina, perché mancano rustc, cargo e i Build Tools MSVC. Gira il fallback Python, con gli stessi test. I 3 test saltati di pytest sono la parità Rust.
- **Chiavi:** quelle vere stanno in `.env`, ignorato da git (ruotate dall'utente il 14/10). Con `.env` pieno `npm start` va in LIVE e costa. I test e il runner passano tutti da `demoEnv()` (`scripts/lib/backend-launcher.js`), che svuota ogni chiave.
- **Da fare per l'utente:**
  - il backup della riscrittura della history (`../agent-world-before-scrub.bundle`, accanto alla cartella del repo) c'è ancora e **contiene i dati personali**: va cancellato, o tenuto offline;
  - **`npm run scan:secrets` non è pulito (18/10): 11 rilievi, tutti nei 5 commit di merge che GitHub ha creato per le PR #1, #3, #4, #5 e #6** (`def76ca`, `2e91b97`, `2e55864`, `6ca7919`, `67f98c7`). Il messaggio "Merge pull request #N from …" porta il nome dell'account, e autore e committer hanno l'identità vera. Sono già su `origin/main`. Per le PR future: "Squash and merge" o "Rebase and merge", oppure il merge in locale con l'identità `agent-world-dev`. Per quelle già fatte serve una nuova riscrittura della history con force push: decide l'utente.
- **Questo file è tracciato su `main`** (dal 16/10, decisione dell'utente). `scripts/secret-scan.js` ne scansiona il contenuto come per ogni altro file: chiavi, percorsi assoluti, parole personali.
- **Push su Windows:** `git push` apre la finestra "Select an account" di Git Credential Manager. Va scelto l'account proprietario del repo (quello nell'indirizzo di `origin`); con l'altro GitHub risponde 403. Il push si lancia in background e si avvisa l'utente.

## 2. Storia in breve (13–18 ottobre)

La storia completa sta nei documenti delle spec; qui solo i punti fermi.

- **13/10:** spec 01, 02 e 03 (la 03 congelata dopo T2: T3–T10, N5 e N2 vanno nel backlog). Poi la spec 04, cioè il porting del backend da Node a FastAPI + Rust, in P0–P7 (`docs/specs/04-backend-port.md`, decisioni D1–D8).
  - Misurato prima del piano: nel backend non c'è nessun calcolo pesante, perché A* e simulazione 3D girano nel browser. L'unico punto caldo era `Brain.add`, che ricostruiva tutto il BM25 (oggi è incrementale).
  - Il Rust entra solo se batte il Python di almeno 5× (`backend/bench/bm25_bench.py`).
- **14/10:** spec 05.
  - Sicurezza della history: `git filter-repo`, identità `agent-world-dev`, hook e `scripts/secret-scan.js`; force push approvato.
  - RAG ibrido (BM25 + coseno, RRF) e Skiller con download protetti (D1–D4).
  - Gli screenshot veri del README.
  - Un messaggio chiaro quando la porta è occupata.
- **15/10:** spec 06 (cinque lingue, inglese di default) e spec 07 (CSRF, DNS rebinding, sandbox dell'anteprima, SSRF, clickjacking). Chiuso A10 (N12).
- **16/10:** chiusi N14 (la demo parla la lingua della run), N15 (i test non toccano i file dell'utente) e N16 (test uguali su ogni sistema). Spec 08 (router, cascata, profiler, RAG su misura del modello, media sempre reali in LIVE). Da qui questo file è tracciato.
- **17–18/10:** spec 09 (failover senza fermate, provider registrati a runtime, arbitro TypeSafe, file del proprietario, dialogo con un task, ripresa, modifiche dopo la fine), unita con la PR #6. Poi il debito tecnico in fondo a questo file.

Lezioni del porting ancora valide:
- `load_env` riempie da `.env` solo le chiavi **assenti**: per questo `demoEnv()` le mette a `""` invece di cancellarle. Due run di QA, prima del fix, avevano consumato API vere.
- La riga "ready" del server si stampa solo dopo il bind della porta.
- `team.release` salta i waiter già cancellati: senza, un agente restava occupato per sempre dopo `stop()`.

## 3. Prossimo passo

1. **Review del branch `claude/tech-debt-i18n-browser-docs-519081`**, poi la PR verso `main` quando l'utente la chiede.
2. **I commit di merge di GitHub con l'identità vera** (sezione 1): come unire le PR d'ora in poi, e se riscrivere la history di `main`. Decide l'utente.
3. **Le verifiche su Windows o con chiavi vere** (in fondo, "Da verificare").
4. **N17** (sezione 4): l'ultimo testo del backend scritto in una lingua sola.
5. **Ogni sonda nuova** usa `scripts/browser/headless.js` (`launch`, `close`), mai una copia dell'avvio. Dopo un giro interrotto: `npm run sweep` (`--dry-run` per vedere prima).

## 4. Ticket futuri

- **N17 — Testi del backend ancora in italiano, fuori dagli errori HTTP** (trovato chiudendo N13):
  - la nota di run `"Risposta non valida, riprovo"` di `tasker.py` (riga 226) compare nella timeline del task in ogni lingua;
  - in console, i log di avvio di `skills.py` e `app.py` ("repo ignorata", "non scaricata", "download spenti").
  
  La correzione: una chiave in `i18n.MESSAGES` per la nota, l'inglese per i log.
- **Spec 03 congelata, nel backlog:**
  - T3–T10: baseline dell'app con le fasi `memory`, `late` e `soak`;
  - **N5:** perdite di memoria della GPU;
  - **N2:** client in ritardo e sessioni lunghe.
  
  Ticket e decisioni D7–D11 restano validi in `docs/specs/03-memory-stability.*`. Sono quasi tutti di front-end; il bus SSE eredita i casi del client lento e della riconnessione.
- **N10 — Client lento senza pause** (D10 della spec 03): con frame oltre i 50 ms il mondo resta indietro, e recupera solo con la spinta delle code. Proposta: riallineare anche quando l'arretrato supera una soglia di tempo del mondo. È lo stesso `dt` limitato a 0,05 s che rallentava le animazioni della camera nel runner (sezione 6).
- **N8 — Pinch su touch screen sopra le etichette** (dalla review della spec 02): le etichette prendono i puntatori, quindi un pinch che inizia sopra un'etichetta non arriva al canvas. È un'ipotesi per costruzione, non misurata.
- **Skill Hub:**
  - la fonte "claudia" la ri-aggiunge l'utente dalla UI;
  - la raccolta vera di skill di Vercel è `vercel-labs/agent-skills`: da proporre, senza aggiungerla da soli.
- **Backlog precedente alla spec 01:**
  - feedback sullo stile v3;
  - chiarire "Claude setup";
  - idee: generazione video, ComfyUI locale (`~/ComfyUI`), routine pianificate, costi in $ per modello, più run in contemporanea.

## 5. Regole di lavoro

**Metodo.** Specs Driven Development in 6 step: Plan → **To-spec** → To-tickets → Implement → Code-review → Retro.

**"Ultra Code" è obbligatorio.** Ragionamento profondo *prima* di scrivere codice, cioè:
- leggere il codice reale, compresi i sorgenti di three.js in `node_modules`;
- misurare invece di stimare;
- prevedere casi limite e regressioni;
- dimostrare che i test sanno fallire;
- documentare ogni deviazione dalla spec;
- correggere e segnalare i difetti nel perimetro; annotare soltanto quelli fuori perimetro.

**Con l'utente:**
- un commit atomico per ticket o per correzione;
- nella review: prima il test che fallisce, poi la correzione, poi le suite verdi, poi il commit;
- **dopo ogni ticket o step ci si ferma e si aspetta il feedback**;
- l'utente fa il QA visivo a schermo intero a 1920×1080;
- niente push senza il suo via libera.

**Lingua:** documenti, UI e messaggi in italiano; codice e commenti in inglese.

**Privacy:** niente nome vero, nomi di account, e-mail o percorsi assoluti nel repo, nella history, nei documenti e in questo file. Mai `--no-verify`: gli hook di `scripts/hooks/` bloccano le fughe.

**Lezioni delle retro, da applicare:**
1. Il runner headless nasce a T0. Il pannello browser dell'app serve solo per guardare.
2. Le attese d'interazione si scrivono dal punto di vista dell'utente, con la matrice ingresso × stato nella spec; i nomi dell'API restano ai ticket.
3. Quando un ticket cambia la semantica di una funzione, prima del commit si fa un passaggio avversario: tutti i chiamanti (grep), "e se succede durante un'animazione?", "e se la precondizione è diversa?".
4. Un limite noto entra nel report solo con il caso peggiore misurato.
5. Verifiche a livelli:
   - `--only <fasi>` per i ritocchi;
   - la suite completa quando cambiano cubi, eventi o `fx`, e sempre a fine step;
   - niente browser per i commit di soli documenti.
6. A fine suite, se restano processi Edge con `agent-world-profile` la suite fallisce.
7. Questo file tiene stato, decisioni, prossimi passi e regole; la storia sta nei documenti della spec.
8. Profondità proporzionata al rischio, e un riassunto di 5 righe in testa ai documenti lunghi.
9. **Un'attesa in un test conta i frame o aspetta una condizione, mai i millisecondi** (18/10): il mondo avanza al massimo 0,05 s per frame, e un browser senza GPU ne disegna 1–2 al secondo.

## 6. Contesto tecnico

**Il progetto.** App multi-agente propria:
- una CEO pianifica;
- i team lead fanno da task manager;
- worker e sub-agenti lavorano in loop fino al QA;
- il router LLM è integrato (OmniRoute);
- un ufficio 3D isometrico in three.js mostra il workflow.

**Backend** (`backend/backend/`, FastAPI):
- `app.py` costruisce tutto: config, store, bus, router, team, Brain, Skill Hub, media, Skiller. Poi il middleware della spec 07 e le route. Il catch-all dei file statici va montato per ultimo;
- `routes/`:
  - `api_state` (`/api/state`, `/api/config`, `/api/router`);
  - `runs` (ciclo di vita, chat, upload, `interact`, `refine`, `resume`);
  - `providers` (registrazione a runtime);
  - `skills_brain`;
  - `events` (SSE su `/api/events`);
  - `gateway` (`/v1`, formato OpenAI);
  - `static` (`public/`, `/vendor/three*` da `node_modules`, `/preview/<run>/` in sandbox);
- motore:
  - `run.py` (missione, scheduler a tick, review, report, ripresa);
  - `tasker.py` (il loop di un worker);
  - `team.py`, `bus.py`, `tools.py` + `paths.py` (una regola dei percorsi per ogni sistema);
  - `run_memory.py`, `rag_budget.py`, `json_repair.py`;
  - `arbiter.py` (TypeSafe), `attachments.py`;
- `router/`: `index.py` (combo, cascata, cooldown, blacklist), `providers.py`, `profiler.py`, `mock.py` + `mock_texts.py` (la demo, nella lingua della run);
- memoria: `brain.py`, `skills.py`, `skiller.py` + `downloads.py`, `embed.py`, `search.py` (BM25 e coseno, Rust se compilato);
- `media.py` (voce: cloud, poi edge-tts, poi la voce del sistema; immagini: cloud, poi il generatore locale), `store.py`;
- lingue: `i18n.py`.
  - `MESSAGES`: i testi della run, nella lingua della run.
  - `HTTP_ERRORS`: gli errori delle API, nella lingua dell'app (`ui.language`, letta a ogni richiesta; senza, l'inglese).
  - Una route scrive solo chiavi; sotto le route si alza `i18n.Refusal(chiave, **valori)`;
- `security.py`: Host ammessi, `Origin` e `Sec-Fetch-Site` prima di ogni route; i 403 nella lingua dell'app.

**Persistenza:**
- tutto in `data/`, spostabile con `AGENT_WORLD_HOME`:
  - `runs/` (più `runs/sessions/` per la ripresa);
  - `brain.json`, `calls/`, `embeddings/`, `uploads/`, `skiller.json`;
  - `workspace/`, una cartella per run;
- configurazione in `config/default.json` più `config/local.json` (`AGENT_WORLD_LOCAL_CONFIG` la sposta: lo fanno i test);
- `.env` (`AGENT_WORLD_ENV_FILE`), riletto quando si registra un provider.

**Front-end** (invariato dal porting):
- `three@0.186.1` da `/vendor/three`;
- `public/js/main.js`: UI, pannelli, schede, `measureInsets()` più un `ResizeObserver` che chiama `world.setInsets()`;
- `public/js/i18n.js`: i dizionari della UI, `LANGS` nello stesso ordine di `i18n.LANGUAGES`;
- `public/css/app.css`: layout fisso, media query a 1250 e 900 px; i pannelli si chiudono con `display: none`;
- 3D in `public/js/world/`:
  - `world.js`: eventi, camera, cubi, etichette in `#labels`; `frame()` limita `dt` a 0,05 s;
  - `framing.js`: inquadratura, limiti di zoom, `scaleAt`;
  - `office.js`: layout ed `ENVELOPE`;
  - `fx.js`: effetti; `fx.active(camera)` è il movimento della camera in corso;
  - `character.js`, `nav.js`, `geo.js`.

**Camera, in breve** (dettagli nella spec 01):
- l'ufficio è inquadrato nell'area lasciata libera dagli ingombri;
- `autoFrame`: in automatico i pannelli riadattano la vista (in 0,35 s), le azioni dell'utente la rendono manuale, ⌂ la riporta in automatico (in 0,6 s);
- zoom effettivo per le etichette = `REF / (unitsPerPx / zoom)`, con `REF` = 62/1920; la classe `far` scatta sotto 0,55 e nasconde le etichette dei worker inattivi.

**Ambiente** (visto il 18/10):
- Windows 11, Node v24.16.0: minimo 20.10 per l'app, 22 per il runner;
- uv 0.11.29, Python 3.13.15 nel venv di `backend/`; niente rustc, cargo e Build Tools MSVC;
- un worktree nuovo non ha `node_modules`: `npm install`, oppure una copia di `node_modules/three` dal checkout principale;
- la **porta 4300** è del server dell'utente: **non toccarla**. Il runner usa la 4397 (`--port` per un'altra).

```sh
npm start                                    # il server (cd backend && uv run python -m backend)
npm test                                     # mondo 3D, dizionari, launcher, avvio, pytest, smoke, flussi, secret-scan, temp (~7 min)
npm run test:backend                         # avvio del backend e pytest
npm run test:browser                         # runner headless completo, missione inclusa
node scripts/browser-test.js --only views,input
node scripts/browser-test.js --skip-run      # senza la missione
node scripts/browser-test.js --shots DIR --json FILE --port N
BROWSER_FLAGS=--disable-gpu BROWSER_CPU_THROTTLE=20 node scripts/browser-test.js --only views,input   # come un container senza GPU (~2 fps)
npm run scan:secrets                         # audit di tutta la history
npm run sweep -- --dry-run                   # cosa lascerebbero gli strumenti uccisi
npm run screenshots                          # gli screenshot del README
```

**Runner del browser** (`scripts/browser-test.js`):
- avvia un server demo proprio sulla porta 4397 e Edge o Chrome headless via DevTools. Il browser viene da `scripts/browser/headless.js`, le cartelle (home `agent-world-browser-<pid>-*`, profilo `agent-world-profile-<pid>-*`) da `scripts/lib/temp.js`;
- fasi: `hygiene`, `views`, `checks`, `cubes`, `input`, `overlaps`, `labels`, `language`, `run`, `recovery`;
- script lato pagina in `scripts/browser/`, con `lib.js` per primo; i rossi attesi in `known-red.json` (oggi vuoto);
- a fine suite fallisce se restano processi del browser con il suo profilo, o le sue cartelle;
- **stampa quanti frame al secondo disegna il browser.** Le attese della camera contano i frame (`__t.still()`: nessun movimento in corso e l'immagine ferma su 8 frame). Un controllo di `views` è verde solo a camera ferma;
- all'avvio spazza i processi e le cartelle degli strumenti morti; Ctrl+C chiude browser e server e rimuove le cartelle (exit 130);
- `Emulation.setDeviceMetricsOverride` cambia il viewport, quindi si possono provare le media query;
- legge gli script all'avvio: modificarli mentre gira è sicuro, modificare `public/` no.

**Lezioni sugli strumenti:**
- **Chiudere Edge su Windows:** si chiude via DevTools (`Browser.close`), e l'albero si uccide solo se risponde ancora. Per controllare: processi `msedge.exe` con `agent-world-profile` nella riga di comando.
- **Uccidere node su Windows** (misurato nella spec 03, §1.2): nessun modo esterno (`taskkill`, `child.kill`, `timeout` della shell) esegue i gestori, ed Edge sopravvive anche a `taskkill /T` su node. Per questo esistono lo spazzino e `AGENT_WORLD_EXIT_WITH_PARENT`.
- **Un test con dati binari nei parametri** ha bisogno di `ids` corti: pytest mette l'id del test in `PYTEST_CURRENT_TEST`, e su Windows una variabile d'ambiente si ferma a 32767 caratteri (visto il 18/10 con un WAV in `test_attachments.py`).
- **Il pannello browser dell'app** è largo circa 476 px e spesso nascosto, quindi niente rAF né `ResizeObserver`. Le misure 3D si fanno con il runner o con gli helper di `scripts/browser/lib.js`.
- **I worktree** (`.claude/worktrees/…`) hanno una git dir propria, `.git/worktrees/<nome>`: ciò che sta in `.git/info/` (come `personal-words`) si legge da `git rev-parse --git-common-dir`. Fino al 18/10 `secret-scan.js` non lo faceva e bloccava ogni commit da un worktree che nominava gli agenti.
- **Heredoc della shell:** con testi lunghi pieni di apici o di lettere accentate a volte si rompe; meglio un file e un piccolo script Python, oppure l'editor.

**Debug:**
- `window.agentWorld` espone `camera`, `controls`, `view`, `insets`, `autoFrame`, `resetView()`, `moveCamera()`, `screenScale()`, `centreLens()`, `footprint()`, `regrab()`, `fx`, `cubes`, `actors`, `labels`, `roomLabels` e `layout`;
- le API sono nel README (sezioni "Streaming", "File, dialogo e ripresa", "Il router OmniRoute").

## 7. Bug noti e limiti

- **Ticket aperti:** N17, N10, N8, più il backlog della spec 03 (sezione 4).
- **Limiti accettati:**
  - un solo run attivo alla volta (409 "the team is already working");
  - la chat con gli agenti sta solo in memoria;
  - durante un resize ogni frame disegna fino a 3 volte;
  - i vettori locali `local/ngram` trovano le varianti di una parola, non il significato: per i sinonimi serve un modello di embedding vero (spec 05);
  - restano in inglese, come dettagli tecnici, i messaggi dei livelli sotto le route (`paths.py`, `downloads.py`), il gateway `/v1` e i `Forbidden` / `Not found` dei file statici (N13, spec 06 §5).
- **Ancora aperti, da prima della spec 01:**
  - scelta delle skill in demo rumorosa;
  - microfono non funzionante nel pannello dell'app;
  - workstream di servizio rimappati su `dev`;
  - run v1 gestiti in parte.
- **claude-mem** può non avere le sessioni più recenti: fa fede questo file.


## Stato al 18/10/2026, sera

- `main` = `67f98c7`: PR #6 (spec 09) unita. Prima erano entrate la PR #5 (spec 08) e le #1–#4 (spec 06, N14, N15, N16).
- Branch `claude/tech-debt-i18n-browser-docs-519081`, da `main`, cinque commit:
  - `ce33dcd` fix(secret-scan): un worktree legge le parole personali del repository;
  - `daf66d5` test(attachments): id corti per i byte dei file, Windows li rifiutava;
  - `72158a2` fix(i18n): gli errori HTTP nella lingua dell'app (N13);
  - `5729fbc` fix(browser-test): le attese della camera contano i frame;
  - il commit di questi documenti (HANDOFF e README).
- Il branch è pushato su `origin` su richiesta dell'utente (18/10); nessuna PR aperta.

### Completate
- **N13, gli errori HTTP nella lingua dell'app** (dettagli: `docs/specs/06-language.md` §5):
  - `i18n.HTTP_ERRORS`: 50 chiavi nelle cinque lingue;
  - `ui_language(cfg)`: `ui.language`, oppure l'inglese se manca o non è valida;
  - `http_error(lang, key, **vars)`, che non alza mai eccezioni;
  - `Refusal` per i livelli sotto le route.
  
  Le route (`runs`, `providers`, `api_state`, `skills_brain`, `static`) e i 403 di `security.py` scrivono solo chiavi; `attachments.py` e `skills.add_repo` alzano `Refusal`. La lingua è quella dell'app e non quella della run: gli errori compaiono in un toast della UI. `Accept-Language` non si usa, perché è la lingua del browser.
  - Test scritti prima, visti rossi (131 su 146 in `test_i18n.py`):
    - tabelle allineate e tradotte;
    - 21 rifiuti di ogni tipo di route nelle cinque lingue, più i tre 403;
    - il cambio di lingua che vale subito;
    - un errore su una run italiana con l'app in tedesco, che esce in tedesco;
    - un controllo AST dei sorgenti, che fallisce se una route torna a scrivere un errore in italiano.
    
    Una mutazione (il middleware senza `language`) fa 4 rossi. Le asserzioni in italiano di `test_runs.py`, `test_state.py` e `test_providers_api.py` ora usano le chiavi (inglese di default).
- **I rossi di `views` e `input` del runner** (dettagli: `docs/specs/09-multimodal-interactive-recovery.md`, "Limiti noti"):
  - **Causa:** il ritmo dei frame, non `framing.js` né `world.js`. Il runner aspettava tempi fissi (900 ms dopo un pannello, 600 ms dopo un resize, controlli ogni 250 ms). Il mondo invece avanza al massimo 0,05 s per frame, quindi una riinquadratura di 0,35 s dura 7 frame: con il WebGL software di un container (1–2 fps) le misure cadevano a metà movimento.
  - **Riprodotto su Windows** con `BROWSER_FLAGS=--disable-gpu` e `BROWSER_CPU_THROTTLE`:

    | fps | rossi |
    |---|---|
    | 9,8 o più | 0 |
    | 2,1 | 3 (`views` 2560×1440 LR e 1440×900 LR, `input` drag) |
    | 0,8 | 4 (in più `views` 1440×900 -R) |

    Anche i verdi lenti misuravano larghezze sbagliate: 1098 o 1207 px invece di 1419. I 6 rossi del container erano lo stesso effetto, a un ritmo ancora diverso.
  - **Correzione:** `__t.still()` in `scripts/browser/lib.js` aspetta la camera ferma contando i frame, e lo usano `viewport()`, `layout()` e `settleView()`. `views` richiede la camera ferma; il runner stampa gli fps. Dopo: 14 controlli su 14 verdi a 2,4 e a 0,4 fps, con le stesse larghezze dell'ufficio della macchina veloce.
- **Test con id troppo lunghi su Windows:** `test_real_files_pass[v.wav-…]` dava errore, perché l'id con i byte del WAV superava i 32767 caratteri di `PYTEST_CURRENT_TEST`. Ora gli id sono il nome del file e la dimensione.
- **`secret-scan.js` nei worktree:** il hook di commit bloccava ogni commit da un worktree che nominava agenti o mondo. `personalWords()` cercava `info/personal-words` sotto `--git-dir`, che in un worktree è `.git/worktrees/<nome>`, un percorso assoluto incollato da `join()` e senza `info/`. Così valeva l'identità `agent-world-dev`. Ora legge la cartella comune. Due controlli nuovi in `secret-scan-test.js`, con un worktree vero; il primo era rosso prima della correzione.
- **Documenti:** questo file riordinato (la storia del 13–14/10 riassunta nella sezione 2; sezioni 1, 3 e 6 sul sistema di oggi). Nel README:
  - via la nota su N13;
  - pytest a 927 test;
  - i 403 nella lingua dell'app;
  - come provare il runner su una macchina lenta.

### Verifiche (Windows 11)
- `npm test` verde in 5 min 50 s: mondo 3D, dizionari, launcher, avvio, **pytest 927 passati e 3 saltati** (la parità Rust), smoke, flussi, secret-scan (19 controlli), cartelle temporanee.
- **`npm run test:browser`: 255 verifiche su 255, ALL OK** in 4 min 53 s, a 106,8 fps, con `known-red.json` vuoto. Il README ne contava 254 (246 più le 8 della spec 09): nessun controllo nuovo in questo branch.
- `--only views,input` con WebGL software e CPU rallentata: 14 su 14 a 2,4 e a 0,4 fps; prima della correzione 3 rossi a 2,1 fps e 4 a 0,8.
- **`npm run scan:secrets`: 11 rilievi, tutti nei 5 commit di merge di GitHub** (sezione 1, "Da fare per l'utente"); i cinque commit di questo branch sono puliti, e il hook li ha scansionati uno per uno.

### Ticket aperti
- I merge di GitHub con l'identità vera (sezione 1): da decidere per l'utente.
- N17 (nuovo): la nota "Risposta non valida, riprovo" di `tasker.py` e alcuni log di avvio sono ancora solo in italiano.

### Da verificare su Windows (o con chiavi vere)
- La voce in una run LIVE senza credito OpenAI ed ElevenLabs: deve parlare edge-tts, senza `uv add`. Senza rete, o con `media.providers.edgetts.enabled: false`, la voce di sistema (SAPI).
- La scoperta dei modelli con Ollama o LM Studio attivi.
- Una chiamata vera a TypeSafe con `TYPESAFE_API_KEY`.
- I nomi dei modelli dei provider nuovi della spec 09: verificati sulle fonti, non con chiamate vere (un nome sbagliato costa un 404, poi la blacklist).
- Il trascinamento di un file dal Desktop nella UI vera.

### Prossimi passi
1. Review del branch e PR verso `main` (quando l'utente la chiede), unita senza un commit di merge di GitHub.
2. La decisione sui merge già fatti (sezione 1).
3. Le verifiche qui sopra.
4. N17.
