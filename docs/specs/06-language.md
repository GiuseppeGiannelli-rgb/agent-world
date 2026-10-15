# Spec 06 — Lingua globale (Italiano / Inglese)

**In breve.** Si sceglie la lingua dell'app (Italiano o Inglese) una volta sola. La scelta cambia:
- l'interfaccia, subito e senza ricaricare la pagina;
- la voce, cioè la sintesi vocale e la dettatura;
- la lingua in cui gli agenti ragionano, scrivono i log e rispondono;
- i messaggi di sistema che il backend manda via SSE.

Si salva in `config/local.json` come `ui.language` e vale fra una sessione e l'altra. Ogni run riceve la lingua nel payload e la tiene ferma fino alla fine.

Decisioni D1–D6 approvate dall'utente il 15/10/2026.

**Stato: fatta.** Backend, frontend e test ci sono tutti. Alla chiusura ho sistemato tre difetti trovati dalle verifiche, nessuno della lingua (§6, "Chiusura"). I risultati delle suite sono nel §7. Restano aperti i ticket N13–N16.

## 1. Decisioni

| # | Decisione |
|---|---|
| D1 | La lingua si salva in `ui.language`, dentro `config/local.json` (con `POST /api/config`). `POST /api/runs` la riceve come `language` e la salva in `run.data["language"]`: cambiarla durante un run non tocca il run in corso. |
| D2 | La UI non ha un'opzione "Auto". Con `language` assente o `None`, i prompt tengono la regola di prima (la lingua del GOAL); è solo un fallback interno. |
| D3 | Le etichette dei team si traducono con un dizionario del frontend, indicizzato per id del team. Se un team non è nel dizionario, si usa `label` di config. |
| D4 | I messaggi di sistema e i log di `run.py` mandati via SSE si traducono: messaggi, testi dei fumetti, errori di task e workstream, titoli delle note del Brain (`Missione ·`, `Lezione ·`), feedback automatici. Gli errori HTTP restano in italiano: ticket **N13**. |
| D5 | I testi del provider demo (`router/mock.py`) non si toccano: in inglese la demo resta in italiano. Ticket **N14**. |
| D6 | Branch `feat/spec06-language`, da `fix/start-port-message` (`809e0cb`). |

## 2. Contratto backend

**Lingue.** `backend/backend/i18n.py` contiene `LANGUAGES = {"it": "Italian", "en": "English"}`, il default `it`, `tr(lang, key, **vars)`, le tabelle `MESSAGES` per `it` ed `en` (stesse chiavi e stessi segnaposto) e `team_label(cfg, team, lang)`.

**Prompt.** `prompts.language_rule(lang)` sostituisce la costante `LANGUAGE`. Tutti i builder hanno il parametro `language=None`:
- `ceo_plan_prompt`
- `lead_plan_prompt`
- `advisor_prompt`
- `rescue_prompt`
- `librarian_prompt` (prima non aveva nessuna regola)
- `prompt_eng_prompt`
- `tasker_system`, che vale per worker e sub-agenti
- `judge_prompt`
- `synth_prompt`
- `chat_prompt` (prima: "nella lingua che usa l'utente")

Con una lingua scelta, la regola chiede di usare quella lingua per pensieri, messaggi, sintesi, report e testi consegnati, in qualunque lingua siano il GOAL o gli input. Le chiavi JSON, i valori fissi (`pass`, `revise`, `retry`, `skip`…) e i nomi dei tool restano come sono scritti: il parsing e il provider demo non cambiano. Una lingua sconosciuta solleva `ValueError`.

**Route.**
- `POST /api/runs`: `language` è opzionale. Un valore assente o `null` prende `ui.language` di config. Un valore fuori da `LANGUAGES` dà 400 (`"Lingua non supportata: …"`, in italiano, vedi N13).
- `POST /api/chat/:id`: usa la lingua del run attivo, se c'è, altrimenti `ui.language`.
- `POST /api/config`: `ui` è fra le chiavi modificabili (`EDITABLE`), e `/api/state` e `/api/config` la espongono. Dà 400 (`"Lingua non supportata: …"`) e non scrive niente se `ui` non è un oggetto o se `ui.language` non è una stringa di `LANGUAGES`.

**Run.** `Run(options={"language": …})` salva la lingua in `data["language"]` e la passa a ogni builder e a ogni `tr()`.

## 3. Frontend

- `public/js/i18n.js` contiene i dizionari `it`/`en`, `t(key, vars)`, `LOCALE = {it: 'it-IT', en: 'en-US'}` e le etichette dei team.
- Il selettore della lingua sta nella modale Impostazioni e, in forma compatta, nella topbar.
- Quando la lingua cambia:
  - si salva con `POST /api/config` (`{ui: {language}}`);
  - `<html lang>` si aggiorna;
  - si chiama `invalidate(...ALL)`;
  - i testi statici di `index.html` (marcati con `data-i18n`) si riscrivono.
- `say()`, `listen()` e le date usano `LOCALE[lang]`.
- `POST /api/runs` manda `language`.

## 4. Test (scritti prima del codice, visti rossi)

**Python**
- `test_prompts.py`: in ogni builder e in entrambe le lingue, il system prompt contiene la regola; con `None` resta la regola di prima; una lingua sconosciuta dà errore; il mock legge ancora i prompt.
- `test_i18n.py`: `it` ed `en` hanno le stesse chiavi e gli stessi segnaposto.
- `test_runs.py`: `language` arriva nelle options; senza `language` vale quella di config; un valore non valido dà 400; la chat usa la lingua giusta.
- `test_config.py`: `ui.language` si salva in `local.json` ed è pubblica.
- `test_run.py`: un run demo in `en` manda la regola "English" in **ogni** chiamata al modello. Nessun messaggio, fumetto, errore o titolo del Brain contiene i pezzi fissi dei testi italiani di `MESSAGES["it"]`.

**Node/browser**
- Il cambio di lingua aggiorna la UI senza reload.
- Il payload del run contiene `language`.
- `utterance.lang` vale `en-US`.
- La scelta resta dopo un reload.

## 5. Ticket aperti

- **N13**: errori HTTP del backend ancora in italiano.
- **N14**: testi del provider demo solo in italiano.
- **N15**: `test_state.py::test_api_config_post_updates_and_emits` scrive nel vero `config/local.json` (per questo lì c'è `limits.maxParallel = 3`). Va isolato su una cartella temporanea. È un problema preesistente, fuori da questa spec. Lo fanno anche i due test di `test_events.py` che chiamano `POST /api/config` (`maxParallel` 1…5): `live_server` crea l'app con il `Config` del repo.
- **N16**: test che passano solo su Windows. Su Linux sono rossi anche su `main`, quindi non c'entrano con questa spec.
  - `test_static.py::test_traversal_forbidden[/..\..\server\index.js]` e `test_tools.py::TestWorkspace::test_resolve_keeps_paths_inside_the_root` (`..\..\x`, `C:/Windows/x`). Su Linux `\` non separa i percorsi e `C:` non è un drive: `..\..\x` è il nome di un file dentro la cartella del progetto, quindi niente esce dalla radice. Il contenimento regge, ma i test si aspettano il rifiuto che fa Windows. Strade possibili: rifiutare `\` e `X:` su ogni sistema, così la regola è una sola e i workspace restano portabili; oppure separare le attese per piattaforma.
  - `temp-test.js` C3, "a killed smoke leaves its folder": uccide lo smoke con `taskkill /PID … /F`, che su Linux non esiste. Lo smoke non viene ucciso, finisce da solo e pulisce la sua cartella (`leftByTheKill: false`). Fuori da Windows serve un kill forzato equivalente (`SIGKILL`).
  - Altre ipotesi di Windows trovate qui: `scripts/lib/backend-launcher.js` cerca solo `backend/.venv/Scripts/python.exe` (su Linux e macOS è `.venv/bin/python`), e `scripts/browser/headless.js` trova solo Edge o Chrome installati. Per le verifiche del §7 ho usato un symlink dentro `.venv` (ignorato da git) e `BROWSER` puntato a Chromium con `--no-sandbox`.

## 6. Scostamenti

**Backend (15/10/2026)**
- `run.data` ha un campo nuovo, `language`. Quindi la forma "Node" del run, controllata da `TestDataShape`, ora ha una chiave in più.
- D3 vale anche per il backend: `i18n.TEAM_LABELS` traduce in inglese le etichette dei team negli elenchi che `run.py` scrive (piano, richiesta di approvazione). Se un team non è nella tabella, si usa `label` di config, come nel frontend.
- `POST /api/config` rifiuta con 400 un `ui.language` non supportato, prima di scrivere `local.json`.
- Il tag `missione` delle note del Brain resta così: è un identificativo, non un testo da mostrare.
- Il test anti-italiano del run in inglese prima toglie dai testi quello che ha scritto il modello, cioè il provider demo (D5): controlla solo le parole del backend. Ho provato che può fallire con due mutazioni:
  - `"Consegnato!"` rimesso come testo fisso;
  - `language` tolto dalla chiamata del judge.

  In entrambi i casi il test è diventato rosso.
- La demo non passa da `rescue` e da `advise`: per quei due builder la regola della lingua è coperta dai test dei prompt, non dal run end-to-end.

**Frontend (15/10/2026)**
- Quando cambia la lingua, `world.build()` non viene chiamato, perché ricostruirebbe la scena e riporterebbe ogni agente alla scrivania a metà run. Al suo posto c'è `World.relabel()`, che cambia solo i testi delle etichette delle stanze e del Brain.
- La lingua si applica a ogni evento `config`: una scelta fatta in un'altra scheda arriva anche a questa.
- Il selettore delle Impostazioni manda `ui.language` insieme alle altre impostazioni. Quello della topbar la salva subito.
- Fase browser `language` (L1–L7) in `scripts/browser-test.js`:
  - il server di prova legge il `config/` del repo, quindi la fase salva `config/local.json` e alla fine lo rimette identico (verificato con `diff`);
  - la richiesta del run e la voce sono simulate dentro la pagina: non parte nessuna missione e nessun audio;
  - ho provato che i controlli possono fallire con tre mutazioni: senza `language` nel payload diventa rosso L4, con `u.lang = 'it-IT'` diventa rosso L5, senza `relabel()` diventa rosso L2. In ogni caso è diventato rosso solo il controllo atteso.
- `brief` e `title` dei team sono già in inglese in `default.json` e restano come sono. Il titolo del CEO (`ceo.title`, "CEO · Regia") si traduce come le etichette dei team (D3): la chiave `team.ceo.title` c'è solo in inglese, e in italiano si usa il valore di config.

**Chiusura (15/10/2026).** Tre difetti trovati dalle verifiche, nessuno della lingua. Ognuno ha il suo commit con il test visto rosso prima della correzione.
- `df7ef3c` — `test_events.py::test_config_post_produces_sse_frame` voleva il frame `config` subito dopo `retry`, con `seq` 1. La reindicizzazione dello Skill Hub all'avvio però emette `skills` sullo stesso bus, e su una macchina veloce arriva prima. Era rosso anche su `main`. Ora il test salta gli altri frame, come già faceva `test_ping_on_idle`, e controlla che `seq` cresca. Con l'evento `config` rinominato diventa rosso in circa 6 s, invece di restare appeso ad aspettare i ping da 15 s.
- `ca94b53` — due difetti del controllo della porta occupata (`809e0cb`), visti su Linux, dove `flows-test.js` falliva con "fetch failed" subito dopo `backend-boot-test.js` (stessa porta, 4398):
  - il bind di prova non usava `SO_REUSEADDR`, quindi le connessioni in TIME_WAIT di un server appena chiuso risultavano "occupate", mentre uvicorn avrebbe fatto il bind senza problemi. Ora il bind di prova fa come uvicorn. Su Windows `SO_REUSEADDR` resta spento, perché lì permetterebbe di fare il bind sopra un listener vivo;
  - il messaggio cominciava con `Agent World  →`, cioè la riga di avvio che gli script aspettano su stdout, e così i test andavano avanti contro un server mai partito. Ora va su stderr e senza quel prefisso.
- `402896d` — `POST /api/config` con `ui.language` lista o oggetto: `x in LANGUAGES` sollevava `TypeError` e la risposta era 500. Ora si controlla prima il tipo, come faceva già `POST /api/runs`, e la risposta è 400.

## 7. Verifiche finali (15/10/2026)

Fatte su Linux (container cloud), quindi non sulla macchina Windows di riferimento. Per ogni rosso ho rifatto lo stesso controllo su `main`, nello stesso ambiente.

| Suite | Risultato | I rossi |
|---|---|---|
| `pytest` | 355 passati, 3 saltati, 2 rossi | i 2 test di percorsi Windows (N16), rossi anche su `main`. I saltati: `aw_core` non compilato (×2) e il clash di maiuscole, che esiste solo su volumi case-insensitive |
| `world-test`, `backend-boot-test`, `smoke`, `flows-test`, `secret-scan-test` | tutti `ALL OK` / `OK` | — |
| `temp-test` | 1 rosso | C3 (N16), rosso anche su `main` |
| `browser-test`, completo | 234 ok, 8 rossi | vedi sotto |
| `browser-test --only language`, dopo le correzioni della chiusura | `ALL OK` (L1–L7) | — |

**Gli 8 rossi della suite browser:**
- `views` ×4 ("floor under the UI", a 2560×1440 e 1440×900, con i pannelli LR e -R);
- `input` ×2 ("a real drag…", "a real click on an agent…");
- D8 ("painted bay text covered at most 27%": 30,9%);
- A10 (ticket N12).

Con `--only views,input,labels`, su `main` sono rossi gli stessi 7 controlli (tutti tranne A10, che sta nella fase `run`), con valori vicini. Quindi dipendono dall'ambiente (Chromium headless con SwiftShader a circa 3 fps, font di Linux) e non da questa spec. Il riferimento resta `npm run test:browser` su Windows.
