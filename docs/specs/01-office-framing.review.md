# Spec 01 — Code-review (SDD step 5)

| | |
|---|---|
| **Oggetto** | `main..feat/office-framing` (`c1312ff..973fba3`), 31 file, +2991 / −79 |
| **Data** | 2026-10-13 |
| **Stato** | concluso. Decisioni dell'utente: R1 approvata (metodo interno di `MapControls` accettato), R3 → ticket N5, R5 sì; R2, R4, R6–R8 da correggere. Esito nella sezione 4 |
| **Baseline** | `npm test` verde; `npm run test:browser` 123/123, missione demo completata in 153 s, 0 processi Edge rimasti |
| **Dopo** | `npm test` verde (13 casi in `world-test.js`); `npm run test:browser` **130/130**, missione completata, 0 processi Edge rimasti |

## 1. Metodo

- Letto tutto il diff, più i sorgenti di three r186 che il codice nuovo usa: `OrbitControls.update()`, gli handler dei puntatori, `MapControls._handleMouseDownPan/_handleMouseMovePan` e `WebGLAnimation`.
- Ogni sospetto è stato **misurato** su `window.agentWorld`:
  - viewport emulato a 1920×1080 nel pannello browser dell'app;
  - pannello nascosto, quindi resize e insets applicati a mano, con una pompa a 60 fps (il metodo di `scripts/browser/lib.js`).
- Ogni correzione proposta è stata **provata a runtime** prima di proporla, senza toccare i file.

## 2. Difetti trovati

Ordinati dal più grave. *In perimetro* = coperto da S1–S5 della spec. *Fuori perimetro* = da trattare secondo S6.3.

### R1 — Un trascinamento iniziato durante un movimento di camera fa scivolare la vista (media-alta, in perimetro: S4.6)

**Causa.** `MapControls` (r186) fa il pan "verso il punto afferrato":
- al `pointerdown` salva il punto del pavimento sotto il cursore (`_panWorldStart`);
- a ogni `pointermove` lo riporta sotto il cursore.

Se nel frattempo un movimento di camera (focus, ⌂, riadattamento ai pannelli) ha spostato la vista, quel punto non è più sotto il cursore. Il primo movimento del puntatore trascina allora la vista per tutto il tragitto dell'animazione.

`settleControls()` scarta lo spostamento in sospeso, ma non l'ancora: il pull si ricrea al `pointermove` successivo. Il report documenta solo il caso sotto i 5 px ("Pressione tenuta ferma durante un'animazione"). La misura mostra che il caso con trascinamento vero è più frequente e più grave.

**Misura** (1920×1080, LR). Pressione 0,05 s dopo l'inizio del movimento, trascinamento di 20 px. Lo scivolamento è la distanza a fine inerzia tra il cursore e il punto che c'era sotto al momento del trascinamento:

| Caso | Oggi | Con la correzione |
|---|---|---|
| Focus su un agente, trascinamento dopo 0,2 s | **253 px** | 0 px |
| ⌂ da un primo piano, trascinamento dopo 0,2 s | **113 px** | — |
| Pannello che si apre (automatico, 0,35 s), trascinamento dopo 0,12 s | **82 px** | — |
| Focus, pressione tenuta fino alla fine del movimento, poi 20 px | **447 px** | 0 px |
| Come sopra, poi solo 3 px (il limite documentato in T6) | **447 px**, resta automatico | 0 px |

La correzione è stata provata sui tre casi del focus. Gli altri due passano dallo stesso `step()` e andrebbero coperti dal test proposto.

**Correzione proposta.** Quando il codice muove la camera sotto una pressione di pan, la presa segue: a ogni passo di `moveCamera()`, compreso il passo istantaneo, se `controls.state === PAN` si riafferra il pavimento nel punto in cui si trova ora il puntatore.
- Si fa con `controls._handleMouseDownPan({ clientX, clientY })`, preceduto da `camera.updateMatrixWorld()`, perché `lookAt()` non aggiorna `matrixWorld`.
- **Costo:** usa un metodo interno di `MapControls` r186. three è fissato a `0.186.1` e servito da `node_modules`, e un test nuovo lo coprirebbe: se un aggiornamento lo cambia, il test fallisce.
- Il pan touch è incrementale (`_handleTouchMovePan`) e la rotazione pure: non serve toccarli.
- **Effetto collaterale positivo:** sparisce anche il limite noto di T6. La riga va tolta dal report.

**Esito** (`2b72e40`). Il pavimento viene riafferrato in `applyView()`, da cui passa ogni cambio dell'immagine fatto dal codice. Il controllo A7 "drag during an automatic re-frame" si aspettava il comportamento vecchio, cioè il punto premuto per primo di nuovo sotto il cursore: ora verifica il punto sotto il cursore all'inizio del trascinamento. È una precisazione di S4.6, annotata nella spec. Sul codice vecchio i quattro casi falliscono (31, 346, 37 e 687 px); ora restano sotto 1 px.

**Test proposto.** In `manual-mode.js`, i casi "pressione durante un movimento, poi 20 px" e "pressione tenuta fino alla fine, poi 3 px", con la soglia di scivolamento < 1 px. Mutazione: senza la ripresa il test deve fallire (253 e 447 px).

### R2 — Clic sull'etichetta di una stanza con il pannello destro chiuso: la stanza non è centrata (media, in perimetro: S3.7)

**Causa.** Il clic chiama `onPickRoom` → `selectTeam(team, true)` (`public/js/main.js:357`). La funzione:
1. chiama **prima** `world.focusRoom(id)`, che calcola la lente con gli ingombri attuali (pannello destro chiuso);
2. **poi** chiama `switchTab('teams')`, che apre il pannello destro;
3. il `ResizeObserver` arriva in modalità manuale e non muove nulla (S3.5).

Ne risulta proprio il sintomo che S3.7 doveva eliminare.

**Misura** (1920×1080, sinistro aperto e destro chiuso, stanze `dev`, `qa` e `research`): il centro della stanza finisce **206 px a destra** del centro dell'area libera, in tutti e tre i casi.

**Perché i test non l'hanno visto.** Lo scenario A7 "click on a room label" apre sempre il pannello destro prima del clic.

**Correzione proposta** (`main.js`, provata a runtime):

```js
function selectTeam(id, focus = false) {
  S.team = id;
  switchTab('teams');
  // the tab may have just opened the right panel: centre the room in the area left free now
  if (focus) {
    world.setInsets(measureInsets());
    world.focusRoom(id);
  }
}
```

- **Risultato:** scarto (0, 0) px e grandezza a schermo esatta (rapporto 1,0000), sia partendo da automatico sia da manuale.
- **Dopo:** il `ResizeObserver` successivo trova gli stessi ingombri ed esce subito.

**Test proposto.** Uno scenario A7 con il pannello destro chiuso prima del clic, che verifica il centro della stanza a ±1 px. Mutazione: con l'ordine vecchio lo scarto deve tornare a 206 px.

**Esito** (`b01fd69`): 206 px sul codice vecchio, 0 px ora.

### R3 — Gli effetti e le card non liberano le risorse GPU (media, fuori perimetro: S6.3)

`scene.remove()` non libera geometrie, materiali e texture. Lo fa solo `dispose()`.

**Misura** con `renderer.info.memory`: 50 effetti per tipo, poi 5,5 s di pompa.

| Effetto | Geometrie in più dopo la fine | Cosa manca in `dispose` |
|---|---|---|
| `beam` (con il suo anello d'arrivo) | +126 (circa 2,5 a fascio) | le sfere `head` e `glow`, i loro 2 materiali, il materiale della linea |
| `ring` | +50 (1 ad anello) | geometria e materiale |
| `burst` | +50 (il suo anello) | — (perde solo tramite `ring`) |
| `sparkle`, `confetti` | 0 | — |
| card rimossa (`removeCard`, `resetRun`) | texture non liberata (1 `CanvasTexture` 300×84 a card), né geometria né materiale | `map`, `material`, `geometry` |
| cubi | già noto nell'handoff | geometria, materiale, e il materiale sostituito da `sinkCube` |

- **Stima per run** (dai conteggi degli eventi della missione demo, non misurata su un run intero): circa 150 fasci, quindi circa 400 geometrie, più una venticinquina di texture di card. La memoria cresce senza limite in una sessione lunga.
- **Rapporto con il branch:** la perdita c'era già, ma questo branch la rende evidente. Prima di N1 gli anelli restavano *congelati nella scena*; ora finiscono e vengono tolti, ma restano sulla GPU.

**Proposta.** Ticket **N5**, oppure correzione ora in un commit a parte se lo preferisci: è piccola e meccanica.

**Esito:** per decisione dell'utente diventa il ticket **N5**, fuori da questo branch, come N2 e N4.
- Le correzioni: `dispose` in `ring` e `beam`, in `removeCard`, in `resetRun`, a fine consegna e affondamento dei cubi, e sul cubo grande di `splitWs`.
- La verifica: `renderer.info.memory` prima e dopo la fase `run` del runner.

### R4 — Un effetto che lancia un'eccezione fa perdere tutti gli effetti in corso (bassa, in perimetro: S4.5)

`Fx.update()` svuota `this.items` prima del ciclo e lo ricompone dopo. Se un `update` lancia, la ricomposizione non avviene:
- tutti gli effetti in corso escono dalla lista, e le loro mesh restano congelate nella scena (proprio il sintomo di N1);
- `tracks` continua a puntare a item orfani, quindi un `moveCamera()` successivo può ereditarne il `goal`.

Prima del branch, con un'eccezione la lista restava intatta.

- **Gravità:** ipotetica. Oggi nessun effetto lancia, e in r186 `setAnimationLoop` richiede il frame successivo *prima* di chiamare il loop, quindi il rendering non si ferma.
- **Correzione:** un `try/finally` che rimette in lista gli effetti non ancora aggiornati e ritira quello che ha lanciato. Più un caso in `world-test.js`.

**Esito** (`957018a`). Al posto del `try/finally` c'è un `try/catch` per ogni effetto: è più semplice e non perde l'ordine. L'effetto che lancia viene segnalato in console e ritirato, gli altri continuano. Il caso 7 di `world-test.js` fallisce sul codice vecchio.

### R5 — Lo zoom delle animazioni è interpolato in modo lineare (bassa, opzionale: è una scelta di resa)

È già annotato in T7 come fuori perimetro. Lo riprendo perché la review riguarda anche la resa delle animazioni.

- **Il problema:** zoom e `unitsPerPx` sono interpolati in modo lineare. Dalla vista completa con LR il focus ingrandisce 3,6 volte, e il primo frame ingrandisce già del **18%**.
- **La proposta:** con un'interpolazione geometrica (`z0 · (z1/z0)^e`, e lo stesso per `unitsPerPx`) il primo frame scende al **9%** e la velocità percepita segue la stessa curva del pan.
- **Il limite di zoom regge:** il vincolo `zoom ≤ unitsPerPx / (REF/4)` resta valido a ogni passo, perché diventa lineare nei logaritmi. La prova del n. 11 in `world-test.js` (ora n. 12) va riscritta di conseguenza.

**Esito** (`565adfe`). `scaleAt()` in `framing.js`, esatta agli estremi. Primo frame del focus dalla vista completa con LR:

| Viewport | Prima | Dopo |
|---|---|---|
| 1920×1080 | +18,1% | +9,3% |
| 2560×1440 | +9,1% | +6,0% |
| 1440×900 | +36,3% | +13,6% |

Zoom e target ora percorrono la stessa quota del loro tragitto in ogni frame (6,97% nel primo). I nuovi controlli, il caso 13 di `world-test.js` e A8 "size and place at the same pace" nei tre viewport, falliscono sul codice vecchio. Lo scenario A8 della trappola ora interrompe ⌂ dopo 1 frame invece di 2: con l'interpolazione geometrica, dopo 2 frame lo zoom è già sotto il limite finale e la mutazione non si vedrebbe più. Serve il QA visivo dell'utente.

Decidi tu: cambia la sensazione dell'animazione e richiede il tuo QA visivo.

### R6 — `updateLabels()` legge `canvas.clientWidth/clientHeight` a ogni frame (bassa, semplificazione)

- **Il punto:** `this.width` e `this.height` contengono già gli stessi valori, perché `resize()` li legge da `#stage` e il canvas è 100%×100%.
- **Perché conta:** leggerli dal DOM in un rAF può forzare un layout sincrono.
- **La correzione:** una riga. La funzione è toccata dal branch, ma la riga è preesistente.

**Esito** (`ec03288`): nessun cambio di comportamento, tutte le suite verdi.

### R7 — La spec nomina costanti che il codice non ha (bassa, documentazione)

- **Cosa dice la spec:** §4 e il ticket T3 nominano `VIEW_DIR`, `VIEW_DIST` e `fitOffice({ …, dir, distance })`.
- **Cosa fa il codice:** usa `VIEW_OFFSET` e `fitOffice({ …, offset })`.
- **Cosa manca:** la deviazione non è annotata nel report, mentre la regola "Ultra Code" chiede di documentarle tutte. Basta una nota di correzione nella spec, nello stesso stile delle altre.

**Esito** (commit `docs` di questo step): spec §4 e ticket T3 corretti, con la nota.

### R8 — `npm run test:browser` richiede Node 22, `engines` dice `>=20.10` (bassa, strumenti)

- **Il problema:** il runner usa il `WebSocket` globale, che è stabile solo da Node 22. Su Node 20 fallisce con `WebSocket is not defined`.
- **La correzione:** un controllo all'avvio con un messaggio chiaro, oppure una nota nel `package.json`. `npm test` non è coinvolto.

**Esito** (`c54618f`). La riproduzione con `node --no-experimental-websocket` ha mostrato un danno più grave del messaggio criptico:
- il runner avviava server ed Edge e falliva dopo 27 s;
- senza DevTools non poteva chiudere il browser, e restavano **9 processi Edge** con il profilo bloccato (li ho chiusi).

Ora esce con codice 1 in 0,1 s, prima di avviare qualsiasi cosa.

## 3. Cosa ho verificato e regge

**Matematica di `framing.js`**
- La base della camera coincide con quella di `Object3D.lookAt`.
- Il target scorre lungo la linea di vista fino a y = 0.
- Segno della lente: offset = −lens, il target appare a centro + lens.
- Lo zoom scala attorno al target (`updateProjectionMatrix` con `view`).
- Il pan resta 1:1.
- `safeRect` regge i degeneri: dimensioni 0, ingombri negativi o più grandi del canvas.

**Zoom verso il cursore con la lente** (non coperto da A3, misurato ora): dopo 4 scatti di rotella in tre punti dello schermo (0,25/0,3; 0,5/0,5; 0,7/0,75), il punto sotto il cursore deriva di **0 px** e il target resta a y = 0.

**`ENVELOPE` contro la geometria di `buildOffice`**
- base `-0.86 ± 0.8` → −1,66;
- plinto `W + 1.3` → 0,65;
- cordolo `5.05 + 0.09` → 5,14, a 0,45 dal pavimento.

Il Brain (cima a y ≈ 6,8, z = −11,6) resta dentro l'ingombro verticale sullo schermo: 12,3 contro 19,6 unità.

**Limiti dei controlli**
- `maxZoom` aggiornato a ogni passo.
- `MIN_ZOOM` relativo al fit.
- L'angolo polare di `VIEW_OFFSET` (0,87 rad) sta dentro `[0,3; 1,15]`, quindi `controls.update()` non lo corregge durante le animazioni.

**`ResizeObserver`:** nessun rischio di loop. `setSize(…, false)` non tocca il CSS e le etichette cambiano solo `transform`.

**`Fx`**
- La `WeakMap` oggetto → item → `OWNER` è un'effemeride: nessuna perdita.
- `retire` è idempotente.
- `track` e `stop` funzionano anche dentro un `done`.

**Cubi:** gli invarianti S5 riletti su tutti i percorsi (`pickupWs`, `splitWs`, `takeTaskCube`, `deliverCube`, `sinkCube`, `dropCube`, `resetRun`, `onDespawn`), più lo split rimandato tramite `lead.carrying`.

**Performance del ciclo di rendering** (nessuna regressione):

| Voce | Costo |
|---|---|
| passo di camera (`applyView`) | circa 0,1 µs |
| `footprint()` | 0,8 µs, ogni 4 frame |
| `pick()` | 22 µs per `pointermove` (434 mesh) |
| `Fx.update()` | 3 array piccoli a frame |
| run headless | 70 fps |

*Osservazione, senza azione:* durante un ridimensionamento della finestra ogni frame disegna fino a 3 volte (il frame, `resize()`, `setInsets()`). Nel pannello nascosto `renderNow()` costa 10–16 ms, una misura rumorosa. È il costo accettato con S3.6, e accorparlo richiederebbe un terzo observer o un ordine fra observer: non vale la complessità.

## 4. Esito

Un commit atomico per voce. Il test è stato scritto prima e ha fallito sul codice vecchio. `npm test` e `npm run test:browser` erano verdi dopo ogni commit.

| Commit | Voce | Il test fallisce senza la correzione |
|---|---|---|
| `2b72e40` | R1, la presa segue la camera sotto una pressione | 4 casi A7: 31, 346, 37 e 687 px |
| `957018a` | R4, un effetto che lancia non porta via gli altri | caso 7 di `world-test.js` |
| `b01fd69` | R2, l'etichetta di una stanza apre la scheda prima del focus | A7: 206 px |
| `565adfe` | R5, zoom interpolato in rapporto | caso 13 di `world-test.js`, A8 nei 3 viewport |
| `7788a29` | controllo A6 reso robusto (sezione 5) | — |
| `ec03288` | R6 | — (nessun cambio di comportamento) |
| `c54618f` | R8 | riproduzione con `--no-experimental-websocket` |
| `docs` | R7, più questo report | — |
| — | R3 → ticket N5 | — |

R4 è stato fatto prima di R2: il suo test era già scritto, e così `npm test` non è mai rimasto rosso tra un commit e l'altro.

## 5. Trovati durante le correzioni

- **A6 instabile.** In 1 giro completo su 6 il controllo "clicks on agents through the lens shift" ha dato 15/16. Un agente a spasso passava davanti a un altro, e il clic selezionava giustamente quello davanti. Il codice non c'entrava: nei 3 giri ripetuti subito dopo il risultato è stato 16/16. Ora il controllo si aspetta il primo agente sul raggio lanciato dal punto proiettato, senza coordinate del clic, e ammette al massimo 2 agenti coperti (`7788a29`).
- **N6, fuori perimetro.** `switchTab()` apre il pannello destro senza aggiornare `body.right-closed`. Roster e minimappa restano posizionati per il pannello chiuso e gli finiscono sotto. A 1920×1080:
  - la minimappa (1704–1908 px) sta tutta sotto il pannello (1508–1908 px);
  - il roster lo invade per 184 px.

  Esisteva già su `main`. Il controllo nuovo di R2 riallinea la classe alla fine del caso, per non sporcare i controlli successivi.
- **N7, fuori perimetro, strumenti.** `scripts/smoke.js` e `scripts/flows-test.js` creano una cartella `agent-world-smoke-*` o `agent-world-flows-*` nella cartella temporanea a ogni `npm test`, e non la rimuovono. Oggi ce ne sono più di 40.
