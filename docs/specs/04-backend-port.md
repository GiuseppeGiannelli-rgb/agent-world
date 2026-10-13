# Spec 04 — Porting del backend (Node → FastAPI + Rust)

| | |
|---|---|
| **Stato** | bozza per la revisione (step 2, To-spec) |
| **Data** | 2026-10-13 |
| **Branch** | `feat/backend-port`, da `main` = `0c20a69` (contiene la spec 03, congelata) |
| **Origine** | Decisione dell'utente di cambiare motore al backend restando identici UX, sistema multi-agente e front-end three.js; piano (step 1) in `HANDOFF.md` §2, approvato con le decisioni D1–D8 (§7) |
| **Decisioni già prese** (Plan, confermate) | D1: bridge Rust subito, dal modulo BM25 del Brain, con ripiego Python e soglia 5×. D2: PyO3 nello stesso processo, niente microservizi. D3: i due backend crescono in parallelo, cambio alla parità. D4: Python 3.13 gestito da `uv`. D5: toolchain Rust (`rustup`, target MSVC, Visual Studio Build Tools C++) già installata e in `PATH` sulla macchina dell'utente. D6: Node resta solo per `three.js` e gli strumenti di test. D7: `/v1/chat/completions` in streaming risponde con un blocco singolo, come oggi. D8: `feat/memory-stability` unito in `main` e push fatti; si parte da qui |

**In breve**
1. **Contesto.** Il server Node (~3550 righe, zero dipendenze npm, un processo, stato in memoria) ha 20 route `/api/*`, il gateway OpenAI-compatibile `/v1/*`, i file statici e un solo flusso SSE con 17 tipi di evento. Misurato: nessun calcolo pesante nel backend (A* e la simulazione girano nel browser); l'unico punto caldo è `Brain.add`, che ricostruisce l'intero indice BM25 a ogni nota (O(N²) per via di `avgLen`): 131 ms in Node contro 704 ms in un porting Python ingenuo a 5000 note.
2. **Obiettivo.** Un backend `backend/` in FastAPI (uv, un solo processo uvicorn) che risponde esattamente come Node — stesse route, stesso JSON, stessi eventi SSE — crescendo accanto a `server/` finché non lo sostituisce. Questa spec dettaglia le prime tre fasi architetturali: **P0** (scheletro e file statici), **P1** (config e store, `/api/state`) e **P2** (bus e SSE). Le fasi successive (P3–P7: router/gateway, skill e Brain, resto dell'engine, bridge Rust, cambio definitivo) restano al livello di piano già approvato e si dettagliano prima dei rispettivi ticket.
3. **Oracolo.** I test Node esistenti restano la prova di parità: una variabile d'ambiente nuova (`AGENT_WORLD_SERVER=node|python`) fa scegliere a `smoke.js`, `flows-test.js` e `temp-test.js` quale processo avviare; le route non ancora portate si segnano rosse in `scripts/browser/known-red.json` con il ticket che le porterà, sullo stesso schema già usato dalla spec 03.
4. **Bridge Rust.** Non in questa spec (P6), ma la matrice delle route e il design di `/api/brain` (§4.5) tengono già conto del punto d'aggancio: `Brain` chiamerà un modulo con la stessa interfaccia del ripiego Python puro, intercambiabile senza cambiare il contratto HTTP.
5. **Verifiche.** Criteri V1–V17 (§5): ogni fase passa quando i test paralleli danno lo stesso risultato sui due backend, bit per bit dove ha senso (JSON) e per forma dove non ce l'ha (timestamp, id).

## 1. Contesto misurato

### 1.1 Come sono state prese le misure

Lettura diretta di `server/**/*.js` (circa 3550 righe) il 2026-10-13, più uno script di misura in scratchpad (non nel repo) che ha cronometrato `Brain.add` e `Bm25.add` a 500, 2000 e 5000 note, in Node e con un porting Python riga per riga di `search.js`. La macchina è Windows 11, Node v24.16.0, Python 3.13 (gestito da `uv` 0.11.29).

### 1.2 Il server oggi

- **Processo.** `server/index.js` crea un `http.Server` puro (nessun framework), un `EventEmitter` globale (`bus`, `setMaxListeners(0)`) e tiene tutto lo stato in memoria: `chats` (Map agentId → cronologia), `live` (Map runId → `Run` attivo), `seq` (contatore SSE). Non ci sono dipendenze npm lato server; `three` serve solo al front-end (`node_modules/three`).
- **Dati su disco.** `data/` (spostabile con `AGENT_WORLD_HOME`): `data/runs/*.json` (uno per run, scritti da `Store`), `data/brain.json` (le note del Brain), `data/calls/<day>/*.json` (log delle chiamate al router, se `router.logCalls`). `workspace/` ospita i file prodotti dai run.
- **Route `/api/*` (20), più il gateway e i file statici** — l'elenco completo, con la fase che le porta, è in §1.6.
- **SSE.** Un solo flusso, `GET /api/events` (`server/index.js:257-263`): `text/event-stream`, header `retry: 2000`, un `: ping` ogni 15 s (`setInterval(…, 15000).unref()`, riga 146-148). Il bus inoltra 17 tipi di evento (`FORWARD`, riga 139): `chat`, `run`, `task`, `workstream`, `subtasks`, `agent`, `agent.spawn`, `agent.despawn`, `message`, `plan`, `file`, `waiting`, `brain`, `skills`, `run.done`, `router.call`, `config`. Ogni frame è `data: {"seq":N,"type":T,"payload":P}\n\n` con `seq` globale e crescente, assegnato al momento dell'emissione (riga 142: `++seq`), quindi **l'ordine delle emissioni decide i numeri**, non l'ordine di scrittura ai client. Nessun replay: alla riconnessione il client rilegge `GET /api/state` (`public/js/main.js:1032`).
- **Nessun calcolo pesante nel backend.** Reindicizzazione delle skill: 116–286 ms, quasi tutto filesystem (`readdir` ricorsivo più lettura dei primi 6000 byte di ogni `SKILL.md`); una ricerca BM25 sulle skill: ~0,01 ms. Il pathfinding A* e la simulazione 3D girano nel browser (`public/js/world/nav.js`, `world.js`); il server si limita a trasmettere gli stati degli agenti.
- **L'unico punto caldo misurato: `Brain.add` (`server/engine/brain.js:27-45`).** Ogni nota aggiunta richiama `this.reindex()` (riga 41), che butta via l'indice e lo ricostruisce da zero su **tutte** le note (riga 17-20). `Bm25.add` (`server/engine/search.js:24-36`) ricalcola `avgLen` con un `reduce` su `this.docs` **a ogni chiamata** (riga 35): il costo di una singola `remember` è quindi O(N) chiamate a `add`, ciascuna O(N) per `avgLen` → **O(N²)** sul numero di note. Misurato al tetto di 5000 note (riga 40, `splice` quando si supera): **131 ms in Node**, **704 ms** in un porting Python riga per riga, **424 ms** con `avgLen` incrementale (si accumula invece di ricalcolare) ma senza toccare l'algoritmo. A 131-704 ms, bloccare il thread/il loop di `asyncio` blocca anche la consegna degli eventi SSE a tutti i client, non solo chi ha scritto la nota.
- **Macchina dell'utente (per il bridge Rust, P6, non di questa fase).** `rustup` (target MSVC) e Visual Studio Build Tools C++ già installati e configurati in `PATH`: nessuna preparazione di comandi necessaria quando si arriverà a P6.

### 1.3 Config, Store e `/api/state`

- **`Config`** (`server/config.js`): `default.json` (in repo) più `local.json` (per-macchina, creato da `update()`) uniti con un merge profondo ricorsivo (`merge()`, righe 6-13: oggetti si fondono chiave per chiave, array e scalari sovrascrivono). `reload()` applica tre override da ambiente — `PORT` (numero), `AGENT_WORLD_ALLOW_SHELL === '1'` (booleano), `AGENT_WORLD_FAST === '1'` (azzera a 20 ms ogni voce di `pacing` e la latenza del provider mock) — poi deriva `staff`: un array piatto con la CEO, poi per ogni team il lead (se presente) e i worker, nell'ordine di `Object.entries(teams)`. `update(patch)` accetta solo le chiavi in `EDITABLE` (`limits`, `pacing`, `router`, `providers`, `combos`, `teams`, `ceo`, `media`, `skills`); `combos` si sostituisce per intero (riga 54, commento: "così un fallback rimosso scompare davvero"), le altre chiavi si fondono. Scrive `local.json` con indentazione 2 e richiama `reload()`.
- **`Store`** (`server/store.js`): un run per file in `data/runs/<id>.json`, indentazione 1. Al boot legge ogni file e, se lo stato non è uno fra `completed`, `completed_with_failures`, `failed`, `stopped`, lo **riscrive in memoria** come `stopped` con `error: 'Interrupted: the server stopped while this run was active.'` (righe 14-17) — **non riscrive il file finché non arriva un nuovo `save()`**. `save(run, immediate)` con `immediate = false` (il caso normale) fa un debounce di 400 ms per run (un `setTimeout` per `run.id`, sostituito a ogni chiamata); `immediate = true` scrive subito (usato solo allo shutdown, `index.js:422`). Un file JSON non parsabile viene scartato in silenzio (`catch` vuoto, riga 19-21).
- **`GET /api/state`** (`index.js:121-134`) aggrega **sei sottosistemi indipendenti** in un solo oggetto: `mode` (Router), `config` (solo i campi pubblici — `publicConfig()`, riga 97-100: `ceo, teams, staff, limits, pacing, router, combos, providers, media, skills`, **mai** segreti o chiavi), `agents` (Team), `run` (il run attivo o l'ultimo salvato), `runs` (lista riassunta, `runList()`), `router` (`Router.snapshot()`), `media` (`Media.status()`), `skills` (`SkillLibrary.summary()`), `brain` (`{ count, recent: brain.list(40) }`). Ogni sottosistema arriva da un modulo diverso, portato in fasi diverse (P1 Config/Store, P3 Router, P4 Skill/Brain, P5 Team/Media/Run) — il design del contratto intermedio è in §4.5.

### 1.4 Macchina e strumenti di test

- Windows 11, Node v24.16.0 (minimo 20.10 per l'app, 22 per il runner), Python 3.13 gestito da `uv` 0.11.29.
- `npm test` lancia in sequenza `world-test.js` (puro front-end, tre.js, resta Node), `router-test.js`, `smoke.js`, `flows-test.js`, `temp-test.js`: ~35 s. `npm run test:browser` è il runner headless (235 verifiche, ~5 min). Ogni test Node che parla col server lo avvia da sé con `spawn(process.execPath, ['server/index.js'], { env, … })` (es. `scripts/smoke.js:21`) su una porta dedicata e propria, con `AGENT_WORLD_HOME` su una cartella temporanea di proprietà (`scripts/lib/temp.js`, dalla spec 03).
- Lezione della spec 03 (§1.2, misurata): su Windows **nessun modo esterno chiude node attraverso i suoi gestori** (`taskkill`, `child.kill()`, `timeout -s INT` della shell non eseguono `process.on('SIGINT', shutdown)`); solo una chiusura "dall'interno" (il processo stesso che riceve e gestisce il segnale, o chiude per `server.close()`) esegue `shutdown()` e salva i run attivi. **Da verificare per uvicorn** (§8, rischio R1): Python/Windows gestisce i segnali diversamente da Node, ma non c'è ancora una misura.

### 1.5 Obiettivo dell'utente, testuale

Il server passa da Node a FastAPI (API, routing agentico asincrono "OmniRoute" — il `Router` di oggi, portato in P3 — e SSE) più Rust per i calcoli pesanti. Restano identici l'esperienza utente, il sistema multi-agente e il front-end three.js: stesse route, stesso JSON, stessi eventi SSE. Il front-end non si tocca in questa spec.

### 1.6 Matrice delle route

Fase che implementa ogni route e cosa succede prima che sia portata (verde = funzionante sul backend Python; rosso = in `known-red.json` con il ticket che la porta).

| Route | Metodo | Sottosistema | Fase | Note |
|---|---|---|---|---|
| `/` , file statici in `public/` | GET | File statici | **P0** | Stesso elenco MIME, stessa risoluzione di `index.html` per le cartelle |
| `/vendor/three/*`, `/vendor/three-addons/*` | GET | File statici | **P0** | Serviti da `node_modules/three` — richiede comunque `npm install` (tre.js resta a Node, D6) |
| `/preview/:runId(/*)` | GET | File statici + Store | **P0** (forma e redirect 302) / **P1** (contenuto reale, serve `Store.get`) | Rosso con contenuto 404 finché Store non esiste |
| `GET /api/state` | GET | Config, Store, Router, Team, Media, Skill, Brain | **P1** (parziale, contratto in §4.5) → completo a **P5** | Campi dei sottosistemi non ancora portati: stub tipizzato, non assente |
| `GET /api/events` | GET | Bus/SSE | **P2** | |
| `GET /api/runs` | GET | Store | **P1** | |
| `POST /api/runs` | POST | Run, Team | **P5** | Rosso fino a P5: nessun run può partire |
| `GET /api/runs/:id` | GET | Store (+ Run se attivo) | **P1** (solo run chiusi, da Store) → **P5** (run attivi, da `live`) | |
| `POST /api/runs/:id/answer` | POST | Run | **P5** | |
| `POST /api/runs/:id/pause\|resume\|stop` | POST | Run | **P5** | |
| `GET /api/runs/:id/files`, `/file` | GET | Workspace (`tools.js`) | **P5** | |
| `GET /api/config` | GET | Config | **P1** | |
| `POST /api/config` | POST | Config | **P1** | |
| `GET /api/router` | GET | Router | **P3** | |
| `POST /api/router/test` | POST | Router | **P3** | |
| `GET /api/skills`, `/skills/read` | GET | SkillLibrary | **P4** | |
| `POST /api/skills/reindex`, `/skills/repo` | POST | SkillLibrary | **P4** | `addRepo` chiama `git`: verificare `git` in `PATH` anche dal processo Python |
| `GET /api/brain`, `POST /api/brain` | GET/POST | Brain, Bm25 | **P4** | Punto d'aggancio del bridge Rust (P6), interfaccia già pensata per essere intercambiabile |
| `GET /api/chat/:id`, `POST /api/chat/:id` | GET/POST | Team + Router | **P5** | |
| `GET /api/media` | GET | Media | **P5** | |
| `GET /v1/models` | GET | Config (solo `combos`) | **P3** (per coerenza con il resto del gateway, benché non serva il Router) | |
| `POST /v1/chat/completions` | POST | Router | **P3** | Streaming = un blocco singolo, come oggi (D7) |

## 2. Obiettivi e non-obiettivi

**Obiettivi (tutta la spec 04, non solo P0–P2):**
- Parità comportamentale completa su route, corpi JSON, eventi SSE e codici di stato, misurabile dagli stessi test che oggi provano Node.
- I due backend condividono gli stessi dati su disco (`data/`, `config/*.json`, `.env`) e le stesse variabili d'ambiente (`AGENT_WORLD_HOME`, `AGENT_WORLD_FAST`, `AGENT_WORLD_ALLOW_SHELL`, `AGENT_WORLD_API_KEY`, `PORT`): si passa da un backend all'altro sugli stessi dati e si torna indietro senza migrazioni.
- Il front-end (`public/`) non cambia una riga in questa spec.
- Un punto d'aggancio pulito per il bridge Rust (P6) sul modulo BM25, senza che la sua presenza o assenza cambi il contratto HTTP.

**Non obiettivi (di questa spec, non solo di P0–P2):**
- Streaming reale dei token su `/v1/chat/completions` (D7): resta un ticket futuro.
- Spostare pathfinding o simulazione 3D sul server (scartato in fase di piano, D1 opzione C): cambierebbe il contratto del front-end.
- Un microservizio separato per Rust (D2): resta nello stesso processo via PyO3.
- Rifare l'interfaccia utente, il Skill Hub o la logica di missione: si porta il comportamento esistente, bug compresi (si segnalano, non si correggono qui, salvo che blocchino la parità).
- In questo documento: dettagliare P3–P7. Restano al livello di piano di `HANDOFF.md` §2 finché non si avvicina il loro ticket.

## 3. Requisiti

### 3.1 P0 — Scheletro del processo (S)

- **S1.** `backend/` è un progetto gestito da `uv` (`pyproject.toml`, `uv.lock`), Python 3.13, con FastAPI e `uvicorn[standard]` come dipendenze dirette; `httpx` per le chiamate HTTP in uscita (sostituisce `fetch` di `providers.js`, usato da P3).
- **S2.** Il processo si avvia con un solo worker uvicorn (niente `--workers N`: lo stato vive in memoria in un solo processo, come oggi) e legge `PORT`, `AGENT_WORLD_HOME` e `.env` con la stessa precedenza di `server/env.js` (righe già presenti nell'ambiente vincono su `.env`; commenti `#`; valori tra virgolette spogliati).
- **S3.** Allo spegnimento (`SIGINT`/`SIGTERM`, o Ctrl+C), un gestore di lifespan di FastAPI chiude ogni connessione SSE aperta (altrimenti uvicorn aspetta che si chiudano da sole) **prima** di uscire. A P0 non ci sono ancora run da salvare (P5): il requisito su "salvare i run attivi allo shutdown" si verifica a P5, ma il meccanismo di lifespan nasce qui perché P2 (SSE) lo userà subito.
- **S4.** Il processo non assume quale backend è "quello vero": gira in parallelo a Node sulla stessa macchina, su una porta diversa durante lo sviluppo (Node resta il default fino alla parità, D3).
- **S5.** Nessuna dipendenza npm nuova lato server; `three` resta l'unica, usata solo per servire i file statici (S, non il processo Python).

### 3.2 P0 — File statici (F)

- **F1.** `GET /` e ogni percorso non riconosciuto da `/api/*`, `/v1/*`, `/vendor/*`, `/preview/*` servono da `public/`, con lo stesso comportamento di `serveFile` (`index.js:70-79`): se il percorso risolto è una cartella, si prova `index.html`; se manca il file, `404`; la risposta usa `Cache-Control: no-cache` (diverso da `/api/*`, che usa `no-store`, F4).
- **F2. Protezione dalla traversal.** La stessa identica regola del Node: il percorso richiesto si normalizza e si risolve contro la radice (`public/`, o la cartella del run per `/preview/`); se il risultato non è la radice stessa e non inizia con `radice + separatore`, risposta `403 Forbidden`. Da provare esplicitamente con `..%2f`, `%2e%2e/`, barre miste `\`/`/` su Windows.
- **F3.** `/vendor/three/*` e `/vendor/three-addons/*` risolvono rispettivamente a `node_modules/three/build` e `node_modules/three/examples/jsm`, con la stessa mappa MIME del Node (`index.js:45-62`: `.html .js .mjs .css .json .md .txt .svg .png .jpg .jpeg .gif .webp .ico .woff2 .wasm`); un'estensione fuori mappa risponde con `application/octet-stream`.
- **F4.** Le risposte JSON di `/api/*` e `/v1/*` portano sempre `Cache-Control: no-store` e `Content-Type: application/json; charset=utf-8` (o `text/plain; charset=utf-8` per i corpi testo semplice), come in `send()` (`index.js:64-68`).
- **F5. `/preview/:runId(/*)`.** Senza slash finale, `302` verso `/preview/:runId/` (riga 404). Con un run inesistente in Store, `404 'Run non trovato'`. A P0 lo Store non esiste ancora: la route risponde sempre `404` (comportamento di transizione, non un rosso — il test di parità la marca "contenuto in P1").

### 3.3 P0 — Harness dei test (H)

- **H1.** Una variabile d'ambiente nuova, `AGENT_WORLD_SERVER` (`node` di default, oppure `python`), letta da `scripts/smoke.js`, `scripts/flows-test.js`, `scripts/temp-test.js` e, più avanti, `scripts/browser-test.js`. Quando vale `python`, il comando lanciato cambia da `spawn(process.execPath, ['server/index.js'], …)` a `spawn('uv', ['run', 'python', '-m', 'backend'], { cwd: ROOT_BACKEND, … })` (o equivalente); tutto il resto del test (porta, `AGENT_WORLD_HOME`, attesa del messaggio di pronti, pulizia) resta invariato.
- **H2. Segnale di "pronto".** Il Node segnala la riga `Agent World` su stdout (`index.js:416`); il Python deve stampare una riga equivalente e riconoscibile allo stesso modo, così i test non devono duplicare la logica di attesa per backend.
- **H3. `known-red.json`.** Lo stesso schema della spec 03 (regole + segni generati, non scritti a mano): ogni route non ancora portata (matrice §1.6) si marca rossa con il ticket che la implementerà, solo quando il backend sotto test è `python`. I rossi attesi su Node restano a zero (la spec 03 li ha già azzerati).
- **H4. `router-test.js` → pytest.** Quando il Router sarà in Python (P3), i suoi test si riscrivono in `backend/tests/test_router.py` e `router-test.js` sparisce da `npm test`; non succede in questa fase (P0–P2 non toccano il Router), ma la struttura delle cartelle di `backend/` (`backend/tests/`) nasce già pronta a riceverli.
- **H5.** `world-test.js` resta sempre Node: è front-end puro (matematica di `framing.js`, nessuna rete), non dipende da quale backend gira.
- **H6. Igiene dei processi Python.** Finché non si misura il contrario (rischio R1, §8), ogni test che avvia il backend Python usa lo stesso spazzino della spec 03 (`scripts/lib/temp.js`), estendendo il pattern di riconoscimento dei processi orfani a `uvicorn`/`python` oltre a `node` ed Edge.

### 3.4 P1 — Config e Store (C, R)

- **C1.** Una classe `Config` Python replica **esattamente** il merge di `server/config.js`: profondo, ricorsivo, oggetti fusi chiave per chiave, array e scalari sovrascritti per intero; stessa precedenza `default.json` < `local.json` < override d'ambiente (`PORT`, `AGENT_WORLD_ALLOW_SHELL`, `AGENT_WORLD_FAST`); stessa lista `EDITABLE` per `update()`; stessa regola speciale per `combos` (sostituito intero, mai fuso).
- **C2.** La derivazione di `staff` (CEO poi, per ogni team nell'ordine del dizionario, lead e worker) produce la stessa lista, nello stesso ordine, a partire dallo stesso `config/default.json` — verificabile confrontando `GET /api/config` byte per byte (a parte la formattazione JSON) fra i due backend.
- **C3.** `update(patch)` scrive `config/local.json` con la stessa indentazione (2 spazi) e gli stessi contenuti del Node, così un file scritto da un backend si legge identico dall'altro.
- **R1.** Una classe `Store` replica `data/runs/<id>.json`: un file per run, indentazione 1, stessa regola di recupero all'avvio (uno stato non terminale diventa `stopped` con lo stesso messaggio d'errore, **solo in memoria** finché non arriva un nuovo salvataggio).
- **R2.** `save(run, immediate=False)` debounced a 400 ms per `run.id` (un timer per run, sostituito a ogni chiamata, non cumulativo); `immediate=True` scrive subito. A P1 non esistono ancora run attivi (serve P5 per crearne): il requisito si misura con fixture che inseriscono file già pronti in `data/runs/`.
- **R3.** Un file JSON non parsabile in `data/runs/` si scarta in silenzio all'avvio, esattamente come oggi (nessuna eccezione che impedisca il boot).
- **A1. `GET /api/state` a P1.** Risponde con lo stesso schema del Node, ma i sottosistemi non ancora portati sono **stub tipizzati e stabili**, non assenti né `null` dove il front-end si aspetta un oggetto: `agents: []`, `run: None`, `router: { mode: "demo", providers: [], combos: [], recent: [] }`, `media: { ready: False, image: [], speech: [] }` (forma minima compatibile con `Media.status()`), `skills: { count: 0, sources: [] }`, `brain: { count: 0, recent: [] }`. `config` e `runs` sono invece **reali** (vengono da Config e Store, già portati). Ogni stub si rimpiazza, campo per campo, quando la sua fase arriva (P3–P5), senza cambiare la forma delle chiavi già presenti.
- **A2.** `GET /api/config` e `POST /api/config` sono reali e completi a P1 (dipendono solo da Config).
- **A3.** `GET /api/runs` e `GET /api/runs/:id` (solo run chiusi, nessun run `live` possibile prima di P5) sono reali a P1.

### 3.5 P2 — Bus e SSE (B)

- **B1. Bus sincrono.** Un oggetto bus con un metodo `emit(type, payload)` che assegna `seq` (contatore globale crescente, mai resettato finché il processo vive) e serializza il frame **una sola volta** (`json.dumps({"seq": seq, "type": type, "payload": payload})`), poi lo mette in coda a ogni client connesso. Stessa semantica del Node: l'ordine dei `seq` è l'ordine delle chiamate a `emit`, non l'ordine di scrittura ai socket.
- **B2. Una coda per client.** Ogni connessione SSE ha una propria `asyncio.Queue` con una capienza massima (da fissare in implementazione, es. 1000 frame: oltre, il client si considera troppo lento). Un `emit` scrive (non bloccante) in ogni coda viva; non aspetta che un client legga.
- **B3. Client lento: si stacca, non si blocca.** Se la coda di un client è piena, quella connessione si chiude lato server (non si butta via l'evento per tutti gli altri). Il client, come già fa oggi (`public/js/main.js:1032`), si riconnette e rilegge `GET /api/state` per riallinearsi — comportamento lato client già esistente e fuori perimetro di questa spec.
- **B4. Stessa lista di eventi, stesso formato.** Solo i 17 tipi di `FORWARD` (§1.2) attraversano l'SSE; `data: {"seq":N,"type":T,"payload":P}\n\n`, `retry: 2000` all'apertura, `: ping\n\n` ogni 15 s. L'endpoint è `StreamingResponse` con `media_type="text/event-stream"`.
- **B5. Chiusura ordinata.** Il lifespan di FastAPI (S3) chiude ogni `StreamingResponse` aperta allo shutdown, così `uvicorn` non resta in attesa di connessioni che non si chiuderanno mai da sole (stesso problema per cui, lato Node, `server.close()` non basta senza gestire le SSE a parte — da verificare, non misurato ancora lato Python: rischio R1 generalizzato all'SSE, §8).
- **B6. Nessun replay.** Una riconnessione non riceve gli eventi persi: identico al Node, il client rilegge lo stato con `/api/state`.
- **B7. Eventi emessi a P2.** A questa fase, l'unico produttore reale di eventi è `POST /api/config` (già portato a P1, emette `config`). Gli altri 16 tipi restano "cablati" nel bus (il canale esiste e il tipo è nella lista consentita) ma senza produttore fino alle fasi che portano i rispettivi sottosistemi (P3–P5). Il test di parità per P2 usa `config` come sonda end-to-end: apre l'SSE, chiama `POST /api/config`, verifica che il frame arrivi con lo stesso `type`, una `payload` con la stessa forma e un `seq` coerente.

## 4. Design tecnico

### 4.1 Struttura di `backend/`

```
backend/
  pyproject.toml          # uv, FastAPI, uvicorn[standard], httpx
  backend/
    __main__.py           # python -m backend: crea l'app, legge PORT/.env, uvicorn.run
    app.py                 # istanza FastAPI, lifespan (S3), montaggio delle route
    config.py              # C1-C3
    store.py               # R1-R3
    bus.py                  # B1-B2 (il bus; la route SSE sta in routes/events.py)
    state.py                # A1: assembla /api/state dagli stub e dai moduli reali
    routes/
      static.py             # F1-F5
      api_state.py          # /api/state, /api/config, /api/runs (parte P1)
      events.py              # /api/events (P2)
  tests/
    conftest.py             # fixture: avvia l'app con httpx.AsyncClient / TestClient
    test_config.py
    test_store.py
    test_state.py
    test_events.py
```

Pacchetto unico, niente microservizi interni (D2): quando arriverà il bridge Rust (P6), `crates/aw_core` (fuori da `backend/`, compilato con `maturin`) si importerà come un modulo Python qualunque da `backend/brain.py`.

### 4.2 File statici (F)

`routes/static.py` replica `serveFile` con `pathlib`: `full = (root / rel).resolve()`; il controllo di traversal è `full == root or str(full).startswith(str(root) + os.sep)`. FastAPI non ha un file-server con questa esatta semantica incorporato (`StaticFiles` di Starlette fa un controllo simile ma con messaggi ed edge-case diversi): si scrive a mano, non si adatta `StaticFiles`, per tenere i codici di stato e il comportamento sulle cartelle identici al Node.

### 4.3 Config (C)

```python
def merge(base: dict, over: dict | None) -> dict: ...  # ricorsiva, stessa semantica di config.js:6-13
class Config:
    def __init__(self, dir: Path): self.reload()
    def reload(self) -> None: ...   # default.json + local.json + override d'ambiente + staff
    def get(self) -> dict: ...
    def update(self, patch: dict) -> None: ...  # solo EDITABLE, combos sostituito intero
```

Un test di parità genera `GET /api/config` sui due backend a partire dallo stesso `config/default.json` (quello vero del repo, nessuna fixture separata) e confronta i due JSON dopo aver normalizzato solo l'ordine delle chiavi (l'ordine dei valori dentro gli array, es. `staff`, deve coincidere esattamente).

### 4.4 Store (R)

`store.py` usa `json.dump(..., indent=1)` per restare bit-compatibile con `JSON.stringify(run, null, 1)` del Node (stessa indentazione, quindi un file scritto da un backend è diffabile contro quello scritto dall'altro). Il debounce (R2) usa `asyncio.get_event_loop().call_later(0.4, write)`, sostituito ad ogni `save()` sullo stesso `run.id` esattamente come il Node fa con `clearTimeout`.

### 4.5 `/api/state` e il contratto degli stub (A)

`state.py` costruisce l'oggetto a partire da due categorie di fonti:
- **Reali a P1:** `config.get()` passato per `publicConfig` (stessa whitelist di campi), `store.list()` per `runs`, `store.get(id)` o il run attivo per `run`.
- **Stub stabili fino alla loro fase:** un dizionario Python costante per sottosistema (Router, Team, Media, SkillLibrary, Brain), con la stessa forma delle chiavi che il front-end legge da `public/js/main.js` (da verificare lettura per lettura prima di chiudere P1 — non in questa spec: il test V5, §5, lo misura già unendo la lettura del JS col JSON prodotto).

Ogni fase successiva **sostituisce** il modulo stub con quello reale senza toccare `state.py` più di una riga per campo: l'assemblaggio resta lo stesso, cambia solo da dove arriva ogni pezzo.

### 4.6 Bus e SSE (B)

```python
class Bus:
    def __init__(self): self._seq = 0; self._clients: set[asyncio.Queue] = set()
    def emit(self, type: str, payload: dict) -> None:
        self._seq += 1
        frame = f'data: {json.dumps({"seq": self._seq, "type": type, "payload": payload})}\n\n'
        for q in list(self._clients):
            try: q.put_nowait(frame)
            except asyncio.QueueFull: self._clients.discard(q)  # si stacca, non blocca (B3)
```

La route (`routes/events.py`) crea la coda, la registra, scrive `retry: 2000\n\n`, poi un generatore asincrono che fa `await asyncio.wait_for(q.get(), timeout=15)` e, allo scadere, scrive `: ping\n\n` (stesso intervallo del Node) finché il client non si disconnette (`request.is_disconnected()`) o il lifespan non chiude tutto (S3, B5).

### 4.7 Harness dei test (H)

`scripts/lib/backend-launcher.js` (nuovo, piccolo): data `AGENT_WORLD_SERVER`, restituisce `{ cmd, args, cwd }` per lo `spawn` — `['node', ['server/index.js']]` oppure `['uv', ['run', 'python', '-m', 'backend']]` con `cwd: join(ROOT, 'backend')`. I tre script (`smoke.js`, `flows-test.js`, `temp-test.js`) importano questo helper invece di costruire il comando a mano; il resto (attesa di "pronti", porta, `AGENT_WORLD_HOME`, pulizia via `scripts/lib/temp.js`) non cambia.

### 4.8 Bridge Rust: solo il punto d'aggancio (non di questa fase)

Non si implementa in P0–P2. Per non doverlo riprogettare a P4/P6, `brain.py` (che nascerà a P4) chiamerà sempre un oggetto con interfaccia `add(id, fields)` / `search(query, k)`, che a P1–P3 non esiste ancora ma la cui forma è già fissata da `search.js` oggi. La soglia di adozione (Rust entra solo se batte il Python ottimizzato di almeno 5× sul corpus misurato, D1) e il fallback Python puro restano come decisi nel piano; nessuna riga di Rust in questa spec.

## 5. Criteri di accettazione

- **V1 (S).** `uv run python -m backend` si avvia sulla stessa porta e con gli stessi override d'ambiente del Node; stampa una riga di "pronto" riconoscibile da `H2`.
- **V2 (S).** Un `Ctrl+C` al processo Python chiude ogni connessione SSE aperta e il processo esce, senza restare in attesa (misurare il tempo di uscita; confrontare con la lezione della spec 03 sul Node, §1.4 — se Python si comporta diversamente, annotarlo come scoperta, non come bug).
- **V3 (F).** Per ogni voce della mappa MIME (§3.2 F3) una richiesta a un file reale in `public/` o `node_modules/three` risponde con lo stesso `Content-Type` sui due backend.
- **V4 (F).** Tre payload di traversal (`..%2f`, `%2e%2e/`, `..\`) rispondono `403` su entrambi i backend.
- **V5 (A).** `GET /api/state` sui due backend, a P1, ha le stesse chiavi di primo e secondo livello; i campi reali (`config`, `runs`) coincidono byte per byte (normalizzando l'ordine delle chiavi JSON); i campi stub hanno la forma che `public/js/main.js` si aspetta di leggere senza eccezioni (misurato aprendo l'app col backend Python e osservando la console del browser: zero errori, anche se il pannello corrispondente resta vuoto).
- **V6 (C).** `GET /api/config` coincide byte per byte fra i due backend sullo stesso `config/default.json`.
- **V7 (C).** `POST /api/config` con un `patch` che include una chiave fuori da `EDITABLE` (es. `server`) non la scrive in `local.json` su nessuno dei due backend.
- **V8 (C).** `POST /api/config` con un nuovo `combos` sostituisce l'intero oggetto (un combo tolto nel patch non sopravvive) su entrambi.
- **V9 (R).** Un file `data/runs/<id>.json` con `status: "running"` scritto a mano, letto all'avvio da entrambi i backend, diventa `stopped` con lo stesso messaggio — in memoria; il file su disco non cambia finché non arriva un nuovo `save()`.
- **V10 (R).** Due `save()` sullo stesso `run.id` entro 400 ms producono **una sola scrittura** su disco, sui due backend.
- **V11 (B).** `GET /api/events` risponde con `retry: 2000` nel primo frame e, senza altri eventi, un `: ping` entro 15-16 s, su entrambi.
- **V12 (B).** `POST /api/config` con l'SSE aperto produce, su entrambi i backend, un frame `config` con `seq` che è esattamente uno in più del `seq` più alto visto finora da quel client.
- **V13 (B).** Con una coda client artificialmente piena (test che non legge apposta), il client si disconnette senza che gli altri client connessi perdano eventi.
- **V14 (H).** `AGENT_WORLD_SERVER=python npm test` esegue gli stessi tre script (`smoke`, `flows`, `temp-test`) contro il backend Python; le route non ancora portate (matrice §1.6) falliscono nel modo previsto da `known-red.json`, non con un errore non gestito.
- **V15 (H).** `AGENT_WORLD_SERVER=node npm test` (il default di oggi) resta verde esattamente come prima di questa spec: **zero regressioni sul Node**, che resta il backend di produzione fino alla parità (D3).
- **V16 (globale).** Nessun file di `public/` cambia in questo ciclo (diff vuoto su `public/`).
- **V17 (globale).** `npm run sweep -- --dry-run` dopo una sessione di test con `AGENT_WORLD_SERVER=python` non trova processi Python/uvicorn orfani (H6); se li trova, è un difetto da correggere prima di chiudere P0, non un rischio da annotare.

## 6. Ticket in bozza

Si dettagliano allo step 3 (To-tickets), nell'ordine P0 → P1 → P2 (un ticket, o pochi, per lettera di requisito: S+F+H per P0, C+R+A per P1, B per P2), con lo stesso schema delle spec precedenti: test che sa fallire prima della correzione dove ha senso, `known-red.json` aggiornato nello stesso commit, QA dell'utente dopo ogni ticket. P3–P7 restano nel piano (`HANDOFF.md` §2) e si tickettano quando ci si arriva, dopo un aggiornamento di questa spec con lo stesso livello di dettaglio di §3–4.

## 7. Decisioni

| # | Domanda | Decisione |
|---|---|---|
| D1 | Quanto Rust | Bridge subito dal modulo BM25, con ripiego Python e soglia d'adozione 5× sul corpus misurato; niente pathfinding o spazio sul server |
| D2 | Tipo di bridge | PyO3 nello stesso processo (niente microservizi) |
| D3 | Strategia | I due backend crescono in parallelo; si cambia alla parità, niente proxy "strangler" (bus, SSE e run attivi sono stato condiviso) |
| D4 | Python | CPython 3.13 gestito da `uv`, non quello del Microsoft Store |
| D5 | Toolchain Rust | `rustup` (target MSVC) e Visual Studio Build Tools C++ già installati e in `PATH`: nessuna preparazione di comandi, si procede diretti quando si arriva a P6 |
| D6 | Node dopo il cambio | Resta solo per `three.js` e gli strumenti di test |
| D7 | Streaming di `/v1` | Un blocco singolo, come oggi; lo streaming vero dei token resta un ticket futuro |
| D8 | Branching | `feat/memory-stability` unito in `main` e `push` fatti (questo documento vive su `feat/backend-port`, da `main` = `0c20a69`) |

## 8. Rischi

- **R1 — Chiusura dei processi su Windows (non misurato).** La spec 03 ha misurato che nessun modo esterno chiude Node attraverso i suoi gestori su Windows; non è ancora misurato se `uvicorn`/Python si comporta uguale, meglio o peggio. Se si comporta peggio, l'igiene dei test (H6) e lo spazzino dovranno trattare i processi Python come già trattano Node ed Edge. Primo ticket di P0: misurare prima di assumere parità.
- **R2 — `uv run python -m backend` più lento ad avviarsi di `node server/index.js`.** Non misurato. Se l'avvio supera il timeout attuale dei test (`smoke.js` aspetta la riga di pronti senza un limite esplicito, ma altri script potrebbero averne uno), va alzato per il caso Python, non abbassato il requisito di parità.
- **R3 — `StaticFiles` di Starlette "quasi" basta.** La tentazione di usarlo invece di scrivere `routes/static.py` a mano (§4.2) produrrebbe codici di stato ed edge-case di traversal leggermente diversi dal Node: il requisito F2 richiede il controllo scritto a mano, non il default del framework.
- **R4 — `/api/skills/repo` chiama `git` come sottoprocesso (P4, non di questa fase, ma da tenere a mente già ora nella struttura di `backend/`).** `spawn('git', …)` in Node e l'equivalente Python (`subprocess` o `asyncio.create_subprocess_exec`) devono restare non bloccanti per il loop asyncio: un clone lento non deve congelare l'SSE (collegato a B1-B2, lo stesso principio del bus che non deve mai aspettare un'operazione lenta).
- **R5 — Debounce di `Store.save` e `asyncio`.** `call_later` di `asyncio` richiede un event loop attivo; se `save()` viene chiamato da un contesto sincrono (thread diverso, es. dal futuro bridge Rust che rilascia il GIL), serve `loop.call_soon_threadsafe`. Non è un problema a P1 (nessun chiamante da un altro thread), ma è da tenere presente quando arriverà P6.
