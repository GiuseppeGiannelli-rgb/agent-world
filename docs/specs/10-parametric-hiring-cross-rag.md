# Spec 10 — Assunzione parametrica dei modelli, routing per sotto-task, RAG a incrocio tra agenti

**In breve.** Richiesta dall'utente il 18/10/2026, partendo da `main` = `937673a`.
- Oggi un worker o un sub-agente lavora sempre sulla combo fissa del suo team (Sviluppo su `code`, Contenuti su `fast`…), qualunque cosa debba fare.
- Con la spec 10 ogni sotto-task **"assume" il suo modello**: il profiler dà a ogni modello una matrice di competenza (taglia, specialità, costo, salute), e `router/hiring.py` incrocia quella matrice con i requisiti del sotto-task. Ne esce una catena di candidati dedicata, e se il modello assunto fallisce subentra il candidato compatibile successivo, senza fermare il lavoro.
- La memoria della run diventa un **bus a incrocio** tra worker, sub-agenti, modelli e QA. Le scoperte dei file (palette, classi, percorsi, titoli) si pubblicano subito; quando un agente collegato consegna, o un modello cambia, il worker riceve un blocco `[LIVE CROSS-AGENT UPDATE]` recuperato con RRF.
- Il prompt cambia forma secondo la famiglia e la taglia del modello assunto: reasoning, coder o piccolo/locale/free.
- La scheda Router e la scheda Task mostrano chi è stato assunto e perché; `GET /api/state` espone il catalogo profilato.

**Stato:** in lavorazione (il riepilogo delle verifiche è in fondo, alla chiusura).

## 1. Il punto di partenza (misurato sul codice di `937673a`)

- `profiler.profile()` (spec 08) ricava dal nome: `paramsB` (solo se il nome lo dice), le famiglie (`reasoning`, `coder`, `vision`, `small`, `flagship`), `context`, `free`, `local`, `json`, `tier` e `compact`. Non c'è nessun punteggio per specialità, nessun costo, nessuna salute.
- `Router.chat()` riceve una combo (o un ruolo che diventa la combo del team) e la percorre, poi scende lungo `router.cascade`. Le statistiche (`stats`), i raffreddamenti, le panchine per credito finito e la blacklist dei modelli spariti ci sono già, ma servono solo a ordinare e saltare.
- `Tasker._use()` sceglie la combo di un worker: l'escalation (`frontier` dopo 2 revisioni), oppure `router.roles.sub` (`fast`) per un sub-agente, oppure la combo del team.
- `RunMemory` (spec 08) indicizza in BM25 + vettori locali i file scritti (primi 600 caratteri), i verdetti, le lezioni, i blocchi e le consegne. Un worker però la legge solo all'inizio, a ogni revisione e a ogni cambio di modello (`rag_context`): un sub-agente parallelo che consegna a metà del suo lavoro non lo raggiunge più.
- `rag_budget` (spec 08) ha due misure, `full` e `compact`; la forma del prompt è la stessa per ogni famiglia di modello.

## 2. Requisiti

### R1 — Matrice di competenza (`router/profiler.py`)
Per ogni modello del catalogo (combo statiche, alias, `:free` di OpenRouter, modelli scoperti da `/models` su Ollama, LM Studio, `localopenai` e sui provider con `discover`):
- **`paramsB`**: i miliardi di parametri scritti nel nome o nei metadati (come oggi, `null` se non si sa); **`sizeB`**: la taglia usata dal matcher, cioè `paramsB` o, se manca, la classe della famiglia (un flagship chiuso vale come 400B, un modello di fascia media come 70B, un nome "small" come 8B); `sizeSource` dice quale delle due;
- **`specialties`**: punteggi da 0 a 1 su `reasoning`, `coding`, `creative`, `research`, `vision`, `toolUse` (affidabilità sullo schema JSON delle azioni) e `speed`;
- **`costTier`**: `local`, `free`, `low` o `high`;
- **`health`** (dal router, non dal nome): chiamate, successi, fallimenti, tasso di successo, latenza media, stato (`ok`, `cooling`, `benched` per credito o chiave, `dead` per un 404, `unready` senza chiave) e il motivo.

I campi seguono la forma camelCase del resto dell'API: `param_billions` della richiesta è `paramsB`/`sizeB`, `cost_tier` è `costTier`, `live_health` è `health`, `tool_reliability` è `specialties.toolUse` (decisione D1).

### R2 — Analisi del sotto-task e catena dedicata (`router/hiring.py`)
- **Analisi**, senza modelli e senza rete: titolo, descrizione, criteri, file attesi, brief del Prompt Lab, skill di Otto, team, strumenti del team, dipendenze, revisioni ed escalation. Ne escono:
  - la **categoria**: `coding`, `creative`, `research`, `reasoning` o `general` (parole chiave nelle cinque lingue, estensioni dei file, team e strumenti);
  - la **complessità** da 0 a 1 e il **livello**: `simple`, `medium`, `complex`. Ogni revisione alza la complessità; un'escalation la porta a `complex`.
- **Catena**: tutti i modelli pronti del catalogo (provider con chiave, non in panchina, non in blacklist; esclusi il simulatore, TypeSafe e i modelli che non scrivono testo, come quelli di embedding), ordinati per affinità con il sotto-task:
  - specialità pesate dalla categoria;
  - taglia minima per livello: un task `complex` vuole 32B o più (meglio 70B+, `frontier`/`smart`/`code`), uno `medium` 14B o più, uno `simple` va bene con qualsiasi taglia;
  - costo: un task `simple` preferisce free e locale e penalizza i modelli costosi, così risparmia la quota pagata; un task `complex` non guarda al costo;
  - salute: il tasso di successo della sessione; un bersaglio che si sta raffreddando va in fondo;
  - affidabilità JSON: sotto una soglia il modello scende.
- Tra i primi `router.hiring.chain` candidati (6) si assume il primo. Dopo la catena restano la combo del team e la cascata di sempre (D3): le opzioni non sono mai meno di prima.
- **Promozione**: se il modello assunto fallisce a metà di un passo (credito finito, 429, 404, rete), il router prova subito il candidato successivo della catena, nella stessa chiamata. Il Tasker registra il subentro (`hire.replacements`) e ricalcola la catena con la salute nuova, così i passi successivi partono dal sostituto.
- Si assume alla creazione dei sotto-task (dopo le skill di Otto e il brief del Prompt Lab), e di nuovo quando il task parte e a ogni revisione, con la salute del momento.

### R3 — Bus a incrocio tra agenti (`crossbus.py`, `run.py`, `tasker.py`)
- **Pubblicazione continua** nella memoria della run (BM25 + vettori), con workstream, task, team e agente:
  - i fatti estratti da ogni file scritto: la palette (colori esadecimali, variabili CSS), le classi e gli id (CSS, HTML), le funzioni e le costanti esportate (JS, Python), i titoli di un testo (Markdown, HTML), le chiavi di un JSON, i file collegati (`src`, `href`);
  - le consegne, i verdetti e le lezioni del QA (gli avvisi di Vera compresi), i blocchi: come oggi.
- **Aggiornamento live a ogni passo critico**: prima del passo successivo di un worker, se dall'ultimo aggiornamento
  - un altro agente ha consegnato un sotto-task collegato (stesso workstream, workstream da cui dipende o che dipende da lui, task da cui dipende), oppure
  - il QA ha dato un verdetto su un sotto-task collegato, oppure
  - il worker stesso ha cambiato modello,
  
  il worker riceve un blocco `[LIVE CROSS-AGENT UPDATE]`: i percorsi reali dei file appena prodotti dagli altri e gli elementi più vicini al suo task (RRF di BM25 e coseno) tra quelli pubblicati dopo il suo ultimo aggiornamento, misurati sul modello assunto. Mai due volte lo stesso elemento.

### R4 — Forma del prompt secondo il modello (`rag_budget.py`, `prompts.py`, `run.py`, `skills.py`)
La forma si decide dal profilo del modello assunto, in quest'ordine:
1. **piccolo** (locale, `:free`, o 14B e meno): istruzioni atomiche passo per passo, generate dal task (i file da leggere, ogni file da scrivere, il controllo, `finish`); un esempio estratto dalla skill assegnata (il primo blocco di codice o la sezione "Example"); il contratto JSON; e un **validatore** a ogni turno: un'azione a cui manca un argomento obbligatorio (per esempio `write_file` senza `content`) riceve un `FORMAT ERROR` che dice cosa manca, invece di arrivare al tool;
2. **reasoning** (`r1`, `qwq`, `o1`/`o3`/`o4`, `gemini-*-pro`, `thinking`): i criteri di accettazione del QA come lista di controllo, i vincoli (trappole, dipendenze, interfacce dei file collegati) e le lezioni del Brain per prime;
3. **coder / tool-use** (`coder`, `deepseek`, `claude-sonnet`, `gpt-5`, `codestral`, `devstral`): gli snippet tecnici delle skill (i blocchi di codice), l'albero esatto della cartella del progetto e le interfacce da rispettare (classi, id, funzioni dei file collegati);
4. **generale**: la forma di oggi. Il simulatore demo resta qui, quindi la demo non cambia.

### R5 — Interfaccia e telemetria (`public/`, `state.py`, `router/index.py`)
- **Scheda Task**: ogni sotto-task mostra il modello assunto, la categoria e il livello. Nel dettaglio: il perché (specialità e taglia scelte dal matcher, costo), i primi candidati della catena e i subentri per failover o credito finito, con il motivo.
- **Scheda Router**: una sezione "Assunzioni" con i sotto-task della run e il loro modello, i subentri segnati; una sezione "Catalogo" con i modelli profilati: taglia, tier, costo, specialità, salute.
- **`GET /api/state`** e **`GET /api/router`**: `router.catalog` con il catalogo profilato.

## 3. Progetto

- `router/profiler.py`: `size_of()`, `specialties()`, `cost_tier()`; `profile()` aggiunge `sizeB`, `sizeSource`, `specialties`, `costTier`. Funzioni pure, senza rete.
- `router/index.py`:
  - `catalog()`: i modelli delle combo, gli alias e quelli scoperti, senza duplicati, ognuno con profilo, `ready` e `health`;
  - `health(key)`: dalle statistiche, dai raffreddamenti, dalle panchine e dalla blacklist;
  - `chat(..., chain=[...])`: una catena esplicita, provata per prima; dopo, la combo del ruolo e la sua cascata. Nei log e nelle statistiche la catena si chiama `hire`.
- `router/hiring.py`:
  - `analyze(task, cfg)` → categoria, complessità, livello, bisogni;
  - `rank(analysis, catalog)` → la catena con un punteggio e un perché per ognuno;
  - `hire(task, cfg, router)` → il record `task["hire"]`;
  - `promote(hire, res, router)` → il subentro.
- `run.py` / `tasker.py`:
  - si assume in `prepare` (e nelle missioni semplici), all'avvio del task e alla revisione;
  - `Tasker` chiama con `chain=hire.chain`;
  - un subentro aggiorna `task["hire"]`, una nota `hire` e l'evento `task`.
- `crossbus.py`:
  - `facts_from_file(path, content)`;
  - `linked(task_a, task_b, run)`;
  - `RunMemory` numera ogni elemento (`seq`), e un Tasker tiene il suo cursore;
  - `Run.cross_update(task, agent, since)` → il blocco, o niente.
- `rag_budget.py`: `shape(profile)` → `small`, `reasoning`, `coder`, `general`. `prompts.py`: i blocchi delle quattro forme. `skills.py`: `example(skill_id)` e `snippets(skill_id)`.

## 4. Decisioni

Prese da me per portare avanti il lavoro; l'utente può ribaltarle.

| # | Decisione | Perché |
|---|---|---|
| D1 | Campi in camelCase (`paramsB`, `sizeB`, `specialties.toolUse`, `costTier`, `health`) | è la forma di tutta l'API (`coolingMs`, `paramsB`); la mappa con i nomi della richiesta è in R1 |
| D2 | Si assume per worker e sub-agenti; CEO, lead, QA, Skill Hub e Prompt Lab restano sui loro tier (spec 08) | è quello che chiede la richiesta; i ruoli di servizio hanno già un tier pensato per loro |
| D3 | Dopo la catena assunta restano la combo del team e la cascata | il "senza fermate" della spec 09 non deve perdere nessuna opzione |
| D4 | L'escalation dopo 2 revisioni riassume con livello `complex` e taglia `frontier` invece di passare alla combo `frontier`; note, contatori e messaggi restano | è lo stesso effetto, ma passa dal matcher e dalla salute |
| D5 | Senza provider pronti (demo) non si assume nessuno: il record dice "demo" e il worker usa la combo di sempre, cioè il simulatore | la demo resta identica e i test di oggi non cambiano |
| D6 | Ordine delle forme del prompt: piccolo, reasoning, coder, generale | un `qwen-coder` da 7B ha bisogno di passi atomici più che di snippet |
| D7 | Un solo blocco live per passo, misurato sul budget del modello (spec 08) | un aggiornamento che si allunga a ogni passo riempirebbe la finestra dei modelli piccoli |
| D8 | Nessun tipo di evento SSE nuovo: l'assunzione viaggia nel task, il catalogo nella fotografia del router | i client di oggi restano compatibili |
| D9 | La salute vale per la sessione del server (dall'avvio) e non si salva | è "le ultime chiamate della sessione"; dopo un riavvio i modelli ripartono alla pari |

## 5. Verifiche (test scritti prima del codice, visti rossi)

- `test_hiring.py`: la matrice di competenza su modelli tipici (locale 7B, `:free` da 70B, flagship, coder); l'analisi nelle cinque lingue; la catena (un task complesso di codice assume un modello grande, uno semplice un modello free o locale, i bersagli non sani escono o scendono); la promozione; una run live con provider finti, in cui un credito finito a metà passo fa subentrare il candidato successivo e la run arriva in fondo; la demo che resta com'era.
- `test_crossbus.py`: i fatti dei file; il blocco live dopo una consegna collegata, e nessun blocco per un workstream non collegato; il blocco dopo un cambio di modello; mai lo stesso elemento due volte; l'ordine RRF.
- `test_prompt_shape.py`: le quattro forme; per i modelli piccoli i passi atomici, l'esempio della skill e il validatore che ferma un'azione incompleta.
- `test_state.py`: `router.catalog` in `/api/state`.
- Runner del browser: la scheda Task e la scheda Router mostrano l'assunzione dopo la missione demo.
