# Agent World

Un'azienda di agenti AI che si vede lavorare. Scrivi una missione: la CEO la divide tra i team, ogni team lead la scompone e la distribuisce ai suoi agenti (e, quando serve, a sub-agenti creati al volo), lo Skill Hub assegna le skill giuste, il Prompt Lab affina i brief, gli agenti lavorano in loop finché il QA non approva, e tutto succede in un ufficio 3D visto dall'alto.

Niente servizi esterni da installare: router dei modelli, orchestrazione, skill, memoria e mondo 3D sono in questa cartella. Il backend è **FastAPI** (Python 3.13, gestito da `uv`, un solo processo uvicorn); Node resta solo per `three.js` e gli strumenti di test del front-end.

## Avvio

```sh
npm install     # three.js per il 3D
npm start       # backend FastAPI: uv sincronizza e avvia (porta 4300)
```

Apri http://127.0.0.1:4300. Richiede [uv](https://docs.astral.sh/uv/) nel PATH (al primo avvio scarica Python 3.13 e le dipendenze da solo). Per lo sviluppo con reload automatico: `npm run dev`.

Senza chiavi API parte in **modalità demo**: un simulatore interpreta ogni ruolo (piani, sub-agenti, revisioni, escalation, immagini e audio segnaposto veri), così vedi tutto il flusso senza spendere nulla. Per usare modelli veri copia `.env.example` in `.env`, inserisci almeno una chiave e riavvia.

## Come lavora l'azienda

```
missione ─► CEO: semplice o complessa? ─► workstream per team, con dipendenze
                                           │
          ┌────────────────────────────────┼─────────────────────────────┐   in parallelo
          ▼                                ▼                             ▼
   Lead Ricerca                     Lead AI Generativa              Lead Sviluppo  …
   prende il workstream dalla board, lo scompone in sotto-task
          │
          ├─► Skill Hub: sceglie 1-3 skill per sotto-task tra tutte quelle indicizzate
          ├─► Prompt Lab (missioni complesse): riscrive ogni brief e i prompt per le immagini
          ▼
   worker + sub-agenti (creati se c'è più lavoro parallelo che persone)
   loop: pensa → tool → risultato … → finish
          │
          ▼
   QA e Sicurezza: criteri di accettazione + controllo di sicurezza sul codice
          │ revise → il worker riprende il SUO loop col feedback
          │ dopo 2 bocciature → escalation alla combo "frontier"
          │ dopo troppe → il lead decide: riprova con indicazioni o salta
          ▼
   consegna ─► sblocca i workstream che dipendono da questo ─► report finale
                                │
                                └─► Brain: lezioni del QA e riassunto della missione restano per le prossime
```

### I team (in `config/default.json`)

| Team | Cosa fa | Strumenti in più |
|---|---|---|
| Ricerca | fatti dal web, note con fonti | `web_search`, `web_fetch` (GitHub, Reddit, Hacker News) |
| Sviluppo | codice completo e funzionante | `run_command` (se abilitato) |
| Contenuti | testi, copy, script | `web_search` |
| Design | palette, CSS, layout, SVG | |
| AI Generativa | immagini e voce | `generate_image`, `generate_speech` |
| Prompt Lab | brief e prompt precisi; affina i brief degli altri team | |
| Skill Hub | sceglie le skill per ogni task | |
| Qualità e Sicurezza | revisione e controllo di sicurezza | |

Tutti hanno anche: file del progetto, `search_skills` / `read_skill`, `recall` / `remember` (Brain), `ask_lead` e `ask_user`.

## Tu nel loop

- **Chat con qualsiasi agente**, anche a voce (🎙): durante un run il messaggio guida il lavoro. Alla CEO arriva a tutti, a un lead a tutto il team, a un worker solo a lui. Con 🔊 le risposte vengono lette ad alta voce.
- **In attesa di te**: quando un agente usa `ask_user`, la domanda compare nel pannello di sinistra e lui aspetta la risposta (per 5 minuti, poi decide da solo).
- **Approvazione del piano**: spunta "Voglio approvare il piano" e la CEO aspetta il tuo ok prima di far partire i team.
- Pausa, ripresa e stop in qualsiasi momento.

## Skill Hub

Indicizza ogni `SKILL.md` delle cartelle in `skills.sources`: le skill dell'app (`skills/`), i plugin di Claude Code (`~/.claude/plugins`), `~/.claude/skills`, `~/.agents/skills` e Codex. Dalla scheda **Skill** puoi cercare, leggere e **aggiungere una repo GitHub di skill** (viene clonata in `skills/vendor/`).

Le repo in `skills.repos` sono predefinite: al primo avvio il server clona quelle che mancano in `skills/vendor/` (oggi [vercel-labs/skills](https://github.com/vercel-labs/skills)). Senza rete l'app parte lo stesso, con le skill che ha, e ci riprova all'avvio successivo; le repo già presenti si aggiornano dalla scheda **Skill**.

## Il router (stile OmniRoute, ma tuo)

- **Provider**: Anthropic, OpenAI, OpenRouter, Groq, Cerebras, Gemini, DeepSeek, Mistral, Ollama, LM Studio, e qualsiasi server compatibile OpenAI.
- **Combo**: liste ordinate di `provider/modello`, `fallback` o `round-robin`. `fast`, `smart`, `frontier` (escalation) e `local` sono già pronte.
- **Cooldown** dopo 429/5xx con backoff; una chiave rifiutata ferma tutto quel provider.
- **Media**: immagini con OpenAI (`gpt-image-1`), fal.ai (Flux) o Pollinations (gratis, spento finché non lo attivi); voce con OpenAI TTS o ElevenLabs.
- **Log** di ogni chiamata in `data/calls/`.
- **Gateway compatibile OpenAI** per altri programmi:

```sh
curl http://127.0.0.1:4300/v1/chat/completions -H "content-type: application/json" \
  -d '{"model": "combo:smart", "messages": [{"role": "user", "content": "ciao"}]}'
```

I nomi dei modelli nelle combo sono un punto di partenza: controlla che corrispondano a quelli dei tuoi account e cambiali dalle Impostazioni.

## L'ufficio 3D

- Un open space caldo, visto dall'alto come un diorama: pareti con finestre, pavimento in legno, angolo caffè e divano.
- La **lavagna kanban** occupa la parete di fondo, rivolta verso di te: le card dei workstream e dei sotto-task passano da DA FARE a FATTO.
- La CEO lavora sulla pedana davanti alla lavagna, con **il Brain** che le fluttua sopra come un ologramma: ogni volta che qualcuno salva o richiama una nota, il Brain si accende.
- Ogni team ha la sua zona con tappeto colorato, la scrivania del lead, quelle dei worker, un oggetto tipico (mappamondo, server, studio con ring light, lavagna di post-it…) e la **sub-agent bay**, dove i sub-agenti compaiono olografici e poi svaniscono.
- I lead vanno alla lavagna a prendere il workstream e lo dividono in cubi sulla scrivania; i worker vengono a prendersi il loro. I messaggi viaggiano come fasci di luce, il QA va alla scrivania di chi ha consegnato e dà il verdetto.
- Click su una persona: la segui e ci chatti. Click sull'etichetta di una zona: pannello del team. Minimappa, tema giorno/notte, ⌂ per la vista completa.

## Configurazione

| Cosa | Dove |
|---|---|
| Chiavi API, porta, shell | `.env` (vedi `.env.example`) |
| Team, persone, combo, media, fonti delle skill, limiti | `config/default.json` |
| Le tue modifiche dall'app | `config/local.json` (creato in automatico) |

Per aggiungere persone o team modifica `teams` in `config/default.json`: ogni team ha `label`, `color`, `kind` (`work` o `service`), `combo`, `brief`, `tools`, `lead`, `workers` e `maxSubAgents`.

`AGENT_WORLD_ALLOW_SHELL=1` permette agli agenti di eseguire comandi nella cartella del run. È spento di default perché i comandi li scrivono i modelli.

## Test

```sh
npm test
```

Adapter dei provider contro server finti, normalizzazione dei piani, ricerca BM25, media demo; poi un'intera missione complessa in demo; poi approvazione e rifiuto del piano, chat, pausa, ripresa e stop.
