# Ticket — Spec 01, inquadratura dell'ufficio v3 e cubi

Riferimento: [01-office-framing.md](01-office-framing.md). Gli ID S* e A* rimandano alla spec.

**Ordine:** T0 → T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8. T3 non dipende da T1 e T2, ma resta in sequenza per tenere una sola cosa aperta alla volta.

**Regole valide per ogni ticket**
- Si chiude solo quando i suoi criteri sono verdi.
- Dopo ogni ticket che tocca codice: `node --check` sui file modificati e `node scripts/world-test.js` (da T1 in poi).
- Un difetto fuori dal perimetro della spec non si corregge al volo: si torna allo step 2 (S6.3).
- Server di prova: `PORT=4310`, `AGENT_WORLD_HOME` nella cartella temporanea della sessione, modalità demo, ritmo normale. Non tocca `data/` né un eventuale server sulla 4300.

| Ticket | Titolo | Spec | Dimensione | Dipende da |
|---|---|---|---|---|
| T0 | Baseline "prima" e riproduzione dei bug dei cubi | S6, A9 | S | — |
| T1 | `Fx`: un'animazione per oggetto (`track` e `stop`), ciclo che regge le aggiunte durante l'aggiornamento | S4.1, S4.2, S4.5, A5 | S | — |
| T2 | Cubi: lo stato logico cambia subito, i voli si possono annullare | S5, A9 | M | T1 |
| T3 | `framing.js` (matematica pura) ed `ENVELOPE` | S1.4, S2.1–S2.4, A1–A4 | M | — |
| T4 | Camera: un'unica animazione per `panTo`, `focus` e `focusRoom` | S4.3 | S | T1 |
| T5 | Integrazione dell'inquadratura: area libera, lente, ⌂, ricalcolo | S1.1–S1.3, S2.2, S2.3, S3.4, S3.6, A1, A3, A6 | M | T3, T4 |
| T6 | Modalità automatica e manuale | S3.1–S3.3, S3.5, S4.4, A7 | S | T5 |
| T7 | Scala assoluta: zoom, focus, etichette, minimappa | S2.5–S2.7, A8 | S | T5 |
| T8 | Verifica finale "dopo" e report | S6, A9–A11 | M | T0–T7 |

---

## T0 — Baseline "prima" e riproduzione dei bug dei cubi

**Obiettivo:** fotografare lo stato attuale prima di cambiare una riga, e verificare che R1–R4 si riproducano davvero.

**Attività**
1. Avviare il server di prova e aprirlo nel pannello browser.
2. Inquadratura iniziale a 1920×1080, 2560×1440 e 1440×900, con i pannelli LR, -R e --. Per ogni vista:
   - uno screenshot;
   - la percentuale di pavimento coperta, misurata con uno snippet in console che proietta la griglia del pavimento e la confronta con i rettangoli del DOM.
3. Una missione complessa a 1920×1080 con LR. Screenshot dei momenti chiave:
   - card sulla lavagna;
   - split in cubi;
   - worker che prendono i cubi;
   - sub-agenti nella bay;
   - QA alla scrivania con il verdetto;
   - consegna;
   - fine run.
4. Uno snippet in console che forza R1–R4 chiamando direttamente i metodi della `World`, con il controllo degli orfani di A9.

**Output:** `docs/specs/01-office-framing.report.md`, sezione "Prima". Contiene:
- le misure di copertura, da confrontare con la tabella 1.1 della spec;
- l'esito di R1–R4;
- le osservazioni su sub-agenti, QA e cubi.

**Fatto quando:**
- il report "Prima" è completo;
- ogni difetto nuovo è segnalato (se esce dal perimetro mi fermo e chiedo);
- nessun file di codice è stato modificato.

## T1 — `Fx`: un'animazione per oggetto

**File:** `public/js/world/fx.js`, `scripts/world-test.js` (nuovo), `package.json`.

**Attività**
1. Aggiungere `this.tracks = new WeakMap()`.
2. `track(obj, item)`:
   - annulla l'animazione attiva su `obj`;
   - registra `item`;
   - alla fine naturale di `item`, rimuove la voce dalla mappa solo se punta ancora a lui.
3. `stop(obj)`: segna l'animazione come annullata. `update()` la scarta senza chiamarla più, quindi `done` non parte mai. Chiama `dispose` se esiste.
4. `fly()` restituisce `this.track(obj, …)`. Nessun cambio di firma.
5. *(S4.5, dopo T0)* `update()` non sostituisce più l'array mentre lo scorre: gli effetti aggiunti durante il ciclo partono dal frame successivo, e quelli annullati vengono scartati senza `done`.
6. `scripts/world-test.js` con la suite `fx`:
   - un volo completato chiama `done` una volta e lascia l'oggetto a destinazione;
   - un secondo `fly` sullo stesso oggetto annulla il primo, senza `done` del primo;
   - `stop()` annulla senza `done`;
   - oggetti diversi non si annullano a vicenda;
   - lo stop di un'animazione già finita non ha effetti;
   - un effetto aggiunto dentro l'`update` o il `done` di un altro viene aggiornato e poi eliminato (`dispose` chiamato, mesh tolte dalla scena);
   - un `fly` avviato dentro il `done` di un altro `fly` sullo stesso oggetto parte davvero e non viene annullato dalla pulizia del primo.
7. `npm test` diventa `node scripts/world-test.js && …` (prima degli altri script, perché è il più veloce).

**Fatto quando:** A5 è verde e `npm test` parte con la nuova suite.

## T2 — Cubi: lo stato logico cambia subito

**File:** `public/js/world/world.js`.

**Attività**
1. `makeCube`: aggiungere `mesh.userData.cube = true`.
2. `carryInto(actor, mesh)`:
   - all'inizio, `this.fx.stop(mesh)`, `toScene(mesh)` e `actor.carrying = mesh`;
   - nel `done`, `if (actor.carrying === mesh) { this.scene.remove(mesh); actor.carry(mesh); }`.
3. `splitWs`: `fx.stop(big.mesh)` prima di `toScene`. Va verificato che `onSplit` ora rimandi lo split finché il lead ha il cubo, perché `carrying` è valorizzato già durante il volo (R2).
4. `deliverCube` e `sinkCube`: `fx.stop(mesh)` prima di `toScene`.
5. `dropCube`:
   - `const mesh = actor.release()` (ora restituisce anche un cubo in volo);
   - `fx.stop(mesh)`, poi `toScene(mesh)` al posto di `root.remove` + `scene.add`;
   - posizionamento sulla scrivania come oggi.
6. `takeTaskCube`: se il proprietario precedente aveva `carrying === cube.mesh`, chiamare `release()` su di lui prima di riassegnare il cubo.
7. `resetRun`: `fx.stop(mesh)` su tutti i cubi prima di rimuoverli.

**Fatto quando:**
- lo snippet di T0 rilanciato dà A9 verde per R1–R4;
- un mini-run demo non mostra regressioni sui cubi: split, presa, consegna, affondamento.

## T3 — `framing.js` ed `ENVELOPE`

**File:** `public/js/world/framing.js` (nuovo), `public/js/world/office.js`, `scripts/world-test.js`.

**Attività**
1. `office.js`: `export const ENVELOPE`, gli 11 punti di S2.1 (base del diorama e cime delle pareti), con un commento sull'origine dei numeri.
2. `framing.js` importa solo `three` ed esporta:

   | Nome | Cosa fa |
   |---|---|
   | `GAP = 12`, `MARGIN = 0.04`, `MIN_SAFE = [240, 160]` | costanti dell'area libera |
   | `REF_UNITS_PER_PX = 0.0323` | scala di riferimento (S2.5) |
   | `VIEW_DIR`, `VIEW_DIST` | direzione e distanza della camera (S2.4) |
   | `safeRect(w, h, insets)` | restituisce `{ x0, y0, x1, y1, cx, cy }`, con il fallback di S1.4 |
   | `fitOffice({ width, height, insets, envelope })` | restituisce `{ target, position, unitsPerPx, lensX, lensY, safe }`. L'ingombro lo passa la `World`, così `framing.js` non dipende da `office.js` |
   | `applyFrustum(camera, w, h, unitsPerPx, lensX, lensY)` | imposta la proiezione (S2.3) |

3. Suite `framing` in `world-test.js`:
   - ingombri simulati con le regole del CSS (sezione 6 della spec);
   - A1 su 5 risoluzioni × 4 combinazioni di pannelli;
   - A2 a zoom 0,5, 1, 2,2 e 4;
   - l'invariante del pan di A3;
   - il fallback di A4.

**Fatto quando:** A1–A4 sono verdi. Il modulo non è ancora collegato: nessun cambiamento visibile.

## T4 — Camera: un'unica animazione

**File:** `public/js/world/world.js`.

**Attività**
1. Aggiungere `moveCamera({ target, offset, zoom, duration = 0.7 })`:
   - un'unica animazione registrata con `fx.track(this.camera, …)` e ease-out cubica;
   - interpola target, offset della camera (lerp, poi lunghezza riportata a quella corrente) e zoom;
   - chiama `updateProjectionMatrix` a ogni passo.
2. `panTo`, `focus` e `focusRoom` usano `moveCamera`. `focus` diventa una sola animazione (pan e zoom insieme).
3. È un puro refactor: inquadratura, zoom e durate restano quelli di oggi.

**Fatto quando:**
- nel browser, focus su un agente, focus su una stanza e clic sulla minimappa si comportano come prima;
- un focus lanciato durante un altro focus non produce scatti.

## T5 — Integrazione dell'inquadratura

**File:** `public/js/world/world.js`, `public/js/main.js`.

**Attività**
1. Nuovo stato della `World`: `insets`, `unitsPerPx`, `lens {x, y}`, `viewDirty`, `lastSize`, `framedOnce`.
2. `moveCamera` accetta anche `lens` e `unitsPerPx`. Durante l'animazione la scala resta quella vecchia e lo zoom va verso `vecchia / nuova`. Alla fine si normalizza a `unitsPerPx = nuova` e `zoom = 1`, senza differenze visibili.
3. `resize()`: `setSize`, `applyFrustum` immediato con i parametri correnti, `viewDirty = true` (S3.6).
4. `setInsets(i)`: se gli ingombri non cambiano non fa nulla; altrimenti li salva e imposta `viewDirty = true`.
5. `frame()`: se `viewDirty`, chiama `relayout()` una sola volta. `relayout()` (in modalità automatica, l'unica che esiste fino a T6) chiama `resetView` con l'animazione decisa da S3.4: istantanea la prima volta o se il canvas ha cambiato dimensione, 0,35 s altrimenti.
6. `resetView({ animate, duration })`: `fitOffice` e poi, a seconda dei casi, `moveCamera` o un'applicazione diretta.
7. `main.js`:
   - `measureInsets()` secondo S1.1 (in modalità stretta i pannelli sono ignorati);
   - `ResizeObserver` su `.topbar`, `#left`, `#right` e `#roster`;
   - ⌂ chiama `resetView({ animate: true, duration: 0.6 })`.

**Fatto quando:**
- A1 è verificato nel browser alle 3 risoluzioni e nelle 3 combinazioni di pannelli, con lo snippet di copertura di T0 a 0%;
- A3 nel browser: un punto afferrato resta sotto il cursore;
- A6: apertura e chiusura dei pannelli animate, nessun frame deformato quando si ridimensiona la finestra.

## T6 — Modalità automatica e manuale

**File:** `public/js/world/world.js`.

**Attività**
1. `autoFrame = true`.
2. Le azioni dell'utente passano a manuale e chiamano `fx.stop(this.camera)`:
   - sul canvas: `pointermove` con tasti premuti oltre 5 px dal `pointerdown`, oppure `wheel`;
   - `focus()`, `focusRoom()` e il clic sulla minimappa.
3. `relayout()` in modalità manuale applica solo `applyFrustum` con i parametri correnti (S3.5).
4. `resetView()` rimette `autoFrame = true`.

**Fatto quando:** A7 è verde. Un semplice clic sul pavimento, senza trascinamento, non passa a manuale.

## T7 — Scala assoluta

**File:** `public/js/world/world.js`.

**Attività**
1. A ogni fit: `controls.maxZoom = unitsPerPx / (REF / 4)`, mentre `minZoom` resta 0,5.
2. Zoom del focus:
   - agente: `max(zoom, unitsPerPx / (REF / 2.2))`;
   - stanza: `unitsPerPx / (REF / 2)`;
   - entrambi limitati a `maxZoom`.
3. `updateLabels()`: zoom effettivo `ez = REF / (unitsPerPx / zoom)`, usato per la scala delle etichette e per la classe `far`.
4. `drawMinimap()`: l'impronta della camera si calcola dagli angoli dell'area libera, convertiti in coordinate normalizzate (NDC), invece che dagli angoli del canvas.

**Fatto quando:**
- A8: dopo un focus, `unitsPerPx / zoom` vale `REF / 2.2` ±5%, con e senza pannelli;
- l'impronta nella minimappa corrisponde all'area visibile;
- le etichette sono leggibili negli screenshot.

## T8 — Verifica finale "dopo"

**Attività**
1. Le stesse viste e la stessa missione di T0, a parità di condizioni.
2. Lo snippet A9 rilanciato.
3. `npm test` completo e `node --check` su tutti i moduli front-end modificati.
4. Report, sezione "Dopo": confronto con "Prima" e stato di A1–A11 uno per uno.

**Fatto quando:** A1–A11 sono verdi oppure ogni eccezione è motivata e messa in evidenza.

---

Dopo T8: **step 5 (Code-review)** sul diff completo, poi **step 6 (Retro)** con l'aggiornamento di HANDOFF.md, compresa la correzione "nessun commit" diventata `c1312ff`.
