# Spec 11 — Core Hardening e Intent Engine a doppia modalità (Reverse Engineering + ricostruzione Clean-Room)

**In breve.** Richiesta dall'utente il 19/10/2026, partendo da `main` = `33c6135` (la spec 10 unita).
- **Fase 1, Core Hardening (T01–T05):** budget e circuit breaker, shell e LAN a fiducia zero, tokenizer per il codice e consolidamento del Brain, checkpoint del Tasker, streaming vero su `/v1`.
- **Fase 2, Intent Engine (T06–T10):** la CEO classifica la missione (`direct_build`, `reverse_only`, `deconstruct_and_build`); scheletri AST e tool di Reverse Engineering; il team `reverse`; il passaggio clean-room (Deconstruct → Handover → Build → Parity QA); il simulatore demo del flusso nuovo.
- **Regole di sessione:** un macro-step (un ticket) per sessione; si va avanti solo con `npm test` verde al 100%; ogni funzione aggiunta in `crates/aw_core` ha il gemello Python in `backend/backend/` con parità esatta; a fine step si aggiornano README, questo documento e `HANDOFF.md`.
- **Stato:** T01 fatto (19/10/2026, §3), con le decisioni D1–D5 confermate dall'utente; T02 fatto (19/10/2026, §4), con le decisioni D6–D11 confermate dall'utente; T03 fatto (19/10/2026, §5), con le decisioni D12–D15 confermate dall'utente; T04 fatto (19/10/2026, §6), con le decisioni D16–D19 confermate dall'utente; T05 fatto (20/10/2026, §7), con le decisioni D20–D25 confermate dall'utente; Fase 2, T06–T10, fatta in un'unica passata su richiesta dell'utente (20/10/2026, §8), con le decisioni D26–D35 confermate dall'utente. Spec chiusa: unita in `main` il 20/10/2026 con il merge `43ad2b7`.

## 1. Regole di sessione (dall'utente)

1. **Un solo step per sessione.** Si esegue un macro-step alla volta; non si passa al successivo finché `npm test` (pytest + node + probe di parità Python/Rust) non è verde al 100%.
2. **Parità Python/Rust obbligatoria.** Ogni funzione aggiunta in `crates/aw_core` ha l'equivalente esatto in `backend/backend/`, con tolleranza zero nelle probe di parità.
3. **Aggiornamento dello stato.** A fine step: `README.md`, la spunta dei ticket qui sotto, `HANDOFF.md` con i file toccati, i test aggiunti e il prossimo step esatto da cui ripartire a contesto pulito.

## 2. Ticket

### Fase 1: Core Hardening

- [x] **T01 — Budget e circuit breaker** (`run.py`, `config/default.json`): `limits.maxCallsPerRun` (250) e `limits.maxCostUSD`. Una run che supera la soglia non fallisce: emette l'evento SSE `waiting` e va in pausa, chiedendo all'utente se proseguire. Fatto: §3.
- [x] **T02 — Shell a fiducia zero e autenticazione in LAN** (`tools.py`, `security.py`, `i18n.py`). Fatto: §4.
  - con `run_command` attivo (`AGENT_WORLD_ALLOW_SHELL=1`) il sottoprocesso riceve un `env` ripulito (via tutte le `*_API_KEY`, `GITHUB_TOKEN`, `AGENT_WORLD_API_KEY`);
  - se l'host richiesto non è `127.0.0.1` / `localhost` / `::1`, anche `/api/*` e `/api/events` vogliono `AGENT_WORLD_API_KEY` (Bearer o cookie di sessione);
  - chiudere il ticket N13: i messaggi HTTP 403/400 nel dizionario `i18n.py` della lingua attiva.
- [x] **T03 — Tokenizer per il codice e consolidamento del Brain** (`search.py`, `crates/aw_core`, `brain.py`). Fatto: §5.
  - `tokenize()` (Python e Rust) conserva i token tecnici del codice (identificatori con `_`, `::`, `@`) e i caratteri alfanumerici Unicode, con parità 1:1 nella probe di avvio;
  - `brain.consolidate()`: deduplica le note con similarità coseno > 0,88 e aggiunge un fattore di *time-decay* nell'RRF, per premiare le lezioni del QA più recenti.
- [x] **T04 — Checkpoint e time-travel del Tasker** (`tasker.py`, `store.py`, `run.py`): uno snapshot leggero dello stato del sotto-task a ogni passo valido; quando un worker supera `escalateAfter` (2 bocciature) e passa a `frontier`, si torna all'ultimo snapshot pulito invece di accodare gli errori nel contesto. Fatto: §6.
- [x] **T05 — Streaming vero su `/v1`** (`routes/gateway.py`, `bus.py`): `/v1/chat/completions` con `"stream": true` manda chunk SSE compatibili OpenAI man mano che il provider risponde, invece del blocco unico finale. Fatto: §7.

### Fase 2: Intent Router e motore di Reverse Engineering

**Classificatore d'intenzione della CEO** (`run.py`): all'avvio di `POST /api/runs` la CEO classifica la missione (`run.mode`):
1. `direct_build`: sviluppo classico da zero (il flusso di oggi, invariato);
2. `reverse_only`: analisi, decodifica architetturale, estrazione di API e logica, audit di un bersaglio esistente (cartella locale, repo o codice fornito); si consegna il Blueprint;
3. `deconstruct_and_build`: inversione + ricostruzione clean-room. Il sistema decodifica l'applicazione bersaglio, ne estrae la logica di business in un documento neutrale (`blueprint.json` + specifica Markdown) e poi i team di sviluppo la ricreano da zero dal Blueprint.

- [x] **T06 — Estrattore strutturale** (`aw_core` + fallback Python in `deconstructor.py`): `extract_skeleton(source, ext)` estrae da Python, JS/TS, Rust, HTML/CSS firme di funzioni e classi, import/export, route API, variabili di stato e grafo delle chiamate interne, senza i corpi pesanti. Fatto: §8.
- [x] **T07 — Tool di Reverse Engineering** (`tools.py`). Fatto: §8.
  - `scan_target_tree(path)`: file, linguaggi, entry point, dipendenze (`package.json`, `pyproject.toml`, `Cargo.toml`) e dimensione del bersaglio;
  - `extract_code_skeleton(path)`: la radiografia strutturale di un file (il 90% di token in meno di `read_file`);
  - `write_blueprint(data)`: valida e salva in `data/workspace/<run_id>/blueprint.json` la logica decodificata (architettura, modelli dati, endpoint, regole di business, casi limite, criteri di parità).
- [x] **T08 — Team Reverse Engineering** (`config/default.json`, `public/js/world/`): il team `reverse` (lead *Kira*, worker *Zero*, combo `code`, tool `scan_target_tree`, `extract_code_skeleton`, `write_blueprint` più quelli di base), la sua postazione nell'ufficio 3D e le traduzioni nei 5 dizionari. Fatto: §8.
- [x] **T09 — Orchestrazione dell'inversione** (`run.py`), con `run.mode == "deconstruct_and_build"` (nel codice `run.intent`, §8.3). Fatto: §8.
  1. **Fase A (Deconstruct):** la CEO assegna i primi workstream solo al team `reverse`;
  2. **Fase B (Handover):** quando il QA approva `blueprint.json`, `run.py` lo passa al Prompt Lab (Pia) e alla CEO per i workstream di ricostruzione;
  3. **Fase C (Clean-Room Build):** Sviluppo (Leo, Nina), Design (Iris, Ugo) e Contenuti ricevono nei brief le specifiche del Blueprint e ricreano l'applicazione;
  4. **Fase D (Parity QA):** il QA (Bruno, Vera) confronta il codice generato punto per punto con i requisiti funzionali del Blueprint.
- [x] **T10 — Simulatore demo e test** (`router/mock.py`, `tests/`): `mock.py` e `mock_texts.py` (5 lingue) simulano anche `deconstruct_and_build` senza chiavi; `tests/test_deconstructor.py` (con la parità Python/Rust di `extract_skeleton`) e i test end-to-end del doppio binario. Fatto: §8.

## 3. T01 — Budget e circuit breaker (fatto il 19/10/2026)

### 3.1 Il punto di partenza (misurato su `33c6135`)

- `usage.calls` si contava in tre punti: `Run.chat()` (con i token), `agent_reply()` (senza token) e la vista delle foto (`inspect_image`, con i token). Nessun costo, nessun limite, nessun prezzo in tutto il backend.
- Le richieste al proprietario (`waiting`) erano di tre tipi: `plan`, `question`, `model`.
- **Quante chiamate fa una missione demo** (simulatore, `AGENT_WORLD_FAST=1`, en e it):

  | Missione | Workstream | Task | Chiamate |
  |---|---|---|---|
  | documento semplice | 3 | 3 | 31 |
  | landing page semplice | 5 | 5 | 44 |
  | campagna complessa | 5 | 16 | 162 |
  | web app completa (il piano più grande del simulatore) | 7 | 20 | 213 (en) – 228 (it) |

  La soglia di 250 sta a 22 chiamate dalla missione demo più grande, e la variante italiana ne fa 15 più dell'inglese: per questo il simulatore non conta (D1).

### 3.2 Cosa fa

- **`backend/backend/budget.py`** (nuovo, funzioni pure): `initial()` congela i limiti nella run (`run.budget = {step, limit, approvals}`, 0 o `null` = spento); `simulated()`, `price()`, `cost()`, `spend()` contano ogni risposta (`usage.providerCalls`, `usage.costUSD`); `over()` dice quale limite è raggiunto; `extend()` aggiunge un blocco; `ensure()` dà il budget alle run salvate prima della spec 11.
- **`config/default.json`:** `limits.maxCallsPerRun: 250`, `limits.maxCostUSD: 5`, `router.pricing` (livelli e pattern di modelli, in dollari per milione di token `[input, output]`).
- **`run.py`:**
  - `Run.chat()` passa da `budget_gate()` prima di ogni chiamata del lavoro della run (CEO, lead, Skill Hub, Prompt Lab, worker, QA, consigli, decisioni automatiche, report) e conta la risposta con `budget.spend()`; la vista delle foto fa lo stesso;
  - al limite `trip_budget()` mette la run in pausa, scrive il motivo nel pannello Messaggi, mette la CEO in stato "asking" e apre una richiesta `waiting` di tipo `budget` (`reason`, `spent`, `limit`, `step`, `text`): l'evento SSE `waiting` parte da `add_waiting()`;
  - `answer_budget()`: "approve" (o una risposta senza decisione) aggiunge un blocco contato da dove la run è arrivata, gira le note del proprietario a tutta la squadra e riprende; "reject" scrive `run.error` ("Stopped at the budget: …") e ferma la run, che resta riprendibile;
  - il pulsante Riprendi con una richiesta di budget aperta vale come "approve"; la ripresa dal punto di blocco di una run ferma al budget aggiunge un blocco e lo dice;
  - ogni chiamata del lavoro tiene un posto (`_in_flight`) finché la sua risposta non è contata: il limite delle chiamate è esatto anche con 8 worker in parallelo.
- **`i18n.py`:** 10 testi nuovi nelle cinque lingue; gli importi seguono la lingua della run ("$0.65", "0,65 $").
- **UI** (`public/js/main.js`, `public/js/i18n.js`, 13 chiavi × 5 lingue): la richiesta "budget raggiunto" con "Prosegui (un altro blocco)" e "Ferma la run" e le note per la squadra, e un avviso suo dopo la risposta (non quello del piano); nel pannello della missione le chiamate pagate su limite e il costo stimato su budget (solo quando ha risposto un provider vero); nelle Impostazioni i due limiti, con 0 = nessun limite.

### 3.3 Decisioni (confermate dall'utente il 19/10/2026)

- **D1 — Il simulatore non conta.** Le risposte del simulatore (demo, emergenza in live) restano in `usage.calls` ma non in `usage.providerCalls` né nel costo, quindi non fanno scattare il budget. Misurato in §3.1: con il simulatore contato, la missione demo più grande arriverebbe a 228 chiamate su 250, e il flusso a doppio binario della T10 supererà la soglia in demo, fermando una demo che non costa nulla.
- **D2 — Il costo è una stima, con un budget di serie di 5 $.** `router.pricing.models` (chiave esatta, poi il primo glob in ordine) e poi `router.pricing.tiers` sul `costTier` del profiler (spec 10): `local` e `free` 0, `low` [1, 5], `high` [5, 25]. I prezzi dei modelli di serie sono listini indicativi da verificare (Claude Opus [5, 25], Sonnet [3, 15], Haiku [1, 5], GPT-5 [1,25, 10], GPT-5 mini [0,25, 2], Gemini Pro [2, 12], Grok [3, 15], DeepSeek [0,6, 2,2], Mistral Large [2, 6], Codestral [0,3, 0,9], Sonar Pro [3, 15], Sonar [1, 1]); un modello sconosciuto a pagamento vale come il suo livello, che è prudente. I livelli gratuiti del profiler (Groq, Cerebras, NVIDIA, Cloudflare, Gemini Flash) valgono 0.
- **D3 — Un blocco alla volta.** "Prosegui" porta i limiti a quanto già usato più un blocco della stessa misura (`step`), per chiamate e costo insieme: le chiamate già in volo quando è scattato non si pagano due volte e non arriva subito una seconda richiesta per l'altro limite. "Ferma la run" la ferma (stato `stopped`, ripresa possibile); il pulsante Riprendi e la ripresa dal punto di blocco valgono come un "Prosegui".
- **D4 — Il limite delle chiamate è esatto, quello del costo no.** Una chiamata prende il suo posto al cancello e lo tiene finché la risposta non è contata, quindi le chiamate pagate non superano mai `maxCallsPerRun` (provato con 8 chiamate in parallelo su un limite di 3). Il costo di una chiamata si sa solo quando risponde: il limite di costo può essere superato al massimo dal costo delle chiamate già in volo (al più `maxParallel` worker più i lead che preparano).
- **D5 — Le chiamate chieste dal proprietario si contano ma non si fermano.** "💡 Trova tu una soluzione", una modifica dopo la fine e la risposta di un task al box del proprietario passano anche oltre il budget: un clic del proprietario non deve restare appeso alla sua stessa richiesta di budget. Lo stesso vale per una run salvata (non attiva) o già finita.

### 3.4 Test

- **`backend/tests/test_budget.py`** (33 test):
  - le funzioni pure: limiti di serie, limiti spenti, prezzi (chiave esatta, glob, livello, gratuito, locale), il simulatore che non costa, `over` / `extend` / `ensure`;
  - una run su un provider a pagamento finto: la pausa al limite con l'evento `waiting` e i suoi numeri, "Prosegui" con le note alla squadra, una risposta senza decisione e il pulsante Riprendi, "Ferma la run", il limite di costo, gli importi in italiano, 8 chiamate parallele su un limite di 3, le chiamate del proprietario, il simulatore, una run salvata o finita, uno stop durante l'attesa;
  - missioni intere (la demo, con le risposte rietichettate come di GPT-5): la run si ferma a ogni blocco esattamente al limite e arriva in fondo; una run fermata al budget riprende con un blocco nuovo e finisce; la route `/answer` prende la decisione.
- **`backend/tests/test_run.py`:** la forma di `run.data` e di `usage` cresce di `budget`, `providerCalls` e `costUSD`.
- **Runner del browser, fase `budget`** (5 verifiche, criterio `T01`): la richiesta con i suoi numeri e i due pulsanti, il pannello della missione, "Prosegui" che manda decisione e note e lo dice con il suo avviso, la richiesta che si chiude e il conteggio sul blocco nuovo, le Impostazioni. Una demo non arriva mai al budget (D1): la run live arriva dal flusso di eventi della pagina stessa (un `EventSource` avvolto prima del caricamento) e la risposta alla `fetch` della pagina.
- **Mutazioni:** ognuna deve far diventare rosso il suo test, e lo fa.

  | Mutazione | Test che la prende | Rosso in |
  |---|---|---|
  | nessun posto per le chiamate in volo | 8 chiamate parallele su un limite di 3 | 90 s |
  | nessun cancello in `chat()` | la pausa al limite | 90 s |
  | anche le chiamate del proprietario si fermano | le chiamate del proprietario | 6 s |
  | "Ferma la run" prosegue | il rifiuto | 1 s |
  | il pulsante Riprendi ignora il budget | risposta senza decisione e Riprendi | 6 s |
  | nessun blocco nuovo alla ripresa | la missione fermata al budget che riprende | 7 s |
  | il simulatore conta | il simulatore non fa scattare il budget | 6 s |
  | `extend()` parte dal limite vecchio | `over` / `extend` | 1 s |
  | UI: senza il ramo `budget` della richiesta e senza la spesa | le verifiche 1–3 della fase `budget` | — |

  Due prime prove si fermavano solo per timeout. Quella del pulsante Riprendi ha mostrato un difetto vero, ora corretto: una run tolta dalla pausa con la richiesta di budget ancora aperta faceva girare `budget_gate()` senza mai cedere il loop. Nessun percorso di oggi ci arriva, ma ora il cancello rimette la pausa. La verifica dell'avviso è nata rossa: dopo "Prosegui" la UI diceva "Plan approved: off we go!".

### 3.5 Verifiche

- `npm test` verde in 6 min 20 s; **pytest 1046 passati e 3 saltati** (prima 1013; i saltati sono la parità Rust ×2 senza il modulo compilato e ffmpeg). T01 non aggiunge funzioni a `crates/aw_core`.
- `npm run test:browser`: **266 verifiche su 266**, ALL OK, in 4 min 58 s a 108 fps; `known-red.json` vuoto.
- `test_budget.py` verde in sei giri di fila (le missioni intere sono le più sensibili ai tempi).

- QA visivo a 1920×1080 dagli screenshot della fase `budget` (`--shots`): la richiesta nel pannello di sinistra, la run "running · paused" con "250/250 paid calls" e "≈ $1.23 of $5.00"; le Impostazioni con la sezione "Run budget".

### 3.6 Limiti noti

- I prezzi sono stime da listino, non la fattura: un provider che fa pagare un livello gratuito (o prezzi diversi per contesti lunghi) va aggiunto a `router.pricing.models`.
- Non entrano nel conteggio della run, come prima della spec 11: la chat con un agente (`POST /api/chat/{agent_id}`), le chiamate di TypeSafe come arbitro e quelle del gateway `/v1`.
- Uno stop non aspetta le chiamate già partite: arrivano e si contano dopo che la run è ferma.

## 4. T02 — Shell a fiducia zero e autenticazione in LAN (fatto il 19/10/2026)

### 4.1 Il punto di partenza (misurato su `f66d1d7`, T01)

- **La shell.** `run_command` passava al comando l'ambiente intero del server. `load_env` copia `.env` in `os.environ`, quindi un `env` o un `set` scritto da un modello stampava ogni chiave dei provider, `GITHUB_TOKEN` e `AGENT_WORLD_API_KEY`.
- **Le chiavi che la configurazione nomina** (`keyEnv` in `default.json`): 23. Di queste, 19 finiscono in `_API_KEY`; le altre 4 no (`HF_TOKEN`, `CLOUDFLARE_API_TOKEN`, `FAL_KEY`, `LOCAL_OPENAI_KEY`). La regola letterale del ticket (`*_API_KEY`, `GITHUB_TOKEN`, `AGENT_WORLD_API_KEY`) ne avrebbe lasciate passare 4 su 23 (D6). Un provider registrato dall'app deve avere una chiave che finisce in `_KEY` o `_TOKEN`; un `local.json` scritto a mano può usare qualsiasi nome.
- **La LAN.** `AGENT_WORLD_ALLOWED_HOSTS` bastava ad aprire tutta l'API a chiunque sulla rete, senza login: il README lo diceva in un riquadro. `AGENT_WORLD_API_KEY` proteggeva solo `/v1`, e solo se impostata.
- **Chi è locale.** Il guard della spec 07 decideva tutto dall'header `Host`, che scrive il client: con la chiave chiesta "quando l'host non è `127.0.0.1`", uno script sulla rete l'avrebbe saltata scrivendo `Host: 127.0.0.1` (D7).
- **N13, quello che restava in inglese** tra i 403/400 e vicini: `Forbidden` e `Not found` dei file statici, `Skill not found` (404), il 400 dello Skiller (il testo di `DownloadError`), il 400 e il 401 del gateway `/v1`. In più un difetto: `POST /api/skills/repo` con un git che fallisce (repo che non c'è, niente rete) dava un 500 nudo, con un `RuntimeError` in italiano ("git ha risposto …") nel log e "Error 500" nella UI.

### 4.2 Cosa fa

- **`backend/backend/tools.py`:** `SECRET_WORDS`, `shell_env()` e `config_key_names()`. `run_command` passa sempre al comando `env=shell_env(secrets)`: l'ambiente del server senza ogni variabile che ha una parola segreta nel nome e senza i nomi in `secrets`. I nomi si confrontano in maiuscolo, come fa Windows.
- **`backend/backend/run.py`:** il tool `run_command` passa `secrets=config_key_names(self.cfg)`, cioè ogni `keyEnv` della configurazione in uso (`default.json` più `local.json`, quindi anche i provider registrati a runtime).
- **`backend/backend/security.py`:** dopo i controlli della spec 07 (Host, `Sec-Fetch-Site`, `Origin`), che restano identici e restano primi, una richiesta non locale a `/api/*`, `/api/events` o `/v1/*` vuole la chiave:
  - senza chiave sul server: 403 `lan_needs_key`;
  - senza credenziali valide: 401 `auth_required`, con `WWW-Authenticate: Bearer realm="agent-world"`;
  - le credenziali: `Authorization: Bearer <chiave>` (a tempo costante) o il cookie `aw_session` valido;
  - nuove: `is_local()`, `access_key()` (letta a ogni richiesta, perché la registrazione di un provider rilegge `.env`), `session_token()`, `valid_session()`, `authorized()`.
- **`backend/backend/routes/session.py`** (nuovo): `GET /api/session` dice `local`, `keyRequired`, `keySet`, `authenticated` e la lingua dell'app; `POST /api/session` con `{"key": …}` controlla la chiave e mette il cookie. Sono le sole route di `/api` che dalla rete non vogliono la chiave.
- **N13** (`i18n.py`, 10 chiavi nuove × 5 lingue): `auth_required`, `auth_wrong`, `lan_needs_key`, `forbidden`, `not_found`, `skill_not_found`, `download_refused`, `repo_failed`, `messages_required`, `api_key_invalid`. Le usano `security.py`, `routes/session.py`, `routes/static.py`, `routes/skills_brain.py` e `routes/gateway.py` (che tiene la forma OpenAI degli errori). `skills.read()` alza `Refusal("skill_not_found")`, che resta un `ValueError` per i tool degli agenti; il messaggio di `_git()` è in inglese e porta l'ultima riga di git.
- **UI** (`public/js/main.js`, `public/js/i18n.js` con 5 chiavi × 5 lingue, `public/index.html`, `public/css/app.css`): prima di tutto il resto la pagina chiede `GET /api/session`; dalla rete, senza sessione, mostra il dialogo "Chiave d'accesso" nella lingua dell'app, con l'errore del server sotto il campo, e solo dopo carica lo stato e apre il flusso di eventi. Esc e un clic fuori chiudono gli altri dialoghi, non questo. Con la chiave assente sul server il dialogo dice solo perché la rete è chiusa. Un 401 a pagina aperta (sessione scaduta, chiave cambiata) riapre il dialogo, poi ricarica la pagina.
- **Runner del browser** (`scripts/browser-test.js`): il server del runner ha una chiave d'accesso casuale a ogni giro e ammette il nome `lan.localhost`; la fase `lan` apre lì la stessa app. Tutte le altre fasi girano su `127.0.0.1` con la chiave impostata, quindi provano anche che il flusso locale non cambia.

### 4.3 Decisioni (confermate dall'utente il 19/10/2026)

- **D6 — Dalla shell esce ogni variabile che sembra un segreto, più quelle che la configurazione nomina.** Una variabile resta fuori quando una delle parole del suo nome (separate da `_`) è `KEY`, `KEYS`, `APIKEY`, `TOKEN`, `TOKENS`, `SECRET`, `SECRETS`, `PASSWORD`, `PASSWD`, `CREDENTIALS` o `AUTH`, oppure quando la configurazione la nomina come `keyEnv`, qualunque nome abbia. Così escono anche `HF_TOKEN`, `FAL_KEY`, `CLOUDFLARE_API_TOKEN`, `AWS_SECRET_ACCESS_KEY`, `GOOGLE_APPLICATION_CREDENTIALS`, `SSH_AUTH_SOCK` (l'agente SSH del proprietario) e `OPENAI_API_KEY_BACKUP`; restano `TOKENIZERS_PARALLELISM`, `PORT`, `PATH` e tutto quello che serve ai comandi per partire. Non escono gli URL (`baseUrlEnv`, `CLOUDFLARE_ACCOUNT_ID`): non sono chiavi e un comando può averne bisogno. Non si legge `.env` per togliere anche le sue righe che non sembrano chiavi: ci sono anche impostazioni come `PORT`.
- **D7 — Locale vuol dire `Host` di loopback e connessione da questa macchina.** Il ticket dice "quando l'host non è `127.0.0.1` / `localhost` / `::1`", ma l'header `Host` lo scrive il client: uno script sulla rete che scrive `Host: 127.0.0.1` sarebbe stato locale. Ora la chiave non serve solo con un `Host` di loopback **e** un indirizzo del client di loopback (`127.0.0.0/8`, `::1`, `::ffff:127.0.0.1`). Il nome della rete aperto da questa stessa macchina (`http://192.168.1.20:4300`) vuole la chiave. Uvicorn, dietro un proxy sulla stessa macchina, prende l'indirizzo da `X-Forwarded-For`; un proxy che riscrive l'`Host` in `127.0.0.1` senza quell'header fa sembrare locale tutta la rete (README).
- **D8 — Senza chiave sul server la rete è chiusa.** Prima di T02 `AGENT_WORLD_ALLOWED_HOSTS` da solo apriva l'API a tutta la rete. Ora una richiesta dalla rete senza `AGENT_WORLD_API_KEY` sul server riceve 403 "Access from the network is off: …", e la pagina lo dice. Il test della spec 07 `test_more_hosts_can_be_allowed_for_a_lan_setup` ora manda la chiave.
- **D9 — Dalla rete anche `/v1` vuole la chiave; la pagina e le anteprime no.** Il gateway chiedeva la chiave solo se impostata: dalla rete ora la chiede sempre (D8). La pagina (`public/`, `/vendor/three*`) è il codice dell'app e porta il dialogo del login. Le anteprime `/preview/<run>/` restano aperte: i siti generati girano in una sandbox con un'origine opaca, e le loro richieste (CSS, immagini, script) per il browser sono di un altro sito, quindi un cookie `SameSite` non ci arriverebbe e su `http` un cookie `SameSite=None` non si può mettere. Chi conosce l'id di una run ne vede il sito: ticket **N18** (§4.6).
- **D10 — Il browser entra con un login, e il cookie non è la chiave.** La pagina chiede `GET /api/session`, che non vuole la chiave e dice anche la lingua dell'app (la configurazione è chiusa fino al login). `POST /api/session` controlla la chiave a tempo costante e mette `aw_session`: `HttpOnly` (nessuno script lo legge), `SameSite=Strict` (nessun altro sito lo manda), `Path=/`, `Secure` quando la richiesta è `https`, valido **7 giorni** fissi. Il valore è `<scadenza>.<HMAC-SHA256(chiave, scadenza)>`: niente stato sul server, quindi sopravvive a un riavvio; un cookie rubato scade e non rivela la chiave; cambiare la chiave chiude tutte le sessioni. Confermati anche i 7 giorni e la durata fissa (non si allunga con l'uso).
- **D11 — N13: la frase nel dizionario, il dettaglio tecnico così com'è.** I 30 e più messaggi di `downloads.py` (nomi di file nell'archivio, limiti, cartelle) e l'ultima riga di git restano dettagli in inglese dentro una frase tradotta ("Download rifiutato: …", "Non riesco a scaricare il repository: …"). Un git che fallisce dà 502, come un upstream che non risponde, invece del 500 nudo. Anche i 404 dei file statici e della skill passano dal dizionario, perché stavano nello stesso elenco di N13. Resta com'è il testo che arriva da un provider (il 502 del gateway, il test di una combo nella scheda Router): è la risposta dell'upstream.

### 4.4 Test

- **`backend/tests/test_zero_trust.py`** (nuovo, 27 test):
  - la shell: `shell_env` toglie 14 segreti di forme diverse e tiene 8 variabili che non lo sono; i nomi della configurazione senza badare alle maiuscole; `config_key_names` su `default.json` più un provider con una chiave di nome libero; un comando vero che elenca l'ambiente non vede nessuna chiave e vede il resto; una run vera con `allowShell` e un provider `MYBOX_CREDS` (nome senza parole segrete) non la passa al comando;
  - chi è locale: 10 combinazioni di indirizzo e `Host`, comprese `Host: 127.0.0.1` dalla rete, il nome della rete da questa macchina, nessun indirizzo, `::ffff:127.0.0.1`;
  - il cookie: firmato, scade, muore con la chiave, una scadenza allungata non è firmata, 9 valori rotti rifiutati senza 500;
  - l'app vera (con l'indirizzo del client voluto): il flusso locale con la chiave impostata; dalla rete 401 su 7 letture e su un POST; `Host` falsificato; il Bearer giusto, sbagliato e senza `Bearer`; la rete chiusa senza chiave; il login (risposta di `GET /api/session`, chiave sbagliata, corpo non JSON, chiave giusta, attributi del cookie, l'API e un POST con il cookie); cookie scaduto, di un'altra chiave, la chiave stessa come cookie; i controlli della spec 07 ancora primi, anche sul login; la pagina che si apre senza chiave;
  - il guard da solo: `/api/events` dalla rete solo con il Bearer o il cookie (che può stare tra altri cookie), `HEAD`, `/api` nudo, `/apis-…` che non è API.
- **`backend/tests/test_i18n.py`:** i rifiuti della LAN nelle cinque lingue (e la lingua in `GET /api/session`); `Forbidden` e `Not found` dei file statici; i 400 e 401 del gateway nella forma OpenAI; il 400 dello Skiller e il 502 di git, con il dettaglio; `skill_not_found` tra i rifiuti di ogni route; una guardia sui sorgenti (AST) che fallisce se una route scrive un 4xx con un testo che non viene da `http_error`; la guardia N17 ora vede anche "risposto".
- **`backend/tests/test_security.py`:** la LAN della spec 07 manda la chiave (D8).
- **Runner del browser, fase `lan`** (6 verifiche, criterio `T02`, con l'app in italiano): il login nella lingua dell'app, senza niente dell'ufficio dietro e senza avvisi; Esc e un clic fuori non lo chiudono; una chiave sbagliata con le parole del server; la chiave giusta che apre l'ufficio e il flusso di eventi, con il cookie `HttpOnly`, `SameSite=Strict`, 7 giorni, senza la chiave dentro; un reload senza login; `127.0.0.1` senza login.
- **Mutazioni:** ognuna deve far diventare rosso il suo test, e lo fa.

  | Mutazione | Test che la prende | Rosso in |
  |---|---|---|
  | la shell riceve l'ambiente intero | un comando vero che non vede chiavi; la run che non passa i nomi della configurazione | 7 s |
  | la run non passa i nomi della configurazione | la run che non passa `MYBOX_CREDS` | 2 s |
  | i nomi della configurazione confrontati con le maiuscole | i nomi senza badare alle maiuscole | 7 s |
  | locale guardando solo l'`Host` | 3 casi di chi è locale; `Host: 127.0.0.1` dalla rete | 6 s |
  | nessun controllo della chiave dalla rete | 7 test di `test_zero_trust.py` | 17 s |
  | senza chiave sul server la rete è aperta | la rete chiusa senza chiave | 6 s |
  | una sessione non scade mai | il cookie che scade; il cookie vecchio di 8 giorni | 6 s |
  | il login non è esente dalla chiave | il login; la rete chiusa senza chiave | 6 s |
  | un cookie leggibile dagli script (`HttpOnly=False`, `SameSite=Lax`) | il login | 6 s |
  | `Forbidden` di nuovo in inglese | i rifiuti dei file statici (3 lingue); la guardia sui sorgenti | 52 s |
  | il 400 del gateway di nuovo scritto a mano | i rifiuti del gateway (le 2 lingue non inglesi); la guardia sui sorgenti | 52 s |
  | un git che fallisce torna un 500 nudo | i download delle skill (3 lingue) | 53 s |
  | UI: il boot senza `GET /api/session` | verifica 1 della fase `lan` | 17 s |
  | UI: l'errore del server non si mostra nel dialogo | verifica 3 della fase `lan` | 22 s |
  | UI: Esc chiude anche il login | verifiche 2 e 3 della fase `lan` | 17 s |

  I tempi sono quelli del file di test intero (`test_i18n.py` dura 52 s) o della sola fase `lan`. Dopo ogni mutazione l'impronta di `git diff` è uguale a prima: nessun file resta cambiato.

  **Una mutazione all'inizio è passata verde**, quella del boot senza `GET /api/session`: il 401 di `/api/state` apriva lo stesso il login (la strada di `relogin`, pensata per una sessione che scade a pagina aperta), ma con l'avviso "Could not load the state" dietro il dialogo e in inglese anche con l'app in un'altra lingua. La fase `lan` girava con l'app in inglese, che è anche la lingua di partenza della pagina, quindi non vedeva la differenza. Ora la fase mette l'app in italiano (e la rimette com'era alla fine) e vuole zero avvisi: la mutazione è rossa.

  **Un difetto trovato dal passaggio avversario**, prima del commit: Esc e un clic fuori chiudono ogni `.modal`, quindi chiudevano anche il login e lasciavano la pagina ferma a metà avvio, senza ufficio e senza dialogo. La verifica è stata scritta prima della correzione; che sappia fallire lo mostra la mutazione "Esc chiude anche il login".

### 4.5 Verifiche

- `npm test` verde in 6 min 34 s (due giri: dopo il codice e sull'albero finale, 6 min 35 s): mondo 3D, dizionari, launcher, avvio, **pytest 1093 passati e 3 saltati** (prima 1046: 27 in `test_zero_trust.py`, 20 in `test_i18n.py`; i saltati sono la parità Rust ×2 senza il modulo compilato e ffmpeg), smoke, flussi, secret-scan, cartelle temporanee. T02 non aggiunge funzioni a `crates/aw_core`.
- `npm run test:browser`: **272 verifiche su 272**, ALL OK, in 5 min 8 s a 113,3 fps sull'albero finale (5 min 5 s a 108,9 fps il primo giro); `known-red.json` vuoto. Le 6 nuove sono la fase `lan`; tutte le altre fasi girano con la chiave d'accesso impostata sul server, quindi il flusso locale è provato da tutto il resto del runner.
- QA visivo a 1920×1080 dagli screenshot della fase `lan` (`--shots`): il dialogo "Chiave d'accesso" al centro, con "Entra", sopra l'ufficio vuoto e le schede senza dati; dopo la chiave, l'ufficio con i 16 agenti, la run precedente e i suoi workstream.
- **N18, misurato** (§4.6): un server vero di questo checkout risponde 174 tentativi di `/preview/<id>/` al secondo a un solo client con 64 connessioni (il limite è il server, un processo solo).

### 4.6 Limiti noti

- **La shell non è una sandbox.** Senza chiavi nell'ambiente, un comando legge ancora i file a cui arriva l'utente del server: la cartella della run sta in `data/workspace/`, e `.env` sta tre cartelle più su. T02 toglie la via più facile (`env`, `set`, uno script di `postinstall` che legge `process.env`), non quella dei file: `AGENT_WORLD_ALLOW_SHELL` resta spento di default.
- **N18 — le anteprime dalla rete** (nuovo ticket aperto, D9): `/preview/<id>/` risponde senza chiave. Gli id sono 8 cifre esadecimali (32 bit). Misurato con un server vero di questo checkout: 174 tentativi al secondo da un client con 64 connessioni, tutti 404. Per trovare per caso un sito, in media, servono circa 34 ore con 100 run salvate, 14 giorni con 10, 143 giorni con una. Proposta: un segmento firmato nel percorso (`/preview/<id>.<firma>/`), che le pagine relative del sito si portano dietro, dato dalla UI solo a chi ha la sessione.
- **Nessun limite ai tentativi** sul login e sul Bearer: la difesa è una chiave lunga e casuale (il README dà il comando per farla).
- **Su `http` la chiave e il cookie passano in chiaro.** In una rete che non si controlla serve un proxy `https` davanti (allora il cookie è anche `Secure`).
- **I cookie sono per host, non per porta:** un'altra app web sulla stessa macchina, su un'altra porta, riceve `aw_session`. È una scadenza firmata, non la chiave, e muore in 7 giorni o con una chiave nuova.
- **Un flusso di eventi già aperto resta aperto** dopo la scadenza della sessione: la chiave si controlla quando si apre.
- **Dietro il dialogo**, nella pagina ancora vuota e scurita, gli esempi, il pulsante "Start the company" e il selettore della lingua restano in inglese finché non si entra: la lingua completa (`applyLanguage()`) vuole la configurazione, che dalla rete si legge solo dopo il login. I testi statici e il dialogo sono già nella lingua dell'app.
- **Restano com'erano** (non sono 403/400): i 422 di FastAPI sui parametri e il 500 di un corpo JSON rotto su `/api/*`.

## 5. T03 — Tokenizer per il codice e consolidamento del Brain (fatto il 19/10/2026)

### 5.1 Il punto di partenza (misurato su `4adcaec`)

- **Il tokenizer** divideva su `[^a-z0-9]+`. Un identificatore si spezzava (`budget_gate` → `budget`, `gate`; `std::collections::HashMap` → `std`, `collections`, `hashmap`; `@pytest.fixture` → `pytest`, `fixture`). Il greco, il cirillico, il devanagari e il CJK non davano **nessun** token (`ΟΔΟΣ λόγος`, `Привет мир сервер`, `हिन्दी भाषा`, `数据库很快` → nessun token), `smørrebrød` diventava `rrebr` e `Straße` `stra`.
- **I vettori locali** (`ngram_vector`) codificavano i grammi in ASCII, e il Rust li tagliava a byte: con un token non ASCII il Python avrebbe alzato un errore e il Rust avrebbe tagliato a metà di un carattere.
- **La probe d'avvio** di `aw_core` controllava la classifica BM25 su tre documenti, non il tokenizer.
- **Il Brain** non toglieva i doppioni e non pesava il tempo. Due missioni demo uguali: 12 note, di cui 6 doppie (ogni missione ne scrive 6: 3 note degli agenti, 2 lezioni del QA, il riassunto).
- **Velocità del tokenizer** (i 30 file Markdown del repo, 0,56 milioni di caratteri): la regex di prima 24 milioni di caratteri al secondo; uno scanner Unicode carattere per carattere 6,3 (3,6 volte più lento); un pezzo alla volta tra gli spazi, con la regex sui pezzi ASCII e lo scanner sugli altri, 16,5 (1,45 volte), con gli stessi token. 28 file su 30 hanno almeno un carattere non ASCII, quindi una scorciatoia per il file intero non serve.
- **Il coseno a coppie** in Python puro (dimensione 256): 1000 note 4,3 s, 5000 circa 107 s; 30 note nuove contro 5000, 1,3 s.

### 5.2 Cosa fa

- **`backend/backend/search.py`:** `tokenize()` nuovo (D12): `_scan()`, la regex `_ASCII_TOKEN` per i pezzi ASCII, le parti dei token composti. `TOKENIZE_PROBES` e `_native_tokenizer_matches()`: `_load_rust()` usa `aw_core.Bm25` solo se il tokenizer nativo divide i testi di prova come il Python (D13). `HybridIndex.search(…, boost=)` moltiplica il punteggio fuso prima del taglio a *k*.
- **`backend/backend/embed.py`:** i grammi si tagliano per caratteri e si fa l'hash dei byte UTF-8; `_load_rust_ngram()` vuole anche il tokenizer uguale e prova i testi nuovi.
- **`crates/aw_core`** (il gemello Rust, regola 2): `tokenize_str()` con la stessa grammatica, la categoria Unicode dal crate `unicode-general-category`, minuscole e NFD su tutta la stringa (riordina i segni che ora restano), le lunghezze in caratteri; `ngram_vector_str()` taglia per caratteri. **Non compilato su questa macchina** (§5.6).
- **`backend/backend/brain.py`:** `settings()` (da `rag.brain`, letto a ogni chiamata), `decay()` e il suo uso in `search()` (D15), `consolidate(run_id=, threshold=)` con `_merge()` che calcola in un thread e non scrive le note (D14), `reindex(keep_vectors=)`.
- **`backend/backend/run.py`:** alla fine della run, dopo il riassunto nel Brain, `consolidate(run_id=…)`; un errore si scrive nel log e non ferma la run.
- **`config/default.json`:** `rag.brain` = `dedupeCosine` 0,88, `halfLifeDays` 30, `decayFloor` 0,5.
- **UI** (`public/js/main.js`): la scheda Brain aperta ricarica l'elenco anche dopo un evento `consolidate`, non solo dopo `remember`.
- **Runner del browser:** la fase `brain`.

### 5.3 Decisioni (confermate dall'utente il 19/10/2026)

- **D12 — La grammatica dei token.** Un carattere di parola è una lettera, una cifra o un segno Unicode (categoria L, N o M: i segni servono, per esempio, al devanagari, dove le vocali sono segni). `_` fa parte della parola; `::` e `@` uniscono due parole quando dopo viene un carattere di parola, e `@` può aprire un token. Un token composto dà anche le sue parti: `budget_gate` → `budget_gate`, `budget`, `gate`, così le parole semplici lo trovano ancora e l'identificatore esatto vince. Restano: minuscole, NFD, via i diacritici latini (U+0300–U+036F), almeno 3 caratteri (contati come caratteri, non byte), le stesse stopword. In più `ς` diventa `σ`: il Python minuscola il sigma finale in `ς`, il Rust carattere per carattere in `σ`, e così coincidono (e una query scritta in maiuscolo trova la parola). Il punto non unisce (`app.get` → `app`, `get`), il trattino nemmeno.
- **D13 — La parità con il Rust passa dalla probe d'avvio.** I testi di prova (`TOKENIZE_PROBES`: identificatori, `::`, `@`, sigma finale, cirillico, un segno devanagari, CJK, lettere senza NFD) devono dare gli stessi token in Python e in Rust, se no `aw_core` non si usa né per BM25 né per i vettori locali. Indici e query non possono dividere le parole in due modi diversi.
- **D14 — Il consolidamento.** Alla fine di ogni run, le note di quella run si confrontano con tutte le altre; due note dello stesso tipo con coseno **maggiore** di 0,88 diventano una: resta la più recente, con i tag di tutte e due (al più 8) e `repeats`, il numero di note che ha assorbito. Si uniscono solo le note degli agenti (`lesson`, `note`, `run`, e quelle salvate prima che esistesse `kind`), mai quelle del proprietario (`user`) né i suoi file (`document`). Il confronto è per run, perché il passaggio completo costa O(n²) (§5.1); `consolidate()` senza run lo fa, a mano. Il vettore è quello dell'indice: con `local/ngram` 0,88 unisce testi quasi uguali, con un modello di embedding vero anche le parafrasi.
- **D15 — Il decadimento nel tempo.** Nella ricerca del Brain il punteggio fuso della RRF si moltiplica per `decayFloor + (1 − decayFloor) × 0,5^(età / halfLifeDays)`: 1 per una nota di oggi, 0,75 a 30 giorni, mai sotto 0,5. Vale per le note degli agenti, non per quelle del proprietario. Si applica prima del taglio a *k*, quindi una lezione recente può superarne una vecchia che corrisponde meglio. `halfLifeDays` 0 lo spegne.

### 5.4 Test

- **`backend/tests/test_search.py`** (8 nuovi): il contratto del tokenizer su codice e scritture diverse (12 casi), il sigma finale, le lunghezze in caratteri, la regex dei pezzi ASCII uguale allo scanner su 3000 stringhe casuali di `ab9_:@ x.`, un identificatore che trova prima il suo documento, una query in cirillico e in greco maiuscolo, i vettori locali con ogni scrittura (parole diverse restano lontane) e l'hash dei byte UTF-8 di ogni grammo.
- **`backend/tests/test_search_rust.py`** (3 nuovi, uno saltato senza `aw_core`): il corpus d'oro con codice, cirillico, greco e devanagari e le loro query; i testi di prova coprono tutto; il tokenizer nativo uguale al Python sui testi di prova (saltato qui); un `aw_core` finto con il tokenizer di prima viene rifiutato sia per BM25 sia per i vettori, uno uguale accettato.
- **`backend/tests/test_brain.py`** (10 nuovi): il doppione che diventa la nota più recente (tag, `repeats`, evento, indice, file); quello che resta (solo simile, del proprietario, un altro tipo); la soglia strettamente sopra; il passaggio senza run; i vettori tenuti (solo il sopravvissuto si calcola di nuovo); il decadimento (0,75 a 30 giorni, il pavimento, il proprietario, le note senza `kind`); una lezione recente che supera una vecchia migliore con *k* = 1; le impostazioni di serie; una missione demo che consolida alla fine con il suo `run_id`; un consolidamento che fallisce senza fermare la run.
- **Runner del browser, fase `brain`** (2 verifiche, criterio `T03`): un `recall` non ricarica l'elenco del Brain, un `consolidate` sì, una volta; l'etichetta dell'ufficio segue il conteggio.
- **Mutazioni:** ognuna deve far diventare rosso il suo test, e lo fa.

  | Mutazione | Test che la prende | Rosso in |
  |---|---|---|
  | un token composto senza le sue parti | il contratto del tokenizer; l'identificatore che trova il suo documento | 1 s |
  | i segni non sono caratteri di parola | il contratto del tokenizer (il devanagari) | 1 s |
  | niente `ς` → `σ` | il sigma finale; il contratto | 2 s |
  | la regex dei pezzi ASCII dimentica `@` | la regex uguale allo scanner; il contratto | 1 s |
  | la probe d'avvio ignora il tokenizer | l'`aw_core` finto con il tokenizer di prima | 1 s |
  | i grammi codificati in ASCII (i caratteri persi) | l'hash dei byte UTF-8; parole diverse che restano lontane | 1 s |
  | nessun decadimento nella ricerca | la lezione recente che supera la vecchia | 9 s |
  | anche le note del proprietario invecchiano | il decadimento | 9 s |
  | si uniscono tipi diversi | quello che resta | 9 s |
  | uguale alla soglia si unisce | la soglia strettamente sopra | 9 s |
  | resta la nota più vecchia | il doppione che diventa la più recente | 9 s |
  | dopo il consolidamento si ricalcola ogni vettore | i vettori tenuti | 9 s |
  | la run non consolida | la missione demo che consolida alla fine | 9 s |
  | UI: un `consolidate` non ricarica l'elenco | la verifica 1 della fase `brain` | 20 s |

  I tempi sono quelli del file di test intero o della sola fase `brain`. Dopo le mutazioni l'impronta di `git diff` è uguale a prima: nessun file resta cambiato.

  **Due prime prove sbagliate, corrette.** I grammi codificati in ASCII senza errori (i caratteri non ASCII persi) passavano: un vettore cirillico restava non nullo e di lunghezza 1, solo sbagliato. Ora un test ricalcola l'hash dei byte UTF-8 di ogni grammo (il contratto del gemello Rust) e controlla che parole diverse restino lontane. La mutazione "senza le parti" la prima volta toglieva una riga e lasciava un `if` vuoto, cioè un errore di sintassi che faceva rossi tutti i test: ora sostituisce la riga, e diventano rossi solo i due test giusti. La verifica della fase `brain` è stata scritta dopo la riga della UI: che sappia fallire lo mostra la sua mutazione.

### 5.5 Verifiche

- `npm test` verde in 6 min 45 s: mondo 3D, dizionari, launcher, avvio, **pytest 1114 passati e 4 saltati** (prima 1094 passati e 3 saltati: 21 test nuovi, 8 in `test_search.py`, 3 in `test_search_rust.py` di cui 1 saltato senza `aw_core`, 10 in `test_brain.py`; i saltati sono la parità Rust ×3 senza il modulo compilato e ffmpeg), smoke, flussi, secret-scan, cartelle temporanee. Alla fine nel worktree non c'è né `data/` né `skills/vendor/`.
- `npm run test:browser`: **274 verifiche su 274**, ALL OK, in 5 min 13 s a 109,6 fps; `known-red.json` vuoto. Le 2 nuove sono la fase `brain`.
- **Due missioni demo uguali** sullo stesso Brain: la prima scrive 6 note (3 degli agenti, 2 lezioni, il riassunto), la seconda altre 6, e il consolidamento ne unisce 6: il Brain resta a 6 note invece di 12.
- **Rust:** il codice di `crates/aw_core` è scritto ma non compilato (§5.6).

### 5.6 Limiti noti

- **Il Rust non si compila qui** (niente `rustc`, `cargo`, Build Tools MSVC). Il gemello Rust è scritto riga per riga sul Python, ma la sua parità si prova solo con il modulo compilato: i test di parità sono saltati, come prima di T03. Se il Rust compilato non coincide, la probe d'avvio lo scarta e resta il Python: il rischio è che il Rust non entri, non che dia risultati diversi.
- **Versioni di Unicode:** Python 3.13 ha Unicode 15.1; `unicode-general-category` 1.x e `unicode-normalization` possono averne una più nuova. Un carattere aggiunto dopo la 15.1 può essere una lettera in Rust e non in Python; i testi di prova non lo vedono.
- **Il CJK senza spazi** resta una parola sola per frase (`数据库很快` è un token): per cercare dentro servirebbero i bigrammi.
- **Il consolidamento è per run:** due doppioni di run vecchie si uniscono solo quando una run nuova ne porta un terzo, o con `consolidate()` a mano (O(n²)).
- **Il decadimento è solo del Brain:** le skill e la memoria della run (spec 08) non invecchiano.

## 6. T04 — Checkpoint e time-travel del Tasker (fatto il 19/10/2026)

### 6.1 Il punto di partenza (misurato su `0db28e2`)

- **Una conversazione che cresce solo in coda.** Il Tasker tiene una conversazione per sotto-task e la allunga con `append` (`compact()` ne fa una copia ridotta per il modello, senza toccarla). Una revisione aggiunge "REVISION REQUESTED (attempt N)" con il feedback del QA, e i passi del tentativo bocciato restano tutti, con gli errori di formato e i tool falliti.
- **L'escalation cambiava solo la combo.** Dopo `limits.escalateAfter` (2) bocciature, `run_task` metteva `tasker.use = "frontier"` (`router.escalationCombo`) e il modello più forte riceveva tutto. Misurato sulla demo "A simple document about coffee", dove il simulatore boccia `w2.1` due volte (1 missione demo su 5 provate arriva all'escalation): la prima chiamata su `frontier` portava **18 messaggi, 6293 caratteri, 2 revisioni e gli 8 passi dei due tentativi bocciati**. Nessun test copriva l'escalation di `run_task`.
- **Le conversazioni andavano su disco solo alla fine.** `save_sessions()` (spec 09) girava nel `finally` del ciclo di vita: un server che muore a metà run perdeva tutti i worker, e la ripresa li faceva ripartire dal brief. Sulla demo il file delle sessioni non compariva mai mentre la run lavorava.
- **Lo `Store`** riscriveva il file della run sul posto: una scrittura interrotta lascia un JSON rotto, che all'avvio si salta, cioè la run sparisce. E il salvataggio raggruppato ripartiva da capo a ogni chiamata: con chiamate più fitte di 0,4 s (la demo; 8 worker di una run live fanno un passo ogni 3 s ciascuno, cioè uno ogni 0,4 s in tutto) non scriveva mai finché duravano. Misurato: 12 salvataggi a 0,1 s l'uno dall'altro, nessun file in 1,2 s.

### 6.2 Cosa fa

- **`backend/backend/tasker.py`:**
  - `snapshot()` (D16) dopo il brief (in `init()`), dopo ogni passo valido e dopo la revisione che chiude un rewind; ogni snapshot va alla run (`run.checkpoint()`). Lo stato nuovo: `checkpoints`, `steps`, `clean`, `rejections`, `written`, `base`, `rewound`.
  - Gli errori che sporcano il contesto (`clean = False`): la risposta non JSON, gli argomenti mancanti di un modello piccolo, il finish rifiutato, il risultato di un tool che comincia con `ERROR`, una revisione.
  - `rewind()` (D17), `_clean_point()`, `owner_messages()` (le parole e i file del proprietario e le sue risposte ad `ask_user`, con la domanda), `_rewound_revision()` (la revisione unica).
  - `session()` e `restore()` (D18): il punto pulito di una conversazione sporca, o un rewind che aspetta ancora la sua revisione, sopravvive alla ripresa. `init()` fissa anche il cursore del bus a incrocio (spec 10) dove il brief è stato scritto.
- **`backend/backend/run.py`:** `checkpoint()` scrive `task.checkpoint` (`step`, `attempt`, `clean`) e chiede il salvataggio delle sessioni; `save_sessions(immediate=)` passa dallo `Store` con una funzione che costruisce le sessioni quando la scrittura parte; `load_sessions()`; in `run_task`, all'escalation, `tasker.rewind()` e la nota `rewind` nella timeline del task.
- **`backend/backend/store.py`:** `write_atomic()` (un file temporaneo, poi `os.replace`), usata anche per i file delle run; `_later()`, al più una scrittura ogni 0,4 s per chiave con lo stato più nuovo; `sessions_path()`, `save_sessions()`, `load_sessions()`; all'avvio via i `.tmp` rimasti.
- **`backend/backend/i18n.py`:** `rewind_note` nelle cinque lingue.
- **UI** (`public/js/main.js`): l'icona ⏪ per la nota `rewind` nella timeline (senza, le note sconosciute prendono ⚠️).
- **Runner del browser:** la fase `checkpoint`.

### 6.3 Decisioni (confermate dall'utente il 19/10/2026)

- **D16 — Lo snapshot e il passo valido.** Uno snapshot non copia la conversazione, che cresce solo in coda: ne segna la lunghezza, con il numero di passi validi, il tentativo, il cursore del bus a incrocio e se il contesto è ancora pulito. Si prende dopo il brief e dopo ogni passo valido: un tool eseguito il cui risultato non comincia con `ERROR`, o un finish accettato. Il primo errore (risposta non JSON, argomenti mancanti, finish rifiutato, tool in errore, una bocciatura del QA o del controllo dei file) rende sporco il contesto: gli snapshot dopo si prendono ancora, ma non sono puliti. Il brief è sempre un punto pulito. Anche un finish poi bocciato è un passo valido: senza errori di formato, l'ultimo punto pulito è la fine del primo tentativo (è il caso della demo).
- **D17 — Il time-travel all'escalation.** Quando il worker passa alla combo dell'escalation (la prima volta che le revisioni arrivano a `escalateAfter`, se la combo esiste), la conversazione torna all'ultimo snapshot pulito. Sopra tornano, in ordine, le parole e i file del proprietario arrivati dopo e le sue risposte ad `ask_user` con la domanda; poi **una** revisione con ogni bocciatura da allora (tentativo per tentativo, al più 1500 caratteri ciascuna), i file che i tentativi bocciati hanno lasciato nella cartella (da leggere prima di cambiarli), le lezioni e il contesto della squadra come prima. I file su disco **non** tornano indietro: la cartella è di tutta la run, e i file bocciati sono la base da correggere. Il cursore del bus torna a quello dello snapshot, quindi il lavoro collegato consegnato da allora arriva di nuovo, in un blocco. Dopo il rewind il contesto è pulito e la revisione è il punto pulito nuovo. Il salvataggio del lead (`rescue`, oltre `maxRevisions`) non fa rewind; un contesto ancora pulito non ha niente da togliere.
- **D18 — I checkpoint su disco.** A ogni snapshot la run chiede di scrivere `data/runs/sessions/<run>.json`: entro 0,4 s, con la conversazione (compattata) di ogni worker non finito e, se il contesto è sporco, il suo punto pulito compattato con le parole del proprietario, i file e le bocciature da allora. Prima di T04 il file si scriveva solo alla fine della run. Il cursore del bus non si salva: alla ripresa la memoria della run si ricostruisce, e un cursore vecchio lì non vuol dire niente. Ogni scrittura dello `Store` (le sessioni e i file delle run) passa da un file temporaneo e lo sostituisce, e il salvataggio raggruppato non riparte più da capo a ogni chiamata: una scrittura in attesa tiene la sua ora e prende lo stato più nuovo.
- **D19 — Dove si vede.** Nella timeline del task, subito dopo "⬆️ Escalation…", la nota "⏪ Ripartito dall'ultimo punto pulito, dopo N passi validi: M messaggi con gli errori escono dal contesto, le bocciature stanno in un solo messaggio", nella lingua della run (campi `step` e `dropped`). In più ogni task ha `checkpoint` (`step`, `attempt`, `clean`) nel JSON della run. Nessun badge nuovo sulla scheda: c'è già "⬆️ frontier".

### 6.4 Test

- **`backend/tests/test_tasker.py`** (6 nuovi, con un `FakeRun` che registra gli snapshot, fa fallire i tool che gli si dice, dà le parole del proprietario prima di una chiamata scelta e ha un cursore della memoria): gli snapshot dopo il brief e dopo ogni passo valido, con lunghezza, cursore e pulizia; un tool in errore, un finish rifiutato e gli argomenti mancanti di un modello piccolo non sono passi validi e sporcano; il rewind all'ultimo punto pulito (le parole del proprietario tenute, la revisione unica con le due bocciature e i due file, il cursore dello snapshot, gli snapshot dopo); la risposta del proprietario ad `ask_user` che resta con la sua domanda; nessun rewind su un contesto pulito (e nessuna seconda copia nella sessione); la sessione di un worker sporco con il suo punto pulito, la ripresa che ci torna, e il rewind ancora senza revisione che sopravvive a un'altra ripresa.
- **`backend/tests/test_store.py`** (4 nuovi): una scrittura che muore a metà lascia il file buono (la run e le sessioni, anche dopo un riavvio); le sessioni raggruppate, l'immediata che vince sulla scrittura in attesa, il file tolto quando non resta niente, un file rotto; una run che salva ogni 0,1 s arriva su disco con lo stato più nuovo; i `.tmp` rimasti tolti all'avvio.
- **`backend/tests/test_checkpoint.py`** (nuovo, 3 test): `run_task` vero con un worker e un QA scritti a mano (la prima chiamata su `frontier` porta solo il brief, il passo pulito e la revisione unica; la nota `rewind` dopo `escalate`; `task.checkpoint`); la missione demo che arriva all'escalation; il file delle sessioni su disco mentre la run lavora (in pausa, quindi nessun salvataggio di fine run).
- **Runner del browser, fase `checkpoint`** (1 verifica, criterio `T04`): la run di un task con l'escalation entra dal flusso di eventi della pagina, come nella fase `budget`; la scheda aperta mostra "⏪ …" subito dopo "⬆️ …".
- **Mutazioni:** ognuna deve far diventare rosso il suo test.

  | Mutazione | Test che la prende | Rosso in |
  |---|---|---|
  | nessuno snapshot dopo un passo valido | gli snapshot dopo ogni passo valido; il rewind; la risposta ad `ask_user`; la ripresa | 1 s |
  | un tool fallito vale come passo valido | un tool in errore non è un passo valido | 1 s |
  | un errore di formato lascia il contesto pulito | gli snapshot; il rewind; la risposta ad `ask_user`; la ripresa | 1 s |
  | una bocciatura lascia il contesto pulito | la missione demo che arriva all'escalation | 7 s |
  | il rewind va all'ultimo snapshot, pulito o no | il rewind (unitario e in `run_task`); la risposta ad `ask_user`; la ripresa; la demo | 7 s |
  | il rewind toglie le parole del proprietario | il rewind; la risposta ad `ask_user`; la ripresa | 1 s |
  | la risposta ad `ask_user` si perde | la risposta ad `ask_user` | 1 s |
  | la revisione unica ha solo l'ultima bocciatura | il rewind (unitario e in `run_task`); la ripresa; la demo | 8 s |
  | il cursore del bus non torna indietro | il rewind | 1 s |
  | il numero dei passi non torna indietro | il rewind (unitario e in `run_task`) | 8 s |
  | nessun punto pulito dopo la revisione del rewind | il rewind | 1 s |
  | la sessione di un worker sporco senza punto pulito | la ripresa | 1 s |
  | un rewind in attesa non si salva | la ripresa | 1 s |
  | l'escalation non fa rewind | `run_task` con l'escalation; la demo | 7 s |
  | i checkpoint su disco solo a fine run | il file delle sessioni mentre la run lavora | 15 s |
  | lo `Store` scrive sul posto | una scrittura che muore a metà | 3 s |
  | una scrittura in attesa riparte da capo a ogni chiamata | una run che salva ogni 0,1 s | 4 s |
  | una scrittura immediata lascia indietro quella in attesa | le sessioni raggruppate | 3 s |
  | i `.tmp` restano all'avvio | i `.tmp` tolti all'avvio | 3 s |
  | UI: la nota `rewind` senza ⏪ | la verifica della fase `checkpoint` (la nota torna con ⚠️) | 15 s |

  I tempi sono quelli dei file di test toccati (`test_tasker.py` dura 1 s, `test_store.py` 3 s, `test_checkpoint.py` 7–15 s) o della sola fase `checkpoint`. Dopo le 19 mutazioni del backend e quella della UI l'impronta di `git diff` è uguale a prima: nessun file resta cambiato.

  **Una mutazione la prende un solo test:** "una bocciatura lascia il contesto pulito" la vede solo la missione demo, perché nei test unitari un errore di formato arriva sempre prima della bocciatura. **Due difetti trovati prima del commit, ognuno con il suo test visto rosso:** il passaggio avversario ha trovato che il rewind toglieva anche la risposta del proprietario a un `ask_user`; la misura sulla demo ha trovato che il file delle sessioni non compariva mai mentre la run lavorava, perché il salvataggio raggruppato dello `Store` ripartiva da capo a ogni chiamata (vale anche per il file della run, da prima di T04). Il test della scrittura che muore a metà è nato rosso perché `save_sessions()` non c'era: che sappia fallire anche sul file della run lo mostra la mutazione "lo `Store` scrive sul posto".

### 6.5 Verifiche

- `npm test` verde in 7 min 3 s: mondo 3D, dizionari, launcher, avvio, **pytest 1127 passati e 4 saltati** (prima 1114 passati e 4 saltati: 13 test nuovi, 6 in `test_tasker.py`, 4 in `test_store.py`, 3 in `test_checkpoint.py`), smoke, flussi, secret-scan, cartelle temporanee. Alla fine nel worktree non c'è né `data/` né `skills/vendor/`. T04 non tocca `crates/aw_core`: nessuna funzione Rust nuova, la parità resta quella di prima.
- `npm run test:browser`: **275 verifiche su 275**, ALL OK, in 5 min 18 s a 104,9 fps; `known-red.json` vuoto. La nuova è la fase `checkpoint`.
- QA visivo a 1920×1080 dallo screenshot della fase `checkpoint` (`--shots`): la scheda del task aperta nel pannello di destra, con "2 rev." e "⬆️ frontier", i due verdetti di Bruno e, in fondo alla timeline, "⬆️ Escalated to the "frontier" model" e subito sotto "⏪ Back to the last clean point, after 3 valid steps: …".
- **La demo, prima e dopo** ("A simple document about coffee", task `w2.1`, la prima chiamata su `frontier`): da 18 messaggi, 6293 caratteri, 2 revisioni e 8 passi a 10 messaggi, 4602 caratteri, 1 revisione e 4 passi (il brief, i tre passi e il finish del primo tentativo, la revisione unica). Il file delle sessioni c'è mentre la run lavora (prima di T04 no) e sparisce a fine run, quando non resta niente da riprendere.

### 6.6 Limiti noti

- **I file non tornano indietro** (D17): il modello più forte li trova per nome nella revisione e li deve leggere. Un file che un tentativo bocciato ha rovinato resta rovinato finché non lo riscrive.
- **Il punto pulito arriva fino al primo errore.** Un modello che sbaglia il formato al secondo passo lascia un punto pulito quasi vuoto: il modello più forte rifà l'esplorazione (qualche chiamata in più). Un tool che fallisce per l'ambiente (la rete che non c'è) sporca il contesto come un errore del modello.
- **Un solo rewind per escalation**, e l'escalation è una sola per sessione del worker. Dopo una ripresa (spec 09) le revisioni ripartono da 0, quindi un worker ripreso può salire di nuovo e tornare al suo punto pulito.
- **Le sessioni salvate prima di T04** (run fermate prima dell'aggiornamento) non hanno il punto pulito: alla ripresa vale come pulito il punto della ripresa.
- **Un crash perde al più 0,4 s di passi**, cioè quelli dopo l'ultima scrittura.
- **Su Windows**, se un altro processo tiene aperto il file (un antivirus, l'indicizzatore), `os.replace` fallisce: la scrittura torna sul posto, come prima di T04.

## 7. T05 — Streaming vero su `/v1` (fatto il 20/10/2026)

### 7.1 Il punto di partenza (misurato su `848dcde`)

- **Che cosa mandava `/v1`.** Con `"stream": true` il gateway chiamava `router.chat()`, cioè una richiesta normale al provider, senza `stream`, e solo a risposta finita mandava tre frame: un chunk con tutto il testo (`delta.role` e `delta.content`), il chunk con `finish_reason: "stop"` e l'usage, `data: [DONE]`.
- **Misurato** con un provider finto compatibile OpenAI che scrive 10 pezzi in 2 s, su un server uvicorn vero (l'`ASGITransport` di httpx tiene in memoria tutta la risposta prima di restituirla, quindi non può misurare lo streaming), tre giri per parte:

  | | Chunk con testo | Primo testo al client | Fine |
  |---|---|---|---|
  | prima di T05 (`848dcde`) | 1 | 2,05–2,08 s | 2,05–2,08 s |
  | dopo T05 | 10 | 0,25 s | 2,08–2,10 s |

- **Gli adapter.** Nessuno sapeva fare streaming: `openai_chat` e `anthropic_chat` facevano un POST e leggevano il JSON intero, il simulatore rispondeva in un blocco.
- **`bus.py`** è il fan-out degli eventi dell'app verso la UI (`/api/events`): il gateway non lo usava, e la chiamata arrivava alla UI come evento `router.call` dal log del router.
- **Un difetto trovato misurando:** un modello che non è né una combo né `provider/modello` (`"model": "nope"`) faceva alzare un `ValueError` dentro il router, e il client riceveva un 500 nudo, con e senza `stream`.

### 7.2 Cosa fa

- **`backend/backend/router/providers.py`:** `call_provider_stream()`, il gemello in streaming di `call_provider()`, un generatore asincrono di `{"text"}` e di un `{"end", "usage", "finish", "model"}` finale.
  - `openai_stream()`: `stream: true` e `stream_options.include_usage`; legge le righe `data:` man mano che arrivano (`client.stream`). Un errore dentro un flusso già partito (OpenRouter li manda così) si classifica dalle sue parole, come uno normale. Un server che risponde 400 a `stream_options` o a `response_format` si richiama una volta senza.
  - `anthropic_stream()`: `message_start` (i token in ingresso), `content_block_delta` (il testo), `message_delta` (`stop_reason` e i token in uscita), `error`.
  - `ThinkFilter`: `strip_thinking()` per un testo a pezzi, anche con un tag spezzato tra due pezzi. `FINISH`: `end_turn` e `stop_sequence` → `stop`, `max_tokens` → `length`.
- **`backend/backend/router/index.py`:** `Router.stream()`, `chat()` scritto come generatore di eventi: `start` (il bersaglio che risponde), `delta`, `end` (`usage`, `finish`, `callId`) oppure `error`. Cascata, cooldown, blacklist, alias e simulatore funzionano come in `chat()` fino alle prime parole visibili (D21). `_first_text()` legge fino a lì; `_relay()` inoltra il resto e alla fine registra la chiamata nelle statistiche e nel log, con i token stimati quando il provider non li dà (D23).
- **`backend/backend/router/mock.py`:** `mock_stream()`, la stessa risposta di `mock_chat()` a pezzi di tre parole, con una pausa breve tra i pezzi (`streamMs`, 8–20 ms; in tutto al più circa 2,5 s, per quanto lunga sia la risposta). `backend/backend/config.py`: `streamMs` [1, 2] con `AGENT_WORLD_FAST=1`, come la latenza.
- **`backend/backend/routes/gateway.py`:**
  - con `stream` aspetta il primo evento, cioè le prime parole di un modello, oppure l'errore di tutti, che resta un 502 come prima;
  - poi apre lo `StreamingResponse`: un chunk per pezzo, `delta.role` solo nel primo, lo stesso `id` per tutti (`chatcmpl-aw-…`, deciso al primo chunk: l'id della chiamata del router si sa solo alla fine); poi il chunk con `finish_reason` e `usage`, poi `data: [DONE]`. Header `cache-control: no-cache` e `x-accel-buffering: no`, così un proxy come nginx non trattiene i pezzi;
  - un provider che si interrompe a metà: un frame `error`, poi `[DONE]` (D22);
  - un client che chiude la connessione chiude anche il flusso verso il provider: non si continua a pagare una risposta che nessuno legge;
  - un modello sconosciuto: 404 nella forma OpenAI, con il testo nella lingua dell'app (`model_unknown`, cinque lingue in `i18n.py`), con e senza `stream` (D25).
- **`backend/backend/bus.py`:** invariato (D20).

### 7.3 Decisioni (confermate dall'utente il 20/10/2026)

- **D20 — Il flusso di `/v1` non passa dal bus.** `bus.py` non cambia. Il flusso di `/v1` è di un solo client e di una sola richiesta: va dal router alla risposta HTTP direttamente. Il bus serve la UI e riceve, alla fine di ogni chiamata in streaming, lo stesso evento `router.call` di una chiamata normale, con i token. Un evento per pezzo arriverebbe a ogni pagina aperta.
- **D21 — Il failover vale fino alle prime parole visibili.** Il router legge il flusso di un modello finché non arriva testo visibile, cioè dopo `<think>` e gli spazi iniziali. Un errore, un flusso vuoto o un 4xx/5xx prima di quel punto passano al bersaglio successivo come in `chat()`, e il client non vede niente. Dopo le prime parole il modello è scelto: niente cambio a metà risposta, perché il client mescolerebbe due testi. Il prezzo è che il primo chunk arriva quando il modello scrive la prima parola visibile, non al primo byte.
- **D22 — Un'interruzione a metà risposta** chiude il flusso con `data: {"error": {"message": …, "type": "upstream_error"}}` e poi `data: [DONE]`. Lo stato HTTP è già 200 e non si può più cambiare; è la forma che OpenRouter usa in questi casi. Il bersaglio si raffredda come per un errore normale, e la chiamata risulta fallita nelle statistiche.
- **D23 — I token.** `stream_options.include_usage` per i server compatibili OpenAI, `message_start` e `message_delta` per Anthropic, il conteggio del simulatore. Se il provider non li dà (un server che rifiuta `stream_options`), si stimano come fa il simulatore: un token ogni 4 caratteri del prompt e della risposta.
- **D24 — `<think>` e gli spazi.** Un blocco `<think>` non arriva mai al client, nemmeno spezzato tra due pezzi. Un `<think>` mai chiuso (una risposta tagliata) toglie tutto quello che segue; senza streaming resterebbe nel testo. Gli spazi iniziali si tolgono, quelli finali no: in streaming non si sa quale pezzo è l'ultimo (misurato in §7.1: "… word9 " in streaming, "… word9" senza).
- **D25 — Un modello sconosciuto è un 404** `{"error": {"message": …, "type": "invalid_request_error"}}`, deciso prima di chiamare il router, con e senza `stream`: è la risposta di OpenAI a un modello che non esiste. Prima era un 500 nudo.

### 7.4 Test

- **`backend/tests/test_gateway_stream.py`** (nuovo, 21 test). Nessun test arriva a un provider vero: il client HTTP del router è un `MockTransport`, e i flussi finti aspettano eventi che il test imposta. Un chunk visto prima dell'evento prova che niente è stato trattenuto per strada; per questo i due test sul tempo girano su un server uvicorn vero.
  - Il simulatore: la risposta in molti chunk che, uniti, danno lo stesso testo della risposta senza streaming, `role` solo nel primo, lo stesso id, il chunk finale con `finish_reason` e `usage`, `[DONE]`; la chiamata nel log del router.
  - Un provider OpenAI: le prime parole al client mentre il provider sta ancora scrivendo; le richieste con `stream` e `stream_options`; un client che se ne va chiude il flusso del provider.
  - Anthropic: testo, token e `stop_reason` → `length`.
  - Il failover: un bersaglio che fallisce prima delle prime parole (raffreddato, contato) e un flusso vuoto passano al successivo; nessuno risponde → 502 prima di ogni chunk; un'interruzione a metà → il frame `error` e `[DONE]`.
  - `<think>` spezzato tra tre chunk; un server che rifiuta `stream_options` richiamato senza, con i token stimati e `finish_reason: "length"`; la chiave come per il resto di `/v1`; un modello sconosciuto (404, con e senza `stream`).
  - Il filtro di `<think>`: per 6 testi, ogni taglio in due e 40 tagli casuali in quattro danno quello che toglie `strip_thinking()`; un `<think>` non chiuso non si vede.
- **`backend/tests/test_gateway.py`:** il vecchio test del "blocco unico" si chiama ora `test_v1_chat_completions_stream_ends_with_done`.
- **Visti rossi prima del codice:** con il gateway di `848dcde` al posto del nuovo, 9 dei 19 test di allora sono rossi (gli altri 10 provano il log, il 502, la chiave e il filtro da soli); i 2 del modello sconosciuto sono nati rossi (un `ValueError` dal router).
- **Mutazioni:** ognuna deve far diventare rosso un test, e lo fa. Lo script rimette i byte esatti dei file (il checkout ha file in CRLF e in LF) e chiude l'albero dei processi alla scadenza; l'impronta di `git diff` è uguale prima e dopo.

  | Mutazione | Primo test che la prende | Rosso in |
  |---|---|---|
  | il gateway aspetta tutta la risposta prima di mandare | le prime parole prima della fine del provider | 9 s |
  | nessun failover prima delle prime parole | il bersaglio che fallisce prima delle prime parole | 5 s |
  | un flusso vuoto vale come risposta (nell'adapter e nel router) | il flusso vuoto | 5 s |
  | nessun filtro di `<think>` sui pezzi | `<think>` spezzato tra i chunk | 6 s |
  | nessuna seconda richiesta senza `stream_options` | il server che rifiuta `stream_options` | 6 s |
  | nessuna stima dei token senza usage | il bersaglio che fallisce prima delle prime parole (il secondo non dà usage) | 5 s |
  | il flusso del provider non si chiude quando si smette di leggere | il client che se ne va | 10 s |
  | un'interruzione a metà chiude il flusso in silenzio | l'interruzione a metà | 5 s |
  | lo `stop_reason` di Anthropic ignorato | Anthropic | 5 s |
  | il simulatore scrive un blocco solo | la risposta demo in molti chunk | 3 s |
  | il primo chunk senza `role` | la risposta demo in molti chunk | 3 s |
  | il flusso parte prima che un modello risponda | le prime parole prima della fine del provider | 4 s |
  | il modello sconosciuto non si controlla | il modello sconosciuto | 7 s |
  | un flusso non entra nelle statistiche del router | il bersaglio che fallisce prima delle prime parole | 5 s |

  I tempi sono quelli di `test_gateway_stream.py` fermato al primo rosso (`-x`).

### 7.5 Verifiche

- `npm test` verde in 7 min 10 s: mondo 3D, dizionari, launcher, avvio, **pytest 1148 passati e 4 saltati** (prima 1127 passati e 4 saltati: 21 test nuovi in `test_gateway_stream.py`), smoke, flussi, secret-scan, cartelle temporanee. Alla fine nel worktree non c'è né `data/` né `skills/vendor/`. T05 non tocca `crates/aw_core`.
- Un primo giro di `npm test` (7 min 25 s) era rosso solo all'ultimo controllo, `temp-test` C1: sei cartelle `aw-measure-*` lasciate nella cartella temporanea dalla sonda della misura di §7.1, non dal codice. Tolte quelle, il giro intero rifatto è quello qui sopra.
- `npm run test:browser`: **275 verifiche su 275**, ALL OK, in 5 min 33 s a 80 fps; `known-red.json` vuoto. La UI non usa `/v1`; il runner gira perché T05 cambia il simulatore (`mock.py`), che fa tutte le missioni demo del runner. Nessuna verifica nuova: T05 non cambia niente di quello che la pagina mostra.
- La misura di §7.1, tre giri per parte.

### 7.6 Limiti noti

- **Dopo le prime parole non c'è failover** (D21): un provider che cade a metà lascia al client una risposta tronca, con il frame `error`.
- **Lo spazio finale** di una risposta resta (D24).
- **Le run non usano lo streaming:** T05 riguarda `/v1`. Worker, lead, CEO e QA aspettano ancora la risposta intera, come prima; mostrare i token di un worker man mano nella UI sarebbe un ticket a parte.
- **Il gateway non conta nel budget delle run** (spec 11 §3.6), in streaming come prima.
- **Un client che chiude prima delle prime parole** chiude il flusso del provider, ma la chiamata non risulta nelle statistiche, né riuscita né fallita.
- **Un corpo JSON rotto** su `/v1` dà ancora un 500, come su `/api` (HANDOFF §7, limiti accettati).

## 8. Fase 2 — Intent Engine, T06–T10 (fatta il 20/10/2026)

Su richiesta dell'utente la Fase 2 è stata chiusa in un'unica passata, invece di un ticket per sessione: si riprende il lavoro parcheggiato sul branch `claude/spec11-phase2-wip`, si completa e si verifica una volta sola alla fine (`npm test` e `npm run test:browser`). I commit sono due: `50ddcb5` (T06, il cherry-pick di `4581acc`) e quello della Fase 2 (T07–T10, dal cherry-pick di `9fc9f02` più il completamento).

### 8.1 Il punto di partenza (misurato su `5a8cd96`, T05 confermato)

- **Nessun reverse engineering.** La CEO pianificava sempre una costruzione da zero; non c'era né un team, né un tool, né un posto dove mettere il bersaglio. L'unico modo di far leggere del codice a un agente era allegarlo e farlo leggere con `read_file`, che si ferma a 12000 caratteri.
- **Il lavoro parcheggiato.** `4581acc` (T06) era completo, con i suoi 38 test verdi. `9fc9f02` (T07–T09) aveva il codice dei tool, del team, del modulo dell'intento e della clean room in `run.py`, ma non il simulatore demo né i test, e la suite non era mai stata eseguita su quello stato ("WIP, not verified").
- **Cosa mancava per finirlo** (trovato verificando, §8.6): un conflitto in `i18n.py`, la HAR del campione in una cartella ignorata da git, un obiettivo italiano classificato male, la clean room che bloccava i file dei costruttori, il blueprint in inglese in ogni lingua, una route JS con handler inline letta male, due difetti visti solo dal runner del browser.

### 8.2 Cosa fa

- **T06 — `backend/backend/deconstructor.py`** e il gemello **`crates/aw_core/src/deconstruct.rs`** (tre `pyfunction` nuove in `lib.rs`, che restituiscono JSON; `serde_json` in `Cargo.toml`):
  - `extract_skeleton(source, ext)`: Python, JavaScript/TypeScript, Rust, HTML, CSS. Import ed export, firme di classi, funzioni e metodi senza i corpi, route API servite (FastAPI/Flask, Express, axum e gli attributi di actix/rocket) e chiamate (`fetch`, `axios`…), variabili di stato (comprese quelle di React), grafo delle chiamate interne, con `self.x()` risolto sul metodo della classe;
  - `inspect_artifact_metadata(data, name)`: ELF, PE, Mach-O, WebAssembly, zip/jar/wheel, tar, gzip, PDF, immagini, SQLite e bundle di testo: formato, sezioni, simboli esportati e importati, stringhe leggibili, entropia. Niente si esegue;
  - `summarize_runtime_trace(text)`: HAR, eventi JSON, JSON lines, tracce di Chrome, log di testo: endpoint (i numeri e gli id nei percorsi diventano `{id}`), lo schema dei payload (solo i tipi, mai i valori) e la sequenza degli stati;
  - `DECONSTRUCT_PROBES` e `_load_native()`: il modulo nativo si usa solo se dà esattamente lo stesso risultato su ogni probe (D26); `render_skeleton`, `render_artifact`, `render_trace`: il testo compatto che legge un agente.
- **T07 — `backend/backend/tools.py`:**
  - `scan_target_tree(path)`: file, linguaggi, entry point, dipendenze (`package.json`, `pyproject.toml`, `requirements.txt`, `Cargo.toml`…) e dimensione, senza quello che la clean room nasconde;
  - `extract_code_skeleton(path)`: lo scheletro di un file di codice, i metadati di un artefatto o il riassunto di una traccia, secondo il file;
  - `write_blueprint(data)`: valida, normalizza e salva `blueprint.json` e `blueprint.md` (con i titoli nella lingua della run) nella cartella della run (D29); `read_blueprint()`, `blueprint_problems()` per il controllo meccanico;
  - `copy_target()`: la copia del bersaglio in `target/` (D31).
- **T08 — il team `reverse`** (`config/default.json`): *Reverse Engineering*, lead **Kira**, worker **Zero**, combo `code`, al più 2 sotto-agenti, i tre tool nuovi più quelli di base, `"reverse": true` (D35). La sua stanza nell'ufficio 3D (`public/js/world/office.js`: la nona zona, a nord-ovest, con il prop `scanner`), le etichette nei 5 dizionari (`i18n.py`, `public/js/i18n.js`), il badge dell'intento nell'intestazione della missione (`public/js/main.js`) e la skill `skills/architecture-deconstruction/SKILL.md`.
- **T09 — l'orchestrazione** (`backend/backend/intent.py`, `run.py`, `prompts.py`, `plan.py`, `tasker.py`, `routes/runs.py`):
  - `POST /api/runs` accetta `intent` (uno dei tre; altrimenti 400 `intent_unsupported`) e `target`, una cartella locale (altrimenti 400 `target_not_found`);
  - all'avvio: `prepare_target()` copia il bersaglio, `classify()` decide l'intento (D30), `plan()` con un intento di reverse dà i primi workstream solo al team `reverse`, e l'ultimo consegna sempre `blueprint.json`;
  - `reverse_only`: finita la decodifica, la missione consegna il blueprint;
  - `deconstruct_and_build`: Fase A (Deconstruct), poi `clean_room()`: Fase B `handover()` (D33), Fase C la ricostruzione con i brief del Prompt Lab e il "BLUEPRINT CONTRACT", Fase D `parity_review()` (D34). `run.data` ha `intent`, `intentWhy`, `phase` e `target`, e una run ripresa riparte dalla sua fase;
  - durante la ricostruzione `hidden_for()` e `clean_room_refusal()` tengono l'originale fuori dalla vista dei costruttori (D32); `write_file` non scrive `blueprint.*`.
- **T10 — il simulatore demo** (`router/mock.py`, `router/mock_texts.py` nelle 5 lingue): l'intento, il piano di decodifica, lo scan e gli scheletri del campione, un blueprint vero, il piano di ricostruzione, i brief del passaggio, il codice ricostruito (con un `server.js` quando il blueprint ha degli endpoint) e il verdetto di parità. Il campione è `backend/backend/demo_target/` (*todo-board*: `server.js`, `public/`, `traces/session.har`), usato da una missione demo che non ha un bersaglio.

### 8.3 Scostamenti dal testo dei ticket

- **`run.intent`, non `run.mode`:** `mode` c'era già (`demo` o `live`).
- **La cartella della run** è `data/workspace/<slug>-<id>/`, come per tutti i file delle run, non `data/workspace/<run_id>/`.
- **Niente AST:** scanner a caratteri (D26). Il Python segue il parser vero (verificato su 102 file durante lo sviluppo; il test lo rifà su 5 file del backend).
- **T06 fa anche artefatti e tracce** (`inspect_artifact_metadata`, `summarize_runtime_trace`), come chiesto nella richiesta di T05–T10.
- **"Quando il QA approva `blueprint.json`"** è la review del task che lo scrive: un task `done` ha passato la review (D33).
- **La ricostruzione** usa Sviluppo, Design, Contenuti e IA generativa, cioè i team che costruiscono (`BUILD_TEAMS`).

### 8.4 Decisioni (confermate dall'utente il 20/10/2026)

- **D26 — Scanner a caratteri con regole ASCII, non `ast` né regex.** Il gemello Rust deve dare gli stessi byte: `ast` in Rust non esiste, e la `re` di Python e la crate `regex` non trattano Unicode allo stesso modo. Python e Rust hanno le stesse funzioni con gli stessi nomi, riga per riga. La probe di avvio usa `aw_core` solo se coincide su tutte le `DECONSTRUCT_PROBES` (ogni linguaggio, formato e tipo di traccia), con tolleranza zero; altrimenti lavora Python. Il prezzo: è un'euristica, e solo per Python c'è un parser di riferimento con cui confrontarla.
- **D27 — Lo scheletro è piccolo e dice quando taglia.** Al più 20000 righe lette; 80 import, 80 export, 300 simboli, 80 route, 120 variabili di stato, 300 chiamate; firme fino a 160 caratteri. Quando taglia, lo scrive. Misurato sul codice del repository: circa il 10% di quello che darebbe `read_file` (il test vuole meno dell'11,5% su 8 file, e ognuno sotto il 16%).
- **D28 — Artefatti e tracce senza eseguirli.** Si leggono solo le intestazioni e l'indice: niente si esegue, niente si decomprime oltre l'elenco delle voci; un'intestazione bugiarda o tronca non fa mai alzare un'eccezione. Delle tracce si tengono gli endpoint, i tipi dei payload e la sequenza, mai i valori (che possono contenere dati personali o token).
- **D29 — Il blueprint è il confine della clean room.** `write_blueprint` lo rifiuta (e l'agente riceve l'elenco dei problemi) se non è un oggetto, se supera 200 KB, se un campo contiene codice copiato (4 righe o più, almeno metà con la forma del codice), se manca `summary`, se manca `architecture.components`, se ha meno di 2 `parityCriteria`, se non ha né `endpoints` né `dataModels` né `businessRules`, se un endpoint non ha un metodo HTTP e un percorso che comincia con `/`. Si scrive solo con `write_blueprint`; il controllo meccanico di un task del team `reverse` rilegge `blueprint.json`.
- **D30 — La CEO classifica solo quando c'è un motivo.** Un obiettivo senza parole di reverse engineering o di ricostruzione (nelle 5 lingue), senza bersaglio e senza codice tra i file del proprietario è `direct_build` senza nessuna chiamata: le missioni di prima costano e si comportano come prima. Altrimenti la CEO risponde con l'intento e il perché; una risposta inutilizzabile vale quello che dice `guess()`, la regola delle parole. Il proprietario può fissare l'intento con `intent` in `POST /api/runs`.
- **D31 — Il bersaglio si copia nella run.** `target` è una cartella della macchina del server; prima che la CEO guardi la missione, `copy_target()` la copia in `target/` della run, e gli agenti la leggono con le regole dei percorsi della run, senza uscirne mai. Non si copiano: i link, le cartelle nascoste (`.git`, `.ssh`…), i file nascosti che non sono configurazione, quelli con il nome o l'estensione di un segreto (`.env`, `id_rsa`, `.pem`, `.key`…), le cartelle delle dipendenze e delle build; al più 3000 file e 50 MB. Anche il codice tra gli allegati del proprietario conta come bersaglio. Una missione demo senza bersaglio usa il campione *todo-board*.
- **D32 — Cosa nasconde la clean room.** In `deconstruct_and_build`, dalla Fase C in poi, i task che non sono del team `reverse` non vedono `target/`, il codice tra gli allegati e le note di lavoro del team `reverse`: i tool di lettura rifiutano, e la lista dei file del brief e `scan_target_tree` li tacciono. Passano il confine solo `blueprint.json` e `blueprint.md`, più il "BLUEPRINT CONTRACT" (al più 6000 caratteri) nel brief.
- **D33 — Il passaggio di consegne vuole un blueprint approvato.** Serve un task del team `reverse` finito (cioè passato dalla review del QA) che abbia scritto `blueprint.json`, e un blueprint valido. Altrimenti la fase diventa `failed` e non si ricostruisce niente. La CEO pianifica la ricostruzione dal solo blueprint e con i soli team che costruiscono; Pia (Prompt Lab) scrive i brief clean-room dei nuovi workstream.
- **D34 — La QA di parità rimanda indietro una volta sola.** Un revisore del QA (la CEO, se il QA non c'è) controlla ogni criterio di parità sui file della ricostruzione e scrive `PARITY.md`. Un verdetto `revise` con delle correzioni riapre quei task una volta, con l'istruzione del QA; il secondo verdetto è definitivo. I criteri rimasti aperti non fanno fallire la run: restano in `PARITY.md` e nel messaggio finale.
- **D35 — Il team `reverse` non costruisce.** Con `"reverse": true` resta fuori dai piani di `direct_build` e da quelli della ricostruzione, e lavora solo nella Fase A. La sua stanza è la nona zona dell'ufficio, a nord-ovest; il runner del browser ricava dal config quanti worker e quanti posti nelle bay deve vedere, invece di 7 e 14 scritti a mano.

### 8.5 Test

- **`backend/tests/test_deconstructor.py`** (nuovo, 85 test: 84 passano e 1 si salta).
  - T06 (39, uno saltato): Python con firme, route, stato e chiamate senza i corpi; Python contro il parser vero sui file del backend; TypeScript con classi, interfacce, export, route e stato React; Rust con impl, trait, campi, attributi e route axum, e un'intestazione su più righe; HTML con script, stili, form e campi; CSS; la lingua dall'estensione; stringhe che sembrano codice; i limiti; lo scheletro al 10%. ELF, PE, wasm, archivi, bundle con entropia e stringhe, intestazioni bugiarde. HAR, eventi JSON, JSONL, tracce Chrome, log di testo; quello che non è JSON per `serde` non lo è nemmeno qui. Le probe coprono ogni linguaggio, formato e tipo di traccia; la probe di avvio prende solo un gemello che coincide; il ripiego su Python quando la chiamata nativa fallisce; il Rust è collegato al modulo; il gemello compilato coincide (saltato qui: `aw_core` non è compilato).
  - T07 (16): `scan_target_tree`, anche con quello che la clean room nasconde; `extract_code_skeleton` su codice, artefatti e tracce; `write_blueprint` con il Markdown nella lingua della run (en, it, de) e 8 modi di rifiutarlo; `copy_target` senza segreti, link, cartelle nascoste e build; la run scrive il blueprint solo con `write_blueprint` e lo controlla.
  - T08 (4): il team nel config e fuori dai piani di costruzione; le 5 lingue; una zona per ogni team e il prop; la skill.
  - T09 (18): la regola delle parole nelle 5 lingue (10 obiettivi); gli obiettivi di prima non chiedono niente alla CEO; un obiettivo semplice è `direct_build` senza chiamata, uno con un indizio la chiama; il proprietario fissa intento e bersaglio; `POST /api/runs` con `intent` e `target`; la clean room nasconde l'originale; il passaggio vuole un blueprint approvato; la QA di parità rimanda indietro una volta; una run ripresa riparte dalla sua fase.
  - T10 (8): il simulatore risponde ai ruoli nuovi; una missione demo `reverse_only` consegna il blueprint del campione (nelle 5 lingue); una `deconstruct_and_build` passa per le quattro fasi; una `direct_build` è il flusso di prima.
- **Altri file:** `test_i18n.py` (i testi di `deconstructor.py`, `tools.py` e `intent.py` nella guardia dei dizionari), `test_prompts.py` (i tre tool nuovi), `test_run.py` (la forma di `run.data`).
- **Mutazioni:** 14, ognuna deve far diventare rosso `test_deconstructor.py`, e lo fa. Lo script rimette i byte esatti di ogni file mutato e ne confronta l'hash prima e dopo.

  | Mutazione | Primo test che la prende | Rosso in |
  |---|---|---|
  | T06: le stringhe Python a tre apici non sono stringhe | Python con firme, route, stato e chiamate | 2 s |
  | T06: `self.x()` non si risolve sul metodo | Python con firme, route, stato e chiamate | 2 s |
  | T06: l'entropia con il segno sbagliato | bundle con entropia e stringhe | 3 s |
  | T06: la probe prende qualunque modulo nativo | la probe di avvio | 2 s |
  | T07: il codice copiato passa il controllo del blueprint | i rifiuti di `write_blueprint` | 3 s |
  | T07: i segreti si copiano con il bersaglio | `copy_target` | 3 s |
  | T07: `write_file` scrive `blueprint.json` | la run scrive il blueprint solo con `write_blueprint` | 3 s |
  | T08: la CEO pianifica le costruzioni con il team `reverse` | il team nel config e fuori dai piani | 3 s |
  | T09: ogni obiettivo chiama la CEO | un obiettivo semplice senza chiamata | 4 s |
  | T09: la clean room non nasconde niente | la clean room nasconde l'originale | 5 s |
  | T09: il passaggio non aspetta il QA | il passaggio vuole un blueprint approvato | 7 s |
  | T09: la QA di parità non rimanda mai indietro | la QA di parità rimanda indietro una volta | 6 s |
  | T10: il simulatore non trova il modello dati nelle tracce | il simulatore risponde ai ruoli nuovi | 6 s |
  | T10: il simulatore ignora l'intento del piano | la missione demo `reverse_only` (en) | 9 s |

  I tempi sono quelli di `test_deconstructor.py` fermato al primo rosso (`-x`).

### 8.6 Difetti trovati verificando, e corretti

- **Un conflitto in `i18n.py`** nel cherry-pick di `9fc9f02`: tenuti i testi di T05 e quelli della Fase 2.
- **La HAR del campione era in `logs/`**, che `.gitignore` esclude: un clone pulito non l'avrebbe avuta. Ora è in `demo_target/traces/`.
- **"Decodifica questa applicazione esistente e ricostruiscila"** era `direct_build`: mancavano "decodifica" e le forme di "applicazione esistente" nelle 5 lingue. Aggiunte.
- **La clean room rifiutava `index.html` ai costruttori**: un nome senza cartella si leggeva come un allegato del proprietario anche quando quell'allegato non c'era. Ora vale come allegato solo se il file esiste.
- **`blueprint.md` aveva i titoli in inglese** in ogni lingua: ora vengono da `BLUEPRINT_MD` in `i18n.py`.
- **Una route Express con l'handler inline** (`app.get("/x", (req, res) => …)`) prendeva come nome dell'handler un pezzo della funzione: ora non ha nome, in Python e in Rust.
- **Il runner del browser:** la stanza nuova copriva un'etichetta a 1440×900 (E2): zona spostata. Due verifiche contavano 7 worker e 14 posti scritti a mano: ora i numeri vengono dal config.
- **I numeri delle decisioni nei commenti del codice** (D20…) si scontravano con quelli di T05: ora sono D26–D35.

### 8.7 Verifiche

- **Le missioni demo**, senza chiavi: `reverse_only` in inglese, 23 chiamate, blueprint del campione; `deconstruct_and_build` in italiano (64 chiamate) e in inglese (55), fasi A–D, `PARITY.md` con 6 criteri su 6.
- **`npm test` verde in 7 min 24 s**: mondo 3D, dizionari, launcher, avvio, **pytest 1232 passati e 5 saltati** (prima 1148 e 4: gli 85 di `test_deconstructor.py`, uno saltato), smoke, flussi, secret-scan, cartelle temporanee.
- **`npm run test:browser`: 275 verifiche su 275**, ALL OK, in 5 min 13 s a 98,7 fps; `known-red.json` vuoto. Il primo giro intero aveva 3 rossi (E2 a 1440×900 e i due conteggi scritti a mano, §8.6): corretti, la fase delle etichette rifatta da sola (verde) e poi il giro intero.
- **Dopo `npm test`** sono cambiati solo la zona della stanza, i conteggi del runner e i numeri delle decisioni nei commenti: rifatti `world-test`, `i18n-test` e pytest intero, verdi.
- **QA visivo a 1920×1080:** la stanza *Reverse Engineering* a nord-ovest, Kira e Zero alle scrivanie, lo scanner, l'etichetta leggibile.
- **Il Rust non è compilato qui** (niente toolchain MSVC): la parità di `deconstruct.rs` è provata solo dalla struttura (test) e lo sarà dalla probe di avvio quando `aw_core` verrà compilato.

### 8.8 Limiti noti

- **`deconstruct.rs` non è mai stato compilato:** finché non lo è, lavora il Python; se una volta compilato non coincide su una probe, la probe lo scarta e lavora ancora il Python.
- **Gli scanner sono euristiche** (D26): per JS/TS, Rust, HTML e CSS non c'è un parser di riferimento; macro, template annidati e sintassi rare possono sfuggire.
- **Il bersaglio è solo una cartella locale** o del codice allegato: niente URL git e niente archivi da estrarre (ticket N22). Con l'accesso in LAN (T02) serve la chiave, ma chi la ha può far copiare qualunque cartella che il processo del server sa leggere.
- **La clean room vale per i tool della run**, non per quello che un modello sa già: un'applicazione pubblica può essere nota al modello. Il controllo del codice copiato nel blueprint è un'euristica: un frammento di 3 righe passa.
- **La QA di parità legge i file**, non esegue la ricostruzione; i criteri rimasti aperti non fanno fallire la run (D34).
- **Il roster a 1920×1080** con 18 agenti non entra in larghezza (ticket N21).
- **Nessuna missione vera** dei tre intenti con un provider: solo il simulatore.
