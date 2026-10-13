# Spec 03 — Memoria e stabilità delle sessioni lunghe

| | |
|---|---|
| **Stato** | bozza per la revisione (step 2, To-spec) |
| **Data** | 2026-10-13 |
| **Branch** | `feat/memory-stability`, da `main` = `1817d00` |
| **Origine** | N9 e N7 (retro della spec 02, §4–5), N5 (review della spec 01, R3), N2 (report della spec 01, T2); Plan dello step 1, approvato |
| **Decisioni già prese** (Plan) | D1: ordine strumenti → baseline dell'app → N5 → N2. D2: `build()` dentro N5, come ultimo ticket di N5. D3: al ritorno dopo una pausa del disegno, riallineamento immediato, niente time-lapse. D4: spazzino all'avvio più un comando a mano, nessun processo guardiano. D5: `soak` come fase opzionale, fuori dalla suite di base. D6: pulizia una tantum di `%TEMP%`, tenendo `agent-world-preview` (fatta, §1.2) |

**In breve**
1. **Strumenti.** Su Windows nessun modo esterno di chiudere node esegue i suoi gestori; una sonda uccisa lascia 16 processi Edge e un profilo bloccato. Le cartelle dei test restano a ogni `npm test` (3 a giro). Serve un modulo che avvii e chiuda il browser, dia un proprietario a ogni cartella temporanea e spazzi gli orfani all'avvio.
2. **N5.** Anelli, fasci, card, cubi, sub-agenti e la ricostruzione dell'ufficio tolgono gli oggetti dalla scena senza liberarli. Una missione demo lascia circa 520 geometrie e 23 texture; una ricostruzione dell'ufficio 926 e 15. In three r186 la perdita è vera, non solo un contatore.
3. **N2.** Quando il disegno si ferma (scheda nascosta, pannello nascosto, browser lento) gli eventi continuano ad arrivare. Al ritorno dopo 90 s: 301 passi e 142 effetti in coda, 28 s di replay accelerato; un sub-agente sparisce con 11 passi in coda; 3 cubi restano in scena. A 0,78 della velocità reale, 2 consegne su 17 diventano affondamenti.
4. **Soluzione.** Una funzione unica per liberare gli oggetti, che rispetta le risorse condivise; il sub-agente esce alla fine della sua coda; una consegna in coda non viene affondata; dopo una pausa con eventi arrivati, il mondo si riallinea allo stato del client come una pagina appena caricata.
5. **Verifiche.** Fasi nuove del runner (`hygiene`, `memory`, `late`, `soak` opzionale), uno script nuovo in `npm test` per le cartelle, rossi attesi in `known-red.json` per la parte dell'app.

## 1. Contesto misurato

### 1.1 Come sono state prese le misure

- **Strumenti (N9, N7):** script usa e getta nella cartella temporanea della sessione, con node v24.16.0 ed Edge di sistema. Ogni prova con Edge chiude e verifica da sola i propri processi; a fine prove: 0 processi con `agent-world-profile`.
- **App (N5, N2):** il pannello browser dell'app, con il server di prova (`agent-world-preview`, porta assegnata 9540). Mai la porta 4300.
  - Il pannello era nascosto: niente rAF, e dopo una navigazione il canvas misura 0×0. In queste condizioni three disegna solo il passaggio delle ombre, quindi le texture delle card non vengono mai caricate.
  - Per questo le misure valide hanno lo stage a 1920×1080 (come fa `lib.js` nella sessione di prova) e il mondo disegnato da un timer di 16 ms che chiama `frame()`. Così il pannello disegna a 48–58 fps, ma con il mondo al 78–83% dell'orologio: alcuni frame superano i 50 ms e `frame()` li tronca. È un client un po' lento, e lo si dice dove conta.
- **Contenuto:** la missione demo del runner ("Il sito completo per il lancio di una pizzeria napoletana a Milano, con brand, immagini e testi"), non contenuti sintetici. Le prove per fonte (§1.3) usano N ripetizioni sintetiche dello stesso effetto e lo dicono.

### 1.2 Strumenti: processi e cartelle (N9, N7)

**Residui in `%TEMP%` prima della pulizia D6** (2026-10-13):

| Prefisso | Cartelle | MB | Da dove |
|---|---|---|---|
| `agent-world-profile-` | 4 | 1 462,9 | sonde della review 02, interrotte alle 16:03 |
| `agent-world-smoke-` | 28 | 54,8 | `scripts/smoke.js`, mai rimosse |
| `agent-world-flows-` | 27 | 22,4 | `scripts/flows-test.js`, mai rimosse |
| `aw-` | 29 | 0 | `scripts/router-test.js` (`dataDir`), mai rimosse: **non era nell'handoff** |
| `aw-perf-home` | 4 | 0 | sonde della review 02 |

La pulizia D6 ha rimosso le 92 cartelle (1 540 MB), con 0 processi che le usavano; resta solo `agent-world-preview`, la home del server di prova.

**Come si può chiudere un processo node su Windows**, con gestori per `SIGINT`, `SIGTERM`, `SIGBREAK`, `SIGHUP` ed `exit`:

| Come | Gestori eseguiti | Esito |
|---|---|---|
| `child.kill('SIGINT')`, `'SIGTERM'`, `'SIGBREAK'` | nessuno | chiusura immediata |
| `process.kill(process.pid, 'SIGINT')` (su sé stesso) | nessuno | codice 1 |
| `taskkill /PID` (senza `/F`) | nessuno | rifiutato: "può essere terminato solo forzatamente" |
| `taskkill /PID /F` | nessuno | chiusura immediata |
| `timeout 2 node …` della shell (Git Bash) | nessuno | codice 124 |
| `timeout -s INT 2 node …` | nessuno | **il processo non si chiude**: resta vivo finché non lo si uccide |
| Ctrl+C in un terminale interattivo | non misurabile da qui | per la documentazione di Node arriva come `SIGINT` |

Conclusione: un gestore di segnale protegge solo da Ctrl+C. Contro un limite di tempo della shell o un `taskkill` serve chi viene dopo (lo spazzino).

**Una sonda con Edge uccisa** (lo stesso avvio di `launchBrowser` del runner, con la pagina caricata), due volte:

| Come si uccide node | Processi Edge prima | Dopo 3 s | Genitore del processo principale di Edge | Profilo |
|---|---|---|---|---|
| `taskkill /F` | 16 | **16** | il processo lanciato da node, già uscito | 20,4 MB, `EPERM` finché vivono |
| `taskkill /F /T` (l'albero) | 16 | **16** | idem | 45,1 MB, `EPERM` |

- Edge sopravvive anche alla chiusura dell'albero di node: il suo genitore è il processo lanciato, che passa la mano ed esce. È la causa già scritta nel runner a T8 della spec 01.
- Il profilo cresce con l'uso: 20–45 MB dopo pochi secondi, fino a 365 MB per le sonde della review.
- La ricerca dei processi (`Get-CimInstance Win32_Process`) costa 0,85–1,25 s.

**Le cartelle dei test.**
- `npm test` è verde in 19 s e lascia 3 cartelle a ogni giro: `agent-world-smoke-*`, `agent-world-flows-*`, `aw-*`.
- Nel codice:
  - `smoke.js`: `fail()` chiude il server ed esce con `process.exit(1)`; nessun percorso rimuove la home;
  - `flows-test.js`: il `finally` chiude il server, non rimuove la home;
  - `router-test.js`: la cartella `aw-*` non viene mai rimossa;
  - il runner rimuove home e profilo nel `finally`, quindi a fine normale e con un'eccezione, ma non se viene ucciso.
- Rimuovere la home subito dopo `server.kill()`, senza aspettare l'uscita, è riuscito in 9 prove su 9 (server fermo e a metà missione). Il blocco temuto non si è visto; il design aspetta comunque l'uscita, che costa poco.
- L'avvio e la chiusura del browser esistono solo dentro `scripts/browser-test.js` (`launchBrowser`, `closeBrowser`, `profileProcesses`, `leftovers`), quindi chi scrive una sonda li ricopia.

### 1.3 Risorse GPU, fonte per fonte (N5)

Contatori di `renderer.info.memory` dopo N ripetizioni e il tempo che serve agli effetti per finire, con frame veri; le ripetizioni sono sintetiche. "Programmi" è la lunghezza di `renderer.info.programs`.

| Fonte | N | Geometrie rimaste | Texture rimaste | Programmi | Cosa manca nel codice |
|---|---|---|---|---|---|
| `fx.ring` | 50 | 50 (1 ciascuno) | 0 | 0 | `dispose` toglie la mesh, non libera geometria e materiale |
| `fx.beam` (con il suo anello d'arrivo) | 50 | 150 (**3** ciascuno) | 0 | **+1** | le sfere `head` e `glow` e i 3 materiali; l'anello come sopra. La review 01 stimava circa 2,5 |
| `fx.burst` | 50 | 50 (il suo anello) | 0 | 0 | — (perde solo tramite `ring`) |
| `fx.sparkle`, `fx.confetti` | 50, 10 | 0 | 0 | 0 | — |
| card tolta (`removeCard`) | 20 | 20 | 20 | 0 | geometria, materiale e texture `300×84` |
| card tolte da `resetRun` | 20 | 20 | 20 | 0 | come sopra |
| card che cambia stato (`refreshCard`) | 20 | 0 | 0 | 0 | — (libera già la vecchia texture) |
| cubo consegnato (`deliverCube`) | 20 | 40 (2 ciascuno) | 0 | 0 | cubo e alone, con i materiali |
| cubo affondato (`sinkCube`) | 20 | 40 | 0 | 0 | come sopra, più il materiale sostituito (non contato da three) |
| cubo di workstream diviso in 3 (`splitWs`), poi i 3 affondati | 20 | 180 (9 ciascuno) | 0 | 0 | il cubo grande (2), i 3 cubi (6), l'anello del burst (1) |
| cubi tolti da `resetRun` | 20 | 40 | 0 | 0 | come per la consegna |
| sub-agente creato e rimosso (tutti i 14 posti delle bay) | 14 | 308 (22 ciascuno) | 0 | **+2** | `removeActor` toglie la radice dalla scena e non libera nulla: 17 geometrie disegnate del personaggio (23 sue in tutto, alcune nascoste), circa 10 materiali propri, più gli effetti di comparsa e scomparsa |
| ufficio ricostruito da `build()` (cambia il colore di un team) | 1 | **926** | **15** | 0 | ufficio e attori tolti dalla scena senza liberarli |

**Due fatti dai sorgenti di three r186**, che decidono come misurare e perché la perdita è vera:
- `WebGLGeometries.get` conta una geometria al **primo disegno** e `onGeometryDispose` la scala. Una geometria mai disegnata non compare nei contatori: le misure vanno fatte con la scena tutta in vista e con frame veri.
- `WebGLBindingStates` tiene, per ogni `geometry.id`, il VAO e una cache con un riferimento a ogni `BufferAttribute`. La svuota solo `releaseStatesOfGeometry`, chiamata dal `dispose` della geometria. Senza `dispose`, quindi, il GC non raccoglie nulla: restano gli array nell'heap JS e, tramite la `WeakMap` di `WebGLAttributes` la cui chiave resta viva, i buffer sulla GPU.
- I materiali non hanno un contatore. Un materiale non liberato tiene vivo il suo programma (`releaseProgram` scende solo al `dispose`): sono i "+1" e "+2" della tabella. La cache dei materiali d'ombra di `WebGLShadowMap` vale solo con `alphaTest`, i piani di taglio o le mappe di spostamento: qui non si usa.

**Risorse condivise**, che non vanno liberate finché qualcuno le usa:
- i materiali della cache `mat()` di `geo.js`, usati da ufficio e personaggi: un sub-agente ne usa alcuni (accessori), insieme ai suoi `holo` propri;
- `flowGeo` di `world.js`, la sfera dei pacchetti sulle strade (i materiali dei pacchetti si liberano già);
- dentro un oggetto: la geometria degli occhi, comune ai due occhi di un personaggio; la geometria e i materiali comuni alle particelle di `burst`, `sparkle` e `confetti`, che già si liberano una volta sola.

### 1.4 Una missione intera (N5 e N2)

Due missioni demo complete nel pannello, a ritmo normale (senza `AGENT_WORLD_FAST`):

| | Missione 1 | Missione 2 |
|---|---|---|
| Condizioni | canvas 0×0 (solo ombre), timer di 16 ms, nessuna pausa | stage 1920×1080, timer di 16 ms, **disegno fermo da 40 a 130 s** (modello della scheda nascosta) |
| Durata lato server | 145 s, `completed` | `completed` tra 131 e 178 s (l'istante non è stato registrato) |
| Frame e velocità del mondo | 48 fps di media; mondo al 78% dell'orologio (47% nei primi 71 s) | 51 fps prima della pausa, 58 dopo; mondo all'83% dell'orologio mentre disegna |
| Eventi al mondo | 109 messaggi, 32 operazioni del Brain, 23 file, 6 workstream, 17 task (23 card), 17 prese, 1 sub-agente | 112 messaggi, 32 Brain, 23 file, 6 workstream, 17 task (23 card), 16 prese, 2 sub-agenti |
| Consegne / affondamenti | 15 / 2 | 16 / 0 |
| **Consegne diventate affondamenti** | **2**: `w1.4` (`sara`, 11 passi in coda) e `w2.3` (`ugo`, 9 passi in coda) | 0 |
| **Sub-agenti rimossi con lavoro in coda** | 0 | **1**: `prompt-sub1`, 11 passi in coda (creato e rimosso durante la pausa, mai visto) |
| **Cubi rimasti in scena a fine missione** | 0 | **3** (chiavi non registrate da questa sonda: le registra T3) |
| Memoria a fine missione e dopo `resetRun` | +97 geometrie (solo ombre), +3 programmi | **1 546** geometrie e **58** texture contro le 1 023 e 15 ancora raggiungibili dalla scena: almeno **523 geometrie e 43 texture** perse, più 3 programmi |

- Le 43 texture della missione 2 comprendono le 23 card della missione precedente, che `resetRun` ha tolto all'inizio senza liberarle: a ogni missione nuova si perdono le card di quella prima.
- **Stima per missione**, dai conteggi degli eventi per le perdite per fonte del §1.3 (è una stima, non una misura): circa 140 fasci × 3, 45 anelli, 23 cubi × 2, 6 cubi grandi × 2, 23 card, 1–2 sub-agenti × 22, cioè **500–570 geometrie e 23 texture**. Coincide con le 523 misurate.
- **Ordine di grandezza in byte** (stima): una texture di card è 300×84×4 byte, circa 134 KB con le mipmap, quindi 3 MB a missione; le geometrie sono piccole (una sfera 12×10 circa 5 KB), circa 1,5 MB a missione sulla GPU e altrettanti nell'heap JS. Una sessione di 20 missioni perde circa 90 MB; ogni salvataggio delle impostazioni che cambia staff o team aggiunge un ufficio intero.

### 1.5 Il client in ritardo (N2)

**La causa.** `world.js` disegna con `renderer.setAnimationLoop`, cioè rAF. Quando la pagina non viene disegnata, `frame()` non gira, ma gli eventi SSE e i `setTimeout` continuano:
- `applyState`, `onMessage` e gli altri gestori accodano passi agli attori e creano effetti, che restano fermi;
- il `setTimeout` di 800 ms di `onDespawn` toglie il sub-agente con la coda ancora piena (missione 2);
- il ramo `idle` di `applyState` affonda i cubi del worker il cui task è `done` anche se la consegna è ancora in coda dietro la camminata (missione 1, senza nessuna pausa: basta un mondo più lento dell'orologio).

**Quando il disegno si ferma.** Non solo con la scheda nascosta:
- **pannello dell'app nascosto:** 0 callback di rAF in 2 s, ma `document.visibilityState` era `visible`; dopo una navigazione diventa `hidden`. I timer giravano a piena velocità (63 al secondo con un intervallo di 16 ms). Quindi un riallineamento legato solo a `visibilitychange` qui non scatterebbe;
- **browser lento:** `frame()` limita il passo a 0,05 s, quindi sotto i 20 fps il mondo va più piano dell'orologio. Il runner lo misura già in A10 (`worldSpeed`);
- **scheda nascosta in un browser vero:** rAF si ferma e i timer vengono rallentati. Secondo la documentazione di Chrome (non misurato qui), dopo 5 minuti da nascosta i timer concatenati scattano al massimo una volta al minuto. Con il design di questa spec la durata dei timer da nascosti non conta più (§4.4–4.5).

**L'arretrato al ritorno** (missione 2, disegno fermo per 90 s):

| | Quando il disegno si ferma (40 s) | Al ritorno (130 s) |
|---|---|---|
| Passi in coda agli attori | 42 (al massimo 9 per attore) | **301** (al massimo **63**) |
| Effetti in corso | 23 (11 fasci) | **142** (96 fasci) |
| Oggetti nella scena | 145 | 483 |

Smaltire l'arretrato ha richiesto **28,1 s** (1 633 frame, 27,3 s di mondo): chi torna vede quasi mezzo minuto di replay accelerato dalla spinta delle code (`boost` di `Actor.update`), con decine di fasci insieme.

**Cosa sa già il client.** Il riallineamento può usare lo stato che `main.js` tiene già, senza chiedere niente al server:
- il server manda il run completo (`emitRun`) a ogni cambio di task o di workstream, raggruppato in al più 220 ms; `main.js` lo tiene in `S.run`;
- gli eventi `agent` portano l'agente intero; `main.js` li tiene in `S.agents`;
- la riconnessione SSE di oggi (`es.onopen`) fa già un riallineamento: `applyState(a, true)` per ogni agente, poi `syncRun`. L'avvio della pagina fa lo stesso, più `onRun` per un run finito.

**Vincoli trovati leggendo il codice:**
- i movimenti di camera sono effetti `fx` legati alla camera (`fx.track(this.camera, …)` in `moveCamera`): un riallineamento che ritira tutti gli effetti fermerebbe a metà un movimento di camera;
- `onPlan` e `onSubtasks` fanno volare le card con `setTimeout` (200 e 160 ms per card): dopo un riallineamento quelle card potrebbero non esistere più;
- le fasi del runner fermano il ciclo di disegno anche per minuti (`t.session` in `lib.js`) e chiamano `frame()` a mano. Una regola "pausa lunga, quindi riallinea" scatterebbe anche lì: serve che durante la pausa siano arrivati eventi del server.

## 2. Obiettivi e non-obiettivi

**Obiettivi**
- **G1 (N9):** nessuno strumento lascia processi del browser o profili, comunque finisca. Se viene ucciso, il prossimo strumento che parte pulisce.
- **G2 (N7):** `npm test` e il runner non lasciano cartelle temporanee, nemmeno quando falliscono.
- **G3 (N5):** ogni oggetto tolto dalla scena libera le proprie risorse e nessuna risorsa condivisa ancora in uso. Una sessione lunga non cresce di missione in missione.
- **G4 (N2):** quando il mondo torna a essere disegnato dopo una pausa in cui sono arrivati eventi, mostra subito il presente. Nessuna consegna diventa un affondamento, nessun sub-agente sparisce prima di aver finito, a qualunque frame rate.

**Non-obiettivi**
- **N8** (pinch su touch sopra le etichette).
- Il **processo guardiano** (D4) e il **time-lapse** al ritorno (D3).
- **Recuperare il ritardo di un client lento senza pause:** con il mondo al 78% dell'orologio resta indietro come oggi e recupera con la spinta delle code. Qui si correggono gli errori che il ritardo produce (R1, R2), non il ritardo; vedi la domanda D10.
- **La memoria del server:** già limitata (chat agli ultimi 60 messaggi, `router.recent` a 60, la scheda Comms a 180 righe).
- La home del server di prova, `agent-world-preview`: non è una cartella di test.

## 3. Requisiti

Sono scritti dal punto di vista di chi usa l'app o gli strumenti. I nomi del codice stanno nel §4 e nei ticket.

### 3.1 Strumenti: il browser headless (H)

"Strumento" è il runner (`scripts/browser-test.js`) e ogni sonda che avvia un browser. "Proprietario" di un profilo o di una cartella è il processo node che l'ha creato.

- **H1 — Un solo modulo.** Ogni avvio di un browser headless negli script passa da un solo modulo, che si occupa anche di chiuderlo, di cercare i processi rimasti e di spazzare gli orfani.
- **H2 — Fine normale ed errore.** A fine normale e con un'eccezione, il browser si chiude: 0 processi con il profilo dello strumento, profilo e home rimossi.
- **H3 — Ctrl+C.** Come H2, quando l'utente preme Ctrl+C nel terminale (o Ctrl+Break, o chiude la finestra del terminale).
- **H4 — Uccisione.** Se lo strumento viene ucciso (limite di tempo della shell, `taskkill /F`), il prossimo strumento che parte chiude i processi del browser e rimuove le cartelle i cui proprietari sono morti, prima di avviare il proprio browser. Lo fa anche il comando a mano.
- **H5 — Mai toccare** un'esecuzione parallela viva (proprietario vivo), i processi del browser senza `agent-world-profile-` nella riga di comando (l'Edge dell'utente), `agent-world-preview`, i server sulle porte 4300 e 4310, nessuna cartella fuori dai prefissi dei test.
- **H6 — Costo e resoconto.** Lo spazzino costa al massimo 2 s all'avvio. Ogni pulizia stampa cosa ha chiuso e rimosso (PID, cartelle, MB); il comando a mano esce con 0, anche quando non trova niente.

**Matrice modo di fine × strumento.** Dopo ogni caso si contano i processi con il profilo e le cartelle del proprietario.

| Modo di fine | Runner | Sonda | Atteso | Oggi |
|---|---|---|---|---|
| Fine normale | ✓ | ✓ | H2, subito | runner ok; sonda: dipende da chi la scrive |
| Eccezione | ✓ | ✓ | H2, subito | runner ok; sonda: idem |
| Ctrl+C, Ctrl+Break, chiusura del terminale | ✓ | ✓ | H3, subito | 16 processi e profilo rimasti (stessa via di `taskkill`: nessun gestore) |
| `taskkill /F` o limite di tempo della shell | ✓ | ✓ | H4, al prossimo avvio | **16 processi e il profilo rimasti** (§1.2) |
| Due esecuzioni in parallelo, una viene uccisa | ✓ | ✓ | lo spazzino chiude solo quella morta (H5) | oggi nessuno spazza |

### 3.2 Strumenti: le cartelle temporanee (C)

- **C1 — Nessun resto.** Dopo `npm test` e dopo il runner, in `%TEMP%` non resta nessuna cartella creata da loro: a fine normale, con un test che fallisce e con il server che muore.
- **C2 — Un proprietario per ogni cartella.** Ogni cartella temporanea dei test porta nel nome il PID del suo proprietario, con un prefisso comune (`agent-world-<strumento>-<pid>-`), così lo spazzino di H4 la riconosce.
- **C3 — Anche le cartelle di uno strumento ucciso** vengono rimosse al prossimo avvio di uno strumento (H4) o dal comando a mano.

### 3.3 Memoria GPU (M)

Le "risorse proprie" di un oggetto sono le geometrie, i materiali e le texture che ha creato per sé. Le "risorse condivise" sono quelle del §1.3.

- **M1 — Ogni oggetto tolto libera le sue risorse proprie,** quando esce dalla scena per sempre: alla fine di un effetto, quando si toglie una card, quando un cubo finisce la consegna o l'affondamento, quando un workstream si divide, con `resetRun`, quando un sub-agente esce, quando l'ufficio si ricostruisce.
- **M2 — Nessuna risorsa ancora in uso viene liberata:** in ogni momento, nessun oggetto nella scena usa una geometria, un materiale o una texture già liberati.
- **M3 — Una missione non lascia nulla.** Dopo una missione completa e il `resetRun` del run successivo, geometrie, texture e programmi tornano esattamente ai valori di prima della missione.
- **M4 — Sessione lunga** (fase `soak`, opzionale). Su K missioni di fila, dalla seconda in poi: geometrie, texture e programmi identici dopo ogni missione; heap JS dopo il GC, nodi del DOM e listener che non crescono oltre una soglia, fissata a T3 dalla misura di oggi e almeno 10 volte sotto la crescita misurata oggi.

**Matrice fonte × percorso.** Ogni casella è una verifica: dopo il percorso, le risorse proprie liberate (M1) e nessuna risorsa in uso liberata (M2).

| Fonte | Percorsi | Oggi |
|---|---|---|
| anello | fine dell'effetto | perde 1 geometria e il materiale |
| fascio | fine dell'effetto | perde 2 geometrie e 3 materiali (più il suo anello) |
| burst, sparkle, confetti | fine dell'effetto | ok (burst perde tramite l'anello) |
| card | `removeCard`, `resetRun`, cambio di stato | perde geometria, materiale e texture, salvo il cambio di stato |
| cubo | consegna, affondamento, divisione del workstream, `resetRun` | perde 2 geometrie e 2 materiali; l'affondamento anche il materiale sostituito |
| sub-agente | uscita | perde 17 geometrie e circa 10 materiali (più i suoi effetti) |
| ufficio | `build()` con una configurazione diversa | perde 926 geometrie e 15 texture |
| pacchetti sulle strade | fine del percorso | ok (geometria condivisa, materiale liberato) |

### 3.4 Il client in ritardo (R)

Una "pausa" è un tempo senza frame disegnati: scheda nascosta, finestra ridotta a icona, pannello dell'app nascosto, debugger, macchina in sospensione.

- **R1 — Una consegna non diventa mai un affondamento.** Il cubo di un task `done` vola alla lavagna, qualunque sia il frame rate e qualunque cosa arrivi prima che la consegna parta. Un cubo affonda solo per un task `failed` o `skipped`, o quando il run viene azzerato.
- **R2 — Un sub-agente esce solo dopo aver finito.** Esce, con il suo effetto di uscita, dopo i passi che aveva in coda (consegna compresa); se arriva un riallineamento prima, esce con quello.
- **R3 — Ritorno immediato (D3).** Dopo una pausa di almeno **1 s** in cui sono arrivati eventi del server, al primo frame il mondo mostra il presente. È identico a quello di una pagina caricata in quel momento: stessi attori, ognuno al posto in cui lo mette il caricamento (seduto, oppure accanto alla scrivania che sta revisionando), nessuno che porta un cubo, gli stessi cubi con gli stessi proprietari, le stesse card nelle stesse colonne, nessun passo in coda e nessun effetto arretrato.
- **R4 — Nessun effetto per chi non guarda.** Gli eventi che arrivano mentre il mondo è in pausa non creano effetti; quelli già in corso, al riallineamento, si ritirano liberando le risorse (M1).
- **R5 — Pause brevi e camera.** Una pausa sotto 1 s, o senza eventi arrivati, riprende come oggi, senza salti. Un riallineamento non ferma un movimento di camera in corso e non cambia la modalità della vista (automatica o manuale).
- **R6 — Niente memoria del passato.** Dopo un riallineamento, i timer e i passi nati prima (voli delle card, rimozioni, consegne) non agiscono su oggetti che non esistono più e non ricreano oggetti tolti.

**Matrice pausa × momento della missione.** Le pause sono di 0,5 s, 2 s, 30 s e oltre 5 minuti; i momenti sono quelli in cui il ritardo fa danni.

| Momento in cui la pausa comincia | Atteso al ritorno | Oggi (misurato o letto nel codice) |
|---|---|---|
| durante il piano (card dei workstream in volo) | R3: le card dei workstream nelle colonne giuste | card in volo da `setTimeout` mentre il mondo è fermo |
| durante le divisioni dei workstream | R3: cubi dei task sulle scrivanie giuste | — da misurare a T3 |
| durante le consegne | R1, R3 | missione 1: 2 affondamenti senza pausa, al 78% di velocità |
| durante l'uscita di un sub-agente | R2, R3 | missione 2: rimosso con 11 passi in coda |
| a cavallo della fine del run | R3: card finite sulla lavagna, nessun cubo | missione 2: 3 cubi rimasti |
| mondo lento senza pause (10 fps) | R1, R2; nessun riallineamento | missione 1 |

### 3.5 Contenuti e casi peggiori

Dalla retro della spec 02 (azione 2): il caso peggiore scritto accanto alla matrice.
- **Contenuto:** la missione demo del runner, con i suoi testi (§1.1). Le prove per fonte usano ripetizioni sintetiche, e il report lo dice.
- **Sub-agenti:** tutti i 14 posti delle bay occupati, poi svuotati.
- **Pausa più lunga:** oltre 5 minuti, quando il browser rallenta i timer al minuto.
- **Missione con il client più lento:** il server in modalità veloce (`AGENT_WORLD_FAST`), che manda gli eventi molto più in fretta di quanto il mondo li disegni.
- **Ufficio:** tre ricostruzioni di fila.
- **Strumenti:** due esecuzioni in parallelo, una delle quali uccisa.

## 4. Design tecnico

Questa sezione propone l'implementazione; i ticket la possono affinare.

### 4.1 Il modulo del browser (N9)

**`scripts/browser/headless.js`**, un modulo Node: è il primo file non di pagina in `scripts/browser/`, e il runner non lo inietta (la lista `SCRIPTS` resta esplicita).
- Si sposta dal runner, senza cambiare comportamento: `findBrowser`, `Cdp`, l'avvio, la chiusura robusta (`Browser.close` via DevTools, attesa, `taskkill /T` del vero processo del browser solo se risponde ancora), `profileProcesses` e `leftovers`.
- Si aggiunge:
  - `launch()` crea il profilo con il PID nel nome (`agent-world-profile-<pid>-XXXXXX`), spazza gli orfani **prima** di avviare e registra il browser tra quelli da chiudere all'uscita;
  - `close(browser)` chiude, controlla i processi rimasti e rimuove il profilo con i tentativi di oggi;
  - gestori di uscita installati una volta: `SIGINT`, `SIGBREAK`, `SIGHUP`, `uncaughtException`, `unhandledRejection`. Chiudono i browser registrati (con un tempo massimo), rimuovono le cartelle registrate ed escono con 130 (segnali) o 1 (errori);
  - `sweep()` e il comando `node scripts/browser/headless.js --sweep` (e `npm run sweep`).

**Le cartelle con un proprietario: `scripts/lib/temp.js`**, usato da tutti gli script di test e dal modulo del browser:
- `ownedDir(tool)` crea `agent-world-<tool>-<pid>-XXXXXX` in `tmpdir()` e la registra per i gestori di uscita;
- `removeDir(dir)`, con i tentativi di oggi (40 × 500 ms);
- `sweepDirs()`: per ogni cartella con un prefisso dei test e un PID nel nome, se il proprietario è morto (`process.kill(pid, 0)` fallisce) la rimuove.

**Lo spazzino**, in ordine:
1. cartelle `agent-world-profile-<pid>-*` con il proprietario morto;
2. se ce ne sono, oppure se ci sono processi con `agent-world-profile-` il cui profilo non esiste più: una ricerca dei processi (circa 1 s), chiusura degli alberi dei loro browser (`taskkill /T /F` sul processo principale, quello senza `--type=`), poi i processi rimasti uno per uno;
3. rimozione dei profili, poi `sweepDirs()` per le altre cartelle dei test.

**Precisioni:**
- **PID riusato.** Se il PID di un proprietario morto è stato riassegnato a un altro processo, lo spazzino crede il proprietario vivo e lascia l'orfano fino alla volta dopo. È l'errore dalla parte sicura.
- **Nomi senza PID** (cartelle di checkout vecchi): lo spazzino automatico non li tocca. Il comando a mano li elenca e li rimuove solo se nessun processo li usa.
- **Ctrl+C** non si può simulare da uno script su Windows (§1.2): H3 si verifica a mano, nel QA.
- **Le sonde** diventano fasi opzionali del runner quando le misure vanno riportate (retro 02); quelle usa e getta importano il modulo.

### 4.2 Le cartelle dei test (N7)

- `smoke.js`, `flows-test.js`, `router-test.js` e il runner prendono la cartella da `ownedDir()` e chiamano `sweepDirs()` all'avvio.
- Il server si chiude e **si aspetta la sua uscita** prima di rimuovere la home, su ogni percorso: `fail()` di `smoke.js` diventa asincrona e passa dalla pulizia prima di uscire; `flows-test.js` lo fa nel `finally`.
- **`scripts/temp-test.js`**, ultimo script di `npm test`:
  - nessuna cartella dei test con un proprietario morto dopo gli script precedenti;
  - percorso di errore: lancia `smoke.js` e `flows-test.js` con una variabile d'ambiente che li fa fallire subito dopo l'avvio del server (solo per i test), poi controlla che la loro cartella sia sparita;
  - uccisione: lancia `smoke.js`, lo uccide con `taskkill /F` a metà, controlla che la cartella resti (orfana) e che lo spazzino la tolga;
  - proprietario vivo: una cartella propria, viva, sopravvive allo spazzino.

  `npm test` passa da 19 a circa 35 s (stima).

### 4.3 Liberare le risorse (N5)

**`public/js/world/dispose.js`**, `disposeObject(root)`:
- visita `root` e i figli; per ogni geometria, materiale e texture dei materiali (ogni proprietà che è una texture) chiama `dispose()` una volta sola;
- salta le risorse condivise, segnate con `userData.shared = true`: i materiali della cache `mat()`, `flowGeo`;
- salta i cubi (`userData.cube`) attaccati a un attore che esce: hanno un loro percorso, e liberarli con l'attore libererebbe un cubo ancora in `world.cubes` (§1.5, passaggio avversario).

**Dove si chiama:**
- `fx.ring` e `fx.beam`: nel loro `dispose`, che `Fx.retire` chiama già alla fine di ogni effetto;
- card: `removeCard` e `resetRun`;
- cubi: alla fine del volo di consegna, alla fine dell'affondamento, sul cubo grande di `splitWs`, in `resetRun`; `sinkCube` libera subito il materiale che sostituisce;
- sub-agenti: `removeActor`;
- ufficio: `build()` libera il vecchio gruppo dell'ufficio e gli attori, tranne i materiali condivisi (che il nuovo ufficio riusa dalla stessa cache).

**Alternativa scartata:** contare i riferimenti di ogni risorsa. Oggi le condivisioni sono poche e note; un segno esplicito è più semplice e la verifica M2 lo controlla.

### 4.4 L'ordine degli eventi (N2: R1, R2)

- **R1.** La consegna in coda porta la chiave del cubo (`{ type: 'call', fn, deliver: key }`). Il ramo `idle` di `applyState` e il ciclo di `onDespawn` non affondano un cubo che ha una consegna in coda nel suo proprietario: quel cubo partirà con la consegna.
- **R2.** `onDespawn` non usa più un `setTimeout`: accoda all'attore un passo di uscita (effetti di uscita, rimpicciolimento, poi `removeActor`) dopo quelli che ha. Le code si svuotano solo con i frame, quindi la rimozione segue il mondo, non l'orologio. Se il mondo è in pausa, l'uscita la fa il riallineamento (R3).
- **Passaggio avversario** (retro 01, lezione 3), da ripetere nel ticket: tutti i chiamanti di `sinkCube` (grep) e di `removeActor`; un sub-agente che esce mentre porta un cubo; un `idle` che arriva mentre la consegna è già in volo (il cubo non è più in `world.cubes`); un `delivering` senza `taskId`.

### 4.5 Il riallineamento (N2: R3–R6)

**Quando.** In `frame()`, se dall'ultimo frame è passato almeno 1 s **e** nel frattempo è arrivato un evento del server, il mondo chiama `onBehind()` prima di disegnare.
- "Evento del server" lo segna `main.js` in `handle()`: le fasi del runner chiamano i metodi del mondo direttamente, quindi non lo segnano, e una sessione di prova lunga non provoca riallineamenti.
- Il segnale è il buco tra i frame, non `visibilitychange`: copre anche il pannello nascosto, dove la visibilità resta `visible` (§1.5).
- La soglia di 1 s è circa 12 volte l'intervallo medio tra frame più lento visto finora (79 ms, nel run a 12,6 fps del report 01).

**Cosa fa.** `main.js` collega `onBehind` a una funzione `resync()`, la stessa che usa la riconnessione SSE, con `S.run` e `S.agents` già aggiornati (§1.5):
1. il mondo ritira gli effetti, tranne quelli della camera, liberandone le risorse;
2. per ogni agente, `applyState(a, true)`: posto, posa e animazione di base del caricamento; code vuote, cubi in mano lasciati;
3. i sub-agenti che non sono più in `S.agents` escono senza effetti; quelli nuovi entrano;
4. `syncRun(S.run)` se il run è vivo; se è finito, come all'avvio della pagina (`syncRun(null)` e poi `onRun(S.run)`);
5. i voli delle card in `setTimeout` e i passi delle code controllano che il loro oggetto esista ancora (R6).

**Mentre è in pausa (R4).** Se l'ultimo frame è più vecchio di 1 s, i gestori del mondo non creano effetti (fasci, anelli, scintille, coriandoli, fumetti). Lo stato degli attori e delle card continua ad aggiornarsi come oggi.

**Passaggio avversario:** riallineamento durante un movimento di camera; durante la selezione di un sub-agente che non c'è più (oggi `main.js` già la toglie); due pause di fila; pausa di 0,9 s con eventi (nessun riallineamento); un evento che arriva tra il buco e il primo frame.

### 4.6 Il runner e i rossi attesi

**Fasi nuove:**

| Fase | Cosa misura | Durata attesa | Nella suite di base |
|---|---|---|---|
| `hygiene` | H2–H6: una sonda vera uccisa con `taskkill /F` e spazzata; una sonda viva lasciata intatta; il comando a mano | ≤ 30 s | sì |
| `memory` | M1, M2, fonte per fonte (§3.3), con la scena tutta in vista a 1920×1080 e frame veri | ≤ 60 s | sì |
| `late` | R1–R6 sulla matrice del §3.4, con un secondo server demo in modalità veloce | ≤ 3 min | sì |
| `run` (A10, esistente) | in più M3: memoria prima della missione = dopo la missione e il `resetRun` | invariata | sì |
| `soak` | M4 su K missioni (`--soak K`, 3 di default), a ritmo normale | circa 3 min a missione | **no** (D5) |

**Come `memory` riconosce le perdite.** Lo script di pagina importa `three` dalla stessa mappa di import dell'app, quindi lo stesso modulo, e avvolge `dispose` di `BufferGeometry`, `Material` e `Texture` per segnare ciò che viene liberato. Durante ogni percorso visita la scena a ogni frame e raccoglie le risorse nate dopo l'inizio (gli `id` di three crescono sempre). Alla fine:
- ogni risorsa raccolta che non è più raggiungibile dalla scena e non è condivisa deve essere stata liberata (M1);
- nessuna risorsa raggiungibile dalla scena deve essere stata liberata (M2);
- in più, i contatori di `renderer.info` tornano alla base.

Il controllo vale anche per i materiali, che three non conta, e per le perdite future che nessuno ha ancora elencato.

**Come `late` fa una pausa.** Ferma il ciclo di disegno (`setAnimationLoop(null)`) per il tempo voluto, mentre il server manda eventi veri, poi lo riprende. Il modello si confronta una volta con una pagina nascosta vera (§8).

**L'equivalenza di R3.** Al ritorno il runner mette in pausa il run (`/api/runs/:id/pause`), fotografa il mondo, carica la stessa pagina in una seconda scheda, la fotografa e confronta, poi riprende il run. La fotografia contiene attori (posizione ±0,05, posa, cubo in mano), cubi (chiave, proprietario, in mano o sulla scrivania), card (chiave, colonna, aspetto), effetti del mondo in corso e passi in coda.

**Rossi attesi.**
- Le verifiche dell'app (`memory`, `late`, la memoria di `run`) nascono a T3, girano sul codice di oggi e i loro rossi si segnano in `known-red.json` con il ticket che li chiude. I segni si **generano dal JSON della baseline** e poi si rivedono a mano (retro 02, azione 3).
- Ogni verifica riporta tutti i casi rossi, non solo il primo.
- Le verifiche verdi dall'inizio (sparkle, confetti, pacchetti, `refreshCard`, la pausa breve) hanno una mutazione permanente che deve essere presa: un `dispose` saltato; un riallineamento forzato su una pausa breve.
- Gli strumenti (T1, T2) cambiano insieme al loro test: ogni ticket mostra prima il test rosso sul codice di oggi, poi la correzione, e lo scrive nel messaggio di commit.

## 5. Criteri di accettazione

| ID | Criterio | Come si verifica | Oggi | Ticket |
|---|---|---|---|---|
| V1 | H1: nessun avvio di browser fuori dal modulo (grep di `--remote-debugging-port`) | grep, nel runner | solo nel runner, ma niente modulo | T1 |
| V2 | H2: fine normale ed eccezione, 0 processi, profilo e home rimossi | runner (verifica di oggi, estesa alle cartelle) | verde | T1 |
| V3 | H4, C3: dopo un `taskkill /F`, il prossimo avvio lascia 0 processi e 0 cartelle del proprietario morto, entro 2 s | fase `hygiene` | rosso: 16 processi e il profilo | T1 |
| V4 | H5: un'esecuzione viva e l'Edge dell'utente intatti; `agent-world-preview` intatta | `hygiene` | — | T1 |
| V5 | H6: resoconto dello spazzino e comando a mano | `hygiene` | — | T1 |
| V6 | H3: Ctrl+C sul runner a metà → 0 processi e 0 cartelle | QA dell'utente in un terminale | rosso (§1.2) | T1 |
| V7 | C1, C2: `npm test` non lascia cartelle, anche con un test che fallisce e con il server ucciso | `scripts/temp-test.js` in `npm test` | rosso: 3 cartelle a giro | T2 |
| V8 | M1, M2: matrice fonte × percorso del §3.3 | fase `memory`, una verifica per fonte | rosso per anello, fascio, card, cubi, sub-agenti, ufficio | T4–T7 |
| V9 | M3: una missione torna ai valori di prima | fase `run` | rosso: almeno 523 geometrie e 43 texture | T7 |
| V10 | M4: sessione lunga piatta | fase `soak` (opzionale), a fine ciclo | da misurare a T3 | T10 |
| V11 | R1: nessun task `done` affondato e nessun cubo rimasto a fine missione, a 60 e a 10 fps e con le pause | fase `late` | rosso: 2 affondamenti (missione 1), 3 cubi (missione 2) | T8 |
| V12 | R2: nessun sub-agente rimosso con passi in coda | `late` | rosso: 1 su 2 (missione 2) | T8 |
| V13 | R3, R6: al ritorno, mondo identico a una pagina caricata in quel momento | `late`, con l'equivalenza del §4.6 | rosso: 301 passi e 142 effetti in coda, 28 s di replay | T9 |
| V14 | R4, R5: nessun effetto arretrato; pausa breve senza riallineamento; camera intatta | `late` | rosso (R4); verde (R5), con la mutazione | T9 |
| V15 | A10 della spec 01 e tutta la suite verdi; `npm test` verde; QA dell'utente a 1920×1080 (anche con la scheda nascosta durante una missione) | suite completa, utente | — | T10 |

## 6. Ticket in bozza

La suddivisione definitiva si fa nello step 3. Dopo ogni ticket ci si ferma per il tuo feedback.

| Ticket | Cosa | Fermata |
|---|---|---|
| **T1** | N9: `scripts/browser/headless.js` e `scripts/lib/temp.js` (§4.1); il runner li usa; fase `hygiene`; `npm run sweep` | QA: Ctrl+C sul runner in un terminale (V6) |
| **T2** | N7: smoke, flows, router e runner con le cartelle di proprietà; `scripts/temp-test.js` in `npm test` (§4.2) | feedback |
| **T3** | Baseline dell'app: fasi `memory`, `late`, la memoria di `run`, `soak`; segni generati dal JSON e rivisti; confronto del modello di pausa con una pagina nascosta vera | **rivedi i rossi e i numeri** prima delle correzioni |
| **T4** | N5, effetti: `dispose.js`, il segno delle risorse condivise, `ring` e `beam` | feedback |
| **T5** | N5, card e cubi | QA |
| **T6** | N5, sub-agenti | QA (bay piene, poi vuote) |
| **T7** | N5, ricostruzione dell'ufficio (`build()`, D2); M3 verde | QA (cambio di colore di un team nelle impostazioni) |
| **T8** | N2, ordine degli eventi: R1, R2 (§4.4) | QA |
| **T9** | N2, riallineamento: R3–R6 (§4.5) | QA: scheda nascosta durante una missione |
| **T10** | verifica finale, `soak`, report "Dopo", QA a 1920×1080 | approvazione dello step |

## 7. Decisioni

Prese nel Plan: D1–D6 (intestazione).

**Da prendere alla revisione di questa spec:**
- **D7 — Soglia della pausa: 1 s.** Più bassa riallinea anche dopo un alt-tab veloce; più alta lascia più replay. *Consiglio: 1 s.*
- **D8 — `late` nella suite di base, su un secondo server in modalità veloce,** circa 3 minuti in più: la suite completa passa da circa 6 a circa 9–10 minuti. In alternativa `late` diventa opzionale come `soak`, e nella suite resta solo un caso per requisito. *Consiglio: nella suite di base; i ritocchi usano `--only`.*
- **D9 — `npm test` da 19 a circa 35 s** per `temp-test.js`, che uccide e fa fallire apposta gli altri script. *Consiglio: sì; è l'unico modo di provare C1 sui percorsi di errore.*
- **D10 — Client lento senza pause.** Con frame che superano i 50 ms il mondo resta indietro (al 78% dell'orologio nella missione 1, al 47% nei suoi primi 71 s) e recupera con la spinta delle code. R1 e R2 ne tolgono gli errori, ma il ritardo resta. Un riallineamento anche quando l'arretrato supera una soglia (per esempio 10 s di mondo) lo toglierebbe, a costo di salti visibili mentre si guarda. *Consiglio: fuori perimetro, annotato come ticket; la fase `soak` riporta il ritardo misurato.*
- **D11 — Ctrl+C verificato a mano.** Su Windows uno script non può mandare un Ctrl+C vero a un altro processo (§1.2): V6 è un passo del tuo QA, non una verifica automatica. *Consiglio: sì.*

## 8. Rischi

- **Modello della pausa.** `late` ferma il ciclo di disegno invece di nascondere la pagina. Se a T3 una pagina nascosta vera si comporta in modo diverso (per esempio eventi SSE rallentati), il modello va corretto prima di usarlo per le verifiche: T3 si ferma lì.
- **Una risorsa condivisa non segnata.** Liberarla romperebbe un oggetto vivo; three ricaricherebbe la risorsa al frame dopo, quindi si vedrebbe come un costo, non come un errore. M2 serve a questo; il passaggio avversario di ogni ticket cerca le condivisioni con grep (`??=`, cache, riuso tra mesh).
- **Riallineamento visibile.** Chi torna vede gli agenti saltare ai loro posti invece di camminarci. È la scelta di D3; R5 lo limita alle pause con eventi lunghe almeno 1 s.
- **Spazzino troppo zelante.** Un errore nel riconoscere i proprietari potrebbe chiudere un'esecuzione parallela: V4 lo prova con due esecuzioni vere.
- **Durata della suite.** Fino a circa 10 minuti (D8). Per i ritocchi si usano le fasi singole (`--only memory`, `--only late`), come prevede la lezione 5 della retro 01.
- **Il pannello browser dell'app** misura con il canvas a 0×0 se non è visibile: le misure 3D si fanno nel runner o con lo stage dimensionato a mano, come in questa spec.
