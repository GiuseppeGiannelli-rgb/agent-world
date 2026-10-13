# Ticket — Spec 04, P3: router "OmniRoute", provider, mock, gateway /v1

Scritti rapidamente durante la sessione continua P0–P7 (l'utente ha chiesto di non fermarsi tra le fasi): meno prosa dei ticket di P0–P2, stesso rigore TDD.

**Perimetro:** porta `server/router/index.js`, `server/router/providers.js`, `server/router/mock.js` in `backend/backend/router/`. Nessun file in `public/` cambia.

| Ticket | Titolo | Dipende da |
|---|---|---|
| T9 | `Router`: `expand`, `plan`, cooldown, round-robin, `chat()`, `snapshot()` | T6 (Config) |
| T10 | Provider HTTP: OpenAI-compatibile e Anthropic, via `httpx` | T9 |
| T11 | Provider mock (demo): risposte credibili per ogni ruolo | T9 |
| T12 | `GET /api/router`, `POST /api/router/test`, gateway `GET /v1/models`, `POST /v1/chat/completions` | T10, T11 |

**TDD:** ogni modulo ha il suo test scritto prima (rosso: `ModuleNotFoundError`), poi l'implementazione. Un confronto diretto con `router-test.js` (stessi casi: fallback, cooldown, round-robin, JSON mode, demo fallback) assicura la parità comportamentale (non lo streaming vero, D7: un blocco singolo).

**Fatto quando:** i test paralleli ai casi di `scripts/router-test.js` sono verdi in pytest; `GET /v1/models` e `POST /v1/chat/completions` rispondono con lo stesso schema del Node in modalità demo.
