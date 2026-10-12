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
