# HANDOFF — Agent World

*Aggiornato il 2026-10-14, sera.*
- *`npm start` falliva con WinError 10048: la 4300 era tenuta dal **vecchio server Node** (`node server/index.js`, avviato il 12/10). Su richiesta dell'utente ("blocca tutti i server") sono stati fermati i 5 server di Agent World: la 4300 e quattro `python -m backend` sulle porte 4494–4497. **Non toccati:** la Claudio app (4173, 5000) e un `node server/index.js` sulla 3939, di altri progetti.*
- *Branch `fix/start-port-message` = `809e0cb`, sopra `main` e non pushato: con la porta occupata, ora un messaggio chiaro al posto del traceback (`tests/test_main.py`); nel README, i passi di avvio uno per uno. **Il working tree è su quel branch.***

*Prima (pomeriggio):* L'utente ha pushato `main` = `d290ae6`: su GitHub il README non mostrava le immagini, perché `docs/assets/*.png` non esistevano. Ora c'è `b1d7724` **su `main`, locale, NON pushato**:*
- *8 screenshot veri (`npm run screenshots` → `scripts/readme-shots.js`: missione demo al ritmo normale, 1920×1080, home temporanea così non compaiono i plugin della macchina);*
- *ogni immagine controllata a vista: nessun dato personale.*

*Per pubblicarlo serve `git push origin main` (con la finestra di Git Credential Manager).*

*Prima: **Merge fatto dall'utente in locale.** `main` = `d290ae6`, il merge `--no-ff` di `feat/spec05-rag-skiller`, con identità `agent-world-dev` e lo stesso albero testato (`f4e5a20`). **Push NON fatto**: l'utente l'ha interrotto con Ctrl+C. `main` è 10 commit avanti a `origin/main` (`8650aaa`), e `feat/spec05-rag-skiller` non è su `origin`.*

*Prima: **Spec 05 CHIUSA.** Branch `feat/spec05-rag-skiller` = `48f271e`, non pushato, pronto per il merge in `main` (fast-forward possibile; il merge `--no-ff` simulato dà lo stesso albero testato, `f4e5a20`).*

*Comandi preparati, da lanciare con il via libera dell'utente:*
- *`git checkout main`*
- *`git merge --no-ff feat/spec05-rag-skiller`*
- *`git push origin main feat/spec05-rag-skiller`*

*Prima o poi va anche cancellato `../agent-world-before-scrub.bundle`.*

*Ultimo commit `48f271e`: download esterni (`backend/backend/downloads.py`, solo per lo Skiller, D1–D4 approvate dall'utente), `test_downloads.py` (70 test, scritti prima del codice), 7 test d'integrazione in `test_skiller.py`. `npm test` verde (pytest 317 passed, 2 skipped: parità Rust). Suite browser 234/235: A10 rosso, intermittente, preesistente; l'utente ha scelto di chiudere e tenerlo come ticket **N12** (spec 05 §6). Chiavi API ruotate dall'utente (confermato il 14/10). Identità git locale `agent-world-dev`; le parole personali stanno in `.git/info/personal-words`.*

*Aggiornato il 2026-10-14, circa alle 02:30. **Spec 05: fasi 1 e 2 fatte, fase 3 fatta fino al checkpoint dell'utente.** I download esterni dello Skiller (`CUSTOM_DOWNLOAD_PATH`) **non sono implementati**: aspettano l'approvazione della logica di sicurezza (`docs/specs/05-rag-skiller.md` §5) e delle decisioni D1–D4 (§4).*

*Commit:*
- *`chore/security-audit` = `origin/chore/security-audit` = `0f810a5`: gli id dei commit nei documenti, rimappati dopo il filter-repo e pushati;*
- *branch `feat/spec05-rag-skiller` (da `0f810a5`), **non pushato**:*
  - *`fd67869` codice morto;*
  - *`9923f39` uvicorn senza `[standard]`;*
  - *`ccaae44` RAG ibrido;*
  - *`2f3a7fc` Skiller + spec 05.*

*Verifiche: `npm test` verde (pytest 240 passed, 2 skipped: la parità Rust, perché `aw_core` non è compilato); suite browser 235/235 dopo la fase 2. **A10 non è deterministico**: rosso due volte il 13/10, verde il 14/10.*

*Il codice Rust nuovo (`crc32`, `ngram_vector`, `cosine_top_k` in `aw_core`) non è compilato: manca la toolchain.*

*Le 8 chiavi di `.env` sono ancora da ruotare (lo fa l'utente).*

*Aggiornato il 2026-10-14, circa all'01:45. **History riscritta con `git filter-repo`, approvata dall'utente:***
- *autore e committer di tutti i 54 commit sono ora `agent-world-dev <dev@agent-world.invalid>`, anche come identità locale del repo (`git config` locale);*
- *`HANDOFF.md` è sparito da tutta la history;*
- *il nome dell'account è uscito da tutte le versioni della retro (il commit `docs: no account name…` è diventato vuoto ed è stato potato).*

*Prima di applicarla: prova su un clone mirror `--no-local`, alberi di ogni branch identici fra prova e repo vero, `npm run scan:secrets` pulito. Backup di tutti i ref in `../agent-world-before-scrub.bundle`: **contiene ancora i dati personali**, va cancellato dopo la verifica o tenuto offline. Mappa dei commit vecchio → nuovo in `.git/filter-repo/commit-map`.*

*Nuove punte: `main` = `feat/backend-port` = `8650aaa`, `chore/security-audit` = `96274cf`, `feat/memory-stability` = `6a980ae`, `feat/office-framing` = `0914146`, `feat/ui-overlaps` = `7102214`. Gli hash citati qui e nei documenti delle spec sono stati aggiornati con la mappa: 60 sostituzioni in 10 documenti e 31 in questo file, solo prefissi univoci di commit vecchi. Fa eccezione `4ebfc65`, il commit potato, che non ha un sostituto. **Force push fatto (01:50):** `origin` è identico ai branch locali (6 branch, compresi i nuovi `chore/security-audit` e `feat/backend-port`). Dopo il fetch, `npm run scan:secrets` è pulito anche sui ref di `origin`.*

***Resta all'utente:** ruotare le 8 chiavi di `.env`; cancellare il bundle; se vuole, chiedere a GitHub Support la pulizia della cache dei commit vecchi; il nome dell'account resta nell'URL del repo. **Fase 2 (snellimento) non ancora iniziata**: aspetta il via dell'utente.*

*Aggiornato il 2026-10-14, circa all'01:40. **Spec 05, fase 1 (sicurezza): fatta fino alla riscrittura della history, che aspetta la conferma dell'utente.** Branch `chore/security-audit`, da `main` = `8650aaa` (`main` è 10 commit avanti a `origin/main`, niente pushato):*
- *`4ebfc65` docs: tolto il nome dell'account dalla retro della spec 01;*
- *`79526f5` `scripts/secret-scan.js` (`--staged`, `--message`, `--history`), hook in `scripts/hooks/` attivati da `npm install` (`prepare`, cioè `core.hooksPath`, già impostato qui), `.gitignore` rinforzato, `secret-scan-test.js` in `npm test` (15 verifiche, viste rosse con tre mutazioni). Le parole personali si leggono da git config e da `.git/info/personal-words`, mai scritte nel repo;*
- *`5508681` `.gitattributes`: gli hook restano in LF.*

*Audit (51 commit, tutti i ref): **nessuna chiave API nella history**; `.env.example` ha sempre avuto solo `PORT=4300`. Da ripulire: (1) l'identità dell'autore con nome ed e-mail veri in tutti i 51 commit; (2) il vecchio `HANDOFF.md` (commit `33d9361`, tolto in `0914146`) con 5 percorsi assoluti, tra cui quello di un altro progetto; (3) il nome dell'account nelle versioni vecchie della retro. Tutto è su `origin`. I file per `git filter-repo` sono in `.git/info/scrub/` (`replacements.txt`, `mailmap.template`). Il nome dell'account resta comunque nell'URL del repo su GitHub.*

*⚠️ Le 8 chiavi in `.env` sono le stesse comparse in chiaro il 13/10: stanno in 3 transcript locali e in 3 file di claude-mem, e sono passate dal modello. Da ruotare (lo fa l'utente).*

*Aggiornato il 2026-10-14, circa all'01:10. **Stato reale dopo la verifica di questa sessione:***
- ***Merge di `feat/backend-port` in `main`: NON fatto.** Il classificatore dei permessi l'ha negato ("Modify Shared Resources"). Lo fa l'utente, oppure dà il permesso; poi il push, solo con il suo via libera. Il merge va fatto `--no-ff`, come per la spec 03.*
- *Su `feat/backend-port`, sopra `36947e8` (P7): `778e84d` docs, README vetrina (6 diagrammi Mermaid, tutti renderizzati senza errori con Mermaid 11.4.1; `docs/assets/README.md` elenca gli 8 screenshot attesi); `8650aaa` fix: torna `GEMINI_API_KEY=` in `.env.example` (il commit WIP `456819b` l'aveva tolta).*
- ***Verifiche:***
  - *`npm test` verde: world, boot, **pytest 205 passed**, smoke, flows, temp (97 s);*
  - *missione demo completa nel pannello (backend Python, chiavi svuotate con `demoEnv`): 17/17 task, 200 chiamate; SSE con 1269 eventi in 168 s, `seq` continuo, 0 errori, 0 riconnessioni, buco massimo durante il run 3,4 s (pacing e latenza del mock);*
  - ***suite del browser: 233/235, 2 rossi, uguali al secondo giro (`--only hygiene,run`).***
    - *H6, "sweep at a start ≤ 2 s": 2663 e 2247 ms. I 17 processi chiusi sono l'orfano creato apposta dalla fase `hygiene`. Gli strumenti (`scripts/browser/`, `scripts/lib/temp.js`) non sono cambiati nella spec 04: è un limite di tempo sulla macchina carica di oggi, non una regressione del backend.*
    - *A10, "sub-agents work at their bay seat": riproducibile, e sempre su `research-sub3` (`workingMax` 2,29 e 2,66 contro 0,5; gli altri 15 sub-agenti a 0). Era verde su Node (T2 della spec 03).*
  - ***Pista per A10:** `backend/backend/team.py:73` documenta una deviazione voluta da Node. Con `spawn_limit > 0` i sub-agenti prendono il lavoro PRIMA dei worker liberi (in Node: prima i worker, poi i sub-agenti). È fissata da `test_team.py`, e si vede anche nello smoke (`research-sub4` con `maxSubAgents` 3). Contraddice il requisito "UX identica" della spec 04: decide l'utente, con un ticket.*
- ***Scostamenti trovati, da ticket:***
  - *(a) le cartelle dei run ora stanno in `data/workspace/` (in Node erano in `workspace/`): `app.py` fa `home = data_home()` → `<home>/data`, poi `workspace_root = home / "workspace"`. I run vecchi restano visibili, perché il JSON salva il percorso assoluto;*
  - *(b) `Brain.add` chiama ancora `reindex()`, cioè ricostruisce tutto l'indice a ogni nota: di incrementale c'è solo la media delle lunghezze. Il punto caldo misurato allo step 1 (circa 424 ms a 5000 note in Python) resta;*
  - *(c) nel codice non esistono chunking semantico, embedding né similarità del coseno: il README lo dice e mette il recupero ibrido come proposta.*
- *Le chiavi API vere ora stanno in `.env` (8 chiavi), non più in `.env.example`: `npm start` va in modalità LIVE e costa. Per le prove visive si usa un wrapper che passa da `demoEnv()` (come i test).*

*Versione precedente (2026-10-13, notte, seconda revisione). **Spec 04 "Porting del backend" COMPLETATA (P0–P7)**: il backend è ora FastAPI (Python 3.13, uv, uvicorn) con bridge Rust pronto ma in fallback (`crates/aw_core`, PyO3: entra solo se batte il Python di almeno 5×, D1; toolchain assente su questa macchina, D5). `server/` (Node) **rimossa** in P7 dopo QA end-to-end verde (boot, smoke, flows, world, temp). Suite Python 203 test verdi. `npm start` avvia il backend Python (`cd backend && uv run python -m backend`).*

*Cronologia commit su `feat/backend-port` (da `main` = `0c20a69`): `f1b7b22` docs spec 04 e ticket P0–P2 → `500ebb2` P0–P2 (scheletro, config/store, SSE) → `9901d29` P3 (router OmniRoute, provider, mock, `/v1`) → `46098ef` P4 (Bm25, Brain, SkillLibrary) → `456819b` WIP P0/P1 (msg fuorviante: era molto più avanti) → `84eb06d` P5 (engine completo + route run/chat/media) → `b26db52` P6 (seam BM25 con soglia 5×) → chiusura P7.*

*Note di P7 (dettagli nei commit):*
- *`backend-launcher.js` lancia solo il venv Python (`uv run` orfana uvicorn su Windows, T1/R1); `smoke.js`/`flows-test.js`/`browser-test.js` lo usano; `router-test.js` eliminato (scenari coperti dalla suite Python).*
- ***Bug preesistente in demo mode***: gli script cancellavano le `*_API_KEY` dall'ambiente, ma `load_env` rilegge da `.env` le chiavi ASSENTI → i run "demo" andavano live se le chiavi stanno solo in `.env`. Fix: `demoEnv()` nel launcher blanka anche i `keyEnv` dei config. Due run di QA pre-fix hanno consumato API reali (~900k token in ingresso, soprattutto Anthropic).*
- ***Fix `team.release`***: salta i waiter il cui future è già cancellato (in Node l'abort rimuove il waiter in modo sincrono, in asyncio la cancellazione arriva un giro dopo: senza il guard un agente restava busy per sempre dopo `stop()` — visto: vera, qa). Test di regressione in `test_team.py`.*
- ***Fix `__main__.py`***: la riga "ready" si stampa solo dopo il bind della porta (lo smoke leggeva il marker e faceva fetch prima del bind → ECONNREFUSED).*
- *`.claude/launch.json`: runtime `uv run --directory backend python -m backend`; `.claude/preview.env` non viene più letto (PORT arriva dal pannello o da `.env`).*

*Per compilare il bridge Rust (quando ci sarà la toolchain): `winget install Rustlang.Rustup` + MSVC Build Tools, poi `cd backend && uv run maturin develop --manifest-path ../crates/aw_core/Cargo.toml`, verifica con `uv run pytest tests/test_search_rust.py` e `uv run python bench/bm25_bench.py`.*

---

*Versione precedente (2026-10-13, notte): **Spec 03 congelata dopo T2**, **unita in `main`**; push di `feat/memory-stability` e di `main` fatti (D8). **Spec 04 "Porting del backend": step 1 (Plan) approvato (D1–D8); step 2 (To-spec) e step 3 (To-tickets) consegnati e commessi** — `docs/specs/04-backend-port.md` e `.tickets.md`, sul branch `feat/backend-port` (commit `f1b7b22`, non pushato). Ticket T1–T8 (P0, P1, P2) pronti: **in attesa del via libera dell'utente prima di avviare lo step 4 (Implement)**, non ancora toccato nessun file di codice.*

*Branch attuale: `feat/backend-port`, da `main` = `origin/main` = `0c20a69`. Working tree pulito, salvo `.env.example` (vedi l'avviso in testa). `main` contiene anche i 4 commit della spec 03 (merge `ort`, niente fast-forward):*
- *`4172385` docs: spec e ticket della spec 03;*
- *`251fd4e` **T1** (N9): `scripts/browser/headless.js`, `scripts/lib/temp.js`, `scripts/browser/probe.js`, fase `hygiene` (H1–H6), `npm run sweep`;*
- *`4c80d97` **T2** (N7): smoke, flows e router con cartelle di proprietà, `scripts/temp-test.js` in `npm test`;*
- *`06793f9` **pulizia di chiusura**: via la fonte `../Claudio/claudio-skills` dallo Skill Hub (la rinomina in "claudia" toccava un altro repo: l'utente la rifà dalla UI); nuova chiave `skills.repos` con `https://github.com/vercel-labs/skills`, clonata al primo avvio in `skills/vendor/` (passando da `skills/vendor/.incoming`); `skills/vendor/` ignorato da git; test in `router-test.js` (visto rosso senza lo skip di `.incoming`). `npm test` verde in 35 s; skill indicizzate 81 → 49 (−36 di Claudio, +3 di vercel-labs). Suite browser non rilanciata: nessun cubo, evento o `fx` toccato.*
- *`6a980ae` docs: nota "congelata" in testa a `03-memory-stability.md` e `.tickets.md` (`.env.example` non toccato).*

*Pulizia dei percorsi (2026-10-13): nei documenti tracciati non c'era nessun percorso assoluto locale; gli unici erano in questo file e sono diventati relativi. Resta assoluto solo `.claude/preview.env` (configurazione locale, non documentazione: `AGENT_WORLD_HOME` deve esistere davvero).*

*Processi node da non toccare, visti il 2026-10-13: porta 4300 (server dell'utente), 3939 (un altro progetto), 4310 (server di prova di un'altra sessione).*

*⚠️ **`.env.example` (tracciato da git) contiene chiavi API vere nel working tree**, non scritte da Claude e mai committate: non va mai aggiunto a un commit (usare sempre `git add` con i percorsi espliciti). Detto all'utente il 2026-10-13; la decisione (spostarle in `.env`, che è ignorato, e valutare la rotazione) è sua.*

## 1. Stato

- **Repo:** questa cartella (`agent-world/`), remote `origin` su GitHub (l'indirizzo è in `git remote -v`; qui non si scrive il nome dell'account). Da non confondere con `../Claudio`, che è un altro repo (non va toccato: la sua cartella `claudio-skills` non è più una fonte dello Skill Hub).
- **Branch:** `feat/backend-port`, da `main` = `origin/main` = `0c20a69` (spec 03 unita e congelata, spec 02). Un commit sopra: `f1b7b22` (docs: spec 04 e ticket P0–P2), non pushato.
- **Documenti della spec 03 (congelata dopo T2, in `main`):** `docs/specs/03-memory-stability.md` e `.tickets.md`, con la nota "congelata" in testa a entrambi (commit `6a980ae`).
- **Documenti della spec 04 (commit `f1b7b22`):**
  - `docs/specs/04-backend-port.md` (step 2): contesto misurato (route, SSE, punto caldo del Brain), matrice delle route per fase, requisiti dettagliati S/F/H (P0), C/R/A (P1), B (P2), design tecnico, V1–V17, decisioni D1–D8, rischi R1–R5. P3–P7 restano al livello di piano (sotto).
  - `docs/specs/04-backend-port.tickets.md` (step 3): T1–T8, nell'ordine T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8. T1 scheletro `backend/` (FastAPI, uv), T2 file statici e traversal, T3 lanciatore parametrico `AGENT_WORLD_SERVER` e `scripts/backend-parity-test.js` (matrice delle route, `scripts/backend/known-red.json`), T4 Config, T5 Store, T6 `/api/state`+`/api/config`+`/api/runs` con gli stub tipizzati, T7 bus e SSE, T8 verifica finale e QA. Ogni ticket: test prima (visto rosso), poi il codice, un commit atomico. Precisazione in T3: `smoke.js`/`flows-test.js` non si parametrizzano ancora (dipendono da `POST /api/runs`, P5).
  - **Prossimo passo:** via libera dell'utente, poi step 4 (Implement) a partire da T1. Nessun file di codice toccato finora su questo branch.
- **Documenti della spec 02:** `docs/specs/02-ui-overlaps.md` (contesto misurato, requisiti P1–P6 ed E1–E7, matrici ingresso × stato, design, criteri V1–V13), `02-ui-overlaps.tickets.md` (T0–T5), `02-ui-overlaps.report.md` ("Prima" e "Dopo"), `02-ui-overlaps.review.md` e `02-ui-overlaps.retro.md`. La storia sta lì, non qui.
- **Spec 01 chiusa e unita in `main`:** i documenti sono in `docs/specs/01-office-framing.*`, compresa la retro (`01-office-framing.retro.md`), le cui lezioni valgono per questo ciclo.
- **Questo file è tracciato su `main`** (dal 16/10/2026, decisione dell'utente): non è più in `.gitignore`, e `scripts/secret-scan.js` non ne blocca più il nome, ma ne scansiona il contenuto come per ogni altro file (chiavi, percorsi assoluti, parole personali). *Prima era solo locale.*
  - *Superato:* l'avviso sul checkout dei commit precedenti a `0914146` valeva finché il file era solo locale. Ora che è tracciato, git lo riporta tornando avanti; le modifiche non committate vanno committate o messe da parte prima del checkout, come per ogni file.
- **Push su Windows:** `git push` apre la finestra "Select an account" di Git Credential Manager e aspetta che l'utente scelga l'account. Si lancia in background e si avvisa l'utente.

## 2. Spec 04 — Porting del backend: piano (step 1), spec (step 2) e ticket (step 3), tutti approvati o consegnati

**Obiettivo dell'utente:** il server passa da Node a FastAPI (API, routing agentico asincrono "OmniRoute", SSE) più Rust per i calcoli pesanti. Restano identici l'esperienza utente, il sistema multi-agente e il front-end three.js: stesse route, stesso JSON, stessi eventi SSE.

**Contesto misurato il 2026-10-13** (script in scratchpad, non nel repo):
- `server/`: circa 3550 righe, nessuna dipendenza npm (three serve solo al front-end); un processo, stato in memoria (run attivi, chat, client SSE), file in `data/`.
- 20 route `/api/*`, più `/v1/models`, `/v1/chat/completions`, i file statici (`public/`, `/vendor/three*` da `node_modules`) e `/preview/:run/`.
- SSE: un flusso `/api/events` con 17 tipi di evento, frame `data: {"seq","type","payload"}`, `retry: 2000`, `: ping` ogni 15 s, nessun replay. Alla riconnessione il client rilegge `/api/state` (`public/js/main.js:1032`).
- **Nessun calcolo pesante nel backend:** reindicizzazione delle skill 116–286 ms (quasi tutto filesystem), ricerca 0,01 ms. Il pathfinding A* e la simulazione 3D girano nel browser (`public/js/world/nav.js`, `world.js`); il server trasmette solo gli stati degli agenti.
- **L'unico punto caldo:** `Brain.add` ricostruisce tutto l'indice BM25, e `Bm25.add` ricalcola `avgLen` su tutti i documenti (O(N²)). Al tetto di 5000 note: 131 ms per `remember` in Node, 704 ms con un porting Python riga per riga (424 con `avgLen` incrementale). Bloccherebbe il loop di asyncio, quindi anche l'SSE.
- **Macchina:** Python 3.13 (versione del Microsoft Store) e uv 0.11.29; **nessun** rustc, cargo o maturin, **nessun** MSVC Build Tools. Il `link.exe` nel PATH è quello di Git, che coprirebbe il linker MSVC.

**Piano in breve:**
- `backend/` (progetto uv, FastAPI, uvicorn con un solo processo, httpx) cresce accanto a `server/`. Node resta il backend predefinito fino alla parità.
- Gli stessi file e le stesse variabili d'ambiente (`data/`, `config/*.json`, `.env`, `AGENT_WORLD_HOME`, `AGENT_WORLD_FAST`, `AGENT_WORLD_ALLOW_SHELL`, `AGENT_WORLD_API_KEY`, `PORT`): si passa da un backend all'altro sugli stessi dati e si torna indietro.
- **SSE:** bus sincrono (`emit` assegna `seq` e serializza una volta) → una coda `asyncio.Queue` limitata per client → `StreamingResponse` con `retry: 2000` e `: ping` a 15 s. Un client troppo lento viene staccato: si riconnette e rilegge `/api/state`. Il lifespan chiude i flussi allo spegnimento (sennò uvicorn aspetta le connessioni SSE a Ctrl+C) e salva i run.
- **Bridge Rust:** crate `crates/aw_core` con PyO3 e maturin (abi3), modulo nativo nello stesso processo. Primo modulo: BM25 e tokenizzatore. Rilascia il GIL e si chiama con `asyncio.to_thread`. C'è sempre un fallback in Python puro con la stessa interfaccia, e un test di parità sui token e sulla classifica (corpus d'oro generato dal JS di oggi). **Soglia:** il Rust entra solo se batte il Python ottimizzato di almeno 5× sul corpus misurato. La correzione dell'algoritmo (indice incrementale) si fa comunque.
- **I test fanno da oracolo:** smoke, flows, `temp-test` e il runner del browser scelgono il server con una variabile (`AGENT_WORLD_SERVER`). Le verifiche delle route non ancora portate si segnano rosse con il ticket che le porta (`known-red.json`). `router-test` passa a pytest insieme ai moduli; `world-test` resta Node (è front-end).
- **Fasi (diventano ticket allo step 3):** P0 scheletro, file statici e test parametrizzati → P1 config, store e `/api/state` → P2 bus e SSE → P3 router "OmniRoute", provider, mock e gateway `/v1` → P4 skill, Brain e ricerca → P5 engine (run, tasker, team, tools, web, media) → P6 bridge Rust con la soglia → P7 cambio di `npm start`, suite completa verde su Python, rimozione di `server/` dopo il QA dell'utente.

**Decisioni aperte (con il consiglio):**

| # | Domanda | Consiglio |
|---|---|---|
| D1 | Quanto Rust | A: bridge subito, primo modulo BM25, fallback e soglia. Le alternative sono B (Rust rimandato a quando c'è un punto caldo misurato) e C (anche spazio e pathfinding sul server: cambia il contratto del front-end, sconsigliato) |
| D2 | Bridge | PyO3 nello stesso processo; il microservizio interno porta IPC e un processo in più da avviare e chiudere su Windows (i problemi della spec 03) |
| D3 | Strategia | costruzione in parallelo e cambio alla parità; il proxy "strangler" è scomodo, perché bus, SSE e run attivi sono stato condiviso |
| D4 | Python | CPython 3.13 gestito da uv, non quello del Microsoft Store |
| D5 | Toolchain Rust | rustup (target MSVC) e Visual Studio Build Tools C++ (alcuni GB): li installa l'utente, oppure si preparano i comandi; fino ad allora gira il fallback |
| D6 | Node dopo il cambio | solo per three e per gli strumenti di test; in alternativa, three copiato in `public/vendor` |
| D7 | Streaming di `/v1` | parità (un solo chunk, come oggi); lo streaming vero dei token è un ticket futuro |
| D8 | Branch | unire `feat/memory-stability` (T1, T2, pulizia: verdi) in `main` e partire da lì con `feat/backend-port`; serve il via libera al push |

## 3. Prossimo passo

1. **Via libera dell'utente ai ticket T1–T8** (step 3, già commesso in `f1b7b22`): poi si parte con lo step 4 (Implement) da T1, un ticket alla volta, fermandosi dopo ciascuno per il feedback. P3–P7 restano nel piano sotto, da dettagliare con un aggiornamento della spec prima dei loro ticket.
2. **Ogni sonda nuova** usa `scripts/browser/headless.js` (`launch`, `close`), mai una copia dell'avvio; dopo un giro interrotto, `npm run sweep` (con `--dry-run` per vedere prima).
3. **Stato delle verifiche su questo branch (dopo `06793f9`):** `npm test` verde in 35 s. La suite completa (235 verifiche, 290 s) è stata verde a T2, e la pulizia non tocca il browser. In `%TEMP%` c'è solo `agent-world-preview`. `scripts/browser/known-red.json` è vuoto (`{}`).
4. **Push:** nella finestra di Git Credential Manager va scelto l'account proprietario del repo (quello nell'indirizzo di `origin`); con l'altro account GitHub risponde 403.

## 4. Ticket futuri, fuori da questa spec

- **Spec 03 congelata, nel backlog:** T3–T10 (baseline dell'app con le fasi `memory`, `late` e `soak`; **N5** perdite di memoria GPU; **N2** client in ritardo e sessioni lunghe). Ticket e decisioni D7–D11 restano validi in `docs/specs/03-memory-stability.*`. Sono quasi tutti di front-end, quindi il porting non li tocca; il bus SSE della spec 04 ne eredita i casi (client lento, riconnessione). N9 e N7 sono fatti (T1, T2).
- **Skill Hub, dopo la pulizia:** l'utente ri-aggiunge dalla UI la fonte "claudia" (la rinomina di `../Claudio/claudio-skills` non è stata fatta: era un altro repo). `vercel-labs/skills` è il repo della CLI `npx skills`: dà 3 skill, `find-skills` più `pr-labeling` e `triage`, che sono flussi interni di quel repo (in `.factory/`). La raccolta vera di skill di Vercel è `vercel-labs/agent-skills`: da proporre, senza aggiungerla da soli.
- **N10 — Client lento senza pause** (D10 della spec 03): con frame oltre i 50 ms il mondo resta indietro (al 78% dell'orologio nella missione 1 della spec) e recupera solo con la spinta delle code. Proposta da valutare: riallineare anche quando l'arretrato supera una soglia di tempo di mondo. Il `soak` di T10 ne riporta la misura.
- **N11 — Chiavi negli script di test** (trovato in T2 della spec 03): `smoke.js` e `flows-test.js` tolgono le variabili `*_API_KEY` con `delete`, quindi `server/env.js` le riempirebbe da `.env` se ce ne fossero; il runner le imposta a `""`. Oggi `.env` imposta solo `PORT`.
- **N8 — Pinch su touch screen sopra le etichette** (dalla review della spec 02; registrato per decisione dell'utente): le etichette prendono i puntatori, quindi un pinch con due dita che inizia sopra un'etichetta non arriva al canvas. Ipotesi per costruzione, non misurata.
- **Backlog precedente alla spec 01:**
  - feedback sullo stile v3 (personaggi, arredi, angolo di camera);
  - repo e skill annunciate (scheda Skill oppure `POST /api/skills/repo`);
  - chiarire "Claude setup";
  - test live con modelli veri (serve una chiave in `.env`);
  - nomi dei modelli in `config/default.json`;
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

**Lezioni della retro della spec 01, da applicare:**
1. Il runner headless nasce a T0. Il pannello browser dell'app serve solo per guardare.
2. Le attese d'interazione si scrivono dal punto di vista dell'utente, con la matrice ingresso × stato nella spec; i nomi dell'API restano ai ticket.
3. Quando un ticket cambia la semantica di una funzione, prima del commit si fa un passaggio avversario: tutti i chiamanti (grep), "e se succede durante un'animazione?", "e se la precondizione è diversa?".
4. Un limite noto entra nel report solo con il caso peggiore misurato.
5. Verifiche a livelli:
   - `--only checks` (o le fasi nuove) per i ritocchi;
   - la suite completa quando cambiano cubi, eventi o `fx`, e sempre a fine step;
   - niente browser per i commit di soli documenti.
6. A fine suite, se restano processi Edge con `agent-world-profile` la suite fallisce (T0).
7. Questo file tiene stato, decisioni, prossimi passi e regole; la storia sta nei documenti della spec.
8. Profondità proporzionata al rischio, e un riassunto di 5 righe in testa ai documenti lunghi.

## 6. Contesto tecnico

**Il progetto.** App multi-agente propria:
- una CEO pianifica;
- i team lead fanno da task manager;
- worker e sub-agenti lavorano in loop fino al QA;
- c'è un router LLM integrato;
- un ufficio 3D isometrico in three.js mostra il workflow.

**Architettura:**
- server Node senza dipendenze: HTTP, SSE su `/api/events`, gateway `/v1/*`;
- persistenza su file in `data/` e `workspace/`, spostabile con `AGENT_WORLD_HOME`;
- configurazione in `config/default.json` più `config/local.json`;
- Skill Hub (`server/engine/skills.js`): `skills.sources` sono cartelle da indicizzare, `skills.repos` sono repo GitHub predefinite, clonate in `skills/vendor/` all'avvio se mancano (via `skills/vendor/.incoming`, che l'indicizzatore salta). `skills/vendor/` è ignorato da git;
- front-end senza build: `three@0.186.1` da `/vendor/three`;
- `public/js/main.js`: UI, pannelli, schede, `measureInsets()` più un `ResizeObserver` che chiama `world.setInsets()`;
- `public/css/app.css`: layout fisso, media query a 1250 e 900 px;
- 3D in `public/js/world/`:
  - `world.js`: eventi, camera, cubi, etichette in `#labels`;
  - `framing.js`: inquadratura, limiti di zoom, `scaleAt`;
  - `office.js`: layout e `ENVELOPE`;
  - `fx.js`: effetti;
  - `character.js`, `nav.js`, `geo.js`.

**Camera, in breve** (dettagli nella spec 01):
- l'ufficio è inquadrato nell'area lasciata libera dagli ingombri;
- `autoFrame`: in automatico i pannelli riadattano la vista, le azioni dell'utente la rendono manuale, ⌂ la riporta in automatico;
- zoom effettivo per le etichette = `REF / (unitsPerPx / zoom)`, con `REF` = 62/1920; la classe `far` scatta sotto 0,55 e nasconde le etichette dei worker inattivi.

**Ambiente:**
- Windows 11, Node v24.16.0: minimo 20.10 per l'app, 22 per il runner;
- per la spec 04: Python 3.13 del Microsoft Store e uv 0.11.29; niente Rust (rustc, cargo, maturin) e niente MSVC Build Tools; il `link.exe` nel PATH è quello di Git (visto il 2026-10-13);
- modalità DEMO, perché non c'è nessuna chiave;
- la **porta 4300** è del server dell'utente: **non toccarla**.

```sh
npm test                                     # world-test + router-test + smoke + flows-test + temp-test (~35 s)
npm run test:browser                         # runner headless, 235/235 (~5 min, missione inclusa)
node scripts/browser-test.js --only checks   # A6, A7, A8 della spec 01 (~1 min)
node scripts/browser-test.js --only hygiene  # H1-H6 della spec 03 (~45 s, con le sonde vere)
node scripts/browser-test.js --skip-run      # senza la missione
node scripts/browser-test.js --shots DIR --json FILE --port N
npm run sweep -- --dry-run                   # cosa lascerebbero gli strumenti uccisi (--legacy: i nomi vecchi)
```

**Runner del browser:**
- server demo proprio sulla porta 4397, Edge o Chrome headless via DevTools; il browser viene da `scripts/browser/headless.js`, le cartelle (home `agent-world-browser-<pid>-*`, profilo `agent-world-profile-<pid>-*`) da `scripts/lib/temp.js`;
- fasi `hygiene`, `views`, `checks`, `cubes`, `input`, `overlaps`, `labels`, `run`; script lato pagina in `scripts/browser/`, con `lib.js` per primo (`headless.js` e `probe.js` sono moduli Node, non iniettati); rossi attesi in `known-red.json`; a fine suite fallisce se restano processi del browser con il proprio profilo o le sue cartelle;
- all'avvio spazza i processi e le cartelle degli strumenti morti; Ctrl+C chiude browser e server e rimuove le cartelle (exit 130);
- `Emulation.setDeviceMetricsOverride` cambia il viewport, quindi le media query si possono provare;
- legge gli script all'avvio: modificarli mentre gira è sicuro, modificare `public/` no.

**Lezioni sugli strumenti:**
- **Chiudere Edge su Windows:** si chiude via DevTools (`Browser.close`), e l'albero si uccide solo se risponde ancora. Per controllare: processi `msedge.exe` con `agent-world-profile` nella riga di comando.
- **Uccidere node su Windows** (misurato nella spec 03, §1.2): nessun modo esterno (`taskkill`, `child.kill`, `timeout` della shell) esegue i gestori; `timeout -s INT` non chiude nemmeno il processo. Edge sopravvive anche a `taskkill /T` su node. Per questo esiste lo spazzino.
- **File con CRLF:** `scripts/browser-test.js` e `public/js/world/world.js` hanno fine riga CRLF: gli script che li modificano devono normalizzare e ripristinare.
- **Il pannello browser dell'app:** è largo circa 476 px e spesso nascosto, quindi niente rAF né `ResizeObserver`, e il roster non viene disegnato.
  - `resize_window` emula 1920×1080, 1200, 1000 o 800 px, e il CSS segue.
  - Le misure 3D si fanno con gli helper di `scripts/browser/lib.js` (resize e insets a mano, pompa a 60 fps).
- **Atomicità dei commit:** `git stash push -- <file>` mette da parte i test della correzione successiva.

**Server di prova per il pannello dell'app:**
- `.claude/launch.json`, configurazione `agent-world-preview`, porta 4310 con `autoPort: true`;
- il file env è ora `.claude/preview.env` (azione 7 della retro, fatta il 2026-10-13): `PORT=4310`, `AGENT_WORLD_HOME` = `%TEMP%/agent-world-preview` (nel file il percorso è assoluto, perché la cartella deve esistere davvero). Non dipende più dalla sessione;
- il 2026-10-13 la 4310 era occupata dal server di un'altra chat, quindi il pannello ha assegnato un'altra porta (19382). Con `autoPort` va bene così.

**Debug:**
- `window.agentWorld` espone `camera`, `controls`, `view`, `insets`, `autoFrame`, `resetView()`, `moveCamera()`, `screenScale()`, `centreLens()`, `footprint()`, `regrab()`, `fx`, `cubes`, `actors`, `labels`, `roomLabels` e `layout`;
- API: `GET /api/state`, `POST /api/runs`, `GET /api/runs/:id`.

## 7. Bug noti e limiti

- **Ticket aperti fuori da questa spec:** N8, N10, N11 (sezione 4).
- **Limiti accettati:**
  - la rotella sopra un'etichetta non zooma, perché le etichette ricevono i puntatori per il clic: **si corregge in T4 della spec 02** (D7);
  - durante un resize ogni frame disegna fino a 3 volte.
- **Ancora aperti, da prima della spec 01:**
  - scelta delle skill in demo rumorosa;
  - un solo run attivo alla volta;
  - chat salvata solo in memoria;
  - microfono non funzionante nel pannello dell'app;
  - `run.answer` accetta solo elementi `open`;
  - workstream di servizio rimappati su `dev`;
  - run v1 gestiti in parte.
- **claude-mem:** l'observer risulta disconnesso dall'11/10 ("signed out"); serve `/login`. Fa fede questo file. La lista `work_state` `sdd-p3-memory-stability` è stata chiusa il 2026-10-13, con la spec 03 congelata.



## Stato al 15/10/2026
- main: spec 06 (lingua globale) chiusa e in merge con la PR #1
- PR #1 (claude/charming-thompson-mv8ucu -> main): verde su Windows

### Completate
- **Spec 06, multilingua:** en (default), it, es, fr, de. UI, voce, agenti e messaggi SSE nella lingua scelta; ui.language in config/local.json; inglese di default in config/default.json. Dettagli: docs/specs/06-language.md §8.
- **Spec 07, sicurezza:** S1 CSRF e DNS rebinding (backend/security.py, AGENT_WORLD_ALLOWED_HOSTS per la LAN); S2 anteprima in sandbox; S3 niente SSRF in web_fetch; S4 anti-clickjacking; S5 token /v1 a tempo costante. Dettagli: docs/specs/07-security.md.
- **Bug A10 (N12), chiuso:** world.js applica thinking/tool solo all'arrivo del sub-agente al posto (passo `arrival`); test a clock fisso in scripts/browser/sub-seat.js. Dettagli: docs/specs/05-rag-skiller.md §6.

### Ticket aperti
- N13: errori HTTP ancora in italiano.
- N14: il simulatore demo (router/mock.py) parla solo italiano: con l'inglese di default si nota. **Prossimo, dopo N15.**
- N15: alcuni test (test_state.py, test_events.py) scrivono il vero config/local.json. **Prossimo.**
- N16: test che passano solo su Windows (percorsi con `\`, temp-test C3) e launcher dei test solo per Windows.

### Prossimi passi
1. Merge della PR #1.
2. N15: config isolata in una cartella temporanea per quei test, più un test di guardia.
3. N14: il mock segue la lingua del run.


## Stato al 16/10/2026
- main = `2e55864`: PR #1–#4 unite (spec 06 con il fix del README, N15, N14, N16).
- Branch `claude/charming-thompson-mv8ucu`: spec 08, ripartito da `main`, PR #5 verso `main` aperta.
- Questo file ora è tracciato (commit `891c264` dell'utente). Allineate le regole: fuori da `.gitignore`, nome non più bloccato da `secret-scan.js`, contenuto scansionato come gli altri file (test in `scripts/secret-scan-test.js`).

### Completate
- **N14:** il simulatore demo parla la lingua della run (`router/mock_texts.py`, cinque tabelle); senza lingua, l'inglese.
- **N15:** i test non leggono né scrivono più `config/local.json`, `data/` e `skills/vendor/` dell'utente (`AGENT_WORLD_LOCAL_CONFIG`, `AGENT_WORLD_SKILL_REPOS=0`, guardia in `conftest.py`).
- **N16:** una regola dei percorsi uguale su ogni sistema (`backend/paths.py`: `\` separa, `:` e NUL rifiutati); `hardKill()` per tutti gli script; il server di test muore con il suo script (`spawnBackend()`, `AGENT_WORLD_EXIT_WITH_PARENT`); launcher con `.venv/bin/python` fuori da Windows. `npm test` verde anche su Linux.
- **Spec 08, router, RAG e media** (dettagli: `docs/specs/08-router-rag-media.md`):
  - **Errori letti per causa.** Credito finito (402, `insufficient_quota`…) = provider fuori 6 h; un limite al minuto è solo una pausa; 404 = modello in blacklist e alias provati subito (`gemini-2.5-pro` → `gemini-3.1-pro-preview` → `gemini-2.5-flash`).
  - **Cascata** `frontier → smart → fast → free → local`, poi il simulatore come emergenza visibile (messaggio nella run, `usage.emergencies`). Il pulsante di test e il gateway `/v1` non ricevono risposte simulate.
  - **Provider nuovi:** Together, Fireworks, SambaNova, Cohere, Hugging Face, `localopenai` (`LOCAL_OPENAI_URL`).
    - GitHub Models non c'è: ritirato da GitHub il 30/07/2026.
    - I modelli ritirati sono alias, non combo.
  - **Combo** `free` e `code`; ogni combo finisce con modelli gratuiti. **Ruoli:** CEO e QA su frontier, Sviluppo su code, lead su smart, sub-agenti su fast.
  - **Profiler** (`router/profiler.py`): parametri, famiglia, contesto, gratuità e tier di ogni modello. Scoperta da `/models` dei server locali e dei `:free` di OpenRouter (`AGENT_WORLD_DISCOVER=0` nei test).
  - **RAG su misura del modello:**
    - completo per i modelli grandi;
    - compatto per quelli veloci, gratuiti o locali: top-2 passaggi delle skill, note brevi, contratto JSON;
    - memoria della run condivisa tra worker e sub-agenti, aggiornata a ogni revisione e a ogni cambio di modello;
    - riparazione delle risposte JSON dei modelli piccoli.
  - **Media sempre reali in LIVE.** Voce: cloud → edge-tts → voce del sistema (SAPI, `say`, `espeak-ng`) → jingle. Immagini: cloud → generatore locale (Pollinations resta opt-in).
    - edge-tts è una dipendenza del backend (`pyproject.toml`, `uv.lock`): `npm start` lo installa da solo, e in LIVE non va attivato. Nei test l'import è bloccato (`conftest.py`).
    - Conversione WAV→MP3 con ffmpeg.
    - `write_file` rifiuta i file media.
    - Il QA vede la durata degli audio.
    - Gli embedding saltano il provider senza credito.
  - **Verifiche (Linux):** pytest 629 passati, 3 saltati; `npm test` verde; browser `language` e missione completa (A10) `ALL OK`.

### Ticket aperti
- N13: errori HTTP ancora in italiano.

### Da verificare su Windows
- La voce in una run LIVE senza credito OpenAI ed ElevenLabs: deve parlare edge-tts, senza `uv add` (lo installa `npm start`). Qui il proxy blocca il servizio di Microsoft: ho verificato l'interfaccia nel sorgente, non una sintesi reale.
- Senza rete, o con `media.providers.edgetts.enabled: false`, la voce di sistema (SAPI): qui l'ho provata solo con un motore finto.
- La scoperta dei modelli con Ollama o LM Studio attivi.

### Prossimi passi
1. Review e merge della PR della spec 08.
2. Le verifiche su Windows qui sopra.
3. N13.
