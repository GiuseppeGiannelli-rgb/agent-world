# Spec 11 — Core Hardening e Intent Engine a doppia modalità (Reverse Engineering + ricostruzione Clean-Room)

**In breve.** Richiesta dall'utente il 19/10/2026, partendo da `main` = `33c6135` (la spec 10 unita).
- **Fase 1, Core Hardening (T01–T05):** budget e circuit breaker, shell e LAN a fiducia zero, tokenizer per il codice e consolidamento del Brain, checkpoint del Tasker, streaming vero su `/v1`.
- **Fase 2, Intent Engine (T06–T10):** la CEO classifica la missione (`direct_build`, `reverse_only`, `deconstruct_and_build`); scheletri AST e tool di Reverse Engineering; il team `reverse`; il passaggio clean-room (Deconstruct → Handover → Build → Parity QA); il simulatore demo del flusso nuovo.
- **Regole di sessione:** un macro-step (un ticket) per sessione; si va avanti solo con `npm test` verde al 100%; ogni funzione aggiunta in `crates/aw_core` ha il gemello Python in `backend/backend/` con parità esatta; a fine step si aggiornano README, questo documento e `HANDOFF.md`.
- **Stato:** T01 fatto (19/10/2026, §3), con le decisioni D1–D5 confermate dall'utente. Prossimo: T02.

## 1. Regole di sessione (dall'utente)

1. **Un solo step per sessione.** Si esegue un macro-step alla volta; non si passa al successivo finché `npm test` (pytest + node + probe di parità Python/Rust) non è verde al 100%.
2. **Parità Python/Rust obbligatoria.** Ogni funzione aggiunta in `crates/aw_core` ha l'equivalente esatto in `backend/backend/`, con tolleranza zero nelle probe di parità.
3. **Aggiornamento dello stato.** A fine step: `README.md`, la spunta dei ticket qui sotto, `HANDOFF.md` con i file toccati, i test aggiunti e il prossimo step esatto da cui ripartire a contesto pulito.

## 2. Ticket

### Fase 1: Core Hardening

- [x] **T01 — Budget e circuit breaker** (`run.py`, `config/default.json`): `limits.maxCallsPerRun` (250) e `limits.maxCostUSD`. Una run che supera la soglia non fallisce: emette l'evento SSE `waiting` e va in pausa, chiedendo all'utente se proseguire. Fatto: §3.
- [ ] **T02 — Shell a fiducia zero e autenticazione in LAN** (`tools.py`, `security.py`, `i18n.py`):
  - con `run_command` attivo (`AGENT_WORLD_ALLOW_SHELL=1`) il sottoprocesso riceve un `env` ripulito (via tutte le `*_API_KEY`, `GITHUB_TOKEN`, `AGENT_WORLD_API_KEY`);
  - se l'host richiesto non è `127.0.0.1` / `localhost` / `::1`, anche `/api/*` e `/api/events` vogliono `AGENT_WORLD_API_KEY` (Bearer o cookie di sessione);
  - chiudere il ticket N13: i messaggi HTTP 403/400 nel dizionario `i18n.py` della lingua attiva.
- [ ] **T03 — Tokenizer per il codice e consolidamento del Brain** (`search.py`, `crates/aw_core`, `brain.py`):
  - `tokenize()` (Python e Rust) conserva i token tecnici del codice (identificatori con `_`, `::`, `@`) e i caratteri alfanumerici Unicode, con parità 1:1 nella probe di avvio;
  - `brain.consolidate()`: deduplica le note con similarità coseno > 0,88 e aggiunge un fattore di *time-decay* nell'RRF, per premiare le lezioni del QA più recenti.
- [ ] **T04 — Checkpoint e time-travel del Tasker** (`tasker.py`, `store.py`, `run.py`): uno snapshot leggero dello stato del sotto-task a ogni passo valido; quando un worker supera `escalateAfter` (2 bocciature) e passa a `frontier`, si torna all'ultimo snapshot pulito invece di accodare gli errori nel contesto.
- [ ] **T05 — Streaming vero su `/v1`** (`routes/gateway.py`, `bus.py`): `/v1/chat/completions` con `"stream": true` manda chunk SSE compatibili OpenAI man mano che il provider risponde, invece del blocco unico finale.

### Fase 2: Intent Router e motore di Reverse Engineering

**Classificatore d'intenzione della CEO** (`run.py`): all'avvio di `POST /api/runs` la CEO classifica la missione (`run.mode`):
1. `direct_build`: sviluppo classico da zero (il flusso di oggi, invariato);
2. `reverse_only`: analisi, decodifica architetturale, estrazione di API e logica, audit di un bersaglio esistente (cartella locale, repo o codice fornito); si consegna il Blueprint;
3. `deconstruct_and_build`: inversione + ricostruzione clean-room. Il sistema decodifica l'applicazione bersaglio, ne estrae la logica di business in un documento neutrale (`blueprint.json` + specifica Markdown) e poi i team di sviluppo la ricreano da zero dal Blueprint.

- [ ] **T06 — Estrattore strutturale** (`aw_core` + fallback Python in `deconstructor.py`): `extract_skeleton(source, ext)` estrae da Python, JS/TS, Rust, HTML/CSS firme di funzioni e classi, import/export, route API, variabili di stato e grafo delle chiamate interne, senza i corpi pesanti.
- [ ] **T07 — Tool di Reverse Engineering** (`tools.py`):
  - `scan_target_tree(path)`: file, linguaggi, entry point, dipendenze (`package.json`, `pyproject.toml`, `Cargo.toml`) e dimensione del bersaglio;
  - `extract_code_skeleton(path)`: la radiografia strutturale di un file (il 90% di token in meno di `read_file`);
  - `write_blueprint(data)`: valida e salva in `data/workspace/<run_id>/blueprint.json` la logica decodificata (architettura, modelli dati, endpoint, regole di business, casi limite, criteri di parità).
- [ ] **T08 — Team Reverse Engineering** (`config/default.json`, `public/js/world/`): il team `reverse` (lead *Kira*, worker *Zero*, combo `code`, tool `scan_target_tree`, `extract_code_skeleton`, `write_blueprint` più quelli di base), la sua postazione nell'ufficio 3D e le traduzioni nei 5 dizionari.
- [ ] **T09 — Orchestrazione dell'inversione** (`run.py`), con `run.mode == "deconstruct_and_build"`:
  1. **Fase A (Deconstruct):** la CEO assegna i primi workstream solo al team `reverse`;
  2. **Fase B (Handover):** quando il QA approva `blueprint.json`, `run.py` lo passa al Prompt Lab (Pia) e alla CEO per i workstream di ricostruzione;
  3. **Fase C (Clean-Room Build):** Sviluppo (Leo, Nina), Design (Iris, Ugo) e Contenuti ricevono nei brief le specifiche del Blueprint e ricreano l'applicazione;
  4. **Fase D (Parity QA):** il QA (Bruno, Vera) confronta il codice generato punto per punto con i requisiti funzionali del Blueprint.
- [ ] **T10 — Simulatore demo e test** (`router/mock.py`, `tests/`): `mock.py` e `mock_texts.py` (5 lingue) simulano anche `deconstruct_and_build` senza chiavi; `tests/test_deconstructor.py` (con la parità Python/Rust di `extract_skeleton`) e i test end-to-end del doppio binario.

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
