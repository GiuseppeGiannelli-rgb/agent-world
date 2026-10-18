# Spec 07 — Controllo di sicurezza

**In breve.** Controllo su tutto il progetto, chiesto dall'utente il 15/10/2026 dopo la spec 06 e la chiusura di N12.

**Modello di minaccia.** Il server ascolta su `127.0.0.1` senza login. Le minacce vengono da:
- una pagina web che l'utente apre nel browser;
- i siti che costruiscono gli agenti, serviti dallo stesso server;
- un agente guidato da una pagina malevola (prompt injection) verso la rete locale.

**Esito.** Quattro difetti, tutti corretti e tutti con test visti rossi prima della correzione, più un irrobustimento (S5):
- due gravi: CSRF/DNS rebinding e anteprima sulla stessa origine;
- uno medio: SSRF in `web_fetch`;
- uno basso: clickjacking.

Il resto della superficie regge (§3).

## 1. Difetti trovati e corretti

| # | Gravità | Difetto | Correzione |
|---|---|---|---|
| S1 | alta | **CSRF e DNS rebinding.** Nessuna route controllava `Origin` o `Host`, e `request.json()` legge il corpo qualunque sia il `Content-Type`. Una pagina qualsiasi poteva mandare una richiesta "semplice" (`text/plain`, senza preflight) a `POST /api/config` e puntare `providers.openai.baseUrl` su un suo server: alla chiamata successiva il router le mandava la chiave come `Authorization`. Con un nome che risolve in `127.0.0.1` (DNS rebinding) poteva anche leggere `/api/*`. Provato: la richiesta cross-site riceveva 200 e la configurazione cambiava. | `backend/security.py`, middleware `LocalGuard`, prima di ogni route (vedi sotto). |
| S2 | alta | **Anteprima sulla stessa origine.** `/preview/<run>/…` serve HTML, JS e SVG scritti dagli agenti, che una pagina letta può pilotare, con l'origine dell'app: i loro script potevano usare le API come l'app. | Ogni risposta di `/preview` ha `Content-Security-Policy: sandbox allow-scripts allow-forms allow-popups allow-modals allow-downloads allow-pointer-lock`, senza `allow-same-origin`. Gli script girano con un'origine opaca (`null`), e S1 rifiuta quello che mandano a `/api`. |
| S3 | media | **SSRF in `web_fetch`.** Un agente poteva leggere `127.0.0.1:4300/api/…`, la rete privata o i metadati cloud (`169.254.169.254`), e poi far uscire i dati con una ricerca. | `web.py` (vedi sotto). |
| S4 | bassa | **Clickjacking.** `127.0.0.1` passa il controllo di S1, quindi un sito poteva incorniciare l'app e far cliccare Salva o Approva sopra un'esca. | Ogni pagina statica ha `X-Frame-Options: DENY` e `frame-ancestors 'none'`, più `X-Content-Type-Options: nosniff`. |
| S5 | info | **Token del gateway confrontato con `==`.** Il tempo di risposta dipende dal prefisso giusto. Su localhost l'attacco è poco realistico. | `hmac.compare_digest` in `routes/gateway.py`. Un test sui tempi non sarebbe affidabile: il comportamento resta coperto dai test di `test_gateway.py`. |

**`LocalGuard` (S1).** Rifiuta con 403:
- un `Host` che non è fra quelli ammessi. Sono ammessi `127.0.0.1`, `localhost`, `::1`, `server.host` di config (se non è `0.0.0.0` o `::`) e `AGENT_WORLD_ALLOWED_HOSTS` (lista separata da virgole, per l'uso in LAN);
- un metodo non sicuro (POST…) con un `Origin` diverso dall'origine del server. È ammesso solo `scheme://Host`; ogni altra porta, `https` al posto di `http` o `null` sono rifiutati. Senza `Origin`, cioè uno script o un IDE sul gateway `/v1`, si passa: non è un browser;
- `/api` e `/v1` con `Sec-Fetch-Site` `cross-site` o `same-site`, anche in GET. Un `<img>` su `/api/skills?q=` avrebbe fatto spendere chiamate di embedding.

**`web_fetch` (S3).**
- Il nome si risolve e ogni indirizzo deve essere globale. Si rifiutano loopback, privati, link-local, `100.64/10`, `0.0.0.0`, multicast, e IPv6 ULA e link-local. Gli IPv6 mappati su IPv4 si controllano come IPv4.
- La richiesta va all'indirizzo controllato (pinning), con `Host` e nome TLS (SNI) originali. Così una seconda risposta DNS diversa non passa.
- Nessun redirect seguito, com'era già.
- I lettori di GitHub, Reddit e Hacker News vanno solo ai loro host fissi.

## 2. Test

**`backend/tests/test_security.py`** (37 test, scritti prima del codice e visti rossi: 30 rossi su 36 prima della prima correzione, più quello del clickjacking):
- **CSRF:** la richiesta dell'attacco vero (`text/plain`, `Origin: https://evil.example`) prende 403, e `local.json` non viene scritto. Le origini `null`, un'altra porta e `https` sono rifiutate su `/api/config`, `/api/runs`, `/api/brain` e `/v1/chat/completions`. L'app stessa (stessa origine) e un client senza `Origin` passano.
- **Letture cross-site:** `Sec-Fetch-Site` `cross-site`/`same-site` prende 403 su quattro route; `same-origin` e `none` passano.
- **DNS rebinding:** quattro `Host` estranei sono rifiutati su `/api/state`, `/` e `/api/events`; i nomi loopback, anche in maiuscolo e IPv6, passano; `AGENT_WORLD_ALLOWED_HOSTS` funziona.
- **Anteprima:** HTML, SVG e cartella hanno la sandbox senza `allow-same-origin`; le pagine dell'app no.
- **Clickjacking:** gli header anti-frame ci sono, sull'app e sull'anteprima.
- **SSRF:** 13 indirizzi locali o privati, compresi i casi `2130706433` e `[::ffff:127.0.0.1]`, sono rifiutati prima di qualunque connessione. Lo è anche un nome che risolve in `10.0.0.7`. Il pinning si connette all'indirizzo controllato; un redirect verso `127.0.0.1` non viene seguito.

**Mutazioni**, una per difesa (`tests/test_security.py`):

| Difesa tolta | Test rossi |
|---|---|
| controllo dell'`Origin` | 5 |
| controllo dell'`Host` | 5 |
| `Sec-Fetch-Site` | 2 |
| sandbox dell'anteprima | 1 |
| solo il loopback rifiutato | 9 |
| niente pinning | 1 |

Sopravvive una sola mutazione, lo spacchettamento degli IPv6 mappati su IPv4. Python considera già non globale tutto `::ffff:0:0/96`: lo spacchettamento serve a far passare un indirizzo pubblico mappato, non a difendere.

**Test cambiati:**
- cinque file di test usavano `base_url="http://test"`: ora usano `http://127.0.0.1`, cioè quello che manda un browser vero;
- `test_web.py` risolve i nomi pubblici con un resolver finto, così resta offline, e confronta anche l'header `Host`.

## 3. Controllato, senza difetti

- **XSS nella UI.** Ogni `innerHTML` di `main.js` e `world.js` con dati del modello o di terzi passa da `esc()` o `markdown()`. Gli id interpolati sono generati dal backend: id dei task (`w1.2`), id dei run (esadecimali), id delle skill (SHA-1). `md.js` fa l'escape di tutto prima di trasformare e ammette solo link `https?://`. I toast usano `textContent`.
- **File del run.** `Workspace.resolve()` risolve i symlink prima del controllo di contenimento: un link dentro il workspace verso l'esterno è rifiutato in lettura e in scrittura. `/preview` e i file statici usano lo stesso schema.
- **Repo di skill.** `REPO_URL_RE` ammette solo `https://github.com/owner/repo`; `git` riceve una lista di argomenti, quindi niente opzioni iniettate.
- **Download dello Skiller:** la spec 05 §5, con i suoi 70 test.
- **Log delle chiamate:** solo riepiloghi, nessuna chiave. Le chiavi non escono mai nelle risposte (`public_config` esclude `server`; i provider mostrano solo il nome della variabile).
- **Skill e Brain:** `read_skill` legge solo voci dell'indice; le note del Brain sono tagliate a 160 e 4000 caratteri.

## 4. Rischi accettati, da sapere

- **`AGENT_WORLD_ALLOW_SHELL=1`** dà agli agenti una shell nella cartella del run. Un agente guidato da una pagina malevola può eseguire comandi: per questo è spento di default.
- **La configurazione locale è fidata.** Dall'app si può puntare un provider su qualsiasi `baseUrl` e `keyEnv`. Dopo S1 e S2 può farlo solo l'utente.
- **Senza `AGENT_WORLD_API_KEY`**, il gateway `/v1` è aperto a ogni processo locale: un processo locale può già fare di tutto, quindi il confine resta la macchina.
- **Anteprima e `localStorage`.** Nella sandbox un sito generato non può usare `localStorage` né cookie: per quei casi va aperto dalla cartella del run.
- **Server in LAN.** Con `server.host` uguale a `0.0.0.0` bisogna elencare i nomi in `AGENT_WORLD_ALLOWED_HOSTS`, altrimenti si accede solo in locale.
- **I media** scaricano gli URL che restituiscono i provider di immagini configurati (es. fal): sono fidati quanto il provider.
- **N13 (chiuso il 18/10/2026):** i 403 parlano la lingua dell'app, come gli altri errori HTTP (`Request refused: …` in inglese, `Richiesta rifiutata: …` in italiano).
