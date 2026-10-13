# Spec 02 — Sovrapposizioni dell'interfaccia

| | |
|---|---|
| **Stato** | approvata (SDD step 2). Ticket in `02-ui-overlaps.tickets.md` |
| **Data** | 2026-10-13 |
| **Branch** | `feat/ui-overlaps`, da `main` = `e14f039` |
| **Origine** | difetti N4 e N6 della spec 01 (retro, §5); Plan dello step 1, approvato |
| **Decisioni già prese** | D1: stato dei pannelli con CSS `:has()`, una sola verità. D2: perimetro N6 più Q1, Q2 e Q3. D3: N4 sul bordo anteriore, con la variante scelta dopo le misure di T0. D4: N7 escluso. Alla revisione della spec: D5 Q4 incluso, D6 Q5 incluso, D7 rotella sulle etichette inclusa; approvate anche `(width > 900px)` e `autoPort`. Dopo T0: D8 variante B con l'ordine "agenti sopra", con due eccezioni (§3.2) |

**In breve**
1. Lo stato dei pannelli è duplicato. I pannelli sanno se sono chiusi, il body ne tiene una copia che aggiornano solo i due pulsanti. Da qui vengono N6, Q1 e Q2: il roster e la minimappa finiscono sotto il pannello destro, oppure lasciano fino a 216 px vuoti.
2. L'inspector ha una larghezza fissa. Copre il pannello destro tra 901 e 1035 px (Q3) e, caso nuovo, la minimappa tra 1251 e 1321 px (Q4); con la distanza di 12 px che il resto dell'interfaccia rispetta, le due fasce arrivano a 1047 e a 1333 px.
3. Le etichette delle stanze coprono quelle dei worker (N4: 7 su 7 nella vista completa) e i fumetti di lead e worker.
4. Soluzione:
   - lo stato si legge solo dai pannelli, con `:has()`;
   - il roster e l'inspector condividono una colonna calcolata in un solo punto;
   - le etichette delle stanze vanno sul bordo anteriore, sotto quelle degli agenti.
5. Prima si misura (T0, runner headless), poi alla fermata dopo T0 scegli la variante di N4.

## 1. Contesto misurato

Le misure vengono dal Plan e da questo step, prese nel pannello browser dell'app con il viewport emulato. I valori sono px CSS sull'asse x, salvo dove è indicato altro.

### 1.1 Pannelli e interfaccia fissa

**Da dove nasce il difetto.** La verità sullo stato dei pannelli è la classe `closed` su `#left` e `#right`. Il body ne tiene una copia, `left-closed` e `right-closed`:
- la copia serve solo a tre regole CSS;
- la aggiorna solo `togglePanel()`, cioè i pulsanti ☰ (Missione) e ▤ (Pannello);
- `switchTab()` apre il pannello destro togliendo `closed` senza toccare la copia. La chiamano il clic su una scheda e `selectTeam()`, cioè il clic sull'etichetta di una stanza.

```css
body.left-closed .roster, body.left-closed .inspector { left: 12px; }   /* specificità 0,2,1 */
body.right-closed .roster { right: 228px; }
body.right-closed .minimap { right: 12px; }
```

| # | Caso | Misura | Causa |
|---|---|---|---|
| **N6** | ▤ chiude il pannello destro, poi una scheda lo riapre | a 1920 px la minimappa (1704–1908) sta tutta sotto il pannello (1508–1908) e il roster entra nel pannello per 184 px; a 1200 px il roster (324–972) entra nel pannello (828–1188) per 144 px | la copia nel body resta "chiuso" |
| **Q1** | pannello destro chiuso, finestra ≤ 1250 px | a 1200 px il roster finisce a 972 invece che a 1188: 216 px vuoti, lasciati per una minimappa che a questa larghezza è nascosta | `body.right-closed .roster` (0,2,1) batte `.roster` della media query (0,1,0) |
| **Q2** | pannelli chiusi in modalità larga, poi finestra a 800 px | roster 12–572 invece di 8–792, cioè 220 px più corto; inspector a 12 px dal bordo invece che a 8 | le regole sul body valgono anche in modalità stretta e battono le sue |
| **Q3** | entrambi i pannelli aperti, finestra tra 901 e 1035 px, inspector aperto | a 1000 px l'inspector (324–664) copre il pannello destro (628–988) per 36 px, su tutta la sua altezza (316 px con il contenuto misurato); il suo z-index (6) è sopra quello del pannello (4) | larghezza fissa di 340 px |
| **Q4** *(nuovo)* | entrambi i pannelli aperti, finestra tra 1251 e 1321 px, inspector alto | a 1280×800, con 6 eventi e 8 messaggi l'inspector arriva al suo massimo di 630 px: 354–694 × 70–700, sopra la minimappa (652–856 × 604–788) per 42 × 96 px. *(T0: con il contenuto reale più alto, 6 eventi e 8 messaggi, 42 × 46 px)* | come Q3; la minimappa c'è solo sopra 1250 px |

Note su Q3 e Q4:
- **Q3.** Tra 901 e 1035 px l'inspector copre il pannello. Il resto dell'interfaccia tiene 12 px di distanza dagli altri elementi: con questa regola (P2) il difetto arriva fino a 1047 px.
- **Q4.** È emerso in questo step, misurando il caso peggiore dell'inspector, la cui altezza massima è `100vh − 170px`. Tra 1251 e 1321 px l'inspector copre la minimappa quando è più alto di `100vh − 266px`; con i 12 px di distanza la fascia arriva a 1333 px. La causa è la stessa di Q3.

In modalità stretta (≤ 900 px) i pannelli e l'inspector sono overlay. Un pannello può avere insieme le classi `closed` e `open`; vince `open`.

### 1.2 Etichette

**Geometria** (in unità di mondo, per una stanza centrata in (x, z)):
- **stanza:** 10,4 × 6,6;
  - centri a x −17,8, −6, 6, 17,8 e a z −1,2 (fila posteriore) e 9,6 (fila anteriore);
  - corridoi di 1,4–1,6 tra le stanze e di 4,2 tra le due file;
- **posti:**
  - lead e worker siedono alle scrivanie in fondo, a z − 2,36;
  - i sub-agenti siedono nella bay davanti, a z + 1,14;
  - il segno della bay va da z + 0,4 a z + 3,1 (in x da x − 4,7 a x + 3,9), con la scritta "SUB-AGENT BAY" in basso a destra;
  - l'arredo è nell'angolo posteriore destro;
- **etichetta della stanza oggi:** ancorata a (x − 5,0; 0,1; z − 3,1), cioè nell'angolo posteriore sinistro, sopra il lead e i worker. Si estende verso destra ed è centrata in verticale sull'ancora.

**Pendenza dei bordi.** Con la direzione di camera (15, 40, 45), sullo schermo un bordo parallelo all'asse x scende verso destra di circa 12°: 0,215 px verso il basso per ogni px verso destra (vettori della camera calcolati come in `lookAt` di three). Un'etichetta orizzontale ancorata a un'estremità di un bordo lo attraversa all'altra estremità, di circa un quinto della sua larghezza. Da questo dipende come ancorare le varianti (§4.3).

**Ordine di disegno.** Nessuna etichetta ha uno z-index, quindi conta l'ordine nel DOM:
1. etichette e fumetti degli agenti iniziali;
2. etichette delle stanze;
3. etichetta del Brain;
4. etichette e fumetti dei sub-agenti, aggiunti dopo.

Le stanze coprono quindi anche i fumetti di lead e worker, mentre i sub-agenti coprono le stanze.

**Riferimento** (report della spec 01, 1920×1080): quota dell'etichetta di ogni worker inattivo coperta dall'etichetta della sua stanza.

| Vista | Zoom effettivo | Worker coperti | Sovrapposizione |
|---|---|---|---|
| zoom 1 | 1 | 6/7 | 60–97% |
| zoom 0,8 (vista completa con -- e -R) | 0,8 | 7/7 | 93% |
| vista completa, LR | 0,61 | 7/7 | 89% |
| zoom 1,3 | 1,3 | 1/7 | 12–100% |
| focus su un agente | 2,2 | 0/7 | 0–4% |

**Q5 *(nuovo)*: le etichette nascoste rispondono ancora al puntatore.** Con `far` attivo, le etichette dei worker inattivi diventano trasparenti ma ricevono ancora clic e rotella.
- Misura a 1440×900, LR, vista completa: 8 etichette nascoste. Al loro centro, oggi 7 sono sotto l'etichetta di una stanza e 1 intercetta il clic.
- Spostando le etichette delle stanze, quelle 7 restano scoperte. Il conto esatto si fa a T0.

**Limite accettato nella spec 01:** la rotella sopra un'etichetta non zooma.

## 2. Obiettivi e non-obiettivi

**Obiettivi**
- **G1 (N6, Q1, Q2):** il roster e la minimappa stanno sempre accanto ai pannelli visibili, qualunque sia la sequenza di azioni che ha portato lì.
- **G2 (Q3, Q4):** l'inspector non copre mai pannelli, minimappa o roster.
- **G3 (N4):** le etichette delle stanze non coprono più etichette e fumetti degli agenti, e restano leggibili e cliccabili.
- **G4:** il runner headless misura tutto questo fin da T0, e la suite fallisce se lascia aperti processi del browser.

**Non-obiettivi**
- N2, N5, N7 e lo stile v3 (personaggi, arredi, angolo di camera).
- **Modalità stretta (≤ 900 px):** pannelli e inspector restano overlay che possono coprirsi tra loro. Qui si garantisce solo che non coprano la topbar e il roster, e che lo stato preso in modalità larga non alteri la modalità stretta (Q2).
- Sovrapposizioni tra etichette di agenti: la soglia `far` è della spec 01.
- Inspector, toast e modali come ostacoli dell'inquadratura: resta valida la S1.2 della spec 01.

## 3. Requisiti

Sono scritti dal punto di vista di chi usa l'app. I nomi del codice stanno nel §4 e nei ticket.

### 3.1 Interfaccia fissa (P)

Gli elementi fissi sono: topbar, pannello sinistro, pannello destro, roster, minimappa e inspector. Un elemento è "visibile" quando è mostrato e ha un'area maggiore di 0.

- **P1 — Nessuna sovrapposizione.** In modalità larga due elementi fissi visibili non si sovrappongono mai (0 px²). In modalità stretta la regola vale per la topbar e il roster rispetto a tutti gli altri elementi.
- **P2 — Colonna centrale.** Il roster e l'inspector stanno nella stessa colonna, sempre a 12 px da entrambi i lati:
  - a sinistra la colonna parte dal bordo destro del pannello sinistro, o dal bordo della finestra se il pannello è chiuso;
  - a destra arriva all'ostacolo più vicino: la minimappa se è visibile, altrimenti il pannello destro se è aperto, altrimenti il bordo della finestra;
  - il roster occupa tutta la colonna; l'inspector parte da sinistra ed è largo al massimo 340 px, e il suo contenuto non scorre mai in orizzontale;
  - in modalità stretta entrambi stanno a 8 px dai bordi della finestra, come oggi.
- **P3 — Minimappa.** Sopra 1250 px sta a 12 px dal pannello destro, se è aperto, altrimenti a 12 px dal bordo della finestra. Sotto 1250 px resta nascosta.
- **P4 — Nessuna memoria.** Dopo qualunque sequenza di ingressi, la disposizione è identica, entro ±0,5 px, a quella di una pagina appena caricata alla stessa dimensione e portata agli stessi pannelli con ☰ e ▤.
- **P5 — Inquadratura.** In modalità automatica, ogni azione che apre o chiude un pannello (un pulsante, una scheda, l'etichetta di una stanza) riadatta la vista come fanno i pulsanti. Il criterio A1 della spec 01 resta allo 0%.
- **P6 — Comportamento invariato.** I pulsanti, le schede e la chiusura dell'inspector fanno quello che fanno oggi, in entrambe le modalità. Cambia solo la posizione degli elementi.

**Matrice ingresso × stato.** Gli stati combinano tre dimensioni:
- pannelli: LR, L-, -R, --;
- finestra: 1920×1080, 1280×800, 1200×800, 1000×800, 800×600;
- inspector: chiuso, oppure aperto con il contenuto più alto (6 eventi e 8 messaggi).

Dopo ogni ingresso devono valere P1–P4. La colonna "In più" dice cosa si verifica oltre a questi.

| Ingresso | In più | Oggi |
|---|---|---|
| Caricamento della pagina | è il riferimento di P4 | ok |
| ☰ o ▤ | P5 | ok; Q1 e Q3 dipendono solo dallo stato a cui si arriva |
| Clic su una scheda | apre il pannello destro, come overlay in modalità stretta; P5 | N6 |
| Clic sull'etichetta di una stanza | come la scheda, poi la stanza al centro dell'area libera (A7 della spec 01) | N6 |
| "Vai alla stanza" | la disposizione non cambia | ok |
| Clic su un membro del roster | apre l'inspector nella colonna (P2) | Q3, Q4 |
| ✕ dell'inspector | lo chiude, senza altri cambiamenti | ok |
| Resize oltre 1250 px, nei due versi | P3: minimappa nascosta o mostrata | Q1 |
| Resize oltre 900 px, nei due versi | passaggio alla modalità stretta e ritorno | Q2 |

**Disposizione attesa** (x in px). Nella colonna Pannelli, L e R indicano il pannello sinistro e il destro aperti, il trattino un pannello chiuso.

| Finestra | Pannelli | Roster | Inspector | Minimappa | Oggi, se diverso |
|---|---|---|---|---|---|
| 1920×1080 | LR | 354–1280 | 354–694 | 1292–1496 | dopo N6 (▤, poi una scheda): minimappa 1704–1908 e roster fino a 1692 |
| 1920×1080 | -- | 12–1692 | 12–352 | 1704–1908 | |
| 1280×800 | LR | 354–640 | 354–640 (286 px) | 652–856 | inspector 354–694 (Q4) |
| 1280×800 | L- | 354–1052 | 354–694 | 1064–1268 | |
| 1200×800 | L- | 324–1188 | 324–664 | nascosta | roster fino a 972 (Q1) |
| 1000×800 | LR | 324–616 | 324–616 (292 px) | nascosta | inspector fino a 664 (Q3) |
| 901 × qualsiasi | LR | 324–517 | 324–517 (193 px) | nascosta | inspector fino a 664 (Q3) |
| 800×600 | qualsiasi | 8–792 | 8–792, in basso | nascosta | roster 12–572 dopo aver chiuso i pannelli in modalità larga (Q2) |

**Larghezza dell'inspector.** Scende sotto i 340 px solo con entrambi i pannelli aperti: tra 901 e 1047 px (da 193 a 339 px) e tra 1251 e 1333 px (da 257 a 339 px). Misure fatte con il contenuto reale:

| Larghezza dell'inspector | Campo della chat | Intestazione |
|---|---|---|
| 340 px | 214 px | 1 riga |
| 292 px | 166 px | 2 righe |
| 250 px | 124 px | 2 righe |
| 193 px | 67 px | 3 righe |

In nessun caso compare lo scorrimento orizzontale.

### 3.2 Etichette (E)

Le "etichette dei luoghi" sono quelle delle stanze e del Brain. Gli "agenti seduti" sono lead, worker e sub-agenti al loro posto.

- **E1 — Agenti sopra i luoghi.** Le etichette dei luoghi non coprono nessuna parte di un'etichetta o di un fumetto di un agente (0 px²). Vale in ogni stato, anche con agenti in movimento e fumetti aperti.
- **E2 — Nome della stanza leggibile.** Con gli agenti seduti, nessuna etichetta di agente copre il nome e il quadratino colorato della stanza (0 px²). I fumetti sono temporanei e possono coprirli.
- **E3 — Dentro l'area libera.** Nella vista completa, ogni etichetta di stanza sta per intero nell'area libera.
- **E4 — Nessuna sovrapposizione tra luoghi.** Un'etichetta di stanza non copre un'altra etichetta di stanza né quella del Brain, dalla vista completa al primo piano.
- **E5 — Clic.**
  - Un clic sul corpo di un agente seduto seleziona l'agente: nessuna etichetta di stanza sta sopra i punti in cui lo si può prendere.
  - Un clic sul nome visibile di una stanza apre la stanza.
- **E6 — Etichette nascoste (Q5; D6).** Un'etichetta di agente nascosta da `far` non riceve né clic né rotella.
- **E7 — Rotella sopra un'etichetta (D7).** La rotella sopra qualunque etichetta zooma come sul canvas, verso lo stesso punto.

**Eccezioni accettate con D8** (variante B, misure di T0 nel report, §5):
- **E5, piedi dei sub-agenti.** Il punto di presa più basso (0,4 sopra il pavimento) di al massimo 3 sub-agenti può cadere sotto l'etichetta della loro stanza, in al massimo 2 stati della matrice su 180 (T0: 1920×1080, LR, vista completa, bay piene). Il resto del corpo resta cliccabile. Lead, worker e CEO non hanno eccezioni.
- **Scritta "SUB-AGENT BAY".** È disegnata sul pavimento della bay ed è decorativa: l'etichetta della stanza può coprirla, fino al 27% misurato a T0. Non è un criterio; il report "Dopo" riporta di nuovo la misura.

**Matrice ingresso × stato.** Gli stati combinano quattro dimensioni:
- finestra: 1920×1080, 1440×900, 2560×1440;
- pannelli: LR, -R, --;
- vista: completa, zoom effettivo 0,8, 1 e 1,3, focus su un agente, focus su una stanza, primo piano;
- bay: vuote, oppure piene (tutti i posti occupati).

La classe `far` dipende dallo zoom: è attiva sotto 0,55, per esempio nella vista completa a 1440×900 con LR.

| Ingresso | Atteso | Oggi |
|---|---|---|
| Nessuno: vista ferma, con un fumetto aperto su ogni agente | E1–E4 | E1: fino a 7 worker su 7 coperti (89–93%) |
| Clic sul nome di una stanza | apre la stanza (E5) | ok, ma l'etichetta sta sopra i worker |
| Clic su un agente seduto vicino all'etichetta di una stanza | seleziona l'agente (E5) | *(misurato a T0)* in tutti i 180 stati, 8 lead e worker hanno il corpo sotto l'etichetta della loro stanza |
| Clic o rotella su un'etichetta nascosta | come sul canvas (E6) | intercettati: 1 su 8 a 1440×900 con LR; *(T0)* 15 su 22 con le bay piene |
| Rotella su un'etichetta visibile | zoom (E7) | nessun effetto |

## 4. Design tecnico

Questa sezione propone l'implementazione; i ticket la possono affinare.

### 4.1 Stato dei pannelli con `:has()` (N6, Q1, Q2)

Si eliminano le classi `left-closed` e `right-closed` sul body:
- in modalità larga `togglePanel()` cambia solo `closed`: spariscono le righe 878–879 di `main.js`;
- spariscono anche le regole alle righe 400–402 di `app.css`.

La colonna (P2) e la posizione della minimappa (P3) si calcolano in un solo punto, con tre proprietà su `:root`:

```css
:root {
  --col-left: calc(var(--left-w) + 24px);    /* roster and inspector start here */
  --col-right: calc(var(--right-w) + 240px); /* right panel, then the minimap */
  --map-right: calc(var(--right-w) + 24px);
}
@media (width > 900px) {
  :root:has(#left.closed) { --col-left: 12px; }
  :root:has(#right.closed) { --col-right: 228px; --map-right: 12px; }
}
@media (max-width: 1250px) {
  :root { --left-w: 300px; --right-w: 360px; --col-right: calc(var(--right-w) + 24px); } /* no minimap */
  .minimap { display: none; }
}
@media (900px < width <= 1250px) {
  :root:has(#right.closed) { --col-right: 12px; }
}
.roster { left: var(--col-left); right: var(--col-right); }
.minimap { right: var(--map-right); }
```

**Perché funziona:**
- **Specificità.** `:root:has(#right.closed)` vale (1,2,0): `:root` conta (0,1,0), e `:has()` conta quanto il suo argomento più specifico, `#right.closed`, cioè (1,1,0).
  - Con il pannello chiuso questa regola batte `:root` della media query a 1250 px, che vale (0,1,0).
  - Tra le due regole `:has` con il pannello destro chiuso, che hanno la stessa specificità, vince l'ultima, quella per 901–1250 px: è la correzione di Q1.
  - Con il pannello aperto nessuna `:has` vale, e decide la media query (`right-w + 24`).
- **Q2.** Le regole `:has` stanno solo nella modalità larga. La modalità stretta posiziona il roster con valori propri (`left: 8px; right: 8px`), che vengono dopo con la stessa specificità.
- **Larghezze dei pannelli.** `--left-w` e `--right-w` cambiano nella media query a 1250 px sullo stesso elemento, `:root`. Le proprietà che le usano vengono calcolate lì, quindi seguono il cambio.
- **Precisazione di D1.** Uso `(width > 900px)` invece di `(min-width: 901px)`, perché è il complemento esatto di `(max-width: 900px)`, la query che usano sia il CSS sia `matchMedia` in `main.js`.
  - Con lo zoom del browser la larghezza in px CSS può essere frazionaria, per esempio 900,5. Con `min-width: 901px` a quella larghezza non varrebbe nessuna delle due modalità.
  - Il runner non può misurarlo, perché lo zoom del browser non si emula via DevTools: è una scelta di robustezza, non un difetto osservato.
  - Per coerenza, la fascia intermedia diventa `(900px < width <= 1250px)`.
- **Compatibilità.** `:has()` è supportato da Chrome ed Edge 105, Firefox 121 e Safari 15.4; la sintassi a intervallo da Chrome 104, Firefox 63 e Safari 16.4. L'app gira su Edge.
- **Test della spec 01.** In T1 si toglie il riallineamento a mano nel test A7 (`scripts/browser/manual-mode.js`, righe 179–180).

**Passaggio avversario** (retro, lezione 3), da ripetere in T1 prima del commit:
- **Chiamanti.** `togglePanel` lo chiamano solo i due pulsanti. Le classi del body le leggono solo `app.css` e il test A7 (verificato con grep).
- **Durante un'animazione.** Il cambio è solo CSS. Il `ResizeObserver` di `#right` e `#roster` scatta come con i pulsanti, quindi il riadattamento (P5) segue la stessa strada di oggi.
- **Precondizione diversa.** In modalità stretta `closed` resta sui pannelli, ma le regole `:has` non valgono. Tornando in modalità larga valgono di nuovo, come in un caricamento con gli stessi pannelli (P4).
- **Misura degli ingombri.** `selectTeam` misura gli ingombri subito dopo `switchTab` (S3.7 della spec 01). Del roster legge solo il bordo superiore, che non dipende dai pannelli; per i pannelli, `:has` si ricalcola alla lettura come la classe `closed`.

### 4.2 L'inspector nella colonna (Q3, Q4)

```css
.inspector { left: var(--col-left); right: var(--col-right); width: auto; max-width: 340px; }
@media (max-width: 900px) { .inspector { max-width: none; /* + the current rules */ } }
```

Come funziona:
- con `left` e `right` fissati e `width: auto`, l'inspector prende la larghezza della colonna;
- se la colonna supera 340 px, CSS 2.1 (§10.3.7) rifà il calcolo con 340 px. Il box diventa sovra-vincolato e il browser ignora `right`, quindi l'inspector resta allineato a sinistra;
- altezza e `top` non cambiano;
- la regola `body.left-closed .inspector` sparisce insieme alle altre (§4.1).

Le larghezze risultanti sono nella tabella del §3.1.

**Alternative scartate:**
- lasciare l'inspector sopra il pannello destro: viola P1;
- accorciarlo solo dove tocca la minimappa: servirebbe una media query con soglie ricavate a mano da `--left-w` e `--right-w`, e Q3 resterebbe aperto.

### 4.3 Etichette (N4, Q5, rotella)

**Varianti da misurare a T0.** Ogni variante ha un'ancora e un allineamento, e l'etichetta resta orizzontale. Il punto della trasformazione coincide con l'ancora, così la scala delle etichette la lascia ferma.

| Variante | Ancora (unità di mondo) | Allineamento dell'etichetta | Effetto della pendenza di 12° |
|---|---|---|---|
| oggi | angolo posteriore sinistro (x − 5,0; z − 3,1) | verso destra, centrata in verticale | — |
| **A** | angolo anteriore sinistro, dentro la stanza (x − 5,0; z + 3,1) | verso destra, con il bordo inferiore sull'ancora | il bordo della stanza scende verso destra, quindi l'etichetta resta dentro a ogni zoom |
| **B** *(scelta, D8)* | centro del bordo anteriore, dentro la stanza (x; z + 3,1) | centrata, con il bordo inferiore sull'ancora | la metà sinistra sporge oltre il bordo, fino a circa un decimo della larghezza dell'etichetta |
| **C** | angolo anteriore destro, fuori dalla stanza (x + 5,0; z + 3,5) | verso sinistra, con il bordo superiore sull'ancora | il bordo sale verso sinistra, quindi l'etichetta resta fuori a ogni zoom |

*Precisazione rispetto al Plan:* lì C era "appena fuori dal bordo anteriore", senza un angolo. Con l'ancora a sinistra, la parte destra dell'etichetta entrerebbe nella stanza di circa un quinto della sua larghezza, per via della pendenza.

**Ordine (E1).** Le etichette dei luoghi vanno sotto quelle degli agenti in ogni caso:
- si usa uno z-index (0 per i luoghi, 1 per gli agenti) invece dell'ordine nel DOM, che cambia quando arrivano i sub-agenti;
- `#stage` è `position: fixed`, quindi crea già un contesto di sovrapposizione: lo z-index resta confinato lì;
- spostare le etichette, da solo, non basta per i fumetti *(confermato a T0: con qualunque variante, senza l'ordine restano coperti in 72 stati su 180)*. La stima era:
  - nella vista completa a 1920 con LR, l'etichetta di una stanza posteriore spostata sul bordo anteriore sta circa 40 px sopra le teste della fila anteriore;
  - lì sale il fumetto di un lead: occupa da 19 a 40–55 px sopra la testa;
- l'ordine tra le etichette degli agenti non cambia.

**Etichette nascoste (E6, Q5).** La regola di `far` che nasconde le etichette dei worker inattivi aggiunge `pointer-events: none`. Il cambio è immediato, mentre l'opacità sfuma in 0,3 s.

**Rotella (E7).** `#labels` inoltra al canvas l'evento `wheel` che arriva da un'etichetta, con gli stessi `deltaY`, `deltaMode`, posizione e `ctrlKey` (il pinch del touchpad), e annulla l'originale.
- L'evento passa così dagli stessi controlli e dallo stesso rilevamento della modalità manuale (S3.2 della spec 01).
- Verificato nei sorgenti di three r186:
  - `OrbitControls` non controlla `isTrusted`;
  - legge solo `deltaY`, `deltaMode`, `ctrlKey`, `clientX` e `clientY` (`_customWheelEvent`);
  - chiama `preventDefault`. Il rilevamento in `world.js` usa proprio `defaultPrevented`, quindi l'evento inoltrato deve essere `cancelable`.

### 4.4 Il runner (T0)

**Fasi nuove.** `scripts/browser-test.js` riceve due fasi, ciascuna con il suo script di pagina:
- `overlaps`, che copre P1–P6 e la matrice del §3.1, con `scripts/browser/overlaps.js`;
- `labels`, che copre E1–E7 e la matrice del §3.2, con `scripts/browser/labels.js`.

Il runner, via DevTools, gestisce i ridimensionamenti e i caricamenti. La pagina esegue gli ingressi sugli elementi veri (pulsanti, schede, etichette, membri del roster) e prende le misure.

**Riferimento di P4.** Per ogni finestra e combinazione di pannelli si carica una pagina nuova e la si porta a quei pannelli con ☰ e ▤: 20 caricamenti, circa un minuto.

**Varianti di N4.**
- La pagina calcola i rettangoli delle etichette di stanza dall'ancora proiettata, dalla dimensione non trasformata dell'etichetta e dalla sua scala, senza toccare il codice di produzione.
- Il modello si verifica sulla posizione di oggi. Deve coincidere con le etichette disegnate entro ±1 px e ritrovare i numeri della spec 01 (7 worker su 7 coperti nella vista completa con LR). Se non ci riesce, T0 si ferma lì.

**Scena di prova.** Le bay si riempiono con un sub-agente per posto, creato dagli eventi di spawn della scena. Su ogni agente si apre un fumetto con un testo lungo come quelli reali.

**Verifiche rosse attese.**
- A T0 le verifiche che falliscono sul codice di oggi vengono segnate con il ticket che le chiude e contate a parte: la suite resta verde.
- Ogni ticket toglie i propri segni.
- Se una verifica segnata passa prima del suo ticket, la suite fallisce.

Così ogni verifica dimostra di saper fallire, e nessun commit lascia la suite rossa.

**Processi del browser** (azione 6 della retro):
- a fine suite, dopo la chiusura, il runner cerca per qualche secondo i processi del browser con il profilo di questa esecuzione nella riga di comando, e fallisce se ne restano;
- i processi con un altro `agent-world-profile` (un'esecuzione precedente, o una parallela con un'altra `--port`) li elenca come avviso. Se facessero fallire la suite, due esecuzioni parallele si farebbero fallire a vicenda;
- che il controllo sappia fallire si dimostra una volta, saltando la chiusura del browser.

**Screenshot.** Il nome dei file prende il prefisso della spec; oggi è fisso a `01-`.

**Tempo.** Le due fasi nuove devono durare in tutto al massimo 3 minuti. Si lanciano da sole con `--only overlaps,labels`.

## 5. Criteri di accettazione

| ID | Criterio | Come si verifica | Oggi | Ticket |
|---|---|---|---|---|
| V1 | P1: 0 px² tra elementi fissi visibili in tutta la matrice del §3.1 | fase `overlaps` | rosso (N6, Q3, Q4) | T1, T2 |
| V2 | P2, P3: colonna e minimappa come nella tabella del §3.1, entro ±0,5 px | `overlaps` | rosso (N6, Q1, Q2, Q3, Q4) | T1, T2 |
| V3 | P4: dopo ogni sequenza, la disposizione coincide con quella di un caricamento con gli stessi pannelli, entro ±0,5 px | `overlaps` | rosso (N6, Q2) | T1 |
| V4 | P5: dopo ogni ingresso che apre o chiude un pannello in modalità automatica, A1 della spec 01 resta allo 0% | `overlaps` | verde. Per vederlo fallire si blocca l'aggiornamento degli ingombri | T0 |
| V5 | P6: suite della spec 01 verde (views, checks, cubes, input, run) senza il riallineamento in A7 | suite completa | verde, ma solo con il riallineamento | T1 |
| V6 | E1: 0 px² di etichette e fumetti di agenti coperti da etichette di luoghi, in tutta la matrice del §3.2 | `labels` | rosso (7 worker su 7 nella vista completa) | T3 |
| V7 | E2: 0 px² del nome di una stanza coperti da etichette di agenti seduti | `labels` | verde (T0: oggi le stanze stanno sopra gli agenti iniziali); con B e l'ordine nuovo, 0 | T3 |
| V8 | E3 ed E4: etichette di stanza nell'area libera nella vista completa, e nessuna sovrapposizione tra etichette di luoghi | `labels` | verdi (T0), anche con B | T3 |
| V9 | E5: un clic sui punti di presa di ogni agente seduto seleziona l'agente; un clic sul nome visibile di ogni stanza apre la stanza; salvo l'eccezione dei piedi dei sub-agenti (§3.2) | `labels` (punto per punto) | rosso (T0: 8 lead e worker in 180 stati su 180) | T3 |
| V10 | E6: nessuna etichetta nascosta riceve il puntatore | `labels` | rosso | T4 |
| V11 | E7: un passo di rotella sopra un'etichetta cambia lo zoom come sul canvas (±2%) e porta la vista in modalità manuale | `labels`, con un evento vero via DevTools | rosso | T4 |
| V12 | A fine suite non resta nessun processo del browser con il profilo dell'esecuzione | runner | si dimostra saltando la chiusura del browser | T0 |
| V13 | `npm test` verde, suite completa verde a fine step, QA dell'utente a 1920×1080 | terminale e utente | — | T5 |

## 6. Ticket in bozza

La suddivisione definitiva si fa nello step 3. Dopo ogni ticket ci si ferma per il tuo feedback.

| Ticket | Cosa | Fermata |
|---|---|---|
| **T0** | fasi `overlaps` e `labels`; verifiche rosse attese; controllo dei processi del browser; prefisso degli screenshot; baseline su questo branch, che a T0 coincide con `main`; tabella delle varianti A, B e C, con e senza l'ordine di E1 | **scegli la variante di N4** (D8) |
| **T1** | N6, Q1 e Q2 con `:has()` e la colonna per roster e minimappa (§4.1); via il riallineamento del test A7 | QA |
| **T2** | Q3 e Q4, con l'inspector nella colonna (§4.2) | QA, anche a 1000 e a 1280×800 |
| **T3** | N4 con la variante scelta, più l'ordine tra le etichette (E1) | QA |
| **T4** | Q5 e la rotella sulle etichette (E6, E7), approvate con D6 e D7 | QA |
| **T5** | verifica finale, report "Dopo" con gli screenshot, QA a 1920×1080 | approvazione dello step |

La bozza del Plan aveva T0–T4: T4 (rotella ed etichette nascoste) è nuovo, e la verifica finale diventa T5.

## 7. Decisioni

Prese alla revisione della spec (2026-10-13):
1. **D5 — Q4 entra nel perimetro: sì.** La correzione è la stessa di Q3 (§4.2), senza codice in più.
2. **D6 — Le etichette nascoste smettono di ricevere il puntatore (Q5): sì.** Un elemento invisibile non deve mai intercettare i clic.
3. **D7 — La rotella sopra le etichette zooma: sì.** Lo zoom deve funzionare ovunque si trovi il cursore; il limite accettato nella spec 01 decade.

Presa alla fermata dopo T0, sulla tabella del report (§5):
4. **D8 — Variante di N4: B, con l'ordine "agenti sopra".** Come A, lascia liberi i nomi delle stanze e il corpo di lead e worker; i suoi conflitti residui sono le due eccezioni del §3.2.

Non sono decisioni ma precisioni, già spiegate sopra:
- `(width > 900px)` invece di `(min-width: 901px)` (§4.1);
- la variante C ancorata a destra, per via della pendenza (§4.3);
- il controllo dei processi limitato al profilo dell'esecuzione (§4.4).

## 8. Rischi

- **Modello delle varianti.** Se a T0 non coincide con le etichette disegnate (±1 px) sulla posizione di oggi, le misure delle varianti non valgono. T0 si ferma lì invece di proporre una scelta.
- **Inspector stretto.** A 901 px con entrambi i pannelli aperti l'inspector è largo 193 px: è usabile ma stretto, con il campo della chat di 67 px. Se al QA non basta, l'alternativa è una larghezza minima con l'inspector sopra il pannello destro, cioè rinunciare a P1 in quella fascia. Sarebbe una decisione tua.
- **Modalità stretta.** L'inspector e un pannello aperto si coprono, come oggi (non-obiettivo).
- **Durata della suite.** Aumenta di circa 3 minuti. Per i ritocchi bastano le fasi nuove (`--only overlaps,labels`), come prevede la lezione 5 della retro.
