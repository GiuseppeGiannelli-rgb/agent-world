# Spec 06 — Lingua globale (Italiano / Inglese)

**In breve.** Si sceglie la lingua dell'app (Italiano o Inglese) una volta sola. La scelta cambia:
- l'interfaccia, subito e senza ricaricare la pagina;
- la voce, cioè la sintesi vocale e la dettatura;
- la lingua in cui gli agenti ragionano, scrivono i log e rispondono;
- i messaggi di sistema che il backend manda via SSE.

Si salva in `config/local.json` come `ui.language` e vale fra una sessione e l'altra. Ogni run riceve la lingua nel payload e la tiene ferma fino alla fine.

Decisioni D1–D6 approvate dall'utente il 15/10/2026.

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
- `POST /api/config`: `ui` è fra le chiavi modificabili (`EDITABLE`), e `/api/state` e `/api/config` la espongono.

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
- **N15**: `test_state.py::test_api_config_post_updates_and_emits` scrive nel vero `config/local.json` (per questo lì c'è `limits.maxParallel = 3`). Va isolato su una cartella temporanea. È un problema preesistente, fuori da questa spec.

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
