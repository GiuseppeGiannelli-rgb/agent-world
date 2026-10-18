# Spec 10 — Assunzione parametrica dei modelli, routing per sotto-task, RAG a incrocio tra agenti

**In breve.** Richiesta dall'utente il 18/10/2026, partendo da `main` = `937673a`.
- Oggi un worker o un sub-agente lavora sempre sulla combo fissa del suo team (Sviluppo su `code`, Contenuti su `fast`…), qualunque cosa debba fare.
- Con la spec 10 ogni sotto-task **"assume" il suo modello**: il profiler dà a ogni modello una matrice di competenza (taglia, specialità, costo, salute), e `router/hiring.py` incrocia quella matrice con i requisiti del sotto-task. Ne esce una catena di candidati dedicata, e se il modello assunto fallisce subentra il candidato compatibile successivo, senza fermare il lavoro.
- La memoria della run diventa un **bus a incrocio** tra worker, sub-agenti, modelli e QA. Le scoperte dei file (palette, classi, percorsi, titoli) si pubblicano subito; quando un agente collegato consegna, o un modello cambia, il worker riceve un blocco `[LIVE CROSS-AGENT UPDATE]` recuperato con RRF.
- Il prompt cambia forma secondo la famiglia e la taglia del modello assunto: reasoning, coder o piccolo/locale/free.
- La scheda Router e la scheda Task mostrano chi è stato assunto e perché; `GET /api/state` espone il catalogo profilato.

**Stato:** chiusa il 18/10/2026, in due parti: parte 1 (`354f9a7`: R1–R3), parte 2 (`be1c96e` R4, `bee15ca` R5, più i documenti). Le decisioni D1–D9 sono confermate dall'utente; D10–D12 sono nate nella parte 2. Verifiche e deviazioni nei §6 e §7.

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

D1–D9 prese da me per portare avanti il lavoro e confermate dall'utente il 18/10/2026 (compreso il camelCase di `costTier` e `health`). D10–D12 vengono dalla parte 2: l'utente può ribaltarle.

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
| D10 | Se una revisione assume un altro modello, il `MODEL SWITCH` (nella forma del modello nuovo) arriva prima del suo primo passo, non dopo la prima risposta | altrimenti il primo passo del modello nuovo parte con la forma vecchia: visto nel test live, dove un 8B gratuito alla revisione lascia il posto a Claude Sonnet |
| D11 | L'esempio di una skill è la sezione "Example" (cinque lingue) solo se la parola apre il titolo, al più dopo un'altra parola, e il titolo non parla di cosa evitare; poi il primo blocco di codice; senza skill, un turno d'esempio costruito dal task | "Bad examples" o "Esempi sbagliati" sono proprio quello che un modello piccolo non deve imitare (il test lo ha trovato al primo giro) |
| D12 | Nel runner del browser le assunzioni live e il subentro arrivano dalla risposta di rete di una run salvata, costruita dalla run demo nella forma che scrive `hiring.py` | la demo non assume nessuno (D5), e il runner gira solo in demo; il resto della pagina (rendering, clic, schede, i18n) è quello vero |

## 5. Verifiche (test scritti prima del codice, visti rossi)

- `test_hiring.py`: la matrice di competenza su modelli tipici (locale 7B, `:free` da 70B, flagship, coder); l'analisi nelle cinque lingue; la catena (un task complesso di codice assume un modello grande, uno semplice un modello free o locale, i bersagli non sani escono o scendono); la promozione; una run live con provider finti, in cui un credito finito a metà passo fa subentrare il candidato successivo e la run arriva in fondo; la demo che resta com'era.
- `test_crossbus.py`: i fatti dei file; il blocco live dopo una consegna collegata, e nessun blocco per un workstream non collegato; il blocco dopo un cambio di modello; mai lo stesso elemento due volte; l'ordine RRF.
- `test_hiring.py`, sezione R4 (al posto di un `test_prompt_shape.py`: l'utente ha chiesto i test in `test_hiring.py`): le quattro forme su 18 modelli tipici; per un piccolo i passi atomici, l'esempio della skill e il contratto in fondo; per un reasoning checklist, vincoli e lezioni prima della descrizione; per un coder albero, interfacce e snippet; generale e demo come prima; un failover verso un piccolo che porta la sua forma; il validatore (piccolo sì, generale no); l'esempio di una skill in cinque lingue; una run live su un mercato misto.
- `test_state.py`: `router.catalog` in `/api/state`.
- Runner del browser, fase `hiring` (R5, 6 controlli): la scheda Task e la scheda Router dopo la missione demo, più una run con assunzioni live e un subentro (D12).

## 6. Come è fatta la parte 2, e le deviazioni

**R4, la forma del prompt.**
- `rag_budget.shape(profile)`, nell'ordine di D6:
  - **piccolo**: locale, gratuito (`:free`, i tier gratuiti) o 14B e meno (`sizeB`, o `paramsB`);
  - **reasoning**: la famiglia reasoning del profiler, più `gemini-*-pro`;
  - **coder**: la famiglia coder, più DeepSeek, Claude Sonnet, GPT-5, Codestral, Devstral;
  - **generale**: il resto, e il simulatore sempre.
  
  `budget()` porta la forma; un piccolo ha sempre il contratto JSON.
- `Run.rag_context` aggiunge `lead`, i blocchi che aprono il brief (`prompts.shape_lead`), solo all'avvio e a un cambio di modello:
  - piccolo: `STEPS` numerati (guarda la cartella, leggi i file dei compagni, scrivi ogni file, controlla, `finish`), poi `EXAMPLE FROM YOUR SKILL` o `EXAMPLE OF ONE GOOD TURN`;
  - reasoning: `QA CHECKLIST` (`[ ]` per ogni criterio), `CONSTRAINTS` (trappole, il lavoro da cui dipende, palette e interfacce dei file collegati), `LESSONS FROM THE BRAIN` (le lezioni per prime; più sotto `FROM THE BRAIN` rimanda in alto);
  - coder: `PROJECT TREE` (cartelle prima, righe rientrate così nessuno le legge come la lista `PROJECT FILES`), `INTERFACES TO RESPECT`, `SKILL SNIPPETS` (i blocchi di codice delle skill: 3 e 2400 caratteri con il contesto pieno, 2 e 1200 con quello compatto).
  
  Nessuna riga dei blocchi comincia con un campo che il simulatore legge (`GOAL:`, `TASK:`, `OUTPUTS:`…): i test live passano con le risposte del simulatore.
- `tasker_system` aggiunge una regola per forma; il contratto resta l'ultima cosa del system prompt.
- Il Tasker tiene `shape` (all'avvio, alla ripresa, a ogni cambio). Per un piccolo:
  - il **validatore** (`tasker.missing_args`, `REQUIRED_ARGS`): un'azione a cui manca un argomento obbligatorio, o che lo ha vuoto, riceve un `FORMAT ERROR` con l'argomento e la riga del tool, e non arriva al tool;
  - dopo ogni `RESULT` una riga `NEXT: reply with ONE JSON object only…`: il contratto a ogni turno.
- Il record dell'assunzione dice la forma (`hire.shape`, e `shape` in ogni candidato).

**R5, l'interfaccia.**
- Scheda Task: il badge 🤝 con il modello, il tier e la specialità più pesata dal matcher (`top`, `topScore`); la lettura (categoria · livello); `🔀 replaced` con il motivo nel titolo. La scheda aperta: il perché, la forma del prompt, i candidati, ogni subentro. In demo: `demo · simulator` e la lettura.
- Scheda Router: "Hires in this run" (la run mostrata, subentri segnati) e "Profiled catalog" (taglia, con ≈ quando viene dalla famiglia; tier; costo; sette barre di specialità; salute della sessione; prima i modelli pronti). Si ridisegna anche a ogni evento `task`.
- 52 chiavi nuove in `i18n.js`, nelle cinque lingue.

**Deviazioni dalla spec.**
- I test della R4 stanno in `test_hiring.py`, non in `test_prompt_shape.py` (richiesta dell'utente).
- `skills.py`: oltre a `example()` e `snippets()` (metodi di `SkillLibrary`) ci sono le funzioni pure `example_of()` e `code_blocks()`, che i test usano senza libreria.
- D10, D11 e D12 non erano nella spec.
- Durante lo sviluppo il server di anteprima, avviato nello stesso worktree, ha scritto in `data/` e `skills/vendor/` mentre girava pytest, e la guardia N15 lo ha segnalato. Erano file dell'anteprima, non dei test: cancellati, e la suite finale è girata senza anteprima.

**Limiti noti.**
- Claude Opus, GPT-4o e i Llama a pagamento hanno la forma generale: non sono nelle famiglie della R4.
- Un modello gratuito ha la forma piccola qualunque sia la taglia (`groq/openai/gpt-oss-120b`, un 70B `:free`): è la definizione della richiesta.
- Le interfacce arrivano dai fatti dei file del lavoro collegato (R3); i file del proprietario non ne hanno.
- Tutto è provato con server finti, nessuna chiamata vera.

## 7. Chiusura: le verifiche (18–19/10/2026, Windows 11)

- **Test prima del codice, visti rossi:** parte 1 `test_hiring.py` (R1–R3) e `test_crossbus.py`; parte 2 i 26 test della sezione R4 di `test_hiring.py`, più 8 sull'esempio di una skill. Il test live su un mercato misto ha trovato D10, quello sull'esempio D11; una mutazione (senza il cambio anticipato alla revisione) fa rosso il test live.
- **`npm test`** verde in 7 min 45 s: **pytest 1013 passati e 3 saltati** (la parità Rust ×2 senza il modulo compilato, ffmpeg assente). Prima della spec 10: 934 passati.
- **`npm run test:browser`: 261 verifiche su 261, ALL OK** in 6 min 2 s, a 55,7 fps, con `known-red.json` vuoto: le 255 di prima più i 6 controlli della fase `hiring` (R5).
- **`npm run scan:secrets`:** pulito.
- **QA visivo** a 1920×1080 dagli screenshot del runner (`--shots`): la scheda Task in demo e con un subentro, la scheda Router con il catalogo.
- **Non verificato:** nessuna chiamata a un modello vero; la prima run LIVE con chiavi dirà se le forme del prompt aiutano davvero i modelli piccoli (è in "Da verificare" di `HANDOFF.md`).
