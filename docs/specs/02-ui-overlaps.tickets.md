# Ticket — Spec 02, sovrapposizioni dell'interfaccia

Riferimento: [02-ui-overlaps.md](02-ui-overlaps.md). Gli ID P\*, E\*, V\*, N\* e Q\* rimandano alla spec.

**In breve**
1. **T0** costruisce il runner per tutta la spec. Le fasi `overlaps` (Q1–Q4, N6) e `labels` (N4, Q5, rotella) misurano la baseline e le varianti A, B e C. Poi ci si ferma perché tu scelga la variante (D8).
2. **T1 e T2** correggono i pannelli e l'inspector, solo con CSS più due righe di JS.
3. **T3 e T4** correggono le etichette.
4. **T5** è la verifica finale con il tuo QA.
5. Le verifiche che falliscono sul codice di oggi sono **rossi attesi**, segnati con il ticket che li chiude. La suite resta verde a ogni commit, e ogni verifica dimostra di saper fallire.

**Ordine:** T0 → T1 → T2 → T3 → T4 → T5. Le coppie T1–T2 (pannelli) e T3–T4 (etichette) non dipendono l'una dall'altra, ma restano in sequenza, così c'è una sola cosa aperta alla volta.

**Regole valide per ogni ticket**
- **Chiusura.** Un ticket si chiude solo quando i suoi criteri sono verdi. Poi ci si ferma e si aspetta il tuo feedback; il QA visivo lo fai tu, a 1920×1080.
- **Rossi attesi.** Ogni ticket toglie da `scripts/browser/known-red.json` le voci che chiude, nello stesso commit. Dopo T0 non se ne aggiungono: un rosso nuovo è un difetto nuovo.
- **Perimetro.** Un difetto fuori dal perimetro non si corregge al volo: si annota, e se tocca la spec si torna allo step 2.
- **Passaggio avversario** (retro della spec 01, lezione 3). Prima del commit di T1, T3 e T4, che cambiano la semantica di una funzione o di una regola:
  - tutti i chiamanti, con grep;
  - "e se succede durante un'animazione?";
  - "e se la precondizione è diversa?".

  L'esito va nel messaggio di commit.
- **Verifiche a livelli** (lezione 5):
  - `node --check` sui file JS modificati, e `npm test`;
  - nel browser, le fasi toccate dal ticket, con `--only`;
  - la suite completa a T0 (cambia il runner) e a T5;
  - nessun browser per i commit di soli documenti.
- **Commit.** Un commit atomico per ticket, o per correzione se un ticket ne contiene due. Messaggi in inglese, documenti in italiano. Nessun push senza il tuo via libera.
- **Server di prova.** Serve solo per guardare (lezione 1): `.claude/launch.json`, configurazione `agent-world-preview`, con `autoPort` e l'env in `.claude/preview.env`. La porta 4300 è del tuo server e non si tocca.

| Ticket | Titolo | Spec | Dimensione | Dipende da |
|---|---|---|---|---|
| T0 | Runner: fasi `overlaps` e `labels`, rossi attesi, processi del browser, baseline, varianti di N4 | §4.4, P1–P5, E1–E7, V4, V12 | L | — |
| T1 | N6, Q1, Q2: stato dei pannelli con `:has()` | §4.1, P2–P4, P6, V2, V3, V5 | S | T0 |
| T2 | Q3, Q4: l'inspector nella colonna | §4.2, P1, P2, V1, V2 | S | T1 |
| T3 | N4: etichette delle stanze sul bordo anteriore, sotto quelle degli agenti | §4.3, E1–E5, V6–V9 | M | T0 e D8 |
| T4 | Q5 e rotella sopra le etichette | §4.3, E6, E7, V10, V11 | S | T3 |
| T5 | Verifica finale e report "Dopo" | V1–V13 | M | T0–T4 |

---

## T0 — Runner: fasi `overlaps` e `labels`, baseline e varianti di N4

**Obiettivo:** misurare prima di cambiare una riga di produzione. Ogni caso della spec (N6, Q1–Q5, N4, rotella) deve diventare una verifica automatica che oggi fallisce per il motivo giusto. In più, servono i numeri per scegliere la variante di N4.

**File:**
- `scripts/browser-test.js`;
- `scripts/browser/lib.js`;
- nuovi: `scripts/browser/overlaps.js`, `scripts/browser/labels.js`, `scripts/browser/known-red.json`, `docs/specs/02-ui-overlaps.report.md`;
- `docs/specs/img/02-prima-*.jpg`.

Nessun file in `public/` cambia.

### A. Infrastruttura del runner

1. **Intestazione e fasi.**
   - Il commento in testa copre le spec 01 e 02.
   - Le fasi predefinite diventano `views,checks,cubes,input,overlaps,labels,run`, eseguite in quest'ordine.
   - `--skip-run` resta com'è.
   - Gli script di pagina caricati da `load()` includono `overlaps.js` e `labels.js`.
2. **Rossi attesi.** `known-red.json` ha la forma `{ "<fase> <verifica>": "T1", … }`. `report()` li tratta così:

   | Esito | Segnata | Riga | Conta come errore |
   |---|---|---|---|
   | rosso | sì | `red  <fase> <verifica>  (T1)` | no |
   | verde | sì | `FAIL … passes before T1: remove its mark` | sì |
   | rosso | no | `FAIL`, come oggi | sì |

   - In fondo il runner stampa `ALL OK, N expected reds (T1: a, T2: b, …)`.
   - Con `--tag prima`, cioè misurando un altro checkout, i segni non si applicano e il runner registra soltanto, come oggi per A1 e A9.
   - Una verifica rossa per più cause porta il ticket dell'ultima che la chiude.
3. **Processi del browser (V12)**, dopo `closeBrowser()`, prima di fermare il server e cancellare le cartelle.
   - **Elenco dei processi:**
     - su Windows: `powershell -NoProfile` con `Get-CimInstance Win32_Process`, filtrato su `msedge.exe` e `chrome.exe`, che restituisce PID e riga di comando;
     - altrove: `ps -eo pid=,args=`.
   - **Processi di questa esecuzione.** Sono quelli che hanno nella riga di comando il nome della cartella del profilo di questa esecuzione (`agent-world-profile-XXXXXX`, unico). Il runner li riguarda ogni 250 ms per al massimo 5 s. Se ne restano:
     - `FAIL` con i PID;
     - poi li chiude (`taskkill /T /F`), perché non si accumulino.
   - **Altri processi con `agent-world-profile`.** Escono come `note:` con PID e nome del profilo, senza far fallire la suite (spec §4.4).
4. **`--spec NN`** (predefinito `02`) dà il prefisso degli screenshot: `NN-<tag>-<nome>.jpg`.

### B. Aiuti di pagina (`lib.js`)

- `t.narrow()`: la modalità stretta, con la stessa query di `main.js`.
- `t.fixed()`: i rettangoli degli elementi fissi visibili, cioè topbar, `#left`, `#right`, `#roster`, `#minimap` e `#inspector` con area maggiore di 0. `t.overlap(a, b)` ne dà l'area in comune.
- `t.expected()`: la disposizione attesa del §3.1 della spec.
  - Si ricava dalla larghezza della finestra e dalle classi dei pannelli: 330/400 px sopra 1250, 300/360 sotto, 12 px di distanza, minimappa 204 px, inspector al massimo 340 px; in modalità stretta 8 px.
  - Non dipende dalla posizione misurata degli altri elementi: una minimappa fuori posto non sposta l'attesa sul roster.
- `t.frames(n)`: aspetta n frame veri. La fase `overlaps` non usa `t.session`: il layout CSS è sincrono e servono il `ResizeObserver` e i render veri.
- `t.openInspector({ tall })`:
  - clic sul primo `#roster .member`, poi attesa che l'inspector sia visibile;
  - con `tall`, riempie timeline e chat finché l'inspector arriva alla sua altezza massima (`100vh − 170px`).

  La misura avviene nello stesso task, perché un render dell'inspector cancellerebbe il contenuto aggiunto.

### C. Fase `overlaps` (P1–P5)

Dimensioni della finestra:
- quelle della matrice: 1920×1080, 1280×800, 1200×800, 1000×800, 800×600;
- i bordi delle media query: 1251×800, 1250×800, 901×800, 900×800.

1. **Riferimenti di P4.** Per ognuna delle 5 dimensioni della matrice e per ognuno dei 4 layout, una pagina appena caricata viene portata ai pannelli con ☰ e ▤. Si registrano i rettangoli di topbar, pannelli, roster e minimappa: 20 caricamenti.
2. **Ingressi singoli.** Per ogni dimensione (9), ogni layout di partenza (4, impostato con i pulsanti) e ogni ingresso della matrice, si applica l'ingresso con l'elemento vero e si controllano P1–P3, più P4 dove c'è un riferimento. Gli ingressi sono: ☰, ▤, una scheda diversa da quella attiva, un'etichetta di stanza, "Vai alla stanza", un membro del roster e ✕.
   - Le precondizioni si preparano con gli elementi veri:
     - "Vai alla stanza" richiede la scheda Team con una stanza aperta, cioè un clic sull'etichetta;
     - ✕ richiede l'inspector aperto.
   - Prima di ogni ingresso l'inspector si chiude e i pannelli tornano al layout di partenza.
3. **Resize, oltre 1250 e oltre 900, nei due versi.** Le sequenze sono 1920→1200→1920, 1200→800→1200 e 1920→800→1920, per ogni layout, con l'inspector chiuso e poi aperto. Dopo ogni passo si controllano P1–P4.
4. **Catene note:**
   - N6: ▤ chiude il pannello, una scheda lo riapre, a ogni dimensione larga;
   - Q2: si chiudono entrambi i pannelli a 1920, poi la finestra va a 800;
   - etichetta di una stanza con il pannello destro chiuso.
5. **P5.** A ogni dimensione larga, partendo dalla vista automatica (⌂), si provano tre ingressi: ☰, ▤ e una scheda che riapre il pannello destro. Dopo 0,6 s, `__checks.coverage()` deve dare `floorUnderObstaclesPct` e `envelopeUnderObstacles` a 0.
   - **Mutazione permanente:** `agentWorld.setInsets` viene sostituito da una funzione vuota, poi si preme ▤. La verifica deve fallire ("the frozen insets, put on purpose, are caught"); poi si ripristina. Questo dimostra V4.
6. **Passeggiate casuali.** 3 sequenze da 25 ingressi, con seme fisso: gli ingressi della matrice più i resize tra le 5 dimensioni. Dopo ogni passo si controllano P1–P4. C'è una verifica per sequenza, e il primo passo che fallisce va nei dati.
7. **Contenuto dell'inspector.** A ogni dimensione, con l'inspector aperto e alto, non deve comparire lo scorrimento orizzontale (V2).
8. **Nomi delle verifiche** (peggior caso nei dati): `P1 <dim>`, `P1 <dim> inspector`, `P2 <dim>`, `P2 <dim> inspector`, `P3 <dim>`, `P4 <dim>`, `P5 <dim>`, `walk <n>`. Così i rossi di T1 e quelli di T2 restano separati.
9. **Alla fine** la pagina si ricarica a 1920×1080 con LR, e le fasi successive partono pulite.
10. *(Aggiunto in T0)* **Ingressi applicati.** Una verifica `inputs <dim>` controlla che ogni ingresso della matrice sia stato applicato davvero: senza la sua precondizione, "Vai alla stanza" o ✕ verrebbero saltati in silenzio.

### D. Fase `labels` (E1–E7 e le varianti)

La fase gira dentro `t.session`: orologio a 60 fps e disegno sospeso. `updateLabels()` si chiama in modo esplicito tramite il prototipo, perché la sessione lo sostituisce.

1. **Scena ferma.**
   - `wander` è sospeso e ogni attore torna al posto con `placeAtSeat()`.
   - Si aspetta che non ci siano effetti attivi.
2. **Stati.** Si combinano:
   - finestra 1920×1080, 1440×900 o 2560×1440 (la imposta il runner) e layout LR, -R o --;
   - vista:
     - completa (⌂);
     - zoom effettivo 0,8, 1 e 1,3 attorno al centro della vista completa;
     - focus su un agente: un worker per fila;
     - focus su una stanza: una per fila;
     - primo piano: dopo il focus sull'agente, lo zoom massimo;
   - bay prima vuote, poi piene: 14 sub-agenti, uno per posto, creati con `onSpawn`, con 1 s di animazione;
   - fumetti tutti aperti (un testo di 46 caratteri, come quelli accorciati da `short()`) per E1, tutti chiusi per E2 ed E5.
3. **Modello delle varianti** (oggi, A, B, C; tabella del §4.3 della spec).
   - Il rettangolo a schermo di ogni etichetta di stanza si calcola dall'ancora proiettata, da `offsetWidth`/`offsetHeight`, da `--label-scale` e dall'allineamento della variante.
   - Il nome e il quadratino colorato si ricavano dalle loro posizioni dentro l'etichetta, scalate allo stesso modo.
   - **Verifica del modello:** con la variante "oggi", il rettangolo calcolato deve coincidere con `getBoundingClientRect()` dell'etichetta disegnata entro ±1 px, in ogni stato. **Se non coincide, T0 si ferma lì** (spec §8).
   - **Riproduzione della spec 01:** con la variante "oggi", nella vista completa a 1920×1080 con LR, risultano coperti 7 worker su 7.
4. **Misure per variante e per stato:**

   | Misura | Cosa si conta |
   |---|---|
   | E1 | area di etichette e fumetti degli agenti coperta da etichette di luoghi disegnate sopra. Con due ordini: quello di oggi (stanze sopra gli agenti iniziali, sotto i sub-agenti) e "agenti sopra", l'ordine di T3, dove E1 vale 0 per costruzione e serve da conferma |
   | E2 | area del nome e del quadratino di ogni stanza coperta da etichette di agenti seduti e visibili (non nascoste da `far`), con l'ordine "agenti sopra" |
   | E3 | etichette di stanza fuori dall'area libera (`safeRect` più la posizione del canvas), solo nella vista completa |
   | E4 | coppie di etichette di luoghi che si sovrappongono |
   | E5 | agenti seduti con almeno un punto di presa sotto un'etichetta di stanza. I punti di presa sono la proiezione del corpo a 0,4, 0,8 e 1,2 di altezza; un punto conta solo se lì `pick()` restituisce l'agente stesso |
   | bay | solo informazione: copertura della scritta "SUB-AGENT BAY", allineata a destra in `bayMark`, circa da x + 0,76 a x + 3,53 e da z + 2,39 a z + 2,76 |

5. **Verifiche sul codice di produzione.** Qui si usa il DOM vero, non il modello. Le verifiche sono rosse attese dove la baseline lo dice.
   - **`E1 <dim>` … `E5 <dim>`:** peggior caso su layout, viste e bay.
     - E5 usa `document.elementFromPoint` sui punti di presa e sul centro del nome di ogni stanza.
     - Il controllo A6 della spec 01 manda gli eventi direttamente al canvas e non vede le etichette: E5 lo completa.
   - **`E6 <dim>`:** al centro di ogni etichetta nascosta da `far`, `elementFromPoint` non deve restituire l'etichetta. Oggi è rosso (Q5).
   - **`E7`**, con eventi veri inviati dal runner:
     - `Input.dispatchMouseEvent` di tipo `mouseWheel` con `deltaY` −120 sul centro del nome di una stanza;
     - per confronto, lo stesso evento su un punto libero del canvas, partendo entrambe le volte dalla stessa vista (⌂);
     - atteso: stesso rapporto di scala (±2%) e `autoFrame` falso. Oggi è rosso.
6. *(Aggiunto in T0)* **Il modello anche su A, B e C.** Un involucro di `updateLabels()`, solo nella pagina di test, disegna ogni variante con il CSS come farà T3, con il punto della trasformazione sull'ancora. Il modello deve coincidere con il disegno entro ±1 px. Lo stesso involucro dà gli screenshot delle varianti (`02-variante-n4-*`).
7. **Tabella delle varianti (per D8).** Per oggi, A, B e C riporta il peggior caso su tutta la matrice di E1 (con l'ordine di oggi), E2, E3, E4, E5 e della scritta della bay, con lo stato in cui accade. Va nel JSON (`--json`) e nel report.

### E. Baseline e report

1. Si lancia `node scripts/browser-test.js --only overlaps,labels --json <file>` su questo branch, che oggi coincide con `main`.
2. **Ogni rosso va spiegato** con un difetto noto (N6, Q1–Q5, N4, rotella), leggendo i dati. Diventa una voce di `known-red.json`, con il ticket che lo chiude. **Un rosso che non si spiega così è un difetto nuovo: mi fermo e te lo segnalo.**
3. Le misure di Q1–Q4 devono ritrovare quelle della spec (§1.1) entro 1 px, e quelle di N4 i numeri della spec 01.
4. **Dimostrare che le verifiche sanno fallire:**
   - V4, con la mutazione permanente del punto C.5;
   - V12, una volta, saltando la chiusura del browser con una modifica temporanea che non si committa; l'output va nel report;
   - tutte le altre verifiche nuove risultano rosse nella baseline: quello è la prova.
5. Si lancia la suite completa (`npm run test:browser`), perché il runner è cambiato. Le 130 verifiche della spec 01 devono restare verdi, e la suite deve chiudere senza errori, con l'elenco dei rossi attesi.
6. **Report** `02-ui-overlaps.report.md`, sezione "Prima":
   - riassunto di 5 righe;
   - misure di N6, Q1–Q5 e N4;
   - tabella delle varianti;
   - durata delle fasi nuove, con l'obiettivo di 3 minuti. Se lo supera, il report lo dice e propone di ridurre i riferimenti di P4;
   - screenshot `02-prima-*` a 1920×1080 con LR, -R e --, più N6 dopo ▤ e una scheda, l'inspector a 1000 px e a 1280×800 (Q4).

**Commit:**
- `test(ui): overlaps and labels phases, expected reds, browser process check (T0)`
- `docs(T0): baseline report and the N4 variants`

**Fatto quando:**
- le fasi `overlaps` e `labels` girano, e ogni rosso della baseline è attribuito a un difetto noto e segnato;
- il modello delle varianti coincide con il DOM entro ±1 px e ritrova i numeri della spec 01;
- la suite completa è verde, con i soli rossi attesi;
- V4 e V12 sono stati visti fallire;
- nessun file in `public/` è cambiato.

**Fermata:** scegli la variante di N4 (D8) sulla tabella del report. Se una variante non rispetta E2–E5 in qualche stato, la tabella lo mostra: sceglierla significa accettare quell'eccezione, che va scritta nella spec prima di T3.

## T1 — N6, Q1, Q2: stato dei pannelli con `:has()`

**File:** `public/css/app.css`, `public/js/main.js`, `scripts/browser/manual-mode.js`, `scripts/browser/known-red.json`.

**Attività**
1. In `app.css`, come nel §4.1 della spec:
   - su `:root`, le proprietà `--col-left`, `--col-right` e `--map-right`;
   - `@media (width > 900px)` con le regole `:root:has(#left.closed)` e `:root:has(#right.closed)`;
   - nella `@media (max-width: 1250px)`: `--col-right: calc(var(--right-w) + 24px)` al posto di `.roster { right: … }`;
   - `@media (900px < width <= 1250px)` con `:root:has(#right.closed) { --col-right: 12px; }`;
   - `.roster { left: var(--col-left); right: var(--col-right); }` e `.minimap { right: var(--map-right); }`;
   - `.inspector { left: var(--col-left); }`. Senza questa regola, togliere quella del body sposterebbe l'inspector quando il pannello sinistro è chiuso: è il comportamento di oggi, che resta fino a T2;
   - via le tre regole `body.left-closed` e `body.right-closed`, alle righe 400–402.
2. In `main.js`, nel ramo largo di `togglePanel()` resta solo `$(id).classList.toggle('closed')`: via le righe 878–879.
3. In `manual-mode.js`, via il riallineamento a mano e il suo commento (righe 179–180).
4. In `known-red.json`, via le voci di T1.
5. **Passaggio avversario** (spec §4.1):
   - grep di `left-closed|right-closed` in `public/` e `scripts/`: deve dare 0 occorrenze;
   - `togglePanel` ha solo i due pulsanti come chiamanti;
   - ▤ premuto durante il riadattamento di 0,35 s di un altro ▤;
   - in modalità stretta, `closed` e `open` insieme;
   - `selectTeam` che misura gli ingombri subito dopo `switchTab`.
6. **Verifiche:**
   - `node --check public/js/main.js`;
   - `npm test`;
   - `node scripts/browser-test.js --only views,checks,input,overlaps`: si toccano CSS e pannelli, non cubi né eventi.

**Commit:** `fix(ui): one truth for the panels, read with :has() (T1)`

**Fatto quando:**
- V2 per roster e minimappa, V3 e V5 sono verdi, e i rossi attesi rimasti sono solo di T2–T4;
- il QA a 1920×1080 conferma che:
  - con ▤ che chiude il pannello destro e una scheda che lo riapre, minimappa e roster stanno accanto al pannello;
  - con il pannello destro chiuso e la finestra ristretta sotto 1250 px, il roster arriva fino al bordo.

## T2 — Q3, Q4: l'inspector nella colonna

**File:** `public/css/app.css`, `scripts/browser/known-red.json`.

**Attività**
1. `.inspector { left: var(--col-left); right: var(--col-right); width: auto; max-width: 340px; }`. In modalità stretta si aggiunge `max-width: none` alle regole attuali (8 px dai bordi, larghezza automatica).
2. **Passaggio avversario:**
   - grep di `inspector` in `public/`: lo posizionano solo il CSS e `renderInspector`, e nessun JS ne misura la larghezza;
   - modalità stretta, altezza e `top` restano invariati.
3. In `known-red.json`, via le voci di T2.
4. **Verifiche:** `node scripts/browser-test.js --only overlaps,checks`.

**Commit:** `fix(ui): the inspector shares the roster's column (T2)`

**Fatto quando:**
- V1 e V2 sono verdi ovunque, anche con l'inspector aperto, e a 193 px non compare lo scorrimento orizzontale;
- il QA a 1920×1080 con entrambi i pannelli aperti conferma l'inspector invariato, largo 340 px. Se vuoi, anche con la finestra ristretta a circa 1000 px e 1280 px.

## T3 — N4: etichette delle stanze sul bordo anteriore, sotto quelle degli agenti

**File:** `public/js/world/world.js`, `public/css/app.css`, `scripts/browser/labels.js`, `scripts/browser/known-red.json`.

**Attività**
1. `world.js`, `build()`: ancora della variante scelta (spec §4.3) e allineamento dell'etichetta, salvati in `roomLabels`.
2. `updateLabels()`: la traslazione segue l'allineamento della variante invece del `translate(0, -50%)` fisso.
3. `app.css`:
   - `.room-label`: `transform-origin` sul punto d'ancora della variante. Si toglie la doppia dichiarazione di oggi (`0 50% !important` e `0 100%`);
   - ordine: `.room-label, .brain-label { z-index: 0; }` e `.tag, .bubble { z-index: 1; }`. Lo z-index resta dentro `#stage`, che è `position: fixed`.
4. `labels.js`:
   - il modello della variante scelta diventa la verifica incrociata del codice di produzione: DOM e modello entro ±1 px;
   - nuova mutazione permanente: l'ordine rimesso al contrario (stanze con `z-index: 2`) dev'essere colto da E1.
5. In `known-red.json`, via le voci di T3.
6. **Passaggio avversario:**
   - chi usa `roomLabels`: il test A7 della spec 01 clicca con `el.click()`, che non dipende dalla posizione; `setRoomStats` cambia solo il testo;
   - la fase `input` cerca un punto libero che eviti le etichette (`freeFloor`): va controllato che lo trovi ancora;
   - durante un focus animato l'etichetta segue la camera a ogni frame, come oggi.
7. **Verifiche:**
   - `node --check public/js/world/world.js`;
   - `npm test`;
   - `node scripts/browser-test.js --only views,checks,input,labels`.

**Commit:** `fix(world): room labels on the front edge, under the agents' labels (T3)`

**Fatto quando:**
- V6–V9 sono verdi in tutta la matrice, salvo le eccezioni accettate alla fermata di T0 e scritte nella spec;
- il QA a 1920×1080 in LR, -R e --, nella vista completa, conferma etichette dei worker leggibili e clic che funzionano su stanze e agenti.

## T4 — Q5 e rotella sopra le etichette

**File:** `public/css/app.css`, `public/js/world/world.js`, `scripts/browser-test.js` (commento della fase `input`), `scripts/browser/known-red.json`.

**Attività**
1. **Q5 (E6).** Si cambia la regola in `#labels.far .tag:not(.lead):not(.busy) { opacity: 0; pointer-events: none; }`.
2. **Rotella (E7).** Nel costruttore della `World`, `labelsEl.addEventListener('wheel', …, { passive: false })`:
   - prima `e.preventDefault()`;
   - poi `canvas.dispatchEvent(new WheelEvent('wheel', { deltaX, deltaY, deltaZ, deltaMode, clientX, clientY, screenX, screenY, ctrlKey, shiftKey, altKey, metaKey, bubbles: true, cancelable: true }))`;
   - l'ascoltatore non è passivo perché, con Ctrl (il pinch del touchpad), il browser zoomerebbe la pagina.
3. **Passaggio avversario:**
   - durante un trascinamento `OrbitControls` ignora la rotella (`state ≠ NONE`), come sul canvas;
   - fumetti ed etichetta del Brain non ricevono il puntatore (ereditano `none` da `#labels`), quindi non c'è nulla da inoltrare;
   - l'evento inoltrato parte dal canvas, che sta fuori da `#labels`: non può tornare indietro in un ciclo;
   - la modalità manuale scatta, perché l'evento è annullabile e i controlli chiamano `preventDefault` (verificato nei sorgenti di r186);
   - un'etichetta che sta sfumando (0,3 s) riceve il puntatore solo quando `far` non la nasconde più;
   - si aggiorna il commento della fase `input` ("a wheel over a label never reaches the canvas").
4. In `known-red.json`, via le voci di T4: il file resta vuoto (`{}`), pronto per il prossimo ciclo.
5. **Verifiche:**
   - `node --check public/js/world/world.js`;
   - `npm test`;
   - `node scripts/browser-test.js --only checks,input,labels`.

**Commit**, due correzioni distinte:
- `fix(ui): hidden labels let the pointer through (T4)`
- `feat(world): the wheel zooms over labels too (T4)`

**Fatto quando:**
- V10 e V11 sono verdi e `known-red.json` è vuoto;
- il QA conferma la rotella sopra le etichette di stanze e di agenti, e il pinch del touchpad se ne hai uno.

## T5 — Verifica finale e report "Dopo"

**Attività**
1. `npm test`, `node --check` sui moduli front-end modificati e `npm run test:browser` completo, missione inclusa: 0 errori e 0 rossi attesi.
2. Report, sezione "Dopo":
   - V1–V13 uno per uno, a confronto con il "Prima";
   - screenshot `02-dopo-*` delle stesse viste.
3. Spec viva: ogni correzione emersa nei ticket va annotata nel punto della spec in cui vale, con il ticket che l'ha generata.
4. Aggiornamento di `HANDOFF.md`.
5. **Il tuo QA a 1920×1080**, con questa lista:
   - ▤ chiude il pannello destro, una scheda lo riapre: minimappa e roster stanno accanto al pannello;
   - l'etichetta di una stanza, cliccata con il pannello destro chiuso;
   - l'inspector aperto con entrambi i pannelli, poi la finestra ristretta (se vuoi);
   - la vista completa in LR, -R e --: etichette dei worker leggibili, etichette delle stanze sul bordo anteriore;
   - un clic su un agente vicino all'etichetta della sua stanza;
   - la rotella sopra un'etichetta di stanza e sopra un'etichetta di agente.

**Commit:** `docs(T5): after report, spec as built`

**Fatto quando:** V1–V13 sono verdi, oppure ogni eccezione è motivata e messa in evidenza, e il QA è superato.

---

Dopo T5: **step 5 (Code-review)** sul diff completo, poi **step 6 (Retro)**.
