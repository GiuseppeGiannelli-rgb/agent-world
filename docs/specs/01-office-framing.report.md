# Report — Spec 01, inquadratura dell'ufficio v3 e cubi

## Prima (T0, 2026-10-12, codice al commit `c1312ff`)

### Condizioni

- Server demo sulla porta 4310, con `AGENT_WORLD_HOME` in una cartella temporanea. Nessuna chiave API: modalità DEMO confermata dal log e dalla pill in alto.
- Pannello browser dell'app Claude, con viewport emulato (1920×1080, 2560×1440, 1440×900) e devicePixelRatio 1,25.
- Il pannello è largo solo 476 px, quindi gli screenshot dei viewport emulati escono ridotti di circa 4 volte e non sono leggibili. Per questo **le verifiche sono numeriche**: snippet in console che proiettano la scena con la camera reale e la confrontano con i rettangoli del DOM.

### Inquadratura

Snippet `__cov()`: griglia del pavimento a passo 0,5 proiettata con `agentWorld.camera`. Un punto conta come coperto se cade sotto `.topbar`, `#left`, `#right`, `#roster` o `#minimap`, oppure fuori dallo schermo. Per le zone si proietta la loro area a y = 1 e la topbar non viene contata.

| Viewport | Pannelli | Pavimento coperto | Di cui | Zone coperte (%) | Larghezza dell'ufficio |
|---|---|---|---|---|---|
| 1920×1080 | LR | **21%** | sinistro 7%, destro 11%, minimappa 2% | research 17 · design 44 · genai 51 · qa 15 | 1774 px |
| 1920×1080 | -R | 14% | destro 11%, minimappa 2% | design 44 · qa 15 | 1774 px |
| 1920×1080 | -- | 0% | — | — | 1774 px |
| 2560×1440 | LR | 10% | sinistro 3%, destro 5%, minimappa 1% | design 12 · genai 24 | 2366 px |
| 2560×1440 | -R | 6% | destro 5%, minimappa 1% | design 12 | 2366 px |
| 2560×1440 | -- | 0% | — | — | 2366 px |
| 1440×900 | LR | **38%** | sinistro 15%, destro 21%, minimappa 2% | research 53 · design 88 · genai 86 · qa 54 | 1331 px |
| 1440×900 | -R | 23% | destro 21%, minimappa 2% | design 88 · qa 54 | 1331 px |
| 1440×900 | -- | 0% | — | — | 1331 px |

I valori coincidono al punto percentuale con la stima in Node della spec (tabella 1.1). Lo stesso snippet servirà in T5 e T8.

### Cubi: stress R1–R4

Snippet `__cubeStress()`, salvato come `cube-stress.js` nella cartella temporanea della sessione e da rilanciare in T2 e T8. Chiama direttamente i metodi della `World` per forzare le sequenze; dopo ogni caso controlla gli orfani e ripulisce.

| Caso | Esito | Dettaglio |
|---|---|---|
| R1: lo split viene superato dal volo verso la mano | ✖ | Il cubo di `nina` resta a `(-9.9, 1.0, -2.8)` in coordinate locali, a circa 10 unità dal personaggio |
| R2: pickup ancora in volo quando arriva lo split | ✖ | `teo` porta il cubo grande del workstream, ormai eliminato |
| R3: consegna o affondamento durante il volo verso la mano | ✖ | `ugo` porta il cubo consegnato a `(0, 3, -16.9)` in coordinate locali (le coordinate della lavagna applicate nello spazio del personaggio); `dario` porta il cubo affondato |
| R4: reset del run durante il volo | ✖ | `vera` porta un cubo del run precedente |

### Run completo

- **Missione:** "Il sito completo per il lancio di una pizzeria napoletana a Milano, con brand, immagini e testi", a 1920×1080 con entrambi i pannelli, ritmo normale.
- **Esito:** `completed`, con 6 workstream, 17 task (tutti `done`), 2 sub-agenti creati e rimossi, 23 verdetti del QA (17 promossi, 6 da rivedere).
- **Sonda:** controlli ogni 250 ms sugli orfani dei cubi e sulla posizione dei sub-agenti, più l'aggancio a `applyState` e `bubble` per i verdetti.

| Verifica | Esito |
|---|---|
| Il verdetto del QA compare solo con il revisore alla scrivania | ✔. Il fumetto compare sempre con il revisore a 1,0–1,1 dal destinatario (posto accanto alla sedia), con un ritardo massimo di 1,04 s dall'evento. `yieldTo()` funziona come previsto. |
| I sub-agenti lavorano nella bay | ✔. `research-sub1` e `prompt-sub1` restano entro 1,6 dal proprio posto nella bay mentre sono occupati; il massimo corrisponde alla camminata verso la scrivania del lead per prendere il cubo. |
| Cubi | ✖. **R1 si è verificato anche nel run reale**: `research-sub1` aveva il cubo a `(-20.93, 0.95, -2.82)` in coordinate locali, cioè la posizione della scrivania del lead di research applicata nello spazio del personaggio. Il cubo è rimasto staccato dalla mano finché il sub-agente è stato rimosso. A fine run: 0 cubi rimasti, nessun personaggio con `carrying`. |
| Ciclo di vita, carte e consegne | ✔. 6 pickup, 6 split, 17 prese, 17 consegne, 23 drop; nessun cubo vagante a fine run. |

### Difetto nuovo N1: effetti persi dentro `Fx.update`

`Fx.update()` esegue `this.items = this.items.filter(...)`. Un effetto creato **durante** l'aggiornamento di un altro effetto viene aggiunto con `push` all'array vecchio, che subito dopo viene sostituito. L'effetto non viene mai aggiornato né eliminato, ma le sue mesh sono già nella scena: restano lì congelate per sempre.

Casi concreti:
- l'anello d'arrivo di ogni fascio di luce (`beam` chiama `ring` all'arrivo);
- le scintille sulla carta a ogni consegna (`done` di `deliverCube` chiama `sparkle`).

A fine run, con 0 effetti attivi, la scena conteneva **144 anelli** (`RingGeometry`, scala 1, opacità 0,8) e **170 ottaedri** (17 scintille da 10 particelle, una per consegna). Si accumulano tra un run e l'altro, perché `resetRun` non li tocca.

**Valutazione del perimetro:**
- è un difetto dello stesso ciclo di `Fx` che T1 riscrive;
- le garanzie di S4.1 (`track`/`stop`, `done` mai chiamato dopo l'annullamento) valgono solo se il ciclo regge l'aggiunta di effetti durante l'aggiornamento: un `fly` avviato dentro un `done` oggi andrebbe perso, e la mappa di `track` punterebbe a un effetto morto.

Per questo lo includo in T1 come aggiunta **S4.5** alla spec, con un test dedicato in A5.

### Cosa resta da osservare a schermo

Gli screenshot leggibili richiedono un pannello browser più largo. Le verifiche numeriche coprono i criteri della spec. Una conferma visiva da parte dell'utente su un monitor a 1920×1080 resta utile in T8.

## Verifiche per ticket

### T1 — `Fx` (commit `a64d8b2`)

- `scripts/world-test.js`: 6 controlli verdi, tra cui il caso degli effetti annidati di N1 e i voli concatenati sullo stesso oggetto. La suite parte per prima in `npm test`.
- Controprova sull'`Fx` precedente: nello stesso scenario restavano 11 mesh nella scena (un anello e 10 scintille) e un volo annullato chiamava comunque `done`. Con la versione nuova: 0 e 0.
- `npm test` completo verde.

### T2 — Cubi

**Stress A9**, con lo snippet `__cubeStress()` reso deterministico: la `World` avanza a 60 fps fissi chiamando `frame()`, così il risultato non dipende dal ritmo del browser. Il pannello nascosto gira a 0,7–2 fps.

| Caso | Solo T1 (vecchio `world.js`) | T1 + T2 |
|---|---|---|
| R1: lo split viene superato dalla presa | ✔ (il volo nuovo sostituisce il vecchio) | ✔ cubo in mano |
| R2: pickup in volo, poi split | ✖ `teo` porta il cubo grande eliminato | ✔ split rimandato ed eseguito |
| R3: consegna o affondamento durante la presa | ✖ solo l'affondamento: `dario` porta il cubo affondato | ✔ |
| R4: reset durante la presa | ✖ `vera` porta un cubo del run precedente | ✔ |
| R5: seconda presa con un cubo già in mano | ✖ il primo cubo resta attaccato al personaggio | ✔ il primo va sulla scrivania, il secondo in mano |

**Run completo** con T1 + T2: stessa missione di T0, simulazione a velocità reale. Il rendering è spento durante la pompa, perché il pannello nascosto non disegna.

| Verifica | T0 | T1 + T2 |
|---|---|---|
| Esito | `completed`, 6 workstream, 17/17 task | identico |
| Cubi: pickup, split, prese, consegne, drop | 6 / 6 / 17 / 17 / 23 | 6 / 6 / 17 / 17 / 23 |
| Anomalie dei cubi durante il run | 1 (R1, `research-sub1`) | **0** |
| Cubi rimasti a fine run | 0 | 0 |
| Effetti congelati a fine run (anelli / ottaedri) | 144 / 170 | **0 / 0** |
| Verdetti con il revisore alla scrivania | 23/23 (distanza 1,0–1,1) | 23/23 (distanza 1,0–1,1) |

`npm test` completo verde. `node --check` verde su `world.js` e `fx.js`.

### Difetto N2: il client resta indietro quando la scheda è nascosta (osservato, fuori perimetro)

È un difetto preesistente e non è stato corretto. Il rendering si ferma a pannello o scheda nascosti (bug noto in HANDOFF). Gli eventi del server invece arrivano in tempo reale, quindi le code di azioni dei personaggi si allungano. In un run fatto a 0,7 fps sono comparsi due effetti:
- **cubi che affondano invece di essere consegnati:** lo stato `idle` arriva mentre la consegna è ancora in coda dietro la camminata, e `applyState` (ramo `idle`) affonda il cubo;
- **un cubo lasciato su una scrivania a fine run** (`w1.3` dal lead `rino`): `onDespawn` rimuove il sub-agente con un `setTimeout` di 800 ms (tempo reale) prima che la sua coda arrivi alla presa del cubo.

A velocità reale non succede (0 affondamenti, 0 cubi rimasti). Lo propongo come ticket separato dopo questa spec, per esempio con il recupero del ritardo al ritorno visibile e la rimozione del sub-agente legata alla fine della sua coda.

### T3 — `framing.js` ed `ENVELOPE`

**Correzione di S2.1.** Sotto il pavimento c'è la base del diorama: un blocco alto 1,6 più un plinto, fino a `y = -1.66`, che sporge di 0,65 oltre il bordo. La sua faccia anteriore è visibile dalla camera, e i 7 punti della prima versione della spec la ignoravano. Con i pannelli chiusi, quando l'altezza è l'asse più stretto, il fondo della base sarebbe finito sotto il roster:

| Viewport | Pannelli | Fondo della base con l'ingombro a 7 punti | Con `ENVELOPE` (11 punti) |
|---|---|---|---|
| 1920×1080 | -R | 6 px sotto l'area libera | dentro |
| 1920×1080 | -- | 20 px sotto l'area libera | dentro |
| 1440×900 | -- | 16 px sotto l'area libera | dentro |
| 1920×1080 | LR | dentro (è la larghezza a vincolare) | dentro |

**Larghezza dell'ufficio con la nuova inquadratura** (calcolata, da verificare a schermo in T5):

| Viewport | LR | -R | -- |
|---|---|---|---|
| 1920×1080 | 1098 px (scala 0,61 di oggi) | 1422 px (0,79) | 1422 px (0,79) |
| 1440×900 | 637 px (0,35) | 965 px (0,54) | 1148 px (0,64) |

**Test** (`world-test.js`, suite `framing`):
- A1 su 20 layout (5 risoluzioni × 4 combinazioni di pannelli): tutto l'ingombro dentro l'area libera, centrato (±2 px), il 96,2% dell'asse più stretto occupato (margine 4%), target sul pavimento, angolo di camera invariato;
- A2 a zoom 0,5, 1, 2,2 e 4: il target resta al centro dell'area libera (±1 px);
- A3: lo spostamento usato da `OrbitControls` per il pan coincide con la dimensione reale di un pixel, e 100 px di trascinamento spostano l'immagine di 100 px (±1e-6), con la lente attiva;
- A4: sotto la soglia minima gli ingombri vengono ignorati, e le dimensioni nulle non producono NaN.

**Prova che i test colgono gli errori**, con due errori introdotti apposta in `framing.js`:
- con il segno della lente invertito fallisce "inside the free area";
- senza riportare il target sul pavimento fallisce "target on the floor".

Il modulo non è ancora collegato alla `World`: nessun cambiamento visibile fino a T5.

### T4 — Un'unica animazione della camera

**Cosa cambia:**
- `moveCamera({ target, offset, zoom, duration })` è registrata con `fx.track(this.camera)` e anima insieme target, orbita e zoom (0,7 s, rallentamento cubico come prima). `panTo`, `focus` e `focusRoom` la usano: il focus ora è un'unica animazione invece di due.
- **Scelta che conserva il comportamento di oggi:** un movimento nuovo parte da dove si trova la camera, e i valori che non imposta continuano verso la meta del movimento che sostituisce. Oggi un clic sulla minimappa durante un focus sposta la vista ma lascia finire lo zoom a 2,2; con uno slot unico "ingenuo" lo zoom si sarebbe fermato a metà.
- **L'orbita gira per la via breve**, in coordinate sferiche: il raggio resta costante e un offset invariato viene copiato esatto, senza errori di arrotondamento. Nessun chiamante la usa ancora; servirà a ⌂ in T5.
- `resetView()` ferma l'animazione in corso. **Bug preesistente corretto:** ⌂ premuto durante un focus veniva annullato dal focus, che continuava e riportava la camera sull'agente.
- `Fx.active(obj)` restituisce l'animazione attiva di un oggetto, così la `World` legge la meta corrente senza toccare le strutture interne di `Fx`.

**Equivalenza** con lo snippet `__camTest()`, che fa avanzare la `World` a 60 fps fissi e confronta vecchio e nuovo `world.js` nelle stesse condizioni:

| Scenario | Vecchio | Nuovo |
|---|---|---|
| Focus su un agente | ✔ zoom 2,2, salto massimo per frame 0,701 | ✔ identico |
| Focus su una stanza | ✔ zoom 2 | ✔ identico |
| Pan dalla minimappa | ✔ zoom e orbita invariati | ✔ identico |
| Focus su A, poi su B a metà | ✔ salto massimo 0,701, zoom mai in calo | ✔ identico |
| Pan dalla minimappa durante un focus | ✔ finisce a zoom 2,2, salto massimo 1,331 | ✔ identico |
| ⌂ durante un focus | ✖ finisce sulla CEO a zoom 2,2 | ✔ vista iniziale, zoom 1 |

**Rotazione dell'orbita** (nuova, misurata dal secondo frame in poi):
- da 170° a -170° la camera percorre +18,6°, cioè +20° per la via breve, di cui il primo frame non registrato copre circa il 7%;
- il raggio resta costante a 62,05;
- l'offset finale è esatto (errore circa 1e-14).

`world-test.js` controlla anche `Fx.active`. `npm test` è verde.

### T5 — Inquadratura collegata ai pannelli

**Cosa cambia:**
- **`main.js`:** `measureInsets()` legge topbar, pannelli e roster; un solo `ResizeObserver` li osserva e chiama `world.setInsets()`. Scatta anche quando un pannello viene nascosto, perché la sua dimensione scende a 0. Sotto i 900 px i pannelli non contano. ⌂ chiama `resetView({ animate: true })`.
- **`world.js`:**
  - `resetView()` usa `fitOffice()` e `moveCamera()`;
  - `moveCamera()` anima anche la proiezione (scala e spostamento) insieme a target, orbita e zoom;
  - ogni passo dell'animazione fa il proprio `lookAt`, così l'orientamento non è in ritardo di un frame rispetto ai controlli;
  - prima di ogni movimento, `settleControls()` esaurisce l'inerzia rimasta da un trascinamento.

**Scelte contro gli sfarfallii:**
- **Fit e ridisegno subito, dentro il `ResizeObserver`.** `renderer.setSize()` svuota il canvas dopo che il frame è già stato disegnato, e il browser esegue quei callback prima di dipingere: rimandare il fit al frame dopo, come prevedeva la prima versione del ticket, avrebbe mostrato un frame vuoto o deformato. Per lo stesso motivo anche la prima applicazione dei pannelli, al caricamento, ridisegna subito. S3.6 e il ticket sono aggiornati.
- **Scala animata direttamente invece del trucco sullo zoom.** `OrbitControls.update()` riporta lo zoom dentro [0,5, 4] a ogni frame (riga 895 di r186). Animare lo zoom fino a `vecchia / nuova` scala si sarebbe potuto scontrare con quel limite.

**Verifiche nel browser** (viewport emulato, misure numeriche):

| Verifica | Esito |
|---|---|
| A1: pavimento coperto con i layout LR, -R e -- | **0%** a 1920×1080, 2560×1440 e 1440×900 (prima: 21/14/0, 10/6/0, 38/23/0). Nessuno degli 11 punti dell'ingombro sotto l'interfaccia. |
| A1 su schermo stretto (800×600) | 0%; i pannelli sono ignorati, l'ufficio sta tra topbar e roster |
| Larghezza dell'ufficio a 1920×1080 | LR 1098 px, -R 1403 px, -- 1419 px |
| A6: apertura e chiusura dei pannelli | salto al momento del clic: **0 px**; animazione di 0,35 s esatti; larghezza monotona (1098 → 1403 e ritorno); finisce sul fit esatto |
| Ridimensionamento a 1600×900 | subito dopo il resize, aspetto della proiezione = aspetto del canvas, buffer di disegno aggiornato, vista già sul fit |
| A3: pan | 100 px di trascinamento = 100 px sullo schermo (calcolo di `OrbitControls` contro la proiezione reale) |
| Target al centro dell'area libera | scarto (0, 0) px |
| Click sugli agenti con lo spostamento della proiezione | 16/16 |
| ⌂ dopo un focus | animazione di 0,6 s fino al fit |
| Scenari di T4 | 6/6 ok (lo scenario 6 ora finisce sul fit) |
| Errori in console | nessuno nuovo dopo il ricaricamento |

**Limiti noti fino ai ticket successivi:**
- **Fino a T6** non c'è la modalità manuale: dopo un trascinamento, aprire o chiudere un pannello o ridimensionare la finestra ricentra comunque la vista.
- **Fino a T7:**
  - etichette e primi piani sono ancora relativi al fit, quindi con i pannelli aperti le etichette sembrano più grandi rispetto all'ufficio e il focus è meno ravvicinato di prima;
  - nella minimappa l'impronta della camera copre tutto il canvas.
