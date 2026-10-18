# HANDOFF — Agent World

*Aggiornato il 2026-10-18, notte. In breve:*
- *`main` = il merge `--no-ff` in locale (identità `agent-world-dev`) del branch `claude/spec10-parametric-hiring`, sopra `937673a` (il debito tecnico N13/N17). Le spec 01–10 sono chiuse (la 03 congelata dopo T2).*
- *La spec 10: ogni sotto-task assume il suo modello (matrice di competenza, catena dedicata, subentro senza fermate), il bus a incrocio tra agenti (`[LIVE CROSS-AGENT UPDATE]`), il prompt nella forma del modello assunto (piccolo, reasoning, coder, generale), il badge del modello nella scheda Task e il catalogo profilato nella scheda Router.*
- *`npm run scan:secrets` è pulito: da `71c46c6` la scansione della history lascia passare i merge che GitHub ha fatto per le PR (l'utente ha scelto di non riscriverli).*
- *Lo stato dettagliato e le verifiche sono in fondo, in "Stato al 18/10/2026, notte".*

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
- **Rust:** `aw_core` non è compilato su questa macchina, perché mancano rustc, cargo e i Build Tools MSVC. Gira il fallback Python, con gli stessi test. Dei 3 test saltati di pytest, 2 sono la parità Rust e 1 vuole ffmpeg, che qui non c'è.
- **Chiavi:** quelle vere stanno in `.env`, ignorato da git (ruotate dall'utente il 14/10). Con `.env` pieno `npm start` va in LIVE e costa. I test e il runner passano tutti da `demoEnv()` (`scripts/lib/backend-launcher.js`), che svuota ogni chiave.
- **Da fare per l'utente:**
  - il backup della riscrittura della history (`agent-world-before-scrub.bundle`, accanto alla cartella del repo, con i dati personali) è **nel Cestino** dal 18/10: per toglierlo davvero va svuotato il Cestino;
  - i 5 commit di merge che GitHub ha creato per le PR #1, #3, #4, #5 e #6 (`def76ca`, `2e91b97`, `2e55864`, `6ca7919`, `67f98c7`) portano il nome dell'account e l'identità vera. L'utente ha scelto di non riscriverli: da `71c46c6` `npm run scan:secrets` li riconosce (due genitori, GitHub come committer, oggetto "Merge pull request #N from …") e lascia passare solo quei campi. Per il lavoro futuro: il merge in locale con l'identità `agent-world-dev`, come per il debito tecnico del 18/10 e per la spec 10.
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
- **17–18/10:** spec 09 (failover senza fermate, provider registrati a runtime, arbitro TypeSafe, file del proprietario, dialogo con un task, ripresa, modifiche dopo la fine), unita con la PR #6. Poi il debito tecnico (N13, N17, le attese del runner contate in frame), unito in locale.
- **18/10, sera e notte:** spec 10 in due parti (`docs/specs/10-parametric-hiring-cross-rag.md`, decisioni D1–D12): assunzione dei modelli per sotto-task, bus a incrocio, forma del prompt per famiglia di modello, interfaccia. Unita in locale.

Lezioni del porting ancora valide:
- `load_env` riempie da `.env` solo le chiavi **assenti**: per questo `demoEnv()` le mette a `""` invece di cancellarle. Due run di QA, prima del fix, avevano consumato API vere.
- La riga "ready" del server si stampa solo dopo il bind della porta.
- `team.release` salta i waiter già cancellati: senza, un agente restava occupato per sempre dopo `stop()`.

## 3. Prossimo passo

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
  - `gateway` (`/v1`, formato OpenAI);
  - `static` (`public/`, `/vendor/three*` da `node_modules`, `/preview/<run>/` in sandbox);
- motore:
  - `run.py` (missione, scheduler a tick, review, report, ripresa);
  - `tasker.py` (il loop di un worker);
  - `team.py`, `bus.py`, `tools.py` + `paths.py` (una regola dei percorsi per ogni sistema);
  - `run_memory.py`, `rag_budget.py` (misura del contesto e, spec 10, forma del prompt), `json_repair.py`;
  - `crossbus.py` (spec 10: i fatti dei file e i legami tra lavori, per `[LIVE CROSS-AGENT UPDATE]`);
  - `arbiter.py` (TypeSafe), `attachments.py`;
- `router/`: `index.py` (combo, cascata, cooldown, blacklist; spec 10: `catalog()`, `health()`, `chat(chain=…)`), `providers.py`, `profiler.py` (spec 10: taglia, specialità, costo), `hiring.py` (spec 10: analisi del sotto-task, catena, subentro), `mock.py` + `mock_texts.py` (la demo, nella lingua della run);
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
npm run test:browser                         # runner headless completo, missione inclusa (261 verifiche, ~6 min)
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
- fasi: `hygiene`, `views`, `checks`, `cubes`, `input`, `overlaps`, `labels`, `language`, `run`, `hiring` (spec 10: le assunzioni live e il subentro vengono dalla risposta di rete di una run salvata, perché la demo non assume nessuno), `recovery`;
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

- **Ticket aperti:** N10, N8, più il backlog della spec 03 (sezione 4).
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


## Stato al 18/10/2026, notte

- `main` = il merge `--no-ff` in locale (identità `agent-world-dev`) di `claude/spec10-parametric-hiring`, sopra `937673a`. I commit del branch:
  - `71c46c6` fix(secret-scan): la scansione della history lascia passare i merge che GitHub ha fatto per le PR;
  - `354f9a7` spec 10, parte 1: matrice di competenza, assunzione per sotto-task, subentro, bus a incrocio (R1–R3);
  - `be1c96e` spec 10, parte 2: il prompt nella forma del modello assunto (R4);
  - `bee15ca` spec 10, parte 2: il badge nella scheda Task, il catalogo nella scheda Router, la fase `hiring` del runner (R5);
  - il commit dei documenti: README, spec 10 e questo file.
  
  La parte 2 è nata nel worktree `claude/spec10-parametric-hiring-p2-…` ed è arrivata su `claude/spec10-parametric-hiring` con un fast-forward. Poi `git push origin main`.
- Il debito tecnico del branch precedente (N13, N17, le attese del runner in frame) è descritto in `docs/specs/06-language.md` §5 e `docs/specs/09-multimodal-interactive-recovery.md`, "Limiti noti".

### Completate (spec 10, parte 2)
- **R4, la forma del prompt** (dettagli: spec 10 §6):
  - `rag_budget.shape()`: piccolo (locale, gratuito, 14B e meno), reasoning, coder, generale, in quest'ordine (D6);
  - piccolo: passi atomici numerati, un esempio dalla skill, il contratto in fondo e dopo ogni risultato, il validatore che ferma un'azione a cui manca un argomento;
  - reasoning: checklist del QA, vincoli, lezioni del Brain, tutto prima della descrizione;
  - coder: albero esatto del progetto, interfacce dei file collegati, snippet delle skill;
  - generale e demo: il prompt di prima.
- **R5, l'interfaccia:** il badge 🤝 (modello, tier, specialità) e 🔀 nella scheda Task; le assunzioni e il catalogo profilato nella scheda Router; 52 chiavi nelle cinque lingue.
- **Due difetti trovati dai test, corretti** (D10, D11):
  - alla revisione che assume un altro modello, il primo passo del modello nuovo partiva con la forma vecchia: ora il `MODEL SWITCH` arriva prima del passo. Una mutazione (senza il cambio anticipato) fa rosso il test live;
  - un titolo come "Bad examples" veniva preso come l'esempio da imitare.

### Verifiche (Windows 11)
- `npm test` verde in 7 min 45 s: mondo 3D, dizionari, launcher, avvio, **pytest 1013 passati e 3 saltati** (la parità Rust ×2, ffmpeg assente), smoke, flussi, secret-scan, cartelle temporanee. Prima della spec 10 erano 934 passati.
- **`npm run test:browser`: 261 verifiche su 261, ALL OK** in 6 min 2 s, a 55,7 fps, con `known-red.json` vuoto. I 6 controlli nuovi sono la fase `hiring` (R5).
- **`npm run scan:secrets`: pulito.**
- QA visivo a 1920×1080 dagli screenshot del runner (`--shots`): scheda Task in demo e con un subentro, scheda Router con il catalogo.

### Ticket aperti
- N8, N10 e il backlog della spec 03 (sezione 4).

### Da verificare su Windows (o con chiavi vere)
- **Spec 10 con chiavi vere:** una run LIVE con modelli di famiglie diverse (un locale o `:free`, un reasoning, un coder) per vedere le quattro forme del prompt e un subentro vero per credito finito. Finora solo server finti.
- La voce in una run LIVE senza credito OpenAI ed ElevenLabs: deve parlare edge-tts, senza `uv add`. Senza rete, o con `media.providers.edgetts.enabled: false`, la voce di sistema (SAPI).
- La scoperta dei modelli con Ollama o LM Studio attivi.
- Una chiamata vera a TypeSafe con `TYPESAFE_API_KEY`.
- I nomi dei modelli dei provider nuovi della spec 09: verificati sulle fonti, non con chiamate vere (un nome sbagliato costa un 404, poi la blacklist).
- Il trascinamento di un file dal Desktop nella UI vera.

### Prossimi passi
1. Svuotare il Cestino, con dentro il backup del 14/10 (lo fa l'utente).
2. Le verifiche qui sopra, a partire dalla run LIVE della spec 10.
3. Il prossimo ciclo SDD, dal backlog.
