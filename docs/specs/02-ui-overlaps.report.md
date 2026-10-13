# Spec 02 — Report

Riferimenti: [spec](02-ui-overlaps.md), [ticket](02-ui-overlaps.tickets.md). Gli ID P\*, E\*, V\*, N\* e Q\* rimandano alla spec.

## Prima (T0)

| | |
|---|---|
| **Data** | 2026-10-13 |
| **Codice misurato** | `feat/ui-overlaps` a `0b0eac0`: `main` (`e14f039`) più la spec e i ticket, nessun file di `public/` cambiato |
| **Strumento** | `node scripts/browser-test.js --only overlaps,labels`, Edge headless via DevTools, server demo proprio |
| **Durata delle fasi nuove** | `overlaps` 58–66 s, `labels` 21–22 s (33 s con gli screenshot): circa 85 s in tutto, sotto l'obiettivo di 3 minuti |

**In breve**
1. Le due fasi nuove coprono 1456 casi della matrice dei pannelli (§3.1) e 180 stati della matrice delle etichette (§3.2).
2. Ogni rosso della baseline ha la sua causa tra i difetti noti, e nessun difetto nuovo: N6, Q1 e Q2 per 24 verifiche (T1), Q3 e Q4 per 9 (T2), N4 per 6 (T3), Q5 e la rotella per 3 (T4).
3. Il calcolo delle varianti è validato al pixel: con l'ancora di oggi coincide con le etichette disegnate entro 0,52 px; A, B e C coincidono entro 0,52, 0,66 e 0,81 px con le stesse varianti disegnate dal CSS.
4. Nessuna variante rispetta tutti i criteri in tutta la matrice. **B** è quella con meno conflitti: copre il punto più basso di 3 sub-agenti in 2 stati su 180 e il 27% della scritta "SUB-AGENT BAY". A copre i sub-agenti in 25 stati; C copre i nomi delle stanze posteriori in 26 stati.
5. V4, V12 e la verifica degli ingressi sono stati visti fallire. La suite completa è verde: 130 verifiche della spec 01, 39 nuove, 42 rossi attesi, in 4 min 31 s.

### 1. Lo strumento

- **Fase `overlaps`** (P1–P5):
  - 9 dimensioni della finestra: le 5 della matrice più i bordi delle media query (1251, 1250, 901 e 900 px);
  - da ogni layout di partenza, ogni ingresso con l'elemento vero: ☰, ▤, una scheda, l'etichetta di una stanza, "Vai alla stanza", un membro del roster, ✕;
  - in modalità stretta, i layout di partenza sono le classi `closed` lasciate dalla modalità larga (Q2);
  - 24 sequenze di resize oltre 1250 e oltre 900 px, con l'inspector chiuso e aperto;
  - 3 passeggiate casuali da 25 passi, con seme fisso;
  - P4 confronta ogni disposizione con quella di una pagina appena caricata (19 riferimenti);
  - l'inspector aperto ha sempre il contenuto più alto: 6 eventi e 8 messaggi.
- **Fase `labels`** (E1–E7):
  - 1920×1080, 1440×900 e 2560×1440 × LR, -R e -- × 10 viste (completa; zoom effettivo 0,8, 1 e 1,3; focus su un worker per fila; primo piano; focus su una stanza per fila) × bay vuote o piene (14 sub-agenti);
  - E1 con un fumetto aperto su ogni agente, le altre misure a fumetti chiusi;
  - E7 con eventi veri della rotella inviati via DevTools.
- **Rossi attesi:** `scripts/browser/known-red.json`, 42 voci con il ticket che le chiude.
- **Ingressi applicati:** una verifica per dimensione controlla che ogni ingresso della matrice sia stato applicato davvero. Senza la sua precondizione, "Vai alla stanza" verrebbe saltato in silenzio. Provato togliendo la preparazione per un giro: 9 verifiche rosse, una per dimensione.
- **Processi del browser:** a fine suite il runner controlla i processi con il profilo dell'esecuzione (V12).

### 2. Pannelli: N6, Q1–Q4

| # | Caso misurato | Misura | Spec §1.1 |
|---|---|---|---|
| N6 | 1920×1080, L- poi una scheda | minimappa 1704–1908 invece di 1292–1496, sotto il pannello destro per 22.848 px² (204 × 112); roster fino a 1692 invece di 1280, cioè 184 px dentro il pannello | uguale |
| N6 | 1200×800, L- poi una scheda | roster fino a 972 invece di 816: 144 px dentro il pannello | uguale |
| Q1 | 1200×800, pannello destro chiuso | roster fino a 972 invece di 1188: 216 px vuoti | uguale |
| Q1 | anche a 1250, 1000 e 901 px | 216 px vuoti in ognuna | — |
| Q2 | pannelli chiusi a 1920, poi 800×600 | roster 8–572 (o 12–572) invece di 8–792; inspector a 12 px invece di 8 | uguale |
| Q3 | 1000×800, LR, inspector | 324–664 invece di 324–616: 36 px sopra il pannello destro, su 580 px di altezza | 36 px; l'altezza nella spec era 316 px, con un contenuto più corto |
| Q3 | 901×800, LR, inspector | 324–664 invece di 324–517: 135 px sopra il pannello | — |
| Q4 | 1280×800, LR, inspector alto | 354–694 invece di 354–640: sopra la minimappa per 42 × 46 px | 42 px in larghezza; 96 px in altezza nella spec, misurati con un contenuto sintetico più alto di quello reale |
| Q4 | 1251×800, LR, inspector alto | sopra la minimappa per 71 × 46 px | — |

Quante verifiche falliscono, su quanti casi:

| Verifica | Rossi / casi | Causa | Ticket |
|---|---|---|---|
| P1 (sovrapposizioni senza inspector) a 1920, 1280, 1251 | 6/64, 6/32, 6/32 | N6: minimappa sotto il pannello | T1 |
| P2 (roster) a 1920, 1280, 1251 | 6 ciascuna | N6 | T1 |
| P2 (roster) a 1250, 1200, 1000, 901 | 16–28 ciascuna | Q1, più N6 | T1 |
| P2 (roster e inspector) a 900 e 800 | 24/32, 36/48; inspector 2/4, 6/12 | Q2 | T1 |
| P3 (minimappa) a 1920, 1280, 1251 | 6 ciascuna | N6 | T1 |
| P4 (nessuna memoria) a 1920, 1280, 1200, 1000, 800 | 6, 6, 6, 6, 36 | N6, Q2 | T1 |
| P1 e P2 con l'inspector a 1280, 1251, 1000, 901 | 1/4 ciascuna | Q3, Q4 | T2 |
| Passeggiate 1 e 2 | passi 8–11; 4–6 e 13–24 | N6, Q1 | T1 |
| Passeggiata 3 | passi 23 e 25 | Q3 | T2 |

**Verdi già oggi:** P1 a 1250, 1200, 1000, 901, 900 e 800 px (senza inspector); P3 sotto 1250 px; P5 a ogni dimensione larga. Restano come guardie contro le regressioni.

### 3. P5 e la sua prova (V4)

- A 1920, 1280, 1200 e 1000 px, partendo dalla vista automatica, ☰, ☰, ▤ e una scheda riadattano la vista ogni volta: 0% del pavimento e 0 punti dell'ingombro sotto l'interfaccia.
- **Mutazione permanente:** con gli ingombri congelati apposta, la scheda che riapre il pannello lascia il 16,5% del pavimento e 5 punti dell'ingombro sotto l'interfaccia. La verifica lo coglie.

### 4. Etichette, codice di oggi

| Verifica | Esito | Misura (caso peggiore) | Ticket |
|---|---|---|---|
| E1 | rosso a 1920, 1440, 2560 | a zoom 1 un'etichetta o un fumetto di agente coperto al 100%, 8 elementi coperti | T3 |
| E2 | verde | le etichette delle stanze stanno sopra quelle degli agenti iniziali, quindi oggi nessuna etichetta di agente copre un nome | — |
| E3, E4 | verdi | — | — |
| E5 | rosso a 1920, 1440, 2560 | in tutti i 180 stati, 8 lead e worker hanno il corpo (a 0,8 e 1,2 di altezza) sotto l'etichetta della stanza: un clic lì apre la stanza invece di selezionarli. I nomi delle stanze visibili prendono tutti il clic | T3 |
| E6 | rosso a 1440×900 | con `far` attivo, 15 etichette nascoste su 22 intercettano il puntatore (bay piene); 1 su 8 con le bay vuote | T4 |
| E7 | rosso | un passo di rotella sopra un'etichetta di stanza o di agente non zooma (rapporto di scala 1), sul canvas sì (0,9403) | T4 |

E5 è una conseguenza di N4 che la spec 01 non aveva misurato: l'etichetta nell'angolo posteriore sinistro sta anche sopra il corpo del lead e dei worker, non solo sopra le loro etichette.

**Riproduzione della spec 01:** con l'ancora di oggi, nella vista completa a 1920×1080 con LR, i worker con il centro dell'etichetta sotto quella della stanza sono 7 su 7, come nella spec 01. La copertura misurata qui è 92% per tutti, contro l'89% della spec 01. La differenza è nel metodo: qui area coperta su area dell'etichetta, con la scala delle etichette dopo la review R6.

### 5. Le varianti di N4 (per D8)

**Come sono misurate.** Ogni variante è calcolata dalla pagina, con l'ancora e l'allineamento del §4.3 della spec:
- con l'ancora di oggi, il calcolo coincide con le etichette disegnate entro **0,52 px** in tutti i 180 stati;
- A, B e C, disegnate davvero dal CSS con una patch che vive solo nel test, coincidono con il calcolo entro **0,52, 0,66 e 0,81 px** (casi peggiori: A nel focus su un agente, B nel primo piano, C nel focus).

**Tabella.** Caso peggiore su tutta la matrice (3 dimensioni × 3 layout × 10 viste × bay vuote o piene), e in quanti stati la misura non è zero. Dalla terza colonna in poi le misure usano l'ordine di T3, cioè le etichette degli agenti sopra quelle dei luoghi (E5 non dipende dall'ordine).

| Variante | E1 con l'ordine di oggi | E1 con gli agenti sopra | E2: nome della stanza coperto | E3: fuori dall'area libera | E4: etichette di luoghi sovrapposte | E5: agenti con il corpo sotto un'etichetta | Scritta "SUB-AGENT BAY" coperta |
|---|---|---|---|---|---|---|---|
| oggi | 100% (144/180) | 0 | 229 px² (28/180) | 0 | 0 | 8 lead e worker (180/180) | 0 |
| **A** | 34% (72/180) | 0 | 0 | 0 | 0 | **12 sub-agenti** (25/180), a ogni altezza | 0 |
| **B** | 52% (72/180) | 0 | 0 | 0 | 0 | **3 sub-agenti** (2/180), solo il punto più basso (0,4) | **27%**, sempre |
| **C** | 82% (72/180) | 0 | **303 px²** (26/180) | 0 | 0 | **4 lead e worker** (2/180) | 0 |

**Lettura:**
- **L'ordine di E1 serve con qualunque variante.** Solo spostando le etichette, i fumetti e le etichette degli agenti restano coperti nel 40% degli stati (72/180). Con gli agenti sopra, E1 vale 0 per tutte. È la stima del §4.3 della spec, ora misurata.
- **A** lascia libere le etichette dei worker, ma la sua etichetta sale sopra i sub-agenti seduti nella bay. Succede in 25 stati, quasi tutti con le bay piene: un clic sul corpo di un sub-agente lì apre la stanza.
- **B** è centrata sul bordo anteriore. Tocca soltanto i piedi di 3 sub-agenti in 2 stati su 180. In cambio copre in parte la scritta disegnata sul pavimento della bay (27% nel caso peggiore, la stanza Sviluppo), che è un elemento decorativo.
- **C** sta fuori dalla stanza. Finisce però nel corridoio, dove le etichette e i fumetti della fila anteriore la coprono (fino a 303 px² del nome, in 26 stati); in 2 stati sta sopra il corpo di 4 agenti della fila anteriore.

**Consiglio: B**, con l'ordine di E1. Come A, non tocca né i nomi delle stanze né il corpo di lead e worker. Il suo conflitto con i sub-agenti, però, è molto più piccolo: il punto più basso di 3 sub-agenti in 2 stati, contro 12 sub-agenti interi in 25 stati per A. Il prezzo è la scritta della bay, che è solo decorativa. Se la scegli, propongo di accettarli come eccezioni nella spec, con questi numeri:
- E5: il punto più basso di 3 sub-agenti in 2 stati su 180;
- la scritta della bay coperta fino al 27%.

**Screenshot** a 1920×1080, bay piene, vista completa:

| | Due pannelli | Nessun pannello |
|---|---|---|
| oggi | ![](img/02-prima-n4-oggi-1920x1080-due-pannelli.jpg) | ![](img/02-prima-n4-oggi-1920x1080-nessun-pannello.jpg) |
| A | ![](img/02-variante-n4-A-1920x1080-due-pannelli.jpg) | ![](img/02-variante-n4-A-1920x1080-nessun-pannello.jpg) |
| B | ![](img/02-variante-n4-B-1920x1080-due-pannelli.jpg) | ![](img/02-variante-n4-B-1920x1080-nessun-pannello.jpg) |
| C | ![](img/02-variante-n4-C-1920x1080-due-pannelli.jpg) | ![](img/02-variante-n4-C-1920x1080-nessun-pannello.jpg) |

Gli screenshot dei casi dei pannelli: `img/02-prima-n6-*`, `q1-*`, `q2-*`, `q3-*`, `q4-*`.

### 6. Processi del browser (V12)

- Nelle esecuzioni normali di T0 non è rimasto nessun processo.
- **Prova:** con la chiusura del browser saltata da una modifica temporanea, poi tolta e mai committata, `--only cubes` ha dato `FAIL runner no browser process left with this run's profile` con 17 PID. Il runner li ha poi chiusi: a fine prova i processi con `agent-world-profile` erano 0.

### 7. Suite completa

`npm run test:browser`, con la missione demo: **ALL OK**, in 4 min 31 s.
- le 130 verifiche della spec 01 restano verdi (views, checks, cubes, input, run): il refactor degli aiuti per gli eventi veri di `input` non cambia nulla;
- 39 verifiche nuove verdi, cioè le guardie di P, E2–E4, il modello, gli ingressi e i processi;
- 42 rossi attesi: 24 per T1, 9 per T2, 6 per T3, 3 per T4;
- missione completata in 152 s a 67 fps, nessun processo del browser rimasto.

La verifica degli ingressi è stata aggiunta dopo questo giro, e le fasi nuove sono state rilanciate da sole (ALL OK, stessi rossi attesi).
