# Spec 01 — Inquadratura dell'ufficio v3 e cubi

| | |
|---|---|
| **Stato** | approvata (SDD step 2). Ticket in `01-office-framing.tickets.md` |
| **Data** | 2026-10-12 |
| **Origine** | HANDOFF.md, priorità 1 |
| **Decisioni già prese** | ricentramento automatico, sospeso quando l'utente muove la vista (si torna con ⌂); bug dei cubi incluso; D1 = (a), ufficio sempre intero; D2 = 1920×1080 come riferimento (risoluzione reale non indicata) |

## 1. Contesto: cosa è stato misurato

### 1.1 Inquadratura

Il canvas copre tutta la finestra (`#stage { position: fixed; inset: 0 }`). Topbar, pannelli, roster e minimappa ci stanno sopra.

`resize()` e `resetView()` in `world.js` inquadrano l'intera finestra:
- spazio inquadrato `view = max(31, 62 / aspect)`;
- target fisso in `(0, 0, -0.5)`.

Quindi non tengono conto dei pannelli. Inoltre, aprire o chiudere un pannello non ricalcola nulla: il `ResizeObserver` guarda `#stage`, che non cambia dimensione.

Le misure qui sotto vengono da `framing.mjs`, uno script di calcolo puro con three r186. Simula il layout CSS attuale e la camera attuale, poi proietta una griglia di punti sul pavimento.

Come leggere le tabelle:
- **Zone**: 0–3 sono la fila posteriore (z = -1.2), 4–7 la fila anteriore (z = 9.6), entrambe da sinistra a destra.
- **Coperta** significa: sotto un pannello, la topbar, il roster o la minimappa, oppure fuori dallo schermo.

**Entrambi i pannelli aperti**

| Schermo | Pavimento coperto oggi | Zone più coperte oggi | Con l'inquadratura nuova | Larghezza dell'ufficio: oggi → nuova |
|---|---|---|---|---|
| 1920×1080 | 21% | zona 3: 44%, zona 4: 51% | 0% | 1774 → 1098 px |
| 2560×1440 | 10% | zona 3: 12%, zona 4: 24% | 0% | 2366 → 1713 px |
| 1440×900 | 38% | zone 0, 3, 4, 7: tra 53% e 88% | 0% | 1331 → 637 px |
| 1280×800 | 48% | zona 3: 100%, zona 4: 99% | 0% | 1183 → 483 px |

**Solo il pannello destro aperto**

| Schermo | Pavimento coperto oggi | Con l'inquadratura nuova | Larghezza dell'ufficio: oggi → nuova |
|---|---|---|---|
| 1920×1080 | 14% | 0% | 1774 → 1427 px |

Con l'inquadratura nuova la minimappa copre al massimo l'1% del pavimento, quindi non serve trattarla come un ostacolo.

### 1.2 Cubi

`Fx.fly()` non annulla un volo ancora attivo sullo stesso oggetto. Inoltre `carryInto()` aggiorna `actor.carrying` solo alla fine del volo (nel `done`). Ne nascono quattro casi, tutti verificati leggendo il codice:

| # | Sequenza | Effetto |
|---|---|---|
| R1 | `splitWs` (volo verso la scrivania) seguito da `takeTaskCube` (volo verso la mano) | Due voli muovono lo stesso cubo. Se finisce prima il volo verso la mano, il volo dello split continua a scrivere coordinate del mondo su un cubo ormai figlio dell'attore, che si sposta lontano dal personaggio. È il bug noto. |
| R2 | `pickupWs` (volo verso la mano, 0,45 s) seguito subito da `splitWs` | Durante il volo `lead.carrying` è ancora `null`, quindi lo split non viene rimandato. Il `done` del volo attacca poi il cubo grande, ormai rimosso, alla mano del lead: resta un cubo orfano per sempre. |
| R3 | `carryInto` seguito da `deliverCube` o `sinkCube` durante il volo | Il `done` del volo attacca il cubo all'attore. Il `scene.remove()` finale non ha effetto perché il genitore non è più la scena: resta un cubo orfano in mano. |
| R4 | `resetRun` con voli in corso | I `done` dei voli attaccano i cubi del run precedente ai personaggi del run nuovo. |

## 2. Obiettivi e non-obiettivi

**Obiettivi**
- G1: all'avvio e con ⌂, tutto l'ufficio (pavimento e pareti) sta nell'area non coperta dall'interfaccia, centrato, a qualsiasi risoluzione e con qualsiasi combinazione di pannelli.
- G2: in modalità automatica, aprire o chiudere un pannello o ridimensionare la finestra riadatta la vista.
- G3: in modalità manuale la vista non si muove da sola.
- G4: nessun cubo orfano e nessun cubo mosso da due animazioni insieme.
- G5: osservare un run completo (sub-agenti, QA, cubi) con screenshot di prima e dopo.

**Non-obiettivi**
- Angolo della camera, dimensione dei personaggi, arredi: sono la priorità 2 e dipendono dai tuoi feedback. La direzione della camera resta `(15, 40, 45)`.
- Server e motore.
- Comportamento dei pannelli su mobile (≤ 900 px): lì i pannelli sono overlay a schermo intero e vengono ignorati dall'inquadratura.

## 3. Requisiti funzionali

### S1 — Area libera (safe area)

- **S1.1** `main.js` misura gli ingombri come `{ top, right, bottom, left }`, in px CSS relativi al rettangolo del canvas:
  - `top` = bordo inferiore di `.topbar`;
  - `left` = bordo destro di `#left`, solo se è visibile (larghezza e altezza > 0) e non siamo in modalità stretta;
  - `right` = distanza dal bordo sinistro di `#right` al bordo destro del canvas, con le stesse condizioni;
  - `bottom` = distanza dal bordo superiore di `#roster` al fondo del canvas.
- **S1.2** Non contano come ostacoli: la minimappa (misurata, vedi 1.1), l'inspector (si apre con il focus su un agente, che è già un'azione manuale), i toast e le modali.
- **S1.3** Un solo `ResizeObserver` su `.topbar`, `#left`, `#right` e `#roster` chiama `world.setInsets(insets)`. Copre tutti i casi: apertura e chiusura dei pannelli (`display: none` porta la dimensione a 0), media query, ridimensionamento della finestra, roster che si allarga.
- **S1.4** Area libera = canvas meno gli ingombri, meno un margine `GAP = 12` px per lato. Se il risultato è più piccolo di 240×160 px, gli ingombri vengono ignorati e si usa tutto il canvas.

### S2 — Inquadratura (fit)

- **S2.1** L'ingombro dell'ufficio (`ENVELOPE`) è formato da 7 punti:
  - i 4 angoli esterni del pavimento con lo spessore delle pareti: `(±24.4, 0, ±17.4)`;
  - le 3 cime delle pareti, a `y = 5.14` (cima del cordolo): `(-24.4, 5.14, -17.4)`, `(24.4, 5.14, -17.4)`, `(-24.4, 5.14, 17.4)`.
- **S2.2** Il fit sceglie:
  - il **target** sul pavimento (`y = 0`) in modo che `ENVELOPE` sia centrato nello spazio della vista;
  - la **scala** `unitsPerPx`, cioè le unità di mondo per pixel a zoom 1, in modo che `ENVELOPE` occupi l'area libera con un margine del 4% sull'asse più stretto.
- **S2.3** La lente (lens shift) usa `camera.setViewOffset(w, h, -lensX, -lensY, w, h)`, con `lens` = centro dell'area libera meno centro del canvas. Il punto target appare così al centro dell'area libera. Conseguenze, verificate nel codice di three r186:
  - lo zoom scala attorno al target, che resta al centro dell'area libera a qualsiasi zoom (`OrthographicCamera.updateProjectionMatrix`, righe 207–216);
  - il pan resta 1:1 sotto il cursore. `OrbitControls._pan` usa `(right - left) / zoom / clientWidth` (riga 1015), e `right - left = w · unitsPerPx` non cambia con la lente;
  - lo zoom verso il cursore, il raycasting, le etichette e la minimappa passano da `project`/`unproject` e restano corretti.
- **S2.4** La direzione della camera resta invariata: `normalize(15, 40, 45)`, distanza 62,05.
- **S2.5** Le scale assolute di oggi si conservano. Riferimento `REF = 0.0323` unità/px, cioè la vista attuale a 1920×1080 con zoom 1.
  - `minZoom` = 0,5, relativo al fit;
  - `maxZoom` = `unitsPerPx / (REF / 4)`: il primo piano più stretto resta quello di oggi;
  - il focus su un agente usa zoom `max(zoom, unitsPerPx / (REF / 2.2))`, il focus su una stanza `unitsPerPx / (REF / 2)`, entrambi limitati a `maxZoom`.
- **S2.6** Dimensione delle etichette e classe `far` dipendono dalla scala assoluta e non da `camera.zoom`. Zoom effettivo = `REF / (unitsPerPx / zoom)`. Le etichette restano coerenti con le dimensioni reali sullo schermo.
- **S2.7** L'impronta della camera nella minimappa disegna l'area libera, non tutto il canvas.

### S3 — Modalità automatica e manuale

- **S3.1** `autoFrame = true` all'avvio.
- **S3.2** Passa a manuale (`autoFrame = false`) solo per azioni dell'utente:
  - trascinamento sul canvas oltre 5 px (stessa soglia del clic), sia pan sia rotazione;
  - rotella sul canvas;
  - pinch;
  - `focus()` (clic su un agente o nel roster), `focusRoom()` (scheda Team), clic sulla minimappa.

  I movimenti di camera fatti dal codice non cambiano mai la modalità.
- **S3.3** ⌂ chiama `resetView({ animate: true })`: rimette `autoFrame = true` e anima verso il fit in 0,6 s, ricentrando anche l'angolo se l'utente aveva ruotato.
- **S3.4** In modalità automatica, quando cambiano gli ingombri o il canvas:
  - la prima applicazione degli ingombri è istantanea;
  - un cambio di ingombri a canvas invariato (apertura o chiusura di un pannello) anima in 0,35 s;
  - un cambio di dimensione del canvas è istantaneo.
- **S3.5** In modalità manuale, un cambio di ingombri non muove nulla. Un cambio di dimensione del canvas mantiene `unitsPerPx`, `lens` e il target: il contenuto non si deforma e non salta.
- **S3.6** `resize()` applica subito la proiezione con i parametri correnti, così non c'è mai un frame deformato. Il nuovo fit avviene al frame successivo, una sola volta anche se il frame riceve più notifiche.

### S4 — Animazioni esclusive per oggetto

- **S4.1** `Fx` mantiene al massimo un'animazione di movimento attiva per oggetto (`WeakMap<Object3D, item>`):
  - `fx.track(obj, item)` registra l'animazione e annulla quella precedente sullo stesso oggetto;
  - `fx.stop(obj)` annulla l'animazione attiva;
  - un'animazione annullata non chiama mai `done`.
- **S4.2** `fly()` passa da `track`.
- **S4.3** Le animazioni della camera (fit, ⌂, `panTo`, `focus`, `focusRoom`) diventano un'unica animazione di camera registrata su `this.camera`: target, offset, zoom, lente e scala insieme. `focus` oggi lancia due animazioni separate e va unificato.
- **S4.4** Un'interazione dell'utente (S3.2) chiama `fx.stop(this.camera)`, così l'animazione non combatte con i controlli.
- **S4.5** *(aggiunta dopo T0, difetto N1 del report)* `Fx.update()` deve reggere gli effetti creati durante l'aggiornamento di un altro effetto: vanno aggiornati dal frame successivo, non persi. Oggi si perdono gli anelli d'arrivo dei fasci e le scintille delle consegne, le cui mesh restano congelate nella scena (144 anelli e 170 particelle dopo un run). Lo stesso vale per `track` e `stop` chiamati dentro un `done`.

### S5 — Cubi

- **S5.1** Invariante: **lo stato logico cambia subito, i voli sono solo grafica annullabile.**
  - `carryInto(actor, mesh)` imposta `actor.carrying = mesh` all'inizio del volo;
  - il `done` attacca il cubo alla mano solo se `actor.carrying === mesh`.
- **S5.2** Ogni passaggio di un cubo chiama prima `fx.stop(mesh)` e poi `toScene(mesh)`: `splitWs` (sul cubo grande), `deliverCube`, `sinkCube`, `dropCube`, `takeTaskCube` e `resetRun` (su tutti i cubi).
- **S5.3** `dropCube` funziona anche con il cubo ancora in volo: `release()` ora lo restituisce.
- **S5.4** `takeTaskCube` libera il cubo dal proprietario precedente se lo stava portando.
- **S5.5** `makeCube` marca `mesh.userData.cube = true`, per i controlli di test.

### S6 — Osservazione del run (prima e dopo)

- **S6.1** Il server gira in demo con `AGENT_WORLD_HOME` puntato a una cartella temporanea, ritmo normale (non `AGENT_WORLD_FAST`), missione complessa con sub-agenti.
- **S6.2** Viste da catturare:
  - 1920×1080, 2560×1440 e 1440×900, con i pannelli nelle combinazioni LR, -R e --;
  - a ognuna di queste, l'inquadratura iniziale;
  - a 1920×1080 con LR, i momenti chiave: card sulla lavagna, split in cubi, worker che prendono i cubi, sub-agenti nella bay, QA alla scrivania con il verdetto, consegna, fine run.
- **S6.3** Un difetto osservato che non è coperto da S1–S5 non si corregge al volo. Diventa un'aggiunta a questa spec (si torna allo step 2).

## 4. Design tecnico

| File | Modifica |
|---|---|
| `public/js/world/framing.js` (nuovo) | Matematica pura, senza DOM: `safeRect(w, h, insets)`, `fitOffice({ width, height, insets, envelope, dir, distance })` che restituisce `{ target, position, unitsPerPx, lensX, lensY }`, `applyFrustum(camera, w, h, unitsPerPx, lensX, lensY)`. Costanti `GAP`, `MARGIN`, `REF_UNITS_PER_PX`, `VIEW_DIR`, `VIEW_DIST`. Importa solo `three`. |
| `public/js/world/office.js` | Esporta `ENVELOPE` vicino a `FLOOR`, con un commento sull'origine dei numeri. Nessun'altra modifica. |
| `public/js/world/fx.js` | `track()`, `stop()`, `fly()` tramite `track()`. |
| `public/js/world/world.js` | `setInsets()`, `resize()`, `resetView({ animate })`, un `relayout()` con flag di frame, `moveCamera()` come unica animazione di camera (usata da `panTo`, `focus`, `focusRoom` e dal fit), rilevamento delle interazioni manuali, etichette e minimappa basate sulla scala assoluta, invarianti dei cubi (S5). |
| `public/js/main.js` | `measureInsets()`, il `ResizeObserver` di S1.3, ⌂ che chiama `resetView({ animate: true })`. |
| `scripts/world-test.js` (nuovo) | Test in Node di `framing.js` e `fx.js` (sezione 6), aggiunto a `npm test`. |

## 5. Criteri di accettazione

| ID | Criterio | Come si verifica |
|---|---|---|
| A1 | Con il fit, tutti i punti di `ENVELOPE` cadono nell'area libera (tolleranza 1 px). L'ingombro è centrato (±2 px) e occupa almeno il 95% dell'area libera sull'asse più stretto. Risoluzioni: 1920×1080, 2560×1440, 1440×900, 1280×800, 800×600; pannelli LR, L-, -R, --. | `world-test.js` |
| A2 | Il target appare al centro dell'area libera (±1 px) a zoom 0,5, 1, 2,2 e 4. | `world-test.js` |
| A3 | Pan 1:1: `(right - left) / zoom / w === unitsPerPx / zoom`. | `world-test.js`, più il controllo nel browser: un punto afferrato resta sotto il cursore (±2 px) con la lente attiva |
| A4 | Se l'area libera scende sotto 240×160 px, gli ingombri vengono ignorati. | `world-test.js` |
| A5 | `fly` su un oggetto già in volo annulla il volo precedente senza chiamarne il `done`. `stop()` fa lo stesso. Un volo completato chiama `done` una sola volta. Un effetto creato dentro l'aggiornamento di un altro effetto viene aggiornato ed eliminato (S4.5). | `world-test.js` |
| A6 | In modalità automatica, aprire o chiudere un pannello riadatta la vista con un'animazione di circa 0,35 s, senza frame deformati. | browser |
| A7 | Dopo un trascinamento, la rotella, un clic su un agente, sulla minimappa o su una stanza, aprire o chiudere un pannello non muove la vista. ⌂ ripristina la modalità automatica con un'animazione. | browser |
| A8 | Il focus su un agente lo porta al centro dell'area libera, con la stessa grandezza a schermo di oggi (±5%). | browser, con la misura di `unitsPerPx / zoom` |
| A9 | Stress dei cubi: si forzano R1–R4 da console. Dopo 2 s nessun personaggio ha `carrying` fuori da `world.cubes`, nessun figlio di `actor.root` con `userData.cube` è diverso da `carrying`, e nessun cubo nella scena è fuori da `world.cubes`, salvo quelli in consegna o in affondamento (finiscono entro 1,5 s). | snippet in console |
| A10 | Run completo osservato (S6) e screenshot di prima e dopo allegati al report. | browser |
| A11 | `npm test` verde e `node --check` verde sui moduli front-end modificati. | terminale |

## 6. Test automatici (`scripts/world-test.js`)

- **framing:** A1–A4 su tutte le combinazioni di risoluzione e pannelli. Gli ingombri si calcolano con le stesse regole del CSS: `--left-w` 330 o 300 px, `--right-w` 400 o 360 px, soglia 1250 px, topbar fino a 58 px, roster alto 62 px.
- **fx:** A5 con una `THREE.Scene` reale e `update(dt)` chiamato a mano.
- La logica della `World` (cubi, modalità) richiede WebGL e il DOM: si verifica nel browser (A6–A10).

## 7. Decisioni aperte

1. **D1 — Dimensione dell'ufficio nella vista completa.** Mostrare tutto l'ufficio accanto ai pannelli lo rimpicciolisce: a 1920×1080 con entrambi i pannelli la larghezza passa da 1774 a 1098 px (−38%), a 1440×900 da 1331 a 637 px.
   - **(a) Consigliata:** il fit mostra sempre l'ufficio intero. I primi piani (focus e zoom massimo) restano grandi come oggi grazie a S2.5, e chiudendo i pannelli l'ufficio torna a 1427–1467 px.
   - **(b)** Un limite minimo di scala, per esempio il 75% della grandezza attuale. Quando l'area libera non basta, si accetta che le zone laterali finiscano in parte sotto i pannelli.
2. **D2 — Risoluzione del monitor.** Nel tuo messaggio è rimasto il segnaposto. Uso 1920×1080 come riferimento per gli screenshot. La soluzione non dipende dalla risoluzione: conta solo per valutare D1.

## 8. Rischi

- **`setViewOffset` usato come lente.** È un uso meno comune: three lo documenta per configurazioni multi-monitor. La matematica è verificata nel codice di r186 (sezione S2.3) e coperta da A2 e A3. Se un aggiornamento di three cambiasse `_pan`, A3 lo segnalerebbe.
- **Etichette e zoom effettivo (S2.6).** Con entrambi i pannelli aperti, lo zoom effettivo della vista completa è circa 0,62. Le etichette dei worker inattivi spariscono (`far`), come succede oggi allontanandosi con lo zoom. Va verificato negli screenshot: la soglia è regolabile.
- **Pannello del browser dell'app.** Il rendering si ferma quando il pannello è nascosto (bug noto). Gli screenshot vanno fatti con il pannello visibile.
