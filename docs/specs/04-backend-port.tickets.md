# Ticket — Spec 04, porting del backend: P0, P1, P2

Riferimento: [04-backend-port.md](04-backend-port.md). Gli ID S\*, F\*, H\*, C\*, R\*, A\*, B\*, V\* e D\* rimandano alla spec. Solo le fasi **P0, P1, P2**: P3–P7 restano nel piano (spec §3.5, §6) e si tickettano dopo un aggiornamento della spec con lo stesso dettaglio.

**In breve**
1. **T1–T3** costruiscono gli strumenti prima del comportamento: lo scheletro del processo (T1), i file statici (T2), poi il lanciatore parametrico e la matrice delle route come prova di parità (T3) — che da qui in avanti ogni ticket aggiorna.
2. **T4 e T5** portano Config e Store: due moduli indipendenti, nessuna route ancora collegata.
3. **T6** collega Config e Store alle route (`GET/POST /api/config`, `GET /api/runs[/:id]`, `GET /api/state` con gli stub tipizzati per i sottosistemi non ancora portati) e aggiorna la matrice.
4. **T7** porta il bus e l'SSE (`GET /api/events`), l'unico pezzo di P2.
5. **T8** è la verifica finale di P0–P2: matrice completa, confronto incrociato con Node, igiene dei processi, QA.
6. **Nessun file in `public/` cambia in nessun ticket di questo ciclo** (lo dice anche V16): è tutto backend nuovo, affiancato a `server/`, che resta il default (D3).

**Ordine:** T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8. T4 e T5 non dipendono l'uno dall'altro (Config e Store sono moduli separati) ma si fanno in sequenza, un commit atomico alla volta.

**Regole valide per ogni ticket**
- **Perimetro.** Ogni ticket tocca solo i file elencati nella sua sezione "File"; se durante il lavoro serve toccarne un altro, si annota nel messaggio di commit perché.
- **Test prima, rosso, poi il codice, verde — nello stesso commit.** Ogni ticket scrive prima il test (pytest per il codice Python, Node/`httpx` per i confronti incrociati con Node), lo esegue sul codice che c'è *prima* di questo ticket e verifica che fallisca per il motivo giusto (non per un errore di sintassi o un percorso sbagliato); solo dopo scrive l'implementazione. L'output del giro rosso va nel messaggio di commit, come in T1/T2 della spec 03.
- **Chiusura e fermata.** Un ticket si chiude quando i suoi criteri sono verdi; poi ci si ferma e si aspetta il tuo feedback.
- **Matrice e rossi attesi.** Da T3 in poi, `scripts/backend/known-red.json` elenca solo le route non ancora portate (fase P3 in su, spec §1.6); ogni ticket che porta una route la toglie dal file nello stesso commit. Un rosso non previsto da `red-rules.json` ferma lo script con `UNEXPLAINED` ed esce con 1, senza scrivere il file (stesso schema di `mark-reds.js` nella spec 03).
- **Passaggio avversario.** Prima di ogni commit che introduce o cambia un contratto (forma di un JSON, un header, un codice di stato): tutti i chiamanti noti (grep in `public/js/`), "e se il campo manca?", "e se arriva due volte?". L'esito va nel messaggio di commit.
- **Verifiche a livelli.** `uv run --directory backend pytest -q` per i moduli toccati; `npm test` (deve restare verde, invariato: V15) a ogni ticket che tocca `scripts/`; `node scripts/backend-parity-test.js` da T3 in poi; mai il runner del browser per i commit di solo backend Python (nessun cubo, evento o `fx` cambia).
- **Processi e porte.** Il backend Python si avvia e si chiude con lo stesso spazzino della spec 03 (`scripts/lib/temp.js`), esteso a riconoscere `uv`/`python` (H6); porte 4300 (il tuo server), 3939 e 4310 (altre sessioni) non si toccano; ogni test usa una porta propria.
- **Commit.** Un commit atomico per ticket, messaggi in inglese, documenti in italiano, nessun push senza il tuo via libera.

| Ticket | Titolo | Spec | Dimensione | Dipende da |
|---|---|---|---|---|
| T1 | Scheletro del processo `backend/` | §3.1, §4.1, S1–S5, H2, V1 | M | — |
| T2 | File statici e protezione dalla traversal | §3.2, §4.2, F1–F5, V3, V4 | M | T1 |
| T3 | Lanciatore parametrico e matrice delle route | §3.3, §4.7, H1, H3–H6, V14 | L | T1, T2 |
| T4 | Config | §3.4, §4.3, C1–C3, V6–V8 | S | T1 |
| T5 | Store | §3.4, §4.4, R1–R3, V9, V10 | S | T1 |
| T6 | `/api/state`, `/api/config`, `/api/runs`: gli stub e i reali | §3.4, §4.5, A1–A3, V5 | M | T3, T4, T5 |
| T7 | Bus e SSE (`/api/events`) | §3.5, §4.6, B1–B7, V11–V13 | L | T1, T6 |
| T8 | Verifica finale P0–P2, confronto con Node, QA | V1–V2, V15–V17 | M | T1–T7 |

---

## T1 — Scheletro del processo `backend/`

**Obiettivo:** `uv run python -m backend` si avvia, stampa una riga di "pronto" riconoscibile, e si chiude in modo ordinato (nessuna connessione rimasta in sospeso) — senza ancora nessuna route applicativa.

**File:**
- nuovi: `backend/pyproject.toml`, `backend/uv.lock`, `backend/backend/__init__.py`, `backend/backend/__main__.py`, `backend/backend/app.py`, `backend/backend/env.py`;
- nuovo: `scripts/backend-boot-test.js` (test dedicato di questo ticket, non ancora in `npm test`).

Nessun file in `public/` o `server/` cambia.

**Attività**
1. **Prima il test, su "niente ancora".** `scripts/backend-boot-test.js` fa `spawn('uv', ['run', 'python', '-m', 'backend'], { cwd: 'backend', env: { PORT: '4398', ... } })` e aspetta entro 5 s una riga su stdout che contenga `Agent World`; poi una richiesta `GET /` (qualunque risposta, anche 404, va bene: a questo punto importa solo che il processo risponda in HTTP); poi `SIGINT` e misura il tempo di uscita (atteso: entro 3 s). Eseguito ora: **rosso**, `uv run python -m backend` fallisce con "No module named backend" perché `backend/` non esiste. L'output va nel messaggio di commit.
2. **`backend/pyproject.toml`:** progetto `uv`, Python `>=3.13`, dipendenze `fastapi`, `uvicorn[standard]`, `httpx`; gruppo di sviluppo con `pytest`, `pytest-asyncio`.
3. **`backend/backend/env.py`:** porta `loadEnv` (`server/env.js`) riga per riga: righe `KEY=VALUE`, commenti `#`, valori tra virgolette spogliati, **i valori già in `os.environ` vincono** sempre su quelli del file `.env`.
4. **`backend/backend/app.py`:** `app = FastAPI()`; un gestore di lifespan (`@asynccontextmanager`) che per ora non fa nulla all'avvio e nulla alla chiusura (punto d'estensione per S3, completato in T7 quando esisteranno connessioni SSE da chiudere); zero route applicative (il contratto delle route arriva da T2 in poi).
5. **`backend/backend/__main__.py`:** chiama `env.load_env(root / '.env')`, legge `PORT` (default dalla stessa logica di `config.js`, qui semplificata a `int(os.environ.get('PORT', 4300))` perché `Config` arriva a T4), stampa `Agent World  →  http://127.0.0.1:{port}` (stessa sottostringa `Agent World` del Node, per H2) **prima** di chiamare `uvicorn.run(app, host=..., port=port)`.
6. **Passaggio avversario:** un secondo `SIGINT` durante la chiusura non deve far uscire con un traceback diverso da quello pulito; una porta già occupata fa uscire `uvicorn` con un errore chiaro su stderr (non un hang).
7. **Verifiche:** `node scripts/backend-boot-test.js`; nessun impatto su `npm test` (nessun file toccato in `scripts/` oltre al nuovo).

**Commit:** `feat(backend): FastAPI skeleton boots, prints ready, shuts down on SIGINT (T1)`

**Fatto quando:** V1 verde (avvio, riga di pronti, risposta HTTP); il tempo di uscita su `SIGINT` è misurato e registrato nel messaggio di commit; il test visto rosso su "niente ancora" e verde dopo.

## T2 — File statici e protezione dalla traversal

**File:** nuovo `backend/backend/routes/static.py`, nuovo `backend/tests/test_static.py`; `backend/backend/app.py` (monta le route statiche).

**Attività**
1. **Prima il test, sullo scheletro di T1.** `test_static.py` usa `httpx.ASGITransport` contro `app` direttamente (nessun processo vero: più rapido, e l'app FastAPI è lo stesso oggetto che userà `uvicorn`). Richieste: `GET /` (si aspetta `public/index.html`), un file reale a scelta in `public/`, `GET /vendor/three/three.module.js` (da `node_modules/three/build`), tre payload di traversal (`..%2f`, `%2e%2e/`, `..\`), un'estensione fuori dalla mappa MIME, `GET /preview/qualunque/`. Eseguito ora: **rosso**, tutto risponde `404` (nessuna route statica esiste, l'app di T1 non ne ha).
2. **`routes/static.py`:**
   - `serve_file(request, root: Path, rel: str)`: risolve `full = (root / rel.lstrip('/\\')).resolve()`; se `full != root and not str(full).startswith(str(root) + os.sep)` → `403`; se `full` è una cartella, prova `full / 'index.html'`; se manca → `404`; altrimenti `FileResponse` con il `Content-Type` dalla stessa mappa MIME del Node (§3.2 F3: `.html .js .mjs .css .json .md .txt .svg .png .jpg .jpeg .gif .webp .ico .woff2 .wasm`, default `application/octet-stream`) e `Cache-Control: no-cache`;
   - tre route: `GET /{path:path}` → `public/` (radice del progetto, non `backend/`); `GET /vendor/three/{path:path}` → `node_modules/three/build`; `GET /vendor/three-addons/{path:path}` → `node_modules/three/examples/jsm`;
   - `GET /preview/{run_id}` senza slash finale → `302` verso `/preview/{run_id}/`; con lo slash, **sempre `404` a questa fase** (nessuno Store, F5: comportamento di transizione, non un rosso della matrice).
3. **Passaggio avversario:** una richiesta a un file con `..` in mezzo al percorso ma che *non* esce dalla radice (es. `a/../b`) deve restituire `b`, non `403` (il controllo è sulla destinazione finale, non sulla presenza di `..`); una richiesta a `/vendor/three/../../../server/index.js` deve dare `403`.
4. **Verifiche:** `uv run --directory backend pytest backend/tests/test_static.py -q`; `node scripts/backend-boot-test.js` (ancora verde: non deve essersi rotto l'avvio).

**Commit:** `feat(backend): static files, MIME map and traversal guard match Node (T2)`

**Fatto quando:** V3 e V4 verdi; il test visto rosso sullo scheletro di T1 e verde dopo.

## T3 — Lanciatore parametrico e matrice delle route

**Obiettivo:** una sola variabile d'ambiente decide quale backend si avvia nei test; uno script misura *tutta* la matrice delle route (spec §1.6) contro il backend Python e la confronta con la tabella delle regole, così ogni ticket successivo ha una prova automatica di quante righe della matrice ha tolto dal rosso.

**File:**
- nuovi: `scripts/lib/backend-launcher.js`, `scripts/backend/known-red.json`, `scripts/backend/red-rules.json`, `scripts/backend-parity-test.js`;
- `scripts/temp-test.js` (usa il lanciatore per includere anche l'igiene dei processi Python); `package.json` (nuovo script `test:backend`).

**Attività**
1. **Prima il test, sul backend di T1+T2.** `scripts/backend-parity-test.js`, eseguito ora contro `AGENT_WORLD_SERVER=python`, deve già passare per le **due** route portate finora (i file statici) e segnalare come `UNEXPLAINED` tutte le altre 20+ (nessuna regola ancora scritta). Atteso: **rosso**, esce con 1 e stampa l'elenco delle righe senza regola. L'output va nel messaggio di commit.
2. **`scripts/lib/backend-launcher.js`:** `launchCommand(server)` → `{ cmd, args, cwd }`: `'node'` restituisce `['server/index.js']` da `ROOT`; `'python'` restituisce `['uv', ['run', 'python', '-m', 'backend']]` da `backend/`. Una funzione sola, usata ovunque serva avviare un backend nei test (qui e, più avanti, da `smoke.js`/`flows-test.js` quando avranno senso contro Python — **non in questo ticket**, vedi la precisazione sotto).
3. **`scripts/backend/red-rules.json`:** la tabella "route → ticket" della matrice §1.6, nello stesso formato di `red-rules.json` della spec 03 (`match` come espressione sul percorso e il metodo, `ticket` come stringa): ogni riga con fase P3 o successiva punta al ticket (di una spec futura) che la porterà; le righe P0–P2 non hanno regola, perché devono essere verdi.
4. **`scripts/backend-parity-test.js`:**
   - avvia il backend Python col lanciatore (punto 2), su una porta propria;
   - per ogni riga della matrice §1.6: fa la richiesta (con un corpo minimo sensato per le `POST`) e verifica:
     - fase P0–P2 → risposta diversa da `404 Unknown endpoint`/connessione rifiutata (cioè: la route esiste ed è stata implementata; il contenuto esatto si verifica nei test dei ticket che la portano, qui si verifica solo "non è più assente dalla matrice");
     - fase P3+ → se risponde come "non implementata" (404 sul backend Python, o lo stub previsto) **e** `red-rules.json` ha una regola per quella riga, la segna rossa attesa; se risponde in un altro modo (es. 200 con un corpo a caso) o non ha una regola, la segna `UNEXPLAINED`;
   - con almeno un `UNEXPLAINED`, stampa l'elenco ed esce con 1 **senza** scrivere `known-red.json`; altrimenti scrive il file (route → ticket) e stampa la tabella, poi esce con 0;
   - `--check`: confronta senza scrivere (per rigenerare dopo un cambio di `red-rules.json`).
5. **`temp-test.js`:** aggiunge, solo quando `AGENT_WORLD_SERVER` include `python` (o con un nuovo flag `--with-python`), gli stessi casi C1–C3 della spec 03 ma avviando il backend Python col lanciatore — l'igiene dei processi (spazzino, cartelle di proprietà) non dipende da quale linguaggio genera il processo, quindi si verifica anche qui prima che ci sia una sola route di business a funzionare.
6. **`package.json`:** nuovo script `"test:backend": "uv run --directory backend pytest -q && node scripts/backend-parity-test.js"`. **Non** entra in `npm test` (che resta solo Node, V15): è un comando a parte, per ora.
7. **Passaggio avversario:** due istanze di `backend-parity-test.js` in parallelo su porte diverse non si spazzano a vicenda (stesso principio della spec 03, T1, punto 6); una regola di `red-rules.json` che corrisponde a più righe della matrice le marca tutte.
8. **Verifiche:** `node scripts/backend-parity-test.js` (atteso: tutte le righe statiche verdi, le altre rosse attese, zero `UNEXPLAINED`); `npm test` (invariato, V15); `node scripts/temp-test.js`.

*(Precisazione rispetto al piano.)* **`smoke.js` e `flows-test.js` non si parametrizzano in questo ticket.** Il loro intero contenuto è una missione end-to-end (`POST /api/runs` e il suo ciclo): non hanno granularità più fine, quindi "gira contro Python" oggi significherebbe solo "fallisce sempre", senza informazione in più rispetto a `backend-parity-test.js`. Si parametrizzano quando `POST /api/runs` esiste (P5, fuori da questa spec), riusando lo stesso `backend-launcher.js` scritto qui.

**Commit:** `test(backend): parametrized launcher and route-matrix parity harness (T3)`

**Fatto quando:** V14 verde (la matrice distingue correttamente verde/rosso atteso/`UNEXPLAINED`); zero `UNEXPLAINED` sul backend di T1+T2; `npm test` invariato; il giro iniziale (tutto `UNEXPLAINED` tranne i file statici) è nel messaggio di commit.

## T4 — Config

**File:** nuovi `backend/backend/config.py`, `backend/tests/test_config.py`.

**Attività**
1. **Prima il test.** `test_config.py` importa `Config`, che non esiste ancora: **rosso**, `ImportError`.
2. **`backend/backend/config.py`:**
   - `merge(base, over)`: ricorsiva, oggetti fusi chiave per chiave, array e scalari sovrascritti per intero — stessa funzione di `config.js:6-13`, inclusi i casi `over is None` (vince `base`) e `over` non è un dizionario (vince `over`);
   - `class Config`: `__init__(dir)` chiama `reload()`; `reload()` legge `default.json` (il vero `config/default.json` del repo, non una copia) più `local.json` se esiste, applica gli override `PORT`, `AGENT_WORLD_ALLOW_SHELL`, `AGENT_WORLD_FAST` (azzera `pacing` a 20 e la latenza del provider `mock` a `[10, 40]`, stessa soglia del Node) e deriva `staff` (CEO, poi per ogni team **nell'ordine delle chiavi di `teams` nel JSON**, lead e worker);
   - `get()` restituisce il dizionario; `update(patch)` accetta solo le chiavi `EDITABLE` (`limits, pacing, router, providers, combos, teams, ceo, media, skills`), fonde tutto tranne `combos` (sostituito per intero), scrive `local.json` con `indent=2` e richiama `reload()`.
3. **Passaggio avversario:** un `patch` con una chiave fuori da `EDITABLE` non deve finire in `local.json`; un `patch['combos']` che omette un combo esistente lo fa sparire (non lo fonde); due `Config` sullo stesso `dir` in processi diversi non si pestano i piedi (ognuno scrive il proprio `local.json` per intero, come il Node).
4. **Confronto con Node (V6):** `test_config.py` include un confronto diretto — stesso `config/default.json`, `GET` equivalente da entrambi i lati (qui: `Config(dir).get()` in Python contro `JSON.parse` dell'output di un piccolo script Node una tantum, o più semplicemente il confronto si completa in T6 quando la route esiste; qui si verifica solo che la struttura Python coincida campo per campo con una lettura diretta di `default.json` più le derivazioni).
5. **Verifiche:** `uv run --directory backend pytest backend/tests/test_config.py -q`.

**Commit:** `feat(backend): Config mirrors the deep-merge, EDITABLE whitelist and staff derivation (T4)`

**Fatto quando:** V7 e V8 verdi (le parti verificabili senza la route, completate da V6 in T6); il test visto rosso su "il modulo non esiste" e verde dopo.

## T5 — Store

**File:** nuovi `backend/backend/store.py`, `backend/tests/test_store.py`.

**Attività**
1. **Prima il test.** `test_store.py` importa `Store`: **rosso**, `ImportError`.
2. **`backend/backend/store.py`:**
   - `__init__(data_dir)`: crea `data_dir/runs` se manca; legge ogni `*.json` al suo interno; per ogni run con `status` non in `{completed, completed_with_failures, failed, stopped}`, lo riscrive **in memoria** come `stopped` con `error = "Interrupted: the server stopped while this run was active."` — **senza** toccare il file; un file non parsabile si scarta in silenzio (continua il ciclo, nessuna eccezione propagata);
   - `get(id)`, `list()` (ordinata per `createdAt` decrescente, confronto di stringhe come il Node);
   - `save(run, immediate=False)`: `immediate=True` scrive subito (`json.dump(..., indent=1)`); `immediate=False` pianifica la scrittura con un timer per `run['id']` (`loop.call_later(0.4, write)`), **sostituito** (non accumulato) se arriva un altro `save()` sullo stesso id prima che scatti;
   - `has(id)`.
3. **Passaggio avversario:** due `save()` consecutivi sullo stesso run entro 400 ms producono una sola scrittura su disco (non due, non zero); un `save(immediate=True)` cancella un timer pendente dello stesso run, se c'era; un `run['id']` con caratteri che richiedono attenzione nel nome del file (già vincolato a un formato sicuro altrove: qui si verifica solo che il nome del file coincida con quello che produrrebbe il Node).
4. **Verifiche:** `uv run --directory backend pytest backend/tests/test_store.py -q`.

**Commit:** `feat(backend): Store mirrors the interrupted-run rewrite and the debounced save (T5)`

**Fatto quando:** V9 e V10 verdi; il test visto rosso su "il modulo non esiste" e verde dopo.

## T6 — `/api/state`, `/api/config`, `/api/runs`: stub e reali

**File:** nuovi `backend/backend/state.py`, `backend/backend/routes/api_state.py`, `backend/tests/test_state.py`, `backend/tests/test_api_parity.py`; `backend/backend/app.py` (monta le nuove route, istanzia `Config` e `Store`); `scripts/backend/known-red.json`, `scripts/backend/red-rules.json` (tolte le righe portate).

**Attività**
1. **Prima il test, sull'app di T1–T5 (Config e Store esistono ma non sono collegati a nessuna route).** `test_state.py` chiama `GET /api/state` sull'app: **rosso**, `404` (la route non è montata). `test_api_parity.py` fa lo stesso confronto byte-per-byte fra Node e Python per `GET /api/config` (avvia entrambi i backend col lanciatore di T3): **rosso**, il lato Python risponde `404`.
2. **`backend/backend/state.py`:** `build_state(config, store, live_run)` assembla l'oggetto con due categorie di campi (§4.5 della spec):
   - **reali:** `config` (da `Config.get()`, stessa whitelist di `publicConfig` in `index.js:97-100`: `ceo, teams, staff, limits, pacing, router, combos, providers, media, skills`), `runs` (da `Store.list()`, riassunto come `runList()` del Node: `id, goal, status, mode, createdAt, finishedAt, complexity, workstreams (conteggio), tasks (conteggio), done (conteggio)`), `run` (il run attivo — sempre `None` a questa fase, nessun run può essere "attivo" prima di P5 — o l'ultimo di `Store.list()`);
   - **stub, costanti finché non arriva la loro fase:** `mode: "demo"`, `agents: []`, `router: {"mode": "demo", "providers": [], "combos": [], "recent": []}`, `media: {"ready": False, "image": [], "speech": []}`, `skills: {"count": 0, "sources": []}`, `brain: {"count": 0, "recent": []}`.
3. **`backend/backend/routes/api_state.py`:** `GET /api/state` (chiama `build_state`); `GET /api/config` e `POST /api/config` (quest'ultima valida che ogni combo in `body['combos']` abbia `models` come lista di stringhe con `/`, stesso messaggio d'errore del Node: `Combo "{name}": "models" deve essere una lista di "provider/modello"`); `GET /api/runs`; `GET /api/runs/{id}` (da `Store` — se non c'è, `404 {"error": "Run non trovato"}`).
4. **Aggiornamento della matrice (T3):** `red-rules.json` perde le righe di `GET/POST /api/config`, `GET /api/runs`, `GET /api/runs/:id` (parte Store), `GET /api/state` (come riga della matrice: esiste ed è parzialmente reale — la riga si marca "verde con stub", non rossa, perché risponde ed è conforme al contratto A1, anche se alcuni campi sono segnaposto); si rilancia `backend-parity-test.js` e si committa il `known-red.json` aggiornato.
5. **Passaggio avversario:** `public/js/main.js` legge `state.brain.recent` e `state.media` per riempire i pannelli (grep per confermare le chiavi lette): gli stub devono avere esattamente quelle chiavi, non un sottoinsieme; `POST /api/config` con `combos` malformato non deve scrivere nulla su `local.json` (verificare che il file non cambi mtime).
6. **Verifiche:** `uv run --directory backend pytest backend/tests/test_state.py backend/tests/test_api_parity.py -q`; `node scripts/backend-parity-test.js`; `npm test` invariato.

**Commit:** `feat(backend): /api/state, /api/config and /api/runs with typed stubs for the rest (T6)`

**Fatto quando:** V5, V6, V7, V8 verdi; la matrice non ha più righe rosse per queste route; i test visti rossi su "la route non esiste" e verdi dopo.

## T7 — Bus e SSE (`/api/events`)

**File:** nuovi `backend/backend/bus.py`, `backend/backend/routes/events.py`, `backend/tests/test_bus.py`, `backend/tests/test_events.py`; `backend/backend/app.py` (il lifespan chiude le code SSE allo shutdown, completando S3); `scripts/backend/known-red.json`, `scripts/backend/red-rules.json` (tolta la riga di `/api/events`).

**Attività**
1. **Prima il test.** `test_bus.py` importa `Bus`: **rosso**, `ImportError`. `test_events.py` chiama `GET /api/events`: **rosso**, `404`.
2. **`backend/backend/bus.py`:**
   - `class Bus`: `__init__(self, maxsize=1000)`; `emit(type, payload)` incrementa `self._seq`, serializza **una volta** (`json.dumps({"seq": self._seq, "type": type, "payload": payload})`), e per ogni coda registrata fa `put_nowait`; se una coda è piena, la rimuove dai registrati (si stacca, non blocca — B3) invece di sollevare;
   - `subscribe()` crea e registra una `asyncio.Queue(maxsize)`, restituisce `(queue, unsubscribe)`.
3. **`backend/backend/routes/events.py`:** `GET /api/events` → `StreamingResponse` con `media_type="text/event-stream"`; scrive subito `retry: 2000\n\n`; un generatore che fa `await asyncio.wait_for(queue.get(), timeout=15)` e, su `TimeoutError`, scrive `: ping\n\n`; si ferma quando `await request.is_disconnected()` è vero o quando il lifespan segnala la chiusura (un `asyncio.Event` condiviso, impostato nel ramo di chiusura del lifespan — completa S3).
4. **`app.py`:** solo i 17 tipi di `FORWARD` (§1.2 della spec) possono attraversare il bus da qui in avanti — a questa fase l'unico produttore reale è `POST /api/config` (T6), aggiornato per chiamare `bus.emit('config', public_config)` dopo la scrittura, come fa il Node (`index.js:323`).
5. **Passaggio avversario:** un client che non legge mai la propria coda (riempita apposta nel test) si disconnette senza che gli altri client perdano un solo frame (verificato contando i `seq` ricevuti da un secondo client concorrente); due `emit` nello stesso istante assegnano `seq` consecutivi senza buchi né duplicati (eseguire 100 `emit` da task `asyncio` concorrenti e verificare la sequenza su un client).
6. **Verifiche:** `uv run --directory backend pytest backend/tests/test_bus.py backend/tests/test_events.py -q` (V11, V12, V13); `node scripts/backend-parity-test.js`.

**Commit:** `feat(backend): sync bus fans out to per-client SSE queues; lifespan closes them on shutdown (T7)`

**Fatto quando:** V11, V12, V13 verdi; i test visti rossi su "il modulo/la route non esistono" e verdi dopo; la matrice non ha più la riga di `/api/events` tra i rossi attesi.

## T8 — Verifica finale P0–P2, confronto con Node, QA

**Obiettivo:** chiudere il ciclo con la prova che tutto P0–P2 è verde su entrambi i backend, che Node non ha nessuna regressione, e che i processi Python si chiudono senza lasciare nulla indietro.

**Attività**
1. `node scripts/backend-parity-test.js`: ogni riga P0–P2 della matrice verde; tutte le righe P3+ rosse attese con un ticket (nessun `UNEXPLAINED`).
2. `AGENT_WORLD_SERVER=node npm test` (V15): invariato rispetto a prima di questa spec — stesso tempo, stesso esito, zero regressioni. Si registra il tempo nel messaggio di commit per confronto futuro.
3. `uv run --directory backend pytest -q`: tutti i test di T1–T7 verdi in un solo giro.
4. **Confronto incrociato (V5, V6, V9, V10):** uno script temporaneo (o un test pytest dedicato, a scelta in implementazione) avvia Node e Python sulla stessa istantanea di `config/default.json` e di `data/runs/`, e confronta byte per byte (normalizzando solo l'ordine delle chiavi JSON) `GET /api/config`, `GET /api/runs`, `GET /api/runs/:id` per un run precaricato, e la forma di `GET /api/state`.
5. **Igiene dei processi (V17):** una sessione con `AGENT_WORLD_SERVER=python node scripts/temp-test.js`, poi un'uccisione a metà (`taskkill /F` sul processo `uv`/`python`) e `npm run sweep -- --dry-run`: nessun processo né cartella da spazzare. Se lo spazzino di oggi (pensato per Node ed Edge) non riconosce il processo Python, è un difetto da correggere qui, non un rischio da annotare (coerente con V17 della spec).
6. **`git diff` su `public/` vuoto** (V16): controllo esplicito, non solo per assunzione.
7. Aggiornamento di `docs/specs/04-backend-port.md` con eventuali precisazioni emerse nei ticket (come le note in corsivo di T3) e di `HANDOFF.md`.
8. **Il tuo QA:**
   - avvia a mano `uv run python -m backend` e apri `http://127.0.0.1:<porta>/` nel browser: la pagina si carica (i pannelli che dipendono da route non ancora portate restano vuoti, senza errori in console — verificare proprio quello);
   - **Ctrl+C** al processo Python mentre un client SSE è connesso (apri `/api/events` in una scheda, poi interrompi il processo nel terminale): la connessione si chiude e il processo esce in pochi secondi, senza restare in sospeso (V2).

**Commit:** `docs(T8): P0-P2 backend parity verified against Node`

**Fatto quando:** V1, V2, V5–V17 verdi o, se qualcosa non lo è, l'eccezione è motivata per iscritto nella spec; il tuo QA è superato.

---

Dopo T8: la spec si aggiorna con lo stesso dettaglio per **P3 (router "OmniRoute", provider, mock e gateway `/v1`)** prima dei suoi ticket. Poi **P4 (skill, Brain e ricerca — il punto d'aggancio del bridge Rust)**, **P5 (resto dell'engine)**, **P6 (bridge Rust con la soglia)**, **P7 (cambio di `npm start` e rimozione di `server/`)**, ciascuna con la stessa sequenza: aggiornamento della spec → tuo via libera → ticket → implementazione.
