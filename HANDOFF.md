# HANDOFF — Agent World

*Aggiornato il 2026-10-19. In breve:*
- *Spec 11 aperta (`docs/specs/11-core-hardening-intent-engine.md`), un ticket per sessione. **T01 fatto** (budget e circuit breaker della run, branch `claude/core-hardening-intent-engine-cdd150`) e **T02 fatto** (shell senza chiavi, chiave d'accesso dalla rete, N13 chiuso del tutto) sul branch `claude/youthful-bun-b80533`, che parte dal commit di T01 e quindi li porta tutti e due. Sullo stesso branch, un commit a parte chiude N19 (il test di avvio che scriveva nel checkout), e poi **T03 fatto** (tokenizer per il codice e ogni scrittura, consolidamento e decadimento del Brain). **T04 fatto** (checkpoint del Tasker e ritorno all'ultimo punto pulito all'escalation) sul branch `claude/t04-tasker-checkpointing-90fa3a`, che parte da `0db28e2` (la punta di `claude/youthful-bun-b80533`) e quindi porta T01–T04 e N19. Niente unito né spinto; decisioni D1–D5 (T01), D6–D11 (T02), D12–D15 (T03) e D16–D19 (T04) confermate dall'utente. **Prossimo: T05** (sezione 3).*
- *`main` = il merge `--no-ff` in locale (identità `agent-world-dev`) del branch `claude/spec10-parametric-hiring`, sopra `937673a` (il debito tecnico N13/N17). Le spec 01–10 sono chiuse (la 03 congelata dopo T2).*
- *La spec 10: ogni sotto-task assume il suo modello (matrice di competenza, catena dedicata, subentro senza fermate), il bus a incrocio tra agenti (`[LIVE CROSS-AGENT UPDATE]`), il prompt nella forma del modello assunto (piccolo, reasoning, coder, generale), il badge del modello nella scheda Task e il catalogo profilato nella scheda Router.*
- *`npm run scan:secrets` è pulito: da `71c46c6` la scansione della history lascia passare i merge che GitHub ha fatto per le PR (l'utente ha scelto di non riscriverli).*
- *Lo stato dettagliato e le verifiche sono in fondo, in "Stato al 19/10/2026".*

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
  - 09 file del proprietario, dialogo, ripresa e failover;
  - 10 assunzione dei modelli per sotto-task, bus a incrocio, forma del prompt.
- **Spec aperta:** 11, Core Hardening e Intent Engine a doppia modalità (`docs/specs/11-core-hardening-intent-engine.md`, ticket T01–T10). Si fa **un ticket per sessione**, e si passa al successivo solo con `npm test` verde al 100% (regole di sessione dell'utente, §1 della spec). T01 è fatto sul branch `claude/core-hardening-intent-engine-cdd150`, T02 e T03 sul branch `claude/youthful-bun-b80533`, che parte da T01, e T04 sul branch `claude/t04-tasker-checkpointing-90fa3a`, che parte dalla punta del precedente (worktree omonimi in `.claude/worktrees/`): non ancora uniti né spinti. Unire l'ultimo porta tutto.
- **Rust:** `aw_core` non è compilato su questa macchina, perché mancano rustc, cargo e i Build Tools MSVC. Gira il fallback Python, con gli stessi test. Dei 4 test saltati di pytest, 3 sono la parità Rust e 1 vuole ffmpeg, che qui non c'è.
- **Chiavi:** quelle vere stanno in `.env`, ignorato da git (ruotate dall'utente il 14/10). Con `.env` pieno `npm start` va in LIVE e costa. I test e il runner passano tutti da `demoEnv()` (`scripts/lib/backend-launcher.js`), che svuota ogni chiave.
- **Da fare per l'utente:**
  - il backup della riscrittura della history (`agent-world-before-scrub.bundle`, accanto alla cartella del repo, con i dati personali) è **nel Cestino** dal 18/10: per toglierlo davvero va svuotato il Cestino;
  - i 5 commit di merge che GitHub ha creato per le PR #1, #3, #4, #5 e #6 (`def76ca`, `2e91b97`, `2e55864`, `6ca7919`, `67f98c7`) portano il nome dell'account e l'identità vera. L'utente ha scelto di non riscriverli: da `71c46c6` `npm run scan:secrets` li riconosce (due genitori, GitHub come committer, oggetto "Merge pull request #N from …") e lascia passare solo quei campi. Per il lavoro futuro: il merge in locale con l'identità `agent-world-dev`, come per il debito tecnico del 18/10 e per la spec 10.
- **Questo file è tracciato su `main`** (dal 16/10, decisione dell'utente). `scripts/secret-scan.js` ne scansiona il contenuto come per ogni altro file: chiavi, percorsi assoluti, parole personali.
- **Push su Windows:** `git push` apre la finestra "Select an account" di Git Credential Manager. Va scelto l'account proprietario del repo (quello nell'indirizzo di `origin`); con l'altro GitHub risponde 403. Il push si lancia in background e si avvisa l'utente.

## 2. Storia in breve (13–19 ottobre)

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
- **17–18/10:** spec 09 (failover senza fermate, provider registrati a runtime, arbitro TypeSafe, file del proprietario, dialogo con un task, ripresa, modifiche dopo la fine), unita con la PR #6. Poi il debito tecnico (N13, N17, le attese del runner contate in frame), unito in locale.
- **18/10, sera e notte:** spec 10 in due parti (`docs/specs/10-parametric-hiring-cross-rag.md`, decisioni D1–D12): assunzione dei modelli per sotto-task, bus a incrocio, forma del prompt per famiglia di modello, interfaccia. Unita in locale.
- **19/10:** spec 11 aperta (`docs/specs/11-core-hardening-intent-engine.md`). T01, budget e circuit breaker della run (decisioni D1–D5 confermate dall'utente). T02, shell a fiducia zero e chiave d'accesso dalla rete, più la chiusura di N13 (decisioni D6–D11 confermate dall'utente). N19 chiuso subito dopo. T03, tokenizer per il codice e consolidamento del Brain (decisioni D12–D15 confermate dall'utente). T04, checkpoint del Tasker e time-travel all'escalation (decisioni D16–D19 confermate dall'utente).

Lezioni del porting ancora valide:
- `load_env` riempie da `.env` solo le chiavi **assenti**: per questo `demoEnv()` le mette a `""` invece di cancellarle. Due run di QA, prima del fix, avevano consumato API vere.
- La riga "ready" del server si stampa solo dopo il bind della porta.
- `team.release` salta i waiter già cancellati: senza, un agente restava occupato per sempre dopo `stop()`.

## 3. Prossimo passo

0. **Spec 11, a contesto pulito:** T01, T02, T03 e T04 sono approvati (D1–D19, spec 11 §3.3, §4.3, §5.3, §6.3); il prossimo step è **T05, streaming vero su `/v1`** (spec 11 §2): `/v1/chat/completions` con `"stream": true` manda chunk SSE compatibili OpenAI man mano che il provider risponde, invece del blocco unico finale. Si riparte dal branch `claude/t04-tasker-checkpointing-90fa3a` (T01–T04, N19), o da `main` se nel frattempo è stato unito. Prima: leggere `backend/backend/routes/gateway.py`, `backend/backend/bus.py`, gli adapter in `backend/backend/router/providers.py` (chi sa già fare streaming e chi no), `backend/backend/router/index.py` (`chat()`, cascata e fallback) e `backend/tests/test_gateway.py`. T05 non dovrebbe toccare `crates/aw_core`.
1. **I branch si uniscono in locale** con `git merge --no-ff` e l'identità `agent-world-dev`, poi `git push origin main` (Git Credential Manager chiede l'account: sezione 1).
2. **Le verifiche con chiavi vere** (in fondo, "Da verificare"), compresa una run LIVE della spec 10 con modelli di famiglie diverse.
3. **Il prossimo ciclo SDD** dal backlog (sezione 4), quando l'utente lo sceglie.
4. **Ogni sonda nuova** usa `scripts/browser/headless.js` (`launch`, `close`), mai una copia dell'avvio. Dopo un giro interrotto: `npm run sweep` (`--dry-run` per vedere prima).

## 4. Ticket futuri

- **Spec 03 congelata, nel backlog:**
  - T3–T10: baseline dell'app con le fasi `memory`, `late` e `soak`;
  - **N5:** perdite di memoria della GPU;
  - **N2:** client in ritardo e sessioni lunghe.
  
  Ticket e decisioni D7–D11 restano validi in `docs/specs/03-memory-stability.*`. Sono quasi tutti di front-end; il bus SSE eredita i casi del client lento e della riconnessione.
- **N10 — Client lento senza pause** (D10 della spec 03): con frame oltre i 50 ms il mondo resta indietro, e recupera solo con la spinta delle code. Proposta: riallineare anche quando l'arretrato supera una soglia di tempo del mondo. È lo stesso `dt` limitato a 0,05 s che rallentava le animazioni della camera nel runner (sezione 6).
- **N8 — Pinch su touch screen sopra le etichette** (dalla review della spec 02): le etichette prendono i puntatori, quindi un pinch che inizia sopra un'etichetta non arriva al canvas. È un'ipotesi per costruzione, non misurata.
- **N18 — Le anteprime dalla rete** (spec 11 §4.6, D9): con la chiave d'accesso, `/preview/<id>/` risponde ancora senza chiave a chi conosce l'id di una run (8 cifre esadecimali). Un cookie non arriva alle richieste di una pagina in sandbox; proposta: un segmento firmato nel percorso, dato dalla UI solo a chi ha la sessione.
- **N20 — Le note `hire` con ⚠️ nella timeline** (trovato chiudendo T04, spec 10): le note di assunzione e di subentro di un task (`kind: "hire"`) non hanno un'icona in `taskCard()` di `public/js/main.js`, quindi prendono ⚠️ come un errore. Proposta: un'icona sua (🤝, come il badge).
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
10. **Mai un server di anteprima nello stesso worktree mentre gira pytest** (18/10, spec 10): l'app scrive in `data/` e lo Skiller scarica in `skills/vendor/`, e la guardia N15 di `conftest.py` fa fallire la sessione. Prima della suite: anteprima chiusa, e le due cartelle tolte se le ha create lei.

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
  - `session` (spec 11 T02: `/api/session`, il login di una pagina dalla rete);
  - `gateway` (`/v1`, formato OpenAI);
  - `static` (`public/`, `/vendor/three*` da `node_modules`, `/preview/<run>/` in sandbox);
- motore:
  - `run.py` (missione, scheduler a tick, review, report, ripresa; spec 11: il cancello del budget in `chat()`);
  - `budget.py` (spec 11 T01: limiti della run, prezzi di `router.pricing`, costo stimato, il circuit breaker);
  - `tasker.py` (il loop di un worker; spec 11 T04: lo snapshot dopo ogni passo valido, `rewind()` all'ultimo punto pulito, `session()` / `restore()` con il punto pulito);
  - `team.py`, `bus.py`, `tools.py` (spec 11 T02: `shell_env()`, l'ambiente senza chiavi di `run_command`) + `paths.py` (una regola dei percorsi per ogni sistema);
  - `run_memory.py`, `rag_budget.py` (misura del contesto e, spec 10, forma del prompt), `json_repair.py`;
  - `crossbus.py` (spec 10: i fatti dei file e i legami tra lavori, per `[LIVE CROSS-AGENT UPDATE]`);
  - `arbiter.py` (TypeSafe), `attachments.py`;
- `router/`: `index.py` (combo, cascata, cooldown, blacklist; spec 10: `catalog()`, `health()`, `chat(chain=…)`), `providers.py`, `profiler.py` (spec 10: taglia, specialità, costo), `hiring.py` (spec 10: analisi del sotto-task, catena, subentro), `mock.py` + `mock_texts.py` (la demo, nella lingua della run);
- memoria: `brain.py` (spec 11 T03: `consolidate()` alla fine di ogni run, il decadimento nel tempo in `search()`), `skills.py`, `skiller.py` + `downloads.py`, `embed.py`, `search.py` (BM25 e coseno, Rust se compilato; spec 11 T03: il tokenizer dei token del codice e di ogni scrittura, verificato anche dalla probe d'avvio);
- `media.py` (voce: cloud, poi edge-tts, poi la voce del sistema; immagini: cloud, poi il generatore locale), `store.py` (spec 11 T04: scritture atomiche, al più una ogni 0,4 s per file con lo stato più nuovo, le sessioni dei worker in `runs/sessions/`);
- lingue: `i18n.py`.
  - `MESSAGES`: i testi della run, nella lingua della run.
  - `HTTP_ERRORS`: gli errori delle API, nella lingua dell'app (`ui.language`, letta a ogni richiesta; senza, l'inglese).
  - Una route scrive solo chiavi; sotto le route si alza `i18n.Refusal(chiave, **valori)`;
- `security.py`: Host ammessi, `Origin` e `Sec-Fetch-Site` prima di ogni route; poi (spec 11 T02) dalla rete la chiave d'accesso su `/api`, `/api/events` e `/v1`, come Bearer o cookie `aw_session`, con "locale" = `Host` **e** indirizzo di loopback; i rifiuti nella lingua dell'app.

**Persistenza:**
- tutto in `data/`, spostabile con `AGENT_WORLD_HOME`:
  - `runs/` (più `runs/sessions/` per la ripresa, scritto a ogni passo valido da T04);
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
- un worktree nuovo non ha `node_modules` né `backend/.venv`: `npm install` (oppure una copia di `node_modules/three` dal checkout principale) e `uv sync` in `backend/`;
- la **porta 4300** è del server dell'utente: **non toccarla**. Il runner usa la 4397 (`--port` per un'altra).

```sh
npm start                                    # il server (cd backend && uv run python -m backend)
npm test                                     # mondo 3D, dizionari, launcher, avvio, pytest, smoke, flussi, secret-scan, temp (~6-8 min)
npm run test:backend                         # avvio del backend e pytest
npm run test:browser                         # runner headless completo, missione inclusa (272 verifiche, ~5-6 min)
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
- fasi: `hygiene`, `views`, `checks`, `cubes`, `input`, `overlaps`, `labels`, `language`, `run`, `hiring` (spec 10: le assunzioni live e il subentro vengono dalla risposta di rete di una run salvata, perché la demo non assume nessuno), `budget` (spec 11 T01: una demo non arriva mai al budget, quindi la run live ferma al budget entra dal flusso di eventi della pagina, con un `EventSource` avvolto prima del caricamento; serve `Page.enable`), `recovery`, `lan` (spec 11 T02: il server del runner ha una chiave d'accesso casuale e ammette `lan.localhost`, che il browser risolve da solo su questa macchina e che per il server è un nome della rete);
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
- **Il checkout è in CRLF** (`core.autocrlf true`, 19/10, T04): uno script che riscrive un file con `read_text` / `write_text` lo porta in LF, e git avvisa. Uno script di mutazioni rimette i byte esatti del file, non il testo.
- **`timeout` di Git Bash non chiude pytest su Windows** (19/10): uccide `uv`, ma il python figlio resta e la pipe aspetta per sempre. Per le mutazioni serve uno script Python con `subprocess` e `taskkill /T /F` alla scadenza, e test con `asyncio.wait_for`, così una mutazione è rossa in secondi e non per timeout.

**Debug:**
- `window.agentWorld` espone `camera`, `controls`, `view`, `insets`, `autoFrame`, `resetView()`, `moveCamera()`, `screenScale()`, `centreLens()`, `footprint()`, `regrab()`, `fx`, `cubes`, `actors`, `labels`, `roomLabels` e `layout`;
- le API sono nel README (sezioni "Streaming", "File, dialogo e ripresa", "Il router OmniRoute").

## 7. Bug noti e limiti

- **Ticket aperti:** N20, N18, N10, N8, più il backlog della spec 03 (sezione 4).
- **Limiti accettati:**
  - un solo run attivo alla volta (409 "the team is already working");
  - la chat con gli agenti sta solo in memoria;
  - durante un resize ogni frame disegna fino a 3 volte;
  - i vettori locali `local/ngram` trovano le varianti di una parola, non il significato: per i sinonimi serve un modello di embedding vero (spec 05);
  - N13 è chiuso del tutto (spec 11 T02): restano in inglese solo i dettagli tecnici dentro una frase tradotta (i messaggi di `downloads.py` e `paths.py`, l'ultima riga di git) e il testo che arriva da un provider (il 502 del gateway, il test di una combo). I 422 di FastAPI e il 500 di un corpo JSON rotto su `/api/*` non sono passati dal dizionario;
  - la shell di `run_command` non vede le chiavi, ma non è una sandbox: legge i file a cui arriva l'utente del server, `.env` compreso (spec 11 §4.6).
- **Ancora aperti, da prima della spec 01:**
  - scelta delle skill in demo rumorosa;
  - microfono non funzionante nel pannello dell'app;
  - workstream di servizio rimappati su `dev`;
  - run v1 gestiti in parte.
- **claude-mem** può non avere le sessioni più recenti: fa fede questo file.


## Stato al 19/10/2026

- **Branch `claude/core-hardening-intent-engine-cdd150`** (worktree in `.claude/worktrees/core-hardening-intent-engine-cdd150`), partito da `main` = `33c6135`: un commit per T01 (`f66d1d7`), con codice, test e documenti, più `349f903` (i documenti: D1–D5 confermate dall'utente).
- **Branch `claude/youthful-bun-b80533`** (worktree omonimo), portato in avanti senza merge su `349f903`: sopra c'è un commit per T02. Unire questo branch porta T01 e T02 insieme. Niente unito, niente spinto: si unisce in locale come la spec 10 (sezione 3), quando l'utente approva.
- **Branch `claude/t04-tasker-checkpointing-90fa3a`** (worktree omonimo), portato in avanti senza merge su `0db28e2` (la punta di `claude/youthful-bun-b80533`): sopra c'è un commit per T04. Unire questo branch porta T01, T02, N19, T03 e T04.
- `main` resta il merge della spec 10 (`33c6135`), già su `origin`.

### Completato: spec 11, T04 — checkpoint e time-travel del Tasker (dettagli: spec 11 §6)
- **File toccati:**
  - `backend/backend/tasker.py`: `snapshot()`, `_clean_point()`, `rewind()`, `_rewound_revision()`, `session()`, `owner_messages()`, `WRITE_TOOLS`, `OWNER_PREFIXES`; `init()` (il cursore del bus e lo snapshot del brief), `restore()` (il punto pulito, un rewind in attesa), `work()` (gli errori che sporcano, lo snapshot dopo ogni passo valido, la revisione unica dopo il rewind);
  - `backend/backend/run.py`: `checkpoint()`, `save_sessions(immediate=)` attraverso lo `Store`, `load_sessions()`; in `run_task` il rewind all'escalation e la nota `rewind`; via `sessions_file()`;
  - `backend/backend/store.py`: `write_atomic()`, `_later()`, `sessions_path()`, `save_sessions()`, `load_sessions()`, i `.tmp` tolti all'avvio;
  - `backend/backend/i18n.py`: `rewind_note` × 5 lingue; `public/js/main.js`: l'icona ⏪; `scripts/browser-test.js`: la fase `checkpoint`;
  - test: `backend/tests/test_tasker.py` (6 nuovi), `test_store.py` (4 nuovi), `test_checkpoint.py` (nuovo, 3 test);
  - documenti: README (Revisioni ed escalation, Tasker, Store, Ripresa, Test), spec 11 (§2, §6), questo file.
- **Decisioni confermate dall'utente il 19/10 (spec 11 §6.3):** D16 lo snapshot è un segno nella conversazione (lunghezza, passi, tentativo, cursore, pulito) dopo il brief e dopo ogni passo valido, e il primo errore sporca il contesto; D17 all'escalation si torna all'ultimo snapshot pulito, con le parole del proprietario e le sue risposte, una sola revisione con tutte le bocciature e i file lasciati, i file su disco che non tornano indietro, il cursore del bus dello snapshot; D18 le sessioni su disco entro 0,4 s da ogni snapshot, con il punto pulito, e ogni scrittura dello `Store` atomica e non più rimandata all'infinito; D19 la nota ⏪ nella timeline e `task.checkpoint`.
- **Difetti trovati e corretti nel perimetro:** il salvataggio raggruppato dello `Store` ripartiva da capo a ogni chiamata e con chiamate fitte non scriveva mai (anche il file della run, da prima di T04); il file della run si riscriveva sul posto, e uno interrotto faceva sparire la run all'avvio. Il primo rewind toglieva anche la risposta del proprietario a un `ask_user`: corretto prima del commit, con il suo test.
- **Misure:** la prima chiamata su `frontier` del task `w2.1` della demo "A simple document about coffee" passa da 18 messaggi, 6293 caratteri, 2 revisioni e 8 passi a 10 messaggi, 4602 caratteri, 1 revisione e 4 passi; il file delle sessioni ora c'è mentre la run lavora, e sparisce a fine run.
- **Nuovo ticket fuori perimetro:** N20, le note `hire` con ⚠️ nella timeline (sezione 4).

### Completato: spec 11, T03 — tokenizer per il codice e consolidamento del Brain (dettagli: spec 11 §5)
- **File toccati:**
  - `backend/backend/search.py`: `tokenize()` nuovo (`_scan()`, `_ASCII_TOKEN` per i pezzi ASCII, le parti dei token composti), `TOKENIZE_PROBES`, `_native_tokenizer_matches()` nella probe d'avvio, `HybridIndex.search(boost=)`;
  - `backend/backend/embed.py`: grammi per caratteri, hash dei byte UTF-8, la probe dei vettori nativi con il tokenizer;
  - `crates/aw_core/src/lib.rs` e `Cargo.toml` (`unicode-general-category`): il gemello Rust del tokenizer e dei grammi, **scritto ma non compilato qui**;
  - `backend/backend/brain.py`: `settings()`, `decay()`, `consolidate()`, `_merge()`, `reindex(keep_vectors=)`; `backend/backend/run.py`: `consolidate(run_id=…)` alla fine della run; `config/default.json`: `rag.brain`;
  - `public/js/main.js`: la scheda Brain ricarica l'elenco dopo `consolidate`; `scripts/browser-test.js`: la fase `brain`;
  - test: `backend/tests/test_search.py` (8 nuovi), `test_search_rust.py` (3 nuovi, 1 saltato senza `aw_core`), `test_brain.py` (10 nuovi);
  - documenti: README (RAG, Rust, Test), spec 11 (§2, §5), questo file.
- **Decisioni confermate dall'utente il 19/10 (spec 11 §5.3):** D12 un token è una parola di lettere, cifre o segni Unicode (categorie L, N, M), unita da `_`, `::`, `@`, più le sue parti; `ς` → `σ`; D13 la probe d'avvio prova anche il tokenizer, e un `aw_core` che divide diversamente non si usa; D14 a fine run le note della run si uniscono ai doppioni (coseno > 0,88, stesso tipo, solo note degli agenti), resta la più recente con tag e `repeats`; D15 decadimento moltiplicativo sul punteggio fuso, emivita 30 giorni, pavimento 0,5, solo note degli agenti.
- **Misure:** prima di T03 greco, cirillico, devanagari e CJK non davano nessun token; il tokenizer nuovo costa 1,45 volte quello vecchio (lo scanner su tutto sarebbe costato 3,6 volte); due missioni demo uguali lasciano 6 note invece di 12.

### Completato: N19 — il test di avvio senza scritture nel checkout (19/10, commit a parte su questo branch, chiesto dall'utente)
- **Il difetto** (trovato chiudendo T02): `scripts/backend-boot-test.js` avviava il backend con l'ambiente intero, senza `demoEnv()` né una home temporanea. Ogni `npm test` lasciava una cartella `data/runs/` vuota accanto al codice, e quel server leggeva `.env` (con le chiavi vere sarebbe partito in LIVE, anche se faceva solo `GET /`) e `config/local.json` dell'utente. La guardia N15 di `conftest.py` contava solo i file, e non vedeva né questa cartella né la `skills/vendor/` vuota che un test di T02 creava prima del commit (corretto lì: il test dà alla libreria una cartella temporanea).
- **File toccati:**
  - `scripts/backend-boot-test.js`: `demoEnv(ROOT, { PORT, AGENT_WORLD_HOME })` con una cartella di `ownedDir('boot')`, tolta alla fine; in più tre controlli: il server è in demo, tiene i dati nella sua home, e il checkout non cambia (`data/`, `skills/vendor/`, `config/local.json`);
  - `scripts/launcher-test.js`: ogni script che chiama `spawnBackend()` costruisce l'ambiente con `demoEnv()` (letto dai sorgenti di `scripts/`);
  - `backend/tests/conftest.py`: la guardia N15 conta anche le cartelle (una cartella nuova, anche vuota, è una fuga; una cartella non è mai "cambiata", perché il suo tempo segue i file dentro, controllati uno per uno); `backend/tests/test_isolation.py`: il test della guardia su un checkout finto in una cartella temporanea;
  - README (Test, "Igiene"), questo file.
- **Decisione (confermata dall'utente il 19/10):** la guardia di `pytest` vede anche le cartelle nuove, non solo i file. Nessun test della suite di oggi ne crea: la suite intera è verde con la guardia nuova.
- **Verifiche:** i tre controlli nuovi visti rossi prima della correzione (il boot test: "did not keep its data in its temp home" e "the checkout changed: folders [] -> ["data"]"; il launcher: `backend-boot-test.js` senza `demoEnv()`; `pytest`: la guardia che non vedeva le cartelle), poi verdi. `npm test` verde in 6 min 41 s (**pytest 1094 passati e 3 saltati**), e alla fine nel worktree non c'è né `data/` né `skills/vendor/`. Mutazioni: la guardia senza le cartelle e il boot test senza `demoEnv()` tornano rossi.

### Completato: spec 11, T02 — shell a fiducia zero e autenticazione in LAN (dettagli: spec 11 §4)
- **File toccati:**
  - `backend/backend/tools.py`: `SECRET_WORDS`, `shell_env()`, `config_key_names()`; `run_command` passa sempre l'ambiente senza chiavi (`secrets=` per i nomi in più);
  - `backend/backend/run.py`: il tool `run_command` passa i `keyEnv` della configurazione;
  - `backend/backend/security.py`: `is_local()` (Host e indirizzo di loopback), `access_key()`, `session_token()` / `valid_session()`, `authorized()`; il guard chiede la chiave dalla rete su `/api`, `/api/events` e `/v1` (401 `auth_required`, 403 `lan_needs_key`);
  - `backend/backend/routes/session.py` (nuovo): `GET` e `POST /api/session`; `backend/backend/app.py` la monta;
  - N13: `backend/backend/i18n.py` (10 chiavi × 5 lingue), `routes/static.py`, `routes/skills_brain.py`, `routes/gateway.py`, `skills.py` (`Refusal("skill_not_found")`, il messaggio di git in inglese);
  - `public/js/main.js` (il login prima del boot, il login di nuovo su un 401, Esc e il clic fuori non lo chiudono), `public/js/i18n.js` (5 chiavi × 5 lingue), `public/index.html`, `public/css/app.css`;
  - `scripts/browser-test.js`: la fase `lan`, la chiave casuale e `lan.localhost` per il server del runner;
  - test: `backend/tests/test_zero_trust.py` (nuovo, 27 test), `backend/tests/test_i18n.py`, `backend/tests/test_security.py`;
  - documenti: README (Configurazione, Sicurezza, Usarlo in LAN, Test), spec 11 (§2, §4), questo file.
- **Decisioni confermate dall'utente il 19/10 (spec 11 §4.3):** D6 dalla shell esce ogni variabile con una parola segreta nel nome (`KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `CREDENTIALS`, `AUTH`…) più ogni `keyEnv` della configurazione: la regola letterale ne lasciava passare 4 su 23; D7 locale = `Host` **e** indirizzo di loopback, perché l'`Host` lo scrive il client; D8 senza chiave sul server la rete è chiusa (prima `AGENT_WORLD_ALLOWED_HOSTS` bastava ad aprirla); D9 dalla rete anche `/v1` vuole la chiave, la pagina e le anteprime no (N18); D10 login con la chiave e cookie `aw_session` = scadenza firmata, `HttpOnly`, `SameSite=Strict`, 7 giorni fissi; D11 N13: frase tradotta, dettaglio tecnico com'è, git che fallisce = 502.
- **Difetti trovati e corretti nel perimetro:** `POST /api/skills/repo` con git che fallisce dava un 500 nudo con un messaggio italiano nel log (ora 502 tradotto); il login si poteva chiudere con Esc o un clic fuori, lasciando la pagina ferma a metà avvio.
- **Nuovi ticket fuori perimetro:** N18, le anteprime dalla rete (sezione 4); N19, `backend-boot-test.js` che lasciava `data/runs/` nel checkout, chiuso subito dopo (qui sotto).

### Completato: spec 11, T01 — budget e circuit breaker (dettagli: spec 11 §3)
- **File toccati:**
  - `backend/backend/budget.py` (nuovo): limiti congelati nella run, prezzi di `router.pricing`, costo stimato, `over()` / `extend()` / `ensure()`;
  - `backend/backend/run.py`: il cancello `budget_gate()` in `chat()` e nella vista delle foto, un posto per ogni chiamata in volo (`_in_flight`), `trip_budget()`, `answer_budget()`, il pulsante Riprendi come "Prosegui", la ripresa dal punto di blocco con un blocco nuovo, le chiamate del proprietario contate ma mai fermate (`owner=True`);
  - `backend/backend/i18n.py`: 10 testi × 5 lingue; `config/default.json`: `limits.maxCallsPerRun` 250, `limits.maxCostUSD` 5, `router.pricing`;
  - `public/js/main.js`, `public/js/i18n.js` (13 chiavi × 5 lingue): la richiesta di budget, la spesa nel pannello della missione, i limiti nelle Impostazioni, l'avviso dopo la risposta;
  - `scripts/browser-test.js`: la fase `budget`;
  - `backend/tests/test_budget.py` (nuovo, 33 test), `backend/tests/test_run.py` (la forma di `run.data` e `usage`);
  - documenti: README (Configurazione, SSE, Test), spec 11, questo file.
- **Decisioni confermate dall'utente il 19/10 (spec 11 §3.3):** D1 il simulatore non conta (misurato: la missione demo più grande fa 228 chiamate su 250); D2 costo stimato da `router.pricing`, budget di serie 5 $, prezzi di listino indicativi da verificare; D3 un blocco alla volta, "Ferma la run" la ferma e si può riprendere; D4 limite delle chiamate esatto, quello del costo superabile del costo delle chiamate in volo; D5 le chiamate chieste dal proprietario si contano ma non si fermano.
- **Un difetto trovato da una mutazione, corretto:** con la richiesta di budget aperta e la run tolta dalla pausa, `budget_gate()` girava senza mai cedere il loop; ora rimette la pausa.

### Verifiche di T04 (Windows 11)
- **`npm test` verde** in 7 min 3 s: **pytest 1127 passati e 4 saltati (prima 1114 e 4)**: 6 nuovi in `test_tasker.py`, 4 in `test_store.py`, 3 in `test_checkpoint.py`. Alla fine nel worktree non c'è né `data/` né `skills/vendor/`.
- **`npm run test:browser`: 275 verifiche su 275**, ALL OK in 5 min 18 s a 104,9 fps, `known-red.json` vuoto. La nuova è la fase `checkpoint` (criterio `T04`).
- **Mutazioni:** 20 (19 sul backend, 1 sulla UI), tutte prese; l'impronta di `git diff` uguale prima e dopo (spec 11 §6.4). Lo script è un `subprocess` con `taskkill /T /F` alla scadenza (sezione 6) che rimette i byte esatti di ogni file: il checkout è in CRLF.
- QA visivo a 1920×1080 dallo screenshot della fase `checkpoint`: la scheda del task con "⬆️ Escalated to the "frontier" model" e subito sotto "⏪ Back to the last clean point, after 3 valid steps: …".

### Verifiche di T03 (Windows 11)
- **`npm test` verde** in 6 min 45 s: **pytest 1114 passati e 4 saltati (prima 1094 e 3)** (il quarto saltato è la parità Rust del tokenizer, senza il modulo compilato).
- **`npm run test:browser`: 274 verifiche su 274**, ALL OK in 5 min 13 s a 109,6 fps, `known-red.json` vuoto. Le 2 nuove sono la fase `brain` (criterio `T03`).
- **Mutazioni:** 14 (13 sul backend, 1 sulla UI), tutte prese; due prime prove sbagliate corrette (spec 11 §5.4).
- **Rust:** il codice è scritto riga per riga sul Python ma non compilato: la sua parità la proverà la prima macchina con `rustc` (`test_search_rust.py`), e fino ad allora, se non coincide, la probe lo scarta.

### Verifiche di T02 (Windows 11)
- **`npm test` verde** in 6 min 34 s (rifatto sull'albero finale: 6 min 35 s): **pytest 1093 passati e 3 saltati (prima 1046: 27 in `test_zero_trust.py`, 20 in `test_i18n.py`)**; il resto come per T01.
- **`npm run test:browser`: 272 verifiche su 272**, ALL OK in 5 min 8 s a 113,3 fps sull'albero finale, `known-red.json` vuoto. Le 6 nuove sono la fase `lan` (criterio `T02`); tutte le altre fasi girano con la chiave d'accesso impostata.
- **Mutazioni:** 15 (12 sul backend, 3 sulla UI), tutte prese; quella del boot senza la sessione all'inizio passava verde, e la fase `lan` ora gira con l'app in italiano e senza avvisi (spec 11 §4.4).
- QA visivo a 1920×1080 dagli screenshot della fase `lan` (`--shots`): il dialogo "Chiave d'accesso" (la fase mette l'app in italiano) al centro, sopra l'ufficio vuoto; dopo la chiave, l'ufficio con i suoi agenti. Dietro il dialogo gli esempi e "Start the company" restano in inglese fino al login (spec 11 §4.6).

### Verifiche di T01 (Windows 11)
- **`npm test` verde** in 6 min 20 s: mondo 3D, dizionari, launcher, avvio, **pytest 1046 passati e 3 saltati** (la parità Rust ×2 senza il modulo compilato, ffmpeg assente; prima della spec 11 erano 1013), smoke, flussi, secret-scan, cartelle temporanee. T01 non tocca `crates/aw_core`: nessuna funzione Rust nuova, la parità resta quella di prima.
- **`npm run test:browser`: 266 verifiche su 266, ALL OK** in 4 min 58 s, a 108 fps, con `known-red.json` vuoto. Le 5 nuove sono la fase `budget` (criterio `T01`).
- **Mutazioni:** 8 sul backend e 1 sulla UI, tutte prese (spec 11 §3.4).
- QA visivo a 1920×1080 dagli screenshot della fase `budget` (`--shots`): la richiesta nel pannello di sinistra con "Go on (one more block)" e "Stop the run", la run "running · paused" con "250/250 paid calls" e "≈ $1.23 of $5.00"; le Impostazioni con "Run budget".

### Ticket aperti
- Spec 11: T05–T10.
- N20 (le note `hire` con ⚠️), N18 (le anteprime dalla rete), N8, N10 e il backlog della spec 03 (sezione 4).

### Da verificare su Windows (o con chiavi vere)
- **T03 con il Rust compilato:** su una macchina con `rustc` e maturin, `uv run maturin develop --manifest-path ../crates/aw_core/Cargo.toml`, poi `test_search_rust.py`: i test di parità del tokenizer e dei vettori non devono più essere saltati, e la probe d'avvio deve accettare il modulo.
- **T02 da un dispositivo vero della rete** (un telefono): `server.host` `0.0.0.0`, `AGENT_WORLD_ALLOWED_HOSTS` con l'indirizzo del PC, `AGENT_WORLD_API_KEY`; il login, il cookie, il flusso di eventi, un'anteprima. Il firewall di Windows chiede il permesso a Python la prima volta. Il runner lo prova con `lan.localhost`, che per il server è un nome della rete ma arriva da questa macchina.
- **T01 con chiavi vere:** una run LIVE con `maxCallsPerRun` basso (per esempio 10, dalle Impostazioni) per vedere la pausa, "Prosegui" e "Ferma la run" con un provider vero, e confrontare il costo stimato con la fattura del provider.
- **Spec 10 con chiavi vere:** una run LIVE con modelli di famiglie diverse (un locale o `:free`, un reasoning, un coder) per vedere le quattro forme del prompt e un subentro vero per credito finito. Finora solo server finti.
- La voce in una run LIVE senza credito OpenAI ed ElevenLabs: deve parlare edge-tts, senza `uv add`. Senza rete, o con `media.providers.edgetts.enabled: false`, la voce di sistema (SAPI).
- La scoperta dei modelli con Ollama o LM Studio attivi.
- Una chiamata vera a TypeSafe con `TYPESAFE_API_KEY`.
- I nomi dei modelli dei provider nuovi della spec 09: verificati sulle fonti, non con chiamate vere (un nome sbagliato costa un 404, poi la blacklist).
- Il trascinamento di un file dal Desktop nella UI vera.

### Prossimi passi
1. **T01, T02 e T03 approvati** con D1–D15 (19/10): restano da unire in locale, con N19, quando l'utente lo chiede. Confermata anche la decisione di N19 (la guardia di `pytest` vede anche le cartelle vuote).
2. **T04 approvato** con D16–D19 (19/10, spec 11 §6.3, "così come sono"): resta da unire in locale con il resto (unire `claude/t04-tasker-checkpointing-90fa3a` porta T01–T04 e N19).
3. **T05, a contesto pulito** (spec 11 §2, sezione 3 qui sopra): lo streaming vero su `/v1`. Dal branch `claude/t04-tasker-checkpointing-90fa3a`.
4. Svuotare il Cestino, con dentro il backup del 14/10 (lo fa l'utente).
5. Le verifiche qui sopra.
