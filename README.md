# Agent World

**Un'azienda di agenti AI che puoi guardare mentre lavora.** Scrivi una missione: la CEO la divide tra i team, i lead la scompongono, lo Skill Hub assegna le skill, il Prompt Lab affina i brief, worker e sub-agenti lavorano in loop finché il QA non approva. Tutto succede dal vivo in un ufficio 3D isometrico.

![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.143-009688?logo=fastapi&logoColor=white)
![Rust](https://img.shields.io/badge/Rust-PyO3%200.24-B7410E?logo=rust&logoColor=white)
![three.js](https://img.shields.io/badge/three.js-0.186.1-000000?logo=threedotjs&logoColor=white)

![L'ufficio 3D durante una missione](docs/assets/office-3d.png)

- **Nessun servizio esterno da installare.** Router dei modelli, orchestrazione, skill, memoria e mondo 3D stanno tutti in questa cartella.
- **Backend ibrido.** FastAPI (Python 3.13) dirige il lavoro; Rust (PyO3) è un acceleratore opzionale per la ricerca BM25.
- **Front-end senza build.** three.js servito così com'è; gli eventi arrivano dal server in streaming (SSE).
- **Modalità demo.** Senza chiavi API un simulatore interpreta ogni ruolo, e vedi l'intero flusso senza spendere nulla.

---

## Indice

1. [Screenshot](#screenshot)
2. [Avvio rapido](#avvio-rapido)
3. [Architettura ibrida](#architettura-ibrida)
4. [Streaming in tempo reale (SSE)](#streaming-in-tempo-reale-sse)
5. [Il bridge Python ↔ Rust](#il-bridge-python--rust)
6. [Agenti, sub-agenti e utility](#agenti-sub-agenti-e-utility)
7. [Memoria e recupero (RAG)](#memoria-e-recupero-rag)
8. [Il router OmniRoute](#il-router-omniroute)
9. [File, dialogo e ripresa](#file-dialogo-e-ripresa)
10. [Tech stack](#tech-stack)
11. [Lingue supportate](#lingue-supportate)
12. [Configurazione](#configurazione)
13. [Sicurezza](#sicurezza)
14. [Test](#test)
15. [Struttura del repository](#struttura-del-repository)

---

## Screenshot

Sono catture vere dell'app in modalità demo, a 1920×1080, durante una missione. Si rigenerano con `npm run screenshots` (vedi [`docs/assets/README.md`](docs/assets/README.md)).

| | |
|---|---|
| ![Ufficio 3D, vista completa](docs/assets/office-3d.png) | ![Una missione in corso, scheda Task](docs/assets/mission-tasks.png) |
| *L'ufficio 3D: team, lavagna kanban, il Brain sopra la CEO* | *Una missione in corso: workstream, sotto-task, revisioni* |
| ![Sub-agenti nella sub-agent bay](docs/assets/sub-agents.png) | ![Verdetto del QA](docs/assets/qa-review.png) |
| *I sub-agenti compaiono olografici nella sub-agent bay* | *Il QA va alla scrivania e dà il verdetto* |
| ![Skill Hub](docs/assets/skill-hub.png) | ![Brain](docs/assets/brain.png) |
| *Lo Skill Hub: ricerca tra tutte le skill indicizzate* | *Il Brain: lezioni del QA e riassunti delle missioni* |
| ![Router e combo](docs/assets/router.png) | ![Report finale](docs/assets/final-report.png) |
| *Il router: provider, combo, chiamate e cooldown* | *Il report finale della CEO e i file consegnati* |

---

## Avvio rapido

**Requisiti:** [uv](https://docs.astral.sh/uv/) nel PATH (al primo avvio scarica da solo Python 3.13 e le dipendenze) e Node 20.10 o più recente (per three.js e gli strumenti di test).

**La prima volta**, da un terminale nella cartella del progetto:

```sh
npm install
```

Installa three.js per il 3D. Le dipendenze Python le scarica `uv` da solo al primo avvio.

**Ogni volta che vuoi usarlo:**

```sh
npm start
```

1. Aspetta la riga `Agent World  →  http://127.0.0.1:4300`.
2. Apri **http://127.0.0.1:4300** nel browser.
3. Per fermarlo: **Ctrl+C** nella finestra del terminale.

- **Senza npm:** è lo stesso server. Entra in `backend/` e lancia `uv run python -m backend`.
- **Porta già in uso?** Se all'avvio leggi "la porta 4300 è già in uso", un altro server occupa quella porta: spesso è Agent World stesso, avviato in un'altra finestra. Chiudilo con Ctrl+C nella sua finestra, oppure scegli un'altra porta con `PORT=4301` nel file `.env`.
- **Per lo sviluppo**, con il reload automatico a ogni modifica: `npm run dev`.
- **Demo o modelli veri.** Senza chiavi API l'app parte in **modalità demo** (pillola `DEMO` in alto). Per usare modelli veri copia `.env.example` in `.env`, inserisci almeno una chiave e riavvia: l'app passa in modalità `LIVE`.

> ⚠️ In modalità `LIVE` ogni missione consuma token veri: in demo una missione complessa fa circa 200 chiamate al modello.

---

## Architettura ibrida

Il browser non sa niente del cambio di motore: stesse route, stesso JSON, stessi eventi. FastAPI fa da direttore d'orchestra (API, orchestrazione asincrona, streaming). Il lavoro di calcolo sul testo passa da un'unica interfaccia, che usa Rust quando il modulo nativo è compilato e Python puro altrimenti.

```mermaid
flowchart LR
    subgraph Browser["Browser · front-end senza build"]
        UI["UI e pannelli<br/>public/js/main.js"]
        W3D["Ufficio 3D · three.js<br/>public/js/world/"]
        ES["EventSource"]
    end

    subgraph Py["Backend · FastAPI + uvicorn (1 processo, asyncio)"]
        API["Route REST<br/>/api/* · /v1/* · statici"]
        SSE["/api/events<br/>StreamingResponse"]
        BUS["Bus<br/>seq + code per client"]
        ENG["Engine<br/>Run · Tasker · Team · Tools"]
        RT["Router OmniRoute<br/>combo · fallback · cooldown"]
        MEM["Brain + Skill Hub"]
        SRCH["search.bm25()"]
        PYB["Bm25 in Python puro"]
    end

    subgraph Rs["Rust · opzionale"]
        AW["aw_core<br/>PyO3 · BM25 · n-gram · coseno"]
    end

    subgraph Disk["File locali"]
        DATA[("data/runs · brain.json · calls")]
        WS[("data/workspace/ · un run per cartella")]
        CFG[("config/*.json · .env")]
    end

    LLM["Provider LLM e media<br/>Anthropic · OpenAI · Gemini · Groq · …"]

    UI -->|fetch JSON| API
    ES -->|text/event-stream| SSE
    SSE --> BUS
    API --> ENG
    ENG -->|emit| BUS
    ENG --> RT --> LLM
    ENG --> MEM --> SRCH
    SRCH -.->|se compilato e conforme| AW
    SRCH -->|altrimenti| PYB
    ENG --> WS
    API --> DATA
    API --> CFG
    BUS --> ES
    ES --> W3D
```

**I principi:**

- **Un solo processo con lo stato in memoria:** run attivi, chat e client SSE. Per questo uvicorn gira con un solo worker.
- **Lo stesso formato su disco e le stesse variabili d'ambiente del server Node di prima** (`data/`, `config/`, `.env`, `AGENT_WORLD_*`).
- **Il front-end è invariato.** Il pathfinding A* (`nav.js`) e la simulazione 3D girano nel browser; il server trasmette solo gli stati degli agenti.

### Come scorre una missione

```mermaid
sequenceDiagram
    autonumber
    actor U as Tu
    participant B as Browser
    participant F as FastAPI
    participant C as CEO
    participant L as Lead
    participant W as Worker (Tasker)
    participant Q as QA
    participant E as Bus → SSE

    U->>B: scrive la missione
    B->>F: POST /api/runs
    F-->>B: 201 + id del run
    F->>C: pianifica (Brain: note utili)
    C->>E: plan · workstream
    E-->>B: la CEO va alla lavagna
    L->>L: scompone in sotto-task, Skill Hub sceglie le skill
    L->>E: subtasks · agent.spawn
    loop finché il QA non approva
        W->>W: pensa → tool → risultato … → finish
        W->>E: agent · file · message
        W->>Q: consegna
        Q-->>W: revise con feedback (dopo 2: escalation a "frontier")
    end
    Q->>E: task done (lezione nel Brain)
    C->>E: report finale · run.done
    E-->>B: l'ufficio 3D anima ogni passaggio
```

---

## Streaming in tempo reale (SSE)

Tutto ciò che vedi muoversi nell'ufficio arriva da un unico flusso Server-Sent Events, `GET /api/events`.

```mermaid
flowchart LR
    E1["engine: bus.emit(type, payload)"] --> S["seq += 1<br/>serializza UNA volta"]
    S --> Q1["coda client 1<br/>asyncio.Queue (max 1000)"]
    S --> Q2["coda client 2"]
    S --> Qn["coda client n"]
    Q1 --> R1["StreamingResponse<br/>retry: 2000 · data: … · : ping"]
    Qn -->|coda piena| X["client staccato"]
    X -->|dopo 2 s| RC["EventSource si riconnette<br/>e rilegge /api/state"]
```

- **Formato:** `retry: 2000` all'apertura; poi un frame `data: {"seq", "type", "payload"}` per ogni evento, e un commento `: ping` dopo 15 s di silenzio.
- **I 17 tipi di evento:** `run`, `task`, `workstream`, `subtasks`, `plan`, `agent`, `agent.spawn`, `agent.despawn`, `message`, `chat`, `file`, `waiting`, `brain`, `skills`, `router.call`, `config`, `run.done`.
- **Ordine garantito:** `emit()` è sincrono e assegna `seq` nell'ordine delle chiamate. Ogni frame si serializza una volta sola, qualunque sia il numero di client.
- **Un client lento non rallenta gli altri.** Ogni client ha la sua coda limitata; quando si riempie, quel client viene staccato. Il browser si riconnette dopo 2 s e ricostruisce lo stato da `GET /api/state`. Non c'è replay: lo stato completo basta.
- **Spegnimento pulito:** a Ctrl+C il lifespan di FastAPI chiude i flussi aperti, perché altrimenti uvicorn aspetterebbe connessioni che non finiscono mai.
- **Gateway `/v1`:** `/v1/chat/completions` con `"stream": true` risponde in formato SSE compatibile OpenAI, con tutto il testo in un solo blocco. Lo streaming token per token è previsto in futuro.

---

## Il bridge Python ↔ Rust

Il crate [`crates/aw_core`](crates/aw_core/) è un modulo nativo Python scritto in Rust con **PyO3** e compilato con **maturin**. Gira nello stesso processo del backend: niente rete, niente processi in più da avviare e chiudere.

```mermaid
flowchart TD
    C["Brain / Skill Hub"] --> F["search.bm25(k1, b)"]
    F --> I{"import aw_core<br/>riuscito?"}
    I -->|no| P["Bm25 in Python puro"]
    I -->|sì| PR{"probe di parità<br/>id, ordine, punteggi"}
    PR -->|fallisce| P
    PR -->|passa| R["aw_core.Bm25 (Rust)"]
    R --> G["tokenizzazione e scoring<br/>senza GIL (allow_threads)"]
```

- **Cosa contiene:** `Bm25` (`add`, `search`), `tokenize`, e dalla spec 05 `ngram_vector` (i vettori locali) e `cosine_top_k` (il coseno su tutti i chunk).
- **Stessa interfaccia:** chi chiama non sa quale implementazione sta usando.
- **Due livelli di sicurezza:**
  - all'avvio, una *probe di parità* confronta Rust e Python su un piccolo corpus: se id, ordine o punteggi differiscono (tolleranza 1e-9), il modulo nativo viene ignorato;
  - `tests/test_search_rust.py` fissa la parità su un corpus di riferimento.
- **Niente blocchi:** la tokenizzazione e lo scoring rilasciano il GIL, quindi il loop asincrono continua a servire lo streaming.
- **Soglia di adozione:** il modulo Rust si compila e si distribuisce solo se batte il Python ottimizzato di almeno **5×**. Lo misura `backend/bench/bm25_bench.py`, che stampa `ADOPT` o `FALLBACK`.
- **Stato di oggi:** senza toolchain Rust gira il fallback Python, che è completo e coperto dagli stessi test.

**Compilare il modulo** (servono rustup e, su Windows, i Visual Studio Build Tools C++):

```sh
cd backend
uv run maturin develop --manifest-path ../crates/aw_core/Cargo.toml
uv run pytest tests/test_search_rust.py
uv run python bench/bm25_bench.py
```

---

## Agenti, sub-agenti e utility

### La gerarchia

```mermaid
flowchart TD
    U(["Tu"]) -->|missione · chat · risposte| CEO["Ada · CEO<br/>pianifica e coordina"]
    CEO -->|workstream con dipendenze| LEADS["Lead dei team di lavoro<br/>Rino · Leo · Teo · Iris · Luna · Pia"]
    LEADS -->|sotto-task| WK["Worker<br/>Sara · Nina · Gaia · Ugo · Dario · Max"]
    LEADS -->|più lavoro che persone| SUB["Sub-agenti temporanei<br/>nella sub-agent bay"]
    SH["Skill Hub · Otto<br/>bibliotecario"] -.->|1–3 skill per sotto-task| WK
    SH -.-> SUB
    PL["Prompt Lab · Pia<br/>brief più precisi"] -.->|missioni complesse| WK
    WK -->|consegna| QA["QA e Sicurezza<br/>Bruno · Vera"]
    SUB -->|consegna| QA
    QA -->|revise con feedback| WK
    QA -->|lezioni| BR[("Brain")]
    WK <-->|recall · remember| BR
    WK -->|ask_lead| LEADS
    WK -->|ask_user| U
```

| Ruolo | Chi | Cosa fa |
|---|---|---|
| **CEO** | Ada | Decide se la missione è semplice o complessa, crea i workstream per team con le dipendenze, scrive il report finale. Prima di pianificare legge il Brain. |
| **Lead** | uno per team | Prende il workstream dalla lavagna, lo scompone in sotto-task, risponde ad `ask_lead`. Dopo troppe bocciature decide se riprovare con nuove indicazioni o saltare. |
| **Worker** | uno o più per team | Esegue un sotto-task nel suo loop, con i tool del team. Se il QA lo rimanda indietro riprende lo **stesso** loop, con tutta la memoria. |
| **Sub-agente** | creato al volo | Nasce quando c'è più lavoro parallelo che persone (fino a `maxSubAgents` per team), lavora come un worker e poi svanisce. |
| **Skill Hub** | Otto (servizio) | Per ogni sotto-task cerca le skill candidate con BM25. Nelle missioni complesse ne sceglie 1–3 con un modello; nelle semplici tiene quelle sopra una soglia di punteggio. |
| **Prompt Lab** | Pia, Max | Nelle missioni complesse riscrive i brief e i prompt per le immagini. |
| **QA e Sicurezza** | Bruno, Vera (servizio) | Controlla ogni consegna rispetto ai criteri di accettazione e la sicurezza del codice. Le lezioni utili finiscono nel Brain. |

**I team di lavoro** (in `config/default.json`):

| Team | Persone | Strumenti in più | Sub-agenti al massimo |
|---|---|---|---|
| Ricerca | Rino, Sara | `web_search`, `web_fetch` (GitHub, Reddit, Hacker News) | 3 |
| Sviluppo | Leo, Nina | `run_command` (solo se abilitato), `web_fetch` | 3 |
| Contenuti | Teo, Gaia | `web_search` | 2 |
| Design | Iris, Ugo | — | 2 |
| AI Generativa | Luna, Dario | `generate_image`, `generate_speech` | 3 |
| Prompt Lab | Pia, Max | — | 1 |

Tutti hanno anche `list_files`, `read_file`, `write_file`, `search_skills`, `read_skill`, `recall`, `remember`, `ask_lead`, `ask_user` e `finish`.

**Revisioni ed escalation.** Dopo 2 revisioni il worker passa alla combo `frontier` (`escalateAfter`). Oltre `maxRevisions` (3) decide il lead.

### Le utility

| Componente | File | Ruolo |
|---|---|---|
| **Run** | `backend/backend/run.py` | Il ciclo di vita della missione: piano, approvazione, scheduler a tick, preparazione dei workstream, skill, brief, esecuzione, review, report. Gestisce pausa, ripresa e stop. |
| **Tasker** | `backend/backend/tasker.py` | Il loop di un worker su un sotto-task: il modello risponde con un'azione JSON (`thought`, `tool`, `args`), il tool restituisce il risultato, si ripete fino a `finish`. Compatta il contesto: resta il brief, i passi vecchi diventano un registro di una riga. |
| **Team** | `backend/backend/team.py` | Chi esiste, chi è libero, cosa fa ognuno. Assegna le persone con una coda d'attesa, crea e ritira i sub-agenti. Ogni cambio di stato diventa un evento `agent`, ed è questo che muove i personaggi in 3D. |
| **Bus** | `backend/backend/bus.py` | Numera ogni evento (`seq`) e lo distribuisce alle code dei client SSE. |
| **Tools** | `backend/backend/tools.py` | Una cartella per run: ogni percorso dato da un agente viene risolto lì dentro, con la stessa regola su ogni sistema (`backend/backend/paths.py`): `\` separa come `/`, e i `:` (drive o stream nascosti di Windows) sono rifiutati, così un progetto si copia da un sistema all'altro. I comandi shell sono spenti di default; quando li accendi hanno un timeout e chiudono l'intero albero di processi. |
| **Router** | `backend/backend/router/` | OmniRoute (sotto): combo, fallback, cooldown, adapter dei provider e il simulatore demo. |
| **Brain** | `backend/backend/brain.py` | Memoria condivisa che sopravvive ai run (fino a 5000 note), con ricerca BM25. |
| **Skill Hub** | `backend/backend/skills.py` | Indice di ogni `SKILL.md` delle fonti configurate, più le repo GitHub predefinite. |
| **Media** | `backend/backend/media.py` | Immagini e voce dai provider, oppure PNG e WAV veri generati in demo. |
| **Store** | `backend/backend/store.py` | Un file JSON per run in `data/runs/`, con un salvataggio raggruppato ogni 400 ms. |
| **Web** | `backend/backend/web.py` | Ricerca su DuckDuckGo, letture mirate di GitHub, Reddit e Hacker News. |

---

## Memoria e recupero (RAG)

L'app recupera il contesto con una **ricerca ibrida**: **BM25**, un ranking lessicale classico, fuso con la **similarità del coseno** tra vettori. La fusione è la *reciprocal rank fusion*, e vale per due corpora:

| Corpus | Documento | Campi e pesi |
|---|---|---|
| **Brain** | una nota (lezione del QA, riassunto di un run, nota di un agente o tua) | titolo ×3, testo ×1, tag ×2, team ×1 |
| **Skill Hub** | uno `SKILL.md` (i primi 6000 byte) | nome ×4, descrizione ×2 (fino a 600 caratteri), titoli `#`–`###` ×1 (fino a 12), percorso ×1 |

### Dove entra il contesto recuperato

- **Piano della CEO:** le 4 note del Brain più vicine all'obiettivo entrano nel prompt di pianificazione.
- **Skill per ogni sotto-task:** i 10 candidati migliori, cercati con titolo, descrizione, team e output del sotto-task. Lo Skill Hub ne sceglie da 1 a 3, che entrano nel brief del worker.
- **Durante il lavoro:** con `recall` (5 note) e `search_skills` / `read_skill` (8 skill) l'agente cerca da solo; con `remember` aggiunge una nota.
- **Dopo il QA:** ogni lezione e il riassunto della missione diventano note, e la missione successiva le ritrova.
- **Contesto su misura per il modello** (spec 08): il prompt di ogni worker si dimensiona sul profilo del modello che lo riceverà.
  - Un modello grande (oltre 128k di contesto, né gratuito né locale) riceve fino a 5 note del Brain, le skill assegnate intere e il contesto dettagliato della run.
  - Un modello veloce, gratuito o locale riceve la *modalità compatta*: i 2 passaggi più pertinenti delle sue skill (RRF di BM25 e coseno, con un `minCosine` più severo), note in punti essenziali e un **contratto JSON esplicito** in fondo al system prompt.
  - Le risposte tipiche dei modelli piccoli (apici singoli, chiavi senza virgolette, `Write_File()`, args come stringa, parentesi tagliate) vengono riparate invece di finire in "Risposta non valida, riprovo".
- **Memoria della run** (spec 08): ogni file scritto, bocciatura del QA, lezione, errore e consegna viene indicizzato subito (BM25 + vettori n-gram locali, senza rete), con i tag di workstream, task e team.
  - Un worker, compreso un sub-agente appena generato, ritrova i percorsi reali consegnati dagli altri team e gli eventi più vicini al suo task.
  - Una revisione porta con sé le lezioni che valgono.
  - Un cambio di modello in corsa (fallback o escalation) riceve il contesto ridimensionato per il nuovo modello.
- **Embedding:** se il primo provider della lista ha finito il credito, resta fuori e risponde il successivo (OpenAI, Gemini, Mistral, Ollama, poi `local/ngram`).

```mermaid
flowchart LR
    T["testo"] --> N["minuscole → NFD<br/>→ via i diacritici"]
    N --> SP["split su [^a-z0-9]+"]
    SP --> FI["token di almeno 3 caratteri,<br/>senza stopword IT/EN"]
    FI --> IX["indice: tf pesata per campo,<br/>df, lunghezza media"]
    Q["query"] --> N2["stessa tokenizzazione"] --> SC["punteggio BM25<br/>k1 = 1.4 · b = 0.75"]
    IX --> SC --> K["top-k"] --> P["prompt dell'agente"]
```

### Il punteggio

Per una query con termini $t$ e un documento $d$:

$$
\text{score}(d) = \sum_{t} \ln\left(1 + \frac{N - df_t + 0.5}{df_t + 0.5}\right) \cdot \frac{f_{t,d}\,(k_1 + 1)}{f_{t,d} + k_1\left(1 - b + b\,\frac{|d|}{\overline{|d|}}\right)}
$$

- $f_{t,d}$ è la frequenza del termine **pesata per campo**: un termine nel titolo di una nota vale 3.
- $|d|$ è la lunghezza pesata del documento, $\overline{|d|}$ la media del corpus.
- La lunghezza media si aggiorna con un totale corrente, senza risommare tutti i documenti a ogni aggiunta.

L'implementazione esiste due volte, identica: `backend/backend/search.py` (Python) e `crates/aw_core/src/lib.rs` (Rust). Vedi [il bridge](#il-bridge-python--rust).

### Embedding, chunking semantico e fusione

```mermaid
flowchart LR
    D["SKILL.md · nota"] --> SPL["pezzi: paragrafi,<br/>titolo + paragrafo"]
    SPL --> EMB["embedding"]
    EMB --> MER["chunking semantico:<br/>unisce i vicini simili"]
    MER --> VEC[("vettori dei chunk")]
    Q["query"] --> QE["embedding<br/>(stesso modello)"] --> COS["coseno top-k<br/>(Rust se compilato)"]
    VEC --> COS
    Q --> BM["BM25"]
    COS --> RRF["RRF: Σ w / (60 + rank)"]
    BM --> RRF --> K["top-k"]
```

**Embedding.** `rag.embeddings` in `config/default.json` è una lista ordinata, come una combo. Si usa il primo provider pronto, attraverso il suo endpoint `/embeddings` compatibile OpenAI:
- l'ordine predefinito è `openai/text-embedding-3-small` (512 dimensioni), `mistral/mistral-embed`, `gemini/gemini-embedding-001`, `ollama/nomic-embed-text`;
- i vettori restano in cache su disco (`data/embeddings/`), indicizzati per hash del testo;
- tutti i vettori di un indice vengono dallo stesso modello, e la query usa sempre quello. Se quel modello smette di rispondere, l'indice viene ricostruito con il primo modello che funziona.

**Senza chiavi, in demo o offline: `local/ngram`.** Gli n-grammi di 3 e 4 caratteri di ogni token vengono messi in un vettore di 256 dimensioni con un hash firmato (CRC-32). Non serve nessun modello, è deterministico, ed è uguale in Python e in Rust. **Trova le varianti della stessa parola, non il significato.** Misure del 14/10/2026:

| Coppia | Coseno |
|---|---|
| varianti della stessa parola (*typographic* ~ *typography*) | 0,44–0,76 |
| la stessa parola tra lingue diverse, in testi lunghi (*typography* ~ *tipografia…*) | circa 0,16, debole |
| 66 coppie di testi senza relazione | massimo 0,241, p90 0,13 |

Per questo `rag.minCosine` è 0,25. I sinonimi veri ("tipografia" → "font") li trova solo un modello di embedding vero.

**Chunking semantico** (solo per gli `SKILL.md`; una nota del Brain resta intera):
1. Il testo si divide in paragrafi; ogni titolo resta incollato al paragrafo che lo segue, e un paragrafo troppo lungo si taglia a fine frase.
2. Ogni pezzo diventa un vettore.
3. I pezzi vicini si uniscono finché il coseno con il centroide del chunk resta ≥ `chunk.minSimilarity` (0,5) e il chunk non supera `chunk.maxChars` (1200). Un titolo apre sempre un chunk nuovo.
4. Ogni skill ha in più il chunk "nome: descrizione". Il punteggio vettoriale di un documento è quello del suo chunk migliore.

In questo modo si ritrova anche il testo del corpo, che BM25 non indicizza: lì contano solo nome, descrizione, titoli e percorso.

**Fusione.** $\cos(q, c) = q \cdot c$, perché i vettori sono normalizzati. La classifica vettoriale (solo sopra `minCosine`) e quella BM25 si fondono con la RRF:

$$\text{score}(d) = \frac{w_{bm25}}{60 + r_{bm25}(d)} + \frac{w_{vec}}{60 + r_{vec}(d)}$$

Un documento trovato in tutti e due i modi sale in cima. Ogni risultato riporta `score` (fuso), `bm25` e `cosine`. Nelle missioni semplici, che non hanno un bibliotecario, le skill si scelgono ancora con la soglia BM25 di prima.

**Il Brain** aggiunge una nota a BM25 in modo incrementale; prima ricostruiva tutto l'indice a ogni nota, circa 0,4–0,7 s a 5000 note. Le note ancora senza vettore ne ricevono uno, tutte in un colpo, alla ricerca successiva.

---

## Il router OmniRoute

Il gateway dei modelli dell'app, ispirato a OmniRoute ma interno.

- **Provider:** Anthropic, OpenAI, OpenRouter, Groq, Cerebras, Gemini, DeepSeek, Mistral, Together, Fireworks, SambaNova, Cohere (endpoint compatibile OpenAI), Hugging Face, xAI Grok, Perplexity, NVIDIA NIM, Novita AI, Hyperbolic, Cloudflare Workers AI (`CLOUDFLARE_ACCOUNT_ID` nell'URL), Ollama, LM Studio e qualsiasi server locale compatibile OpenAI (vLLM, llama.cpp, Jan) all'indirizzo `LOCAL_OPENAI_URL`. GitHub Models non c'è: GitHub l'ha ritirato il 30/07/2026.
- **Provider aggiunti dall'app** (spec 09): dalle Impostazioni si registra qualsiasi provider compatibile OpenAI, o un modello nuovo di un provider di serie, senza riavviare (`POST /api/providers`, `DELETE /api/providers/{id}`). I modelli entrano nelle combo scelte o in quelle del loro tier. La chiave resta in `.env`, che viene riletto; valgono le regole della spec 07 (https, niente credenziali nell'URL, una variabile `*_KEY` o `*_TOKEN` tutta sua).
- **Combo:** liste ordinate di `provider/modello`, con strategia `fallback` o `round-robin`. Sono pronte `frontier`, `smart`, `code`, `fast`, `free` e `local`; `frontier`, `smart` e `fast` finiscono con modelli gratuiti (OpenRouter `:free`, Gemini Flash, Groq, Cerebras). La combo `vision` (Gemini Flash, GPT-5 mini, Claude Haiku e Sonnet) guarda le foto del proprietario e non scende mai lungo la cascata (`"cascade": false`).
- **Ruoli e tier** (spec 08): CEO e QA su `frontier`, Sviluppo su `code`, Prompt Lab e AI Generativa su `smart`, Ricerca, Contenuti, Design e Skill Hub su `fast`. Un lead pianifica e aiuta su `smart`, un sub-agente lavora su `fast`; dopo le bocciature il worker sale su `frontier`.
- **Perché una chiamata fallisce** (spec 08):
  - **credito finito** (402, oppure 400/403/429 con `insufficient_quota`, `credit balance`, `billing`…): l'intero provider resta fuori per 6 ore e non si provano i suoi altri modelli;
  - **un limite al minuto** (il 429 di Gemini con `retryDelay`) è solo una pausa, lunga quanto chiede il provider;
  - **modello sparito** (404, `model_not_found`): quel `provider/modello` va in blacklist per 24 ore e si provano subito i suoi alias aggiornati (`router.aliases`, per esempio `gemini-2.5-pro` → `gemini-3.1-pro-preview` → `gemini-2.5-flash`);
  - **chiave rifiutata**: il provider resta fuori 10 minuti;
  - **429 o 5xx**: il bersaglio si raffredda, con un backoff da 15 s a 5 min, e passa in fondo alla lista.
- **Cascata:** se nessun bersaglio di una combo risponde, si scende lungo `router.cascade`: `frontier` → `code` → `smart` → `fast` → `free` → `local`. Se non risponde nessuno, in una run live risponde il simulatore demo come **emergenza**: la run lo dice una volta nel pannello Messaggi e lo conta in `usage.emergencies` (si spegne con `router.emergencyMock: false`). Il pulsante di test e il gateway `/v1` non ricevono mai risposte simulate.
- **Senza fermate** (spec 09): un cambio di modello non ferma il lavoro. Il worker tiene tutta la sua conversazione, il modello nuovo riceve un messaggio `MODEL SWITCH` con il contesto RAG ridimensionato per lui, e la scheda del task mostra il cambio (🔀, evento `model.switch`). Se non risponde nessun modello, la chiamata aspetta il primo che torna (al massimo `limits.modelWaitMaxMs`) e riprova; dopo `limits.modelRetries` tentativi apre una richiesta "nessun modello disponibile" con "Riprova ora", e intanto continua a provare. Vale per worker, lead, CEO e QA.
- **L'arbitro TypeSafe** (spec 09): con `TYPESAFE_API_KEY`, il modello Jev di TypeSafe sceglie tra le opzioni del lead quando una domanda resta senza risposta (vedi [File, dialogo e ripresa](#file-dialogo-e-ripresa)). Jev risponde a domande tipizzate e non scrive testo, quindi non sta in nessuna combo. La sua scelta vale da `router.arbiter.minConfidence` in su.
- **Profiler** (`router/profiler.py`): da nome e metadati di ogni modello ricava parametri, famiglia (reasoning, coder, vision, piccolo), finestra di contesto, gratuità, esecuzione locale e tier. I modelli dei server locali avviati (e i `:free` di OpenRouter) vengono scoperti da `/models` all'avvio e ogni 10 minuti, ed entrano in coda alla combo del loro tier.
- **Demo:** se nessun provider ha una chiave, risponde il simulatore (`router/mock.py`). Risponde nella lingua della run: piani, pensieri, file, pagina e report (testi in `router/mock_texts.py`).
- **Media:** immagini con OpenAI `gpt-image-1`, fal.ai (Flux) o Pollinations (gratis, spento di default); voce con OpenAI TTS o ElevenLabs. In una run live un file media è sempre reale: se i provider cloud non hanno credito o chiave, la voce passa a edge-tts, una voce neurale naturale (è una dipendenza del backend: `npm start` lo installa da solo, senza `uv add`; in LIVE non va attivato, perché i prompt vanno già a provider esterni; si spegne con `media.providers.edgetts.enabled: false`, e senza rete si passa oltre), e poi al sintetizzatore del sistema (SAPI su Windows, `say` su macOS, `espeak-ng` su Linux: offline e gratis), le immagini al generatore locale. Un WAV chiesto come `.mp3` viene convertito con ffmpeg, se c'è; altrimenti si salva come `.wav`.
- **Log:** ogni chiamata viene salvata in `data/calls/`.
- **Gateway compatibile OpenAI** (protetto da `AGENT_WORLD_API_KEY` se la imposti):

```sh
curl http://127.0.0.1:4300/v1/chat/completions -H "content-type: application/json" \
  -d '{"model": "combo:smart", "messages": [{"role": "user", "content": "ciao"}]}'
```

I nomi dei modelli nelle combo sono un punto di partenza: controlla che corrispondano ai tuoi account e cambiali dalle Impostazioni.

---

## File, dialogo e ripresa

Una missione non resta mai ferma ad aspettare un'API esaurita o un passo che un agente non sa chiudere (spec 09, [`docs/specs/09-multimodal-interactive-recovery.md`](docs/specs/09-multimodal-interactive-recovery.md)). Il proprietario può dare i suoi file, parlare con il task bloccato, riprendere il lavoro da dove si è fermato e chiedere modifiche anche a missione finita.

- **I tuoi file.** Nel composer, nel box sotto la missione e nel box di ogni task: pulsante 📎, trascina e rilascia, oppure incolla un'immagine con Ctrl+V.
  - Formati: immagini (`png jpg jpeg webp svg gif`), documenti (`pdf docx txt md csv json html htm css js`), audio (`mp3 wav ogg`).
  - Ogni file viene controllato: estensione in lista, byte che corrispondono all'estensione, un nome semplice, al massimo `limits.maxUploadMB`.
  - Il testo dei documenti entra subito nella memoria della run e nel Brain.
  - Gli agenti li usano al posto di generarli: `use_attachment` mette il file dove il piano lo aspetta, `read_document` ne legge il testo o i passaggi pertinenti, `inspect_image` chiede alla combo `vision` che cosa mostra una foto. Il QA accetta i file del proprietario.
- **Parlare con un task.** Dalla sua scheda ("Parla con l'agente · dai una soluzione o dei file") o dall'inspector dell'agente. Le parole e i file arrivano al worker al passo successivo; se il task era fallito, torna in coda con quello che aveva bloccato.
- **Domande che non scadono.** Una domanda ancora aperta quando la run si ferma resta `pending`: la ritrovi riaprendo la run da "Previous runs", anche dopo un riavvio del server.
- **Nessun collo di bottiglia.** Senza risposta entro `limits.askUserTimeoutMs`, o con "💡 Trova tu una soluzione", decide il lead del team (il CEO, se è il lead a chiedere), con l'arbitro TypeSafe se configurato. `limits.autoAnswer: false` lascia la decisione al worker.
- **Ripresa dal punto di blocco.** "⟲ Riprendi il workflow" fa ripartire una run salvata (ferma, fallita o con errori) senza rifare il lavoro consegnato: la memoria della run viene ricostruita e un worker interrotto riparte dalla sua conversazione.
- **Modifiche dopo la fine.** "Non mi piace la hero: usa questa foto" nel box sotto la missione: il CEO sceglie i task da rifare, che ripartono con la direttiva e i file; il QA li rivede e il report viene riscritto. Si possono fare quanti giri si vuole.

| Endpoint | Che cosa fa |
|---|---|
| `POST /api/uploads?name=…` | carica un file prima della missione (il corpo sono i byte del file) |
| `POST /api/runs {goal, attachments}` | avvia la missione con i file caricati: sono nella run prima che il CEO pianifichi |
| `POST /api/runs/{id}/attachments?name=…&taskId=…` | aggiunge un file a una run, attiva o salvata, e facoltativamente a un task |
| `POST /api/runs/{id}/tasks/{task}/interact {text, attachments, resume}` | parla con un task; `resume: true` riprende anche la run ferma |
| `POST /api/runs/{id}/answer {itemId, text}` o `{itemId, solve: true}` | risponde a una domanda, anche di una run salvata, o la fa decidere alla squadra |
| `POST /api/runs/{id}/resume` | riprende una run salvata dal punto di blocco (su una run in pausa toglie la pausa) |
| `POST /api/runs/{id}/refine {text, attachments, taskId}` | chiede una modifica: i task coinvolti ripartono e il QA li rivede |
| `POST /api/providers` · `DELETE /api/providers/{id}` | registra o toglie un provider compatibile OpenAI senza riavviare |

---

## Tech stack

### Backend (Python)

| Libreria | Versione | Uso |
|---|---|---|
| [FastAPI](https://fastapi.tiangolo.com/) | 0.143 | API REST, streaming SSE, lifespan |
| [Starlette](https://www.starlette.io/) | 1.8 | `StreamingResponse`, sotto FastAPI |
| [uvicorn](https://www.uvicorn.org/) | 0.54 | server ASGI, un processo |
| [httptools](https://github.com/MagicStack/httptools) | 0.9 | parser HTTP veloce, usato da uvicorn in automatico |
| [watchfiles](https://watchfiles.helpmanual.io/) | 1.3 | il reload di `npm run dev` |
| [httpx](https://www.python-httpx.org/) | 0.28 | chiamate asincrone ai provider e al web |
| [Pydantic](https://docs.pydantic.dev/) | 2.14 | dipendenza di FastAPI |
| [pypdf](https://pypdf.readthedocs.io/) | 6.21 | il testo dei PDF caricati dal proprietario (spec 09) |
| [uv](https://docs.astral.sh/uv/) | — | Python 3.13, ambiente virtuale, lockfile |
| [hatchling](https://hatch.pypa.io/) | — | build del pacchetto `backend` |

### Media

| Libreria | Versione | Uso |
|---|---|---|
| [edge-tts](https://github.com/rany2/edge-tts) | 7.3 | voce neurale naturale di una run live quando le voci cloud non hanno credito o chiave. Dipendenza del backend (porta con sé aiohttp): nessuna installazione a mano |
| Sintetizzatore del sistema | di sistema | SAPI su Windows, `say` su macOS, `espeak-ng` su Linux: la voce offline dopo edge-tts |
| [ffmpeg](https://ffmpeg.org/) | di sistema, facoltativo | converte in `.mp3` un WAV chiesto come `.mp3` |

### Acceleratore nativo (Rust)

| Libreria | Versione | Uso |
|---|---|---|
| [PyO3](https://pyo3.rs/) | 0.24 (`abi3-py310`) | binding Python ↔ Rust |
| [maturin](https://www.maturin.rs/) | 1.15 | build del modulo `aw_core` |
| [unicode-normalization](https://crates.io/crates/unicode-normalization) | 0.1 | NFD per la tokenizzazione, identica a Python |

### Front-end

| Libreria | Versione | Uso |
|---|---|---|
| [three.js](https://threejs.org/) | 0.186.1 | ufficio 3D, servito da `/vendor/three` senza build |
| API del browser | — | `EventSource` (SSE), Web Speech (🎙 dettatura e 🔊 lettura ad alta voce) |

### Test e strumenti

| Strumento | Versione | Uso |
|---|---|---|
| [pytest](https://pytest.org/) + pytest-asyncio | 9.1 / 1.4 | 796 test del backend |
| Node.js | ≥ 20.10 (≥ 22 per il runner) | test del mondo 3D, smoke, flussi, cartelle temporanee |
| Edge o Chrome headless | di sistema | runner del browser via DevTools Protocol (254 verifiche) |

### Skill e plugin

Lo Skill Hub indicizza ogni `SKILL.md` delle fonti in `skills.sources`:

- le skill dell'app (`skills/`): copywriting, image-prompting, landing-page, prompt-engineering, security-review, web-research;
- i **plugin di Claude Code** (`~/.claude/plugins`), `~/.claude/skills`, `~/.agents/skills` e Codex (`~/.codex/skills`);
- le **repo GitHub predefinite** in `skills.repos`, clonate al primo avvio in `skills/vendor/` (oggi [vercel-labs/skills](https://github.com/vercel-labs/skills)).

Dalla scheda **Skill** puoi cercare, leggere e aggiungere altre repo GitHub di skill.

### Lo Skiller: lo scout delle skill

Lo Skiller è un job in background (`backend/backend/skiller.py`). Il primo giro parte 10 minuti dopo l'avvio, poi ce n'è uno ogni 24 ore.
- **Dove cerca:** nelle repo GitHub delle query in `skills.skiller.queries` (API di ricerca) e nei link a github.com trovati dalla ricerca web.
- **Cosa scarta subito:** le repo già installate e quelle controllate negli ultimi 7 giorni.
- **Come valuta:** legge **solo metadati**, cioè la scheda della repo, l'elenco dei file, `package.json` / `pyproject.toml` e i registri npm e PyPI.

| Metrica | Punti |
|---|---|
| stelle | fino a 40 (10 × log10(stelle + 1)) |
| ultimo push | 25 entro 30 giorni, 20 entro 90, 12 entro 180, 5 entro 365 |
| issue aperte / stelle | 15 fino a 0,05, 10 fino a 0,15, 5 fino a 0,3 |
| licenza | 10 |
| almeno uno `SKILL.md` | 10 |

**Bastano a scartare una repo:** archiviata, disattivata, fork, senza licenza, senza `SKILL.md`, descritta come deprecata, con un pacchetto deprecato (npm `deprecated` o PyPI "Inactive"), sotto `minStars` o ferma da più di `maxDaysSinceCommit` giorni. Le altre sono approvate da `minScore` (60) in su.

**Il risultato:**
- i verdetti stanno in `data/skiller.json` e si leggono da `GET /api/skills/skiller`; `POST /api/skills/skiller/run` lancia un giro subito;
- `GITHUB_TOKEN` in `.env` (facoltativo) alza il limite delle API GitHub da 60 a 5000 richieste all'ora;
- i test non lo avviano mai (`AGENT_WORLD_SKILLER=0`).

#### Installare le repo approvate (download esterni)

**Si accende solo così.** Serve `CUSTOM_DOWNLOAD_PATH` in `.env`; senza, lo Skiller valuta e basta. È un percorso assoluto, che viene rifiutato se è:
- una radice o la home stessa;
- una cartella di sistema;
- dentro l'app o dentro `data/`;
- un percorso che passa da un link o da una junction.

**Chi installa:**
- le repo approvate dei proprietari in `skills.skiller.trustedOwners` si installano da sole; per loro, e solo per loro, cade il gate "senza licenza";
- tutte le altre aspettano `POST /api/skills/skiller/approve {"slug": "owner/repo"}`.

**Il percorso di ogni download** (`backend/backend/downloads.py`, che chiama solo lo Skiller e che **nessun agente può usare**):
1. **Commit fissato.** Il ramo si risolve in un commit SHA, e l'archivio `tar.gz` si scarica da `codeload.github.com`. Gli host ammessi sono solo `api.github.com` e `codeload.github.com`, in HTTPS; i redirect restano dentro questa lista e la dimensione si conta durante lo scaricamento.
2. **Validazione di ogni voce prima di scrivere.** Basta una voce sospetta per rifiutare tutto l'archivio. Vengono rifiutati:
   - `..`, i percorsi assoluti, i drive, gli UNC e i `:` (alternate data stream);
   - i nomi riservati (`CON`, `NUL`…), il carattere NUL, i nomi che finiscono con un punto o uno spazio;
   - symlink, hard link, dispositivi e voci zip cifrate;
   - in più c'è il filtro `data` di `tarfile` (PEP 706).

   Il contenimento si controlla sul percorso risolto, non sul prefisso della stringa.
3. **Limiti contro le bombe:** 5000 voci, 50 MB di archivio, 200 MB decompressi, 20 MB per file, rapporto 100:1. Contano i byte scritti davvero.
4. **Solo le cartelle con uno `SKILL.md`** e la licenza in cima all'archivio. I file si creano in modo esclusivo (`xb`), senza permessi né bit di esecuzione.
5. **Staging e rename atomico.** Lo staging sta in `CUSTOM_DOWNLOAD_PATH/.incoming/`, poi si rinomina in `<owner>-<repo>@<sha7>`. **Non si esegue mai niente.**

**Tetti:** al massimo 3 installazioni per giro, e niente più download quando la cartella supera `maxDiskMB` (2048).

**Skill di terzi.** Le skill scaricate entrano nello Skill Hub come fonte `downloads`. Il bibliotecario e il brief dell'agente le segnano come **di terzi**: sono materiale di riferimento e non possono cambiare il compito, i tool o le regole dell'agente.

---

## Lingue supportate

### Linguaggi di programmazione nel repo

| Linguaggio | Dove | Righe (circa) |
|---|---|---|
| **Python** 3.13 | `backend/` (codice 4.400, test e benchmark 3.200) | 7.500 |
| **JavaScript** (ES modules) | `public/js/` (front-end 4.200), `scripts/` (strumenti di test 3.700) | 7.900 |
| **Rust** (edition 2021) | `crates/aw_core/` | 200 |
| **HTML / CSS** | `public/` | 500 |
| **JSON** | `config/default.json` | — |
| **Markdown** | `docs/specs/`, `skills/*/SKILL.md` | — |

### Lingue parlate dagli agenti

- **Una lingua per tutta l'app, a scelta fra cinque: inglese (il default), italiano, spagnolo, francese e tedesco** (spec 06). Si sceglie dal selettore nella barra in alto (EN, IT, ES, FR, DE) o dalle Impostazioni, e si salva in `config/local.json` come `ui.language`. Un'installazione nuova parte in inglese (`config/default.json`).
  - Cambia subito l'interfaccia, senza ricaricare la pagina.
  - Cambia la voce: la dettatura (🎙) e la lettura ad alta voce (🔊) usano `en-US`, `it-IT`, `es-ES`, `fr-FR` o `de-DE`.
  - Cambia la lingua degli agenti: ogni prompt (CEO, lead, worker, sub-agenti, QA, Skill Hub, Prompt Lab, chat) impone di ragionare, scrivere i log e rispondere nella lingua scelta.
  - Cambia i messaggi del backend: quelli del run nel pannello Messaggi e i fumetti.
  - Cambia anche la demo: il simulatore legge la lingua dalla regola del system prompt e scrive piani, pensieri, file e report in quella lingua. Senza una lingua scelta risponde in inglese.

  Ogni run riceve la lingua quando parte e la tiene fino alla fine. Restano in italiano solo gli errori HTTP (ticket N13).
- **La voce generata dagli agenti** (`generate_speech`) usa OpenAI TTS o ElevenLabs `eleven_multilingual_v2`, che sono multilingua.
- **La ricerca BM25** toglie le stopword italiane e inglesi e gli accenti (`più` → `piu`). Funziona bene con le lingue in alfabeto latino. Le scritture non latine (cirillico, greco, cinese…) oggi non producono token, perché il tokenizer tiene solo `a-z` e `0-9` dopo aver tolto gli accenti.

---

## Configurazione

| Cosa | Dove |
|---|---|
| Chiavi API, porta, shell | `.env` (vedi `.env.example`) |
| Team, persone, combo, media, fonti e repo delle skill, limiti | `config/default.json` |
| Le tue modifiche dall'app | `config/local.json` (creato in automatico) |

| Variabile | Effetto |
|---|---|
| `PORT` | porta del server (predefinita 4300) |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `XAI_API_KEY`, `NVIDIA_API_KEY`, … | accendono i provider; senza chiavi si va in demo |
| `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` | Cloudflare Workers AI: l'account entra nell'URL del provider |
| `TYPESAFE_API_KEY` (e `TYPESAFE_BASE_URL`, facoltativo) | l'arbitro TypeSafe delle decisioni prese per il proprietario; da solo non accende la modalità live |
| `AGENT_WORLD_API_KEY` | protegge il gateway `/v1` con un Bearer token |
| `AGENT_WORLD_ALLOW_SHELL=1` | consente `run_command` nella cartella del run (spento di default: i comandi li scrivono i modelli) |
| `AGENT_WORLD_HOME` | sposta altrove `data/`: run, Brain, log delle chiamate e cartelle dei run (lo usano i test) |
| `AGENT_WORLD_ALLOWED_HOSTS` | altri nomi con cui raggiungere il server, separati da virgole (es. `studio.lan,192.168.1.20`): servono solo se lo esponi in LAN; di default sono ammessi `127.0.0.1`, `localhost` e `::1` |
| `AGENT_WORLD_FAST=1` | niente pause teatrali, risposte demo quasi istantanee (lo usano i test) |
| `AGENT_WORLD_LOCAL_CONFIG` | sposta il file delle preferenze (di default `config/local.json`): lo usano i test, per non leggere né scrivere le tue |
| `AGENT_WORLD_ENV_FILE` | sposta il file `.env`, che si legge all'avvio e di nuovo quando registri un provider: i test e i loro server non leggono mai il tuo |
| `AGENT_WORLD_SKILL_REPOS=0` | all'avvio non clona le repo di `skills.repos` che mancano (lo usano i test) |
| `AGENT_WORLD_DISCOVER=0` | non chiede ai provider e ai server locali quali modelli hanno (lo usano i test) |
| `AGENT_WORLD_EXIT_WITH_PARENT=1` | il server si chiude quando si chiude il suo stdin, cioè quando muore chi l'ha avviato; senza uno stdin collegato a una pipe non parte. Lo imposta `spawnBackend()` per i server dei test |

I limiti della spec 09 stanno in `limits` di `config/default.json`; il tempo di risposta e `autoAnswer` si cambiano anche dalle Impostazioni:

| Limite | Predefinito | Effetto |
|---|---|---|
| `askUserTimeoutMs` | 300000 (5 min) | dopo quanto una domanda senza risposta viene decisa dalla squadra |
| `autoAnswer` | `true` | `false`: la decide il worker da solo, come prima |
| `modelRetries` / `modelWaitMaxMs` | 4 / 60000 | tentativi e attesa massima quando nessun modello risponde, prima della richiesta "nessun modello disponibile" |
| `maxUploadMB` / `maxAttachments` | 25 / 60 | dimensione di un file del proprietario e numero di file per run |

Per aggiungere persone o team modifica `teams` in `config/default.json`. Ogni team ha `label`, `color`, `kind` (`work` o `service`), `combo`, `brief`, `tools`, `lead`, `workers` e `maxSubAgents`.

---

## Sicurezza

Il server non ha login: ascolta solo su `127.0.0.1`, e si difende dalle pagine web che apri nel browser (spec 07, [`docs/specs/07-security.md`](docs/specs/07-security.md)). Tutte le regole stanno in `backend/backend/security.py` e in `routes/static.py`, e valgono prima di ogni route.

| Regola | Contro cosa |
|---|---|
| Accetta solo i nomi host `127.0.0.1`, `localhost` e `::1`, più quelli di `AGENT_WORLD_ALLOWED_HOSTS` | DNS rebinding: un dominio esterno fatto risolvere in `127.0.0.1` |
| Rifiuta le richieste di modifica (POST…) con un `Origin` diverso da quello dell'app. Un client senza `Origin`, come uno script o un IDE sul gateway `/v1`, passa | CSRF: una pagina che cambia la configurazione e punta un provider su un suo server per ricevere la chiave API |
| Rifiuta le richieste a `/api` e `/v1` fatte dal browser per conto di un altro sito (`Sec-Fetch-Site`), anche in lettura | letture e chiamate a pagamento lanciate da altri siti |
| Serve i siti generati dagli agenti in una sandbox con un'origine opaca (`Content-Security-Policy: sandbox`, senza `allow-same-origin`) | un sito generato, magari guidato da una pagina malevola, che usa le API dell'app |
| `X-Frame-Options: DENY` e `frame-ancestors 'none'` su ogni pagina, più `nosniff` | clickjacking |
| `web_fetch` legge solo indirizzi pubblici e si connette all'indirizzo che ha controllato | SSRF: un agente spinto a leggere `127.0.0.1`, la rete privata o i metadati cloud |
| Il token di `AGENT_WORLD_API_KEY` si confronta a tempo costante | indovinare il token del gateway `/v1` |

**Da sapere:**
- **Anteprima dei siti generati.** Nella sandbox i loro script girano, ma non hanno `localStorage` né cookie. Se un sito ne ha bisogno, aprilo dalla cartella del run.
- **Comandi shell.** `AGENT_WORLD_ALLOW_SHELL=1` dà agli agenti una shell nella cartella del run. Un agente guidato da una pagina malevola può eseguire comandi: tienila spenta se non ti serve.
- **I 403 di queste regole** hanno il messaggio "Richiesta rifiutata: …".

### Usarlo in LAN

Di default il server risponde solo a questa macchina. Per aprirlo ad altri dispositivi della rete:

1. In `config/local.json` fai ascoltare il server su tutte le interfacce:
   ```json
   { "server": { "host": "0.0.0.0" } }
   ```
2. In `.env` elenca i nomi o gli indirizzi con cui gli altri lo raggiungeranno, separati da virgole:
   ```sh
   AGENT_WORLD_ALLOWED_HOSTS=192.168.1.20,studio.lan
   ```
   Senza questa riga ogni richiesta con un altro `Host` riceve 403 "Host non ammesso".
3. Riavvia e apri `http://192.168.1.20:4300` dall'altro dispositivo.

> **Attenzione: `/api` non ha login.** Chi raggiunge il server dalla rete ne ha il controllo completo: avvia missioni, legge i file dei run e cambia la configurazione, compresi gli URL dei provider a cui il router manda le tue chiavi. Fallo solo su una rete di cui ti fidi. `AGENT_WORLD_API_KEY` protegge solo il gateway `/v1`.

---

## Test

```sh
npm test               # tutto: mondo 3D, dizionari delle lingue, avvio del backend, pytest, smoke, flussi, scansione dei segreti, cartelle temporanee
npm run test:backend   # solo il backend: avvio e pytest
npm run test:browser   # runner headless: 254 verifiche sul front-end vero (~5 min)
npm run scan:secrets   # audit di tutta la history: chiavi, percorsi assoluti, dati personali
```

- **`pytest` (796 test):** route e file statici, configurazione, store, bus ed eventi SSE, router e adapter dei provider con server finti, gateway, piano, tasker, team, tools, web, media, Brain, Skill Hub, RAG, Skiller e download, lingue (`test_i18n.py`), sicurezza (`test_security.py`: CSRF, DNS rebinding, sandbox dell'anteprima, clickjacking, SSRF), parità Python/Rust; per la spec 09 failover senza fermate, file del proprietario, dialogo con un task e domande tra sessioni, ripresa, arbitro TypeSafe, modifiche dopo la fine, provider registrati (`test_failover.py`, `test_attachments.py`, `test_owner_files.py`, `test_resume.py`, `test_arbiter.py`, `test_refine.py`, `test_providers_api.py`).
- **Dizionari della UI** (`scripts/i18n-test.js`): ogni lingua ha le chiavi e i segnaposto dell'inglese, una voce sua, ed è tradotta davvero; `index.html` è in inglese.
- **Smoke:** un'intera missione complessa in demo, con sub-agenti, revisioni ed escalation.
- **Flussi:** approvazione e rifiuto del piano, chat che guida il lavoro, pausa, ripresa e stop.
- **Runner del browser:** apre l'app in Edge o Chrome headless e misura inquadratura, etichette, sovrapposizioni dei pannelli, input, le cinque lingue e una missione completa. Con un clock fisso controlla anche che i sub-agenti lavorino solo al loro posto (A10). La fase `recovery` (spec 09) carica file con trascinamento, incolla e 📎, parla con un task bloccato e riprende il workflow, chiede una modifica a fine missione e registra un provider dalle Impostazioni. I rossi attesi stanno in `scripts/browser/known-red.json`.
- **Igiene:** i test non lasciano processi del browser né cartelle temporanee, nemmeno quando falliscono (`npm run sweep` ripulisce dopo un'interruzione).
- **Su ogni sistema:** `npm test` gira uguale su Windows, Linux e macOS. Un server di test si chiude con lo script che l'ha avviato, anche quando lo script viene ucciso dall'esterno. Il runner del browser cerca Edge o Chrome nei percorsi standard; altrimenti indica il browser con `BROWSER`.

Tutti i test girano in demo: le chiavi vengono svuotate anche se sono in `.env`.

**Niente segreti nei commit.** `npm install` attiva gli hook di `scripts/hooks/`. A ogni commit, `scripts/secret-scan.js` blocca:
- chiavi API e token, e valori `NOME_KEY=...` scritti per esteso;
- percorsi assoluti della tua macchina;
- file `.env`, `config/local.json` e i dati in `data/`;
- le parole personali elencate in `.git/info/personal-words`, un file che resta solo sulla tua macchina.

Quello che trova lo stampa oscurato.

---

## Struttura del repository

```
agent-world/
├─ backend/                 backend FastAPI (progetto uv)
│  ├─ backend/              app.py · bus.py · run.py · tasker.py · team.py · tools.py · i18n.py · security.py · attachments.py · arbiter.py
│  │  ├─ routes/            api_state · runs · providers · skills_brain · events (SSE) · gateway (/v1) · static
│  │  └─ router/            index (OmniRoute) · providers · profiler · mock (demo)
│  ├─ tests/                pytest
│  └─ bench/                bm25_bench.py (soglia 5×)
├─ crates/aw_core/          modulo nativo Rust (PyO3 + maturin)
├─ public/                  front-end: index.html, css/, js/main.js, js/i18n.js, js/world/ (three.js)
├─ config/default.json      team, combo, provider, skill
├─ skills/                  skill dell'app (+ vendor/ per le repo clonate)
├─ scripts/                 strumenti di test Node e runner del browser
└─ docs/
   ├─ specs/                spec, ticket, report, review e retro di ogni ciclo
   └─ assets/               screenshot del README
```

Il progetto è cresciuto per cicli di Specs Driven Development. Ogni cambio importante ha in [`docs/specs/`](docs/specs/) la sua spec, i ticket, il report "prima e dopo", la review e la retro. Il porting a FastAPI e Rust è la [spec 04](docs/specs/04-backend-port.md); le lingue sono la [spec 06](docs/specs/06-language.md), il controllo di sicurezza la [spec 07](docs/specs/07-security.md), router, RAG e media la [spec 08](docs/specs/08-router-rag-media.md), file del proprietario, dialogo, ripresa e failover la [spec 09](docs/specs/09-multimodal-interactive-recovery.md).
