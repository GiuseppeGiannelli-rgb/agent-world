# Spec 08 — Router OmniRoute, profili dei modelli, RAG su misura, fallback dei media

**In breve.** Richiesta dall'utente il 16/10/2026, dopo run falliti in produzione con `Every target failed for "frontier"`.

**Le cause trovate nei log:**
- il 429 `insufficient_quota` di OpenAI veniva trattato come un limite temporaneo e ritentato;
- il 404 di Gemini su `gemini-2.5-pro` ("non più disponibile per i nuovi utenti") veniva raffreddato come un server occupato;
- una combo senza bersagli funzionanti lanciava un'eccezione invece di provare le altre;
- per la voce, `Media.run()` falliva quando OpenAI non aveva credito ed ElevenLabs chiedeva un piano a pagamento: il generatore locale si usava solo se nessun provider aveva una chiave. L'agente ha allora scritto a mano un `.mp3` finto di 133 byte, bocciato dal QA.

**Esito.** Sei parti, ognuna con test visti rossi prima del codice e mutazioni che li fanno tornare rossi. Front-end, eventi SSE e test esistenti invariati.

| Suite (Linux, container cloud) | Risultato |
|---|---|
| `pytest` | 626 passati, 3 saltati, 0 rossi |
| `npm test` (script Node) | tutti `ALL OK` / `OK` |

## 1. Router: perché una chiamata fallisce (`router/providers.py`, `router/index.py`)

`_classify()` dà a ogni errore un `kind`:

| kind | Quando | Cosa fa il router |
|---|---|---|
| `quota` | 402, oppure 400/403/429 il cui corpo dice `insufficient_quota`, `credit_balance_exhausted`, `credit balance`, `out of credits`, `insufficient balance`, `exceeded your current quota`, `billing`, `payment required` | l'intero provider resta fuori per `router.quotaCooldownMs` (6 h); i suoi altri modelli non si provano |
| `rate_limit` | 408/409/429, compreso il 429 "per minuto" di Gemini (che dice anche "exceeded your current quota", ma con `retryDelay`) | quel bersaglio si raffredda per il ritardo chiesto dal provider, altrimenti backoff 15 s → 5 min |
| `model_not_found` | 404, 410, oppure un 400 `model_not_found` | quel `provider/modello` va in blacklist per `router.deadModelTtlMs` (24 h); si provano subito i suoi `router.aliases`, prima del bersaglio successivo, e le chiamate dopo vanno dritte all'alias |
| `auth` | 401/403 | il provider resta fuori per `router.authCooldownMs` (10 min) |
| `server` / `network` | 5xx, errori di rete | raffreddamento del bersaglio |
| `bad_request` / `empty` | il resto | nessuna attesa |

Il secondo tentativo senza `response_format` avviene solo su un 400 generico: non quando il credito è finito o il modello non esiste.

## 2. Cascata tra combo

- Quando nessun bersaglio di una combo risponde, si continua lungo `router.cascade`: `frontier` → `smart` → `fast` → `free` → `local`. Una combo fuori dalla catena si aggancia dove dice `joins` (`code` → `smart`).
- Se non risponde nessuno, risponde il simulatore demo:
  - in modalità demo come sempre;
  - in una run live solo come **emergenza** (`router.emergencyMock`, attiva di default): evento `router.emergency`, avviso nel log, un messaggio di sistema nella run, una volta sola e nella sua lingua (`emergency_answer` in `i18n.py`), e il conteggio in `usage.emergencies`.
- Un modello esplicito tiene il suo errore. Il pulsante di test chiede `cascade=False, emergency=False`. Il gateway `/v1` può scendere lungo la cascata, ma non riceve mai una risposta inventata.
- Lo snapshot del router (`/api/router`) mantiene la sua forma: un modello sparito o un provider in panchina compaiono come `reason` e `coolingMs` dei loro bersagli.

## 3. Provider, combo e ruoli (`config/default.json`)

**Provider.**
- Nuovi: Together, Fireworks, SambaNova, Cohere (endpoint di compatibilità OpenAI, `https://api.cohere.ai/compatibility/v1`) e Hugging Face (`https://router.huggingface.co/v1`).
- `localopenai`: un server locale compatibile OpenAI (vLLM, llama.cpp, Jan) all'indirizzo `LOCAL_OPENAI_URL` (`baseUrlEnv`: è pronto solo se la variabile è impostata). `demoEnv()` la svuota insieme alle chiavi.
- Ollama e LM Studio restano spenti finché non li attivi.

**Scostamenti dalla richiesta, verificati sulle fonti ufficiali:**
- **GitHub Models non c'è.** GitHub l'ha ritirato del tutto il 30/07/2026 (playground, catalogo, API di inferenza e BYOK). L'endpoint indicato, `models.inference.ai.azure.com`, era già stato dismesso il 17/10/2025. Aggiungerlo avrebbe mandato il `GITHUB_TOKEN` a un servizio spento.
- **Modelli ritirati.** `gemini-2.5-pro` (404 per i nuovi utenti), `llama-3.3-70b-versatile` di Groq e i vecchi modelli di reasoning (`qwen-qwq-32b`, `deepseek-r1-distill-llama-70b`), `llama-3.3-70b` di Cerebras: non sono nelle combo, ma sono **alias** verso i modelli attuali (`gemini-3.1-pro-preview`, `gemini-2.5-flash`, `gpt-oss-120b`, `qwen-3.8-27b`). Così un `local.json` che li nomina ancora si ripara al primo 404.

**Combo.**
- `frontier`, `smart` e `fast` finiscono con fallback gratuiti (OpenRouter `:free`, Gemini Flash, Groq, Cerebras).
- Nuove `free` e `code`.

**Ruoli.**
- CEO e QA su `frontier`, Sviluppo su `code`, Prompt Lab e AI Generativa su `smart`, Ricerca, Contenuti, Design e Skill Hub su `fast`.
- `router.roles`:
  - un lead pianifica, aiuta (`ask_lead`) e salva (rescue) su `smart`;
  - un sub-agente lavora su `fast`, a meno di escalation;
  - il worker in escalation sale su `frontier`, come prima.

## 4. Profiler parametrico e scoperta dei modelli (`router/profiler.py`)

**Cosa ricava `profile()`.** Da nome e metadati di `/models`:
- miliardi di parametri: `70b`, `qwen3:8b`, `8x7b` = 56;
- famiglia: reasoning (`r1`, `qwq`, `o1`/`o3`/`o4`, `reasoner`, `gpt-oss`), coder, vision, piccolo (flash, haiku, mini, lite…), ammiraglia;
- finestra di contesto: dai metadati, altrimenti dalla famiglia; 8k per un server locale;
- gratuità: `:free`, il router free di OpenRouter, i free tier di Gemini Flash, Groq e Cerebras;
- esecuzione locale e supporto del JSON mode.

**Tier.**
- `frontier`: reasoning, ammiraglie e modelli da 70B in su;
- `code`: i coder;
- `smart`: 24–69B e i nomi di fascia media (sonnet, gpt-4o, deepseek-chat, command…);
- `fast`: i nomi piccoli e i modelli da 7 a 23B;
- `local`: un modello locale fino a 8B.

`compact` è vero per i modelli veloci, gratuiti, locali o con meno di 128k di contesto. Il simulatore conta come modello grande, così i prompt della demo non cambiano.

**Scoperta.**
- Il router chiede `/models` ai server locali pronti e a OpenRouter (`"discover": "free"`: solo i `:free`), all'avvio e ogni `router.discoverIntervalMs` (10 min).
- I modelli trovati entrano in coda alla combo del loro tier (`profiler.combos_for`), al massimo `router.discoverMax` (6) per combo. Un Ollama avviato dopo entra in `local`, e anche in `code` o `frontier` se è abbastanza grande.
- Ogni risposta porta il `profile` del suo modello.
- `AGENT_WORLD_DISCOVER=0` la spegne: lo impostano pytest e `demoEnv()`.

## 5. RAG su misura e memoria della run (`rag_budget.py`, `run_memory.py`, `run.py`, `tasker.py`, `skills.py`)

**Budget** (`Router.peek()` dà il profilo del modello che la chiamata raggiungerà più probabilmente, senza muovere niente):

| | completo (modello grande) | compatto (veloce, gratuito, locale) |
|---|---|---|
| Brain e lezioni del QA | 5 note, 400 caratteri | 3 punti essenziali, 140 caratteri |
| Skill assegnate | intere (fino a 3, 9000 caratteri) | i 2 passaggi più pertinenti (`SkillLibrary.passages`: chunk semantici, RRF di BM25 e coseno, `minCosine` più severo di 0,1) |
| Contesto della run | 12 file consegnati, 6 eventi | 6 file, 3 eventi |
| Contratto JSON | — | `OUTPUT CONTRACT` in fondo al system prompt |

**Memoria della run.**
- Ogni file scritto (testo e media), bocciatura, lezione del QA, errore di un tool e consegna viene indicizzato subito.
- BM25 più vettori n-gram locali: nessuna rete, nessun costo.
- Ogni elemento ha i tag di workstream, task, team e agente.

**Quando il worker la riceve:**
- all'avvio (anche un sub-agente appena generato): i percorsi reali consegnati dagli altri workstream e gli eventi più vicini al suo task;
- su una revisione: le lezioni che valgono;
- su un cambio di modello in corsa (fallback o escalation): un messaggio `MODEL SWITCH` con il contesto ridimensionato per il nuovo modello e, se serve, il contratto JSON.

**Riparazione del JSON.** Le risposte tipiche dei modelli piccoli diventano un'azione invece di "Risposta non valida, riprovo":
- letterali Python (`literal_eval`: solo letterali, mai codice);
- chiavi senza virgolette;
- parentesi tagliate alla fine, ma non dentro una stringa, per non scrivere mezzo file;
- `Write_File()`, `functions.read_file`;
- `args` come stringa;
- la forma `function`/`arguments` di OpenAI;
- argomenti accanto al tool.

## 6. Fallback dei media e degli embedding (`media.py`, `embed.py`)

- Gli errori dei media si leggono come quelli del router: un provider senza credito o con la chiave rifiutata resta fuori per la sessione.
- **Voce, in una run live** (`Media.chain`):
  1. i provider cloud;
  2. edge-tts, se installato (`uv add edge-tts`) e attivato: è un opt-in perché manda il testo a Microsoft;
  3. il sintetizzatore del sistema (SAPI su Windows, `say` su macOS, `espeak-ng` su Linux): offline, gratis, una voce vera lunga quanto il testo. Il testo passa su stdin, mai sulla riga di comando;
  4. il jingle demo, come ultima risorsa.
- **Immagini, in una run live:** i provider cloud, Pollinations solo se attivato (opt-in come prima: manda il prompt fuori), poi il generatore locale.
- Le run demo e lo stato dei media restano invariati.
- **Formato.** Il file ha il formato che ha davvero. Un WAV chiesto come `.mp3` viene convertito con ffmpeg, se c'è; altrimenti si salva come `.wav`, e il `.mp3` atteso dal task conta come consegnato.
- `write_file` rifiuta i file media: arrivano solo da `generate_image` e `generate_speech`.
- Nel dump dei file il QA legge la durata di un audio e le dimensioni di un'immagine.
- **Embedding.** Un 402/429 `insufficient_quota` (o una chiave rifiutata) mette in panchina il provider nel router, e risponde il modello successivo di `rag.embeddings`: OpenAI, Gemini, Mistral, Ollama, poi `local/ngram`.

## 7. Limiti noti

- Non ho chiavi vere: i modelli nuovi (in particolare i `:free` di OpenRouter, che cambiano spesso) li ho verificati sulle fonti, non con chiamate reali. Un nome sbagliato costa un 404 alla prima chiamata, poi va in blacklist.
- Con questo container (Linux, senza `espeak-ng`) il sintetizzatore del sistema non c'è: la catena della voce l'ho provata con un motore finto. La conversione ffmpeg, invece, è reale.
- Le soglie del profiler (70B, 24B, 128k) sono euristiche: un modello nuovo con un nome insolito finisce in `smart`.
