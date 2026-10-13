# Spec 02 — Code-review (SDD step 5)

| | |
|---|---|
| **Oggetto** | `main..feat/ui-overlaps` (`e14f039..3a83aa7`), 12 commit, 36 file, +2163 / −82. Produzione: 3 file, +48 / −21. Test: 6 file, +1140 / −61 |
| **Data** | 2026-10-13 |
| **Fronti chiesti** | prestazioni di `:has()` (ricalcoli di stile a catena, repaint); solidità dell'inoltro della rotella (costo, perdite di memoria); regressioni nelle regole dei breakpoint |
| **Esito** | nessun difetto in perimetro da correggere nel codice dell'app. Una correzione di commento nei test (R7, `3a83aa7`). Una decisione per te: la compatibilità con Safari 15.4–16.3 (R5) |

**In breve**
1. **`:has()`.** Nessun ricalcolo a catena: inserimenti nel DOM, classi sulle etichette e `far` ricalcolano gli stessi elementi di `main` (mediana 1). Il clic su un pannello ricalcola tutto il documento (379 elementi contro una mediana di 267), ma in tempo non costa di più: 5,9 ms in mediana contro 7,8 su `main`, misurati su 60 clic, e senza i picchi di `main` (fino a 1011 elementi e 40 ms).
2. **Rotella.** L'inoltro costa 0,17 ms per passo in mediana (0,59 al 95° percentile) e non perde memoria: in 2000 passi ascoltatori e nodi restano costanti, e l'heap cresce quanto su `main`. Non nascono layer nuovi (57 su entrambi). Lo scorrimento dei pannelli resta veloce come prima: nessuna zona bloccante nuova sopra pannelli, roster, minimappa o topbar.
3. **Breakpoint.** Le combinazioni di regole reggono a 1250/1251 e 900/901 px e sulla scansione da 360 a 1920. Un limite di compatibilità: Safari 15.4–16.3 conosce `:has()` ma non la sintassi a intervallo delle media query, e lì lo stato dei pannelli verrebbe ignorato.
4. **Provata e scartata** una variante che dichiara le variabili della colonna solo sui tre elementi che le usano: 332 elementi a clic, 5,7 ms, nessun guadagno misurabile. Resta il disegno approvato in T1.
5. **Igiene degli strumenti.** Le mie sonde usa e getta, interrotte, hanno lasciato 41 processi Edge (chiusi, 0 rimasti). Il runner non ne ha mai lasciati. È una lezione per la retro.

## 1. Metodo

- **Letto tutto il diff** di produzione e di test.
- **Letti i sorgenti di three r186** usati dall'inoltro: `OrbitControls.onMouseWheel`, `_customWheelEvent`, `_interceptControlDown`, `connect()`.
- **Due sonde con DevTools**, nella cartella temporanea della sessione e non nel repo, eseguite su `main` (`e14f039`, estratto con `git archive`, `node_modules` collegato) e su HEAD:
  - `perf-probe.mjs`: tracing di Chrome (`devtools.timeline`). Per ogni azione conta gli elementi ricalcolati (`UpdateLayoutTree.elementCount`) e il tempo di stile, delimitando ogni passo con `console.timeStamp`. Misura anche la durata delle dispatch di `wheel` (`EventDispatch`), separando l'evento esterno da quello inoltrato, e prende `JSEventListeners`, `Nodes` e `JSHeapUsedSize` dopo una garbage collection forzata;
  - `wheel-regions.mjs`: i layer del compositore (`LayerTree`) con le loro zone `WheelEventHandler`, cioè dove la rotella deve passare dal thread principale.
- **Ogni sospetto è stato misurato**, e ogni modifica provata è stata misurata prima di decidere (R1).

## 2. Fronti chiesti

### R1 — `:has()` e ricalcoli di stile (nessun difetto)

**Il rischio.** `:root:has(#left.closed)` e `:root:has(#right.closed)` mettono sotto osservazione l'intero documento. Il browser potrebbe:
- rivalutarli a ogni mutazione del DOM o delle classi;
- oppure, al loro cambio, ricalcolare tutto per via delle variabili ereditate da `:root`.

**Misure** (1920×1080, mediana e massimo degli elementi ricalcolati per passo):

| Azione | `main` | HEAD | Lettura |
|---|---|---|---|
| inserire e togliere un elemento in un pannello (50 volte) | 1 (max 125) | 1 (max 125) | identico: `:has()` non si rivaluta per mutazioni che non toccano `closed` né `#left` o `#right` |
| classe `hover` su un'etichetta (50 volte) | 1 | 1 | identico |
| classe `far` su `#labels` (20 volte) | 24 (max 48) | 24 (max 48) | identico |
| 120 frame del mondo con le etichette che si muovono | 0 ricalcoli | 0 ricalcoli | identico (le trasformazioni inline non passano dal ricalcolo) |
| clic su ▤ (60 volte) | 267 (min 3, max 1011), 7,8 ms (max 40) | 379 (min 239, max 379), 5,9 ms (max 9) | HEAD ricalcola sempre il documento, ma non costa di più ed è più regolare |

Su 20 clic, un primo giro aveva dato 3,6 ms per `main` e 4,7 per HEAD. I tempi del ricalcolo oscillano di qualche millisecondo da un giro all'altro, ma in nessuno dei due giri HEAD supera il caso peggiore di `main`.

**Variante provata e scartata.** Le variabili `--col-left`, `--col-right` e `--map-right` dichiarate su `.roster`, `.inspector` e `.minimap`, con regole `:root:has(…) :is(.roster, .inspector)`, invece che su `:root`. L'idea era che un clic ricalcolasse tre elementi invece del documento. Misurato con 60 clic: 332 elementi, 5,7 ms. Chrome invalida comunque in modo ampio quando cambia lo stato di `:has()` sulla radice, e il guadagno sta dentro il rumore. Non ne vale la complessità: resta il disegno approvato in T1.

**Repaint.** Il clic su un pannello cambia la disposizione di roster, minimappa e inspector come prima. Il canvas si ridisegna per il riadattamento della vista (spec 01), invariato.

### R2 — Inoltro della rotella: costo e memoria (nessun difetto)

| Misura (60 passi reali di rotella, 1920×1080) | `main` | HEAD |
|---|---|---|
| un passo sopra un'etichetta di stanza | 0,011 ms (non succede nulla) | 0,355 ms in mediana, 1,02 al 95° percentile |
| di cui l'inoltro (evento esterno meno quello annidato) | — | 0,174 ms in mediana, 0,59 al 95° percentile |
| un passo sul pavimento | 0,305 ms | 0,308 ms |

L'inoltro aggiunge circa 0,05–0,17 ms al lavoro di zoom che il canvas fa comunque, su un fotogramma da 16,7 ms. Un passo non alloca altro che un `WheelEvent`.

**Memoria**, dopo una garbage collection forzata, ogni 500 passi sopra l'etichetta:

| | Ascoltatori | Nodi | Heap (MB) |
|---|---|---|---|
| `main` (nessun inoltro) | 52 → 52 → 52 → 52 → 52 | 484, costanti | 11,76 → 11,77 → 11,82 → 11,86 → 11,88 |
| HEAD | 53 → 53 → 53 → 53 → 53 | 484, costanti | 11,86 → 11,96 → 11,96 → 12,01 → 12,01 |

L'unico ascoltatore in più è l'inoltro stesso, registrato una volta sola: `World` si costruisce una volta sola (`main.js:130`), e `build()` non aggiunge ascoltatori. L'heap cresce di 0,15 MB in 2000 passi, contro 0,12 MB su `main`, dove la rotella sull'etichetta non fa nulla: è la pagina stessa, non l'inoltro. Nessuna perdita.

### R3 — Rotella e scorrimento dei pannelli (nessun difetto)

**Il rischio.** L'ascoltatore su `#labels` non è passivo, e `#labels` copre tutta la finestra. Se il browser estendesse la zona di rotella "bloccante" sopra i pannelli, il loro scorrimento dovrebbe aspettare il thread principale, che è occupato dal 3D.

**Misure** (`LayerTree`, 1920×1080):
- **su `main`** `#stage` aveva già una zona bloccante grande quanto la finestra, per l'ascoltatore non passivo di `OrbitControls` sul canvas;
- **su HEAD** si aggiungono le zone di `#labels` e dei layer delle etichette, tutte dentro quella che c'era già;
- **pannelli, roster, minimappa e topbar** hanno layer propri, senza zone bloccanti, prima e dopo: il loro scorrimento resta sul compositore;
- **layer in tutto:** 57 su `main` e 57 su HEAD.

### R4 — Inoltro della rotella: solidità (nessun difetto)

- **Doppie gestioni.** A parte l'inoltro stesso su `#labels`, gli unici ascoltatori di `wheel` dell'app stanno sul canvas: quello di `OrbitControls` e il controllo della modalità manuale. Nessuno su `document` o `window`, quindi nessuno vede due volte lo stesso passo.
- **Cicli.** L'evento inoltrato parte dal canvas, fuori da `#labels`: non può tornare indietro.
- **Eventi sintetici.** `OrbitControls` r186 non legge `isTrusted`; legge solo `deltaY`, `deltaMode`, `ctrlKey`, `clientX` e `clientY`, e l'inoltro li copia tutti.
- **Pinch del touchpad.** `ctrlKey` senza il tasto premuto moltiplica `deltaY` per 10, come sul canvas, perché `_controlActive` viene dagli eventi di tastiera, non dalla rotella.
- **Durante un trascinamento** `OrbitControls` ignora il passo (`state` non è `NONE`) e non chiama `preventDefault`; quindi nemmeno il controllo della modalità manuale scatta. È lo stesso comportamento del canvas.
- **Il punto dello zoom.** E7 lo verifica a ogni giro: la deriva è 0,03–0,05 px, e con la posizione sbagliata la verifica fallisce (T4).

### R5 — Breakpoint (nessuna regressione; un limite di compatibilità, da decidere)

**Verificato:**
- ai bordi esatti, 1250/1251 e 900/901 px, nella fase `overlaps`;
- sulla scansione dell'inspector a 74 larghezze;
- nelle sequenze di resize con l'inspector aperto, dove passa dalla colonna al foglio in basso e viceversa;
- le specificità del §4.1 della spec corrispondono al codice: `:root:has(#right.closed)` (1,2,0) batte `:root` della media query a 1250 (0,1,0); tra le due regole `:has` con il pannello destro chiuso vince l'ultima;
- con larghezze frazionarie, che il runner non può emulare: a 1250,5 px né `(max-width: 1250px)` né `(900px < width <= 1250px)` valgono, quindi vale la modalità sopra 1250 px, coerente; a 900,5 px vale `(width > 900px)`, complemento esatto di `(max-width: 900px)`.

**Il limite.**
- La sintassi a intervallo (`width > 900px`, `900px < width <= 1250px`) richiede Safari 16.4; `:has()` invece c'è da Safari 15.4.
- Su Safari 15.4–16.3 i due blocchi verrebbero ignorati. Roster e minimappa resterebbero posizionati per i pannelli aperti anche a pannelli chiusi: spazio vuoto, non sovrapposizioni.
- Chrome, Edge e Firefox sono a posto: ogni versione che conosce `:has()` conosce anche la sintassi a intervallo.

**Opzioni:**
- **(a), consigliata:** lasciare com'è. L'app gira su Edge, il README non promette altri browser, e la sintassi a intervallo l'hai approvata con D1;
- **(b):** scrivere `@media not all and (max-width: 900px)` al posto di `(width > 900px)`, con il blocco 901–1250 annidato in `@media (max-width: 1250px)`. Il significato è lo stesso, ma è meno leggibile e non verificabile qui: il runner ha solo Edge.

### R6 — `transform-origin: 0 50% !important` tolto da `.room-label` (nessun difetto)

L'`!important` veniva dal commit iniziale `c1312ff`. Nessuno script imposta l'origine della trasformazione (grep di `public/js/`), quindi toglierlo è sicuro. Era anche in conflitto con una seconda dichiarazione (`0 100%`) nella stessa regola, rimasta morta fino a T3.

## 3. Strumenti di test

- **R7 — commento (corretto, `3a83aa7`).** L'intestazione di `scripts/browser/lib.js` parlava solo della spec 01.
- **R8 — portabilità della guardia sulla scritta della bay (nota).**
  - Il limite di D8 è 27%, la misura 26,68%. La copertura dipende dal font, che determina la larghezza delle etichette.
  - Su una macchina con un font diverso (per esempio Linux senza Segoe UI) la guardia potrebbe dare un falso rosso, o un falso verde.
  - Oggi la suite gira solo qui. Se un giorno girerà altrove, la guardia andrà riportata alla misura di quella macchina.
- **Igiene delle sonde di questa review.** Due sonde interrotte (per un limite di tempo della shell) hanno lasciato 41 processi Edge con un profilo `agent-world-profile`. Li ho chiusi tutti (0 rimasti) senza toccare il tuo server sulla 4300.
  - Il runner non ne lascia: chiude via DevTools e controlla (V12). Le sonde invece usavano una chiusura più semplice.
  - Lezione per la retro: anche una sonda usa e getta va chiusa come il runner, oppure deve diventare una fase del runner.
- **Ricontrollato nel codice di test:**
  - rossi attesi: un segno rosso non conta, uno verde fa fallire, e uno che non corrisponde più a nessuna verifica fa fallire anch'esso;
  - le mutazioni permanenti (ingombri congelati, ordine delle etichette al contrario) vengono sempre ripristinate in un `finally`;
  - le passeggiate casuali hanno un seme fisso;
  - il controllo dei processi guarda solo il profilo della propria esecuzione e annota quelli degli altri.

## 4. Osservazioni fuori perimetro

**Pinch su touch screen sopra un'etichetta.** Le etichette prendono i puntatori, quindi un pinch con due dita che inizia sopra un'etichetta non arriva al canvas. È lo stesso caso della rotella prima di T4, ma per il touch.
- *Ipotesi per costruzione, non misurata*: il runner non ha mandato eventi touch.
- L'app è usata su desktop, quindi la annoto come candidata a un ticket (N8) e non la correggo.

## 5. Esito

- **Codice dell'app:** nessuna modifica dalla review. I tre fronti chiesti reggono, con le misure sopra.
- **Commit della review:** `3a83aa7`, solo il commento di R7.
- **Verifiche:** l'ultima suite completa su `6065481` (stesso codice dell'app di oggi) era verde, 226 verifiche. Dopo `3a83aa7`, che cambia un solo commento, basta `node --check`.
- **Da decidere:**
  - R5: compatibilità con Safari 15.4–16.3, (a) o (b);
  - se aprire N8 (pinch touch sopra le etichette) come ticket futuro.
