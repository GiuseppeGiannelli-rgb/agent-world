> **Congelata** (2026-10-13): sostituita dalla Spec 04 (backend FastAPI+Rust). Nessuna nuova modifica attesa qui.

# Ticket — Spec 03, memoria e stabilità delle sessioni lunghe

Riferimento: [03-memory-stability.md](03-memory-stability.md). Gli ID H\*, C\*, M\*, R\*, V\* e D\* rimandano alla spec.

**In breve**
1. **T1 e T2** mettono in sicurezza gli strumenti: un modulo per il browser, cartelle temporanee con un proprietario, uno spazzino degli orfani, `temp-test.js` in `npm test`. Ogni test si vede prima fallire sul codice di oggi, poi si corregge, nello stesso commit.
2. **T3** costruisce le verifiche dell'app (`memory`, `late`, la memoria di `run`, `soak`), misura la baseline e **genera in automatico** i segni di `known-red.json` dal JSON della baseline, con uno script e una tabella di regole. Poi ci si ferma perché tu riveda i rossi.
3. **T4–T7** chiudono N5 per gruppi di fonti; **T8–T9** chiudono N2; **T10** è la verifica finale con il `soak` e il tuo QA, Ctrl+C compreso (D11).
4. Due precisioni rispetto alla spec, emerse leggendo il codice per i ticket: **M3 si chiude a T6**, non a T7 (in una missione non si ricostruisce l'ufficio); **una fonte nuova**, le particelle del Brain, che liberano la geometria ma non il materiale (`brainParticles`, `office.js:442`): va in T4.
5. **D10** (client lento senza pause) diventa il ticket futuro **N10**, fuori da questo ciclo.

**Ordine:** T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9 → T10 (D1).

**Regole valide per ogni ticket**
- **Chiusura e fermata.** Un ticket si chiude quando i suoi criteri sono verdi; poi ci si ferma e si aspetta il tuo feedback. Il QA visivo lo fai tu, a 1920×1080.
- **Rossi attesi.** Da T3 in poi ogni ticket toglie da `scripts/browser/known-red.json` le proprie voci, nello stesso commit. Dopo T3 non se ne aggiungono: un rosso nuovo è un difetto nuovo, e mi fermo a segnalarlo.
- **Test che sanno fallire.** T1 e T2: prima il test, eseguito sul codice di oggi e visto rosso (l'output va nel messaggio di commit), poi la correzione. Da T3: i rossi della baseline sono la prova; per le verifiche verdi dall'inizio c'è una mutazione permanente.
- **Passaggio avversario** (retro 01, lezione 3) prima di ogni commit che cambia la semantica di una funzione: tutti i chiamanti con grep, "e se succede durante un'animazione?", "e se la precondizione è diversa?". L'esito va nel messaggio di commit.
- **Verifiche a livelli** (retro 01, lezione 5): `node --check` e `npm test`; nel browser le fasi toccate, con `--only`; la suite completa a T3 e a T10, e quando un ticket cambia cubi, eventi o `fx`; nessun browser per i commit di soli documenti.
- **Processi e cartelle.** Ogni sonda usa il modulo di T1, anche quelle usa e getta (retro 02, azione 1). Dopo ogni giro interrotto: `npm run sweep`.
- **Commit.** Un commit atomico per ticket, o per correzione. Messaggi in inglese, documenti in italiano. Nessun push senza il tuo via libera. I testi lunghi si scrivono in un file, non con il heredoc della shell (retro 02, azione 5).
- **Porte.** 4300 (il tuo server), 3939 e 4310 (altre sessioni) non si toccano. Il server di prova usa `autoPort`.

| Ticket | Titolo | Spec | Dimensione | Dipende da |
|---|---|---|---|---|
| T1 | N9: modulo del browser, cartelle con proprietario, spazzino, fase `hygiene` | §4.1, H1–H6, V1–V6 | M | — |
| T2 | N7: cartelle dei test e `temp-test.js` | §4.2, C1–C3, V7 | S | T1 |
| T3 | Baseline dell'app: fasi `memory`, `late`, `soak`, memoria di `run`; segni generati | §4.6, V8–V14 | L | T1 |
| T4 | N5, effetti: `dispose.js`, risorse condivise, `ring`, `beam`, particelle del Brain | §4.3, M1, M2 | S | T3 |
| T5 | N5, card e cubi | §4.3, M1 | S | T4 |
| T6 | N5, sub-agenti; M3 verde | §4.3, M1, M3, V9 | S | T5 |
| T7 | N5, ricostruzione dell'ufficio (D2) | §4.3, M1 | S | T6 |
| T8 | N2, ordine degli eventi: R1, R2 | §4.4, V11, V12 | M | T3 |
| T9 | N2, riallineamento: R3–R6 | §4.5, V13, V14 | M | T8 |
| T10 | Verifica finale, `soak`, report "Dopo", QA | V1–V15 | M | T1–T9 |

---

## T1 — N9: il modulo del browser e lo spazzino

**Obiettivo:** un solo punto che avvia e chiude il browser, e nessun processo o profilo che sopravviva a uno strumento, comunque finisca.

**File:**
- nuovi: `scripts/browser/headless.js`, `scripts/lib/temp.js`, `scripts/browser/probe.js` (la sonda di prova della fase `hygiene`);
- `scripts/browser-test.js`, `package.json` (`"sweep": "node scripts/browser/headless.js --sweep"`).

Nessun file in `public/` cambia.

**Attività**
1. **Prima il test, sul codice di oggi.** La fase `hygiene` del runner (punto 5) gira prima di ogni altra modifica, con una sonda che ricopia l'avvio di oggi. Atteso: rossa, con 16 processi Edge e il profilo rimasti dopo `taskkill /F`, come nel §1.2 della spec. L'output va nel messaggio di commit.
2. **`scripts/lib/temp.js`:**
   - `ownedDir(tool)`: `mkdtempSync(join(tmpdir(), \`agent-world-${tool}-${process.pid}-\`))`, registrata per i gestori di uscita;
   - `removeDir(dir)`: i tentativi di oggi del runner (40 × 500 ms), poi un avviso con il codice d'errore;
   - `ownerOf(name)`: il PID dal nome, con `^agent-world-([a-z]+)-(\d+)-[A-Za-z0-9]{6}$`; `null` per i nomi senza PID (`agent-world-preview` compresa);
   - `sweepDirs({ legacy })`: rimuove le cartelle con un proprietario morto (`process.kill(pid, 0)` lancia `ESRCH`); con `legacy` anche i nomi vecchi senza PID (`agent-world-(profile|browser|smoke|flows)-XXXXXX`, `aw-XXXXXX`) che nessun processo usa. Restituisce `{ removed: [{ dir, mb }] }`;
   - `onExit(fn)`: registra una pulizia per i gestori di uscita (punto 3).
3. **`scripts/browser/headless.js`:**
   - si spostano dal runner, senza cambiare comportamento: `findBrowser` (righe 89–102), `Cdp` (139–176), l'avvio (179–194), `closeBrowser` e `kill` (200–229), `profileProcesses` (233–243), `leftovers` (247–254). `profileProcesses` riconosce anche i nomi con il PID;
   - `launch({ tool })`: spazza (punto 4), crea il profilo con `ownedDir('profile')`, avvia, registra il browser. Restituisce `{ exe, proc, profile, connect(), close() }`;
   - `close(browser)`: chiusura robusta, poi `leftovers`, poi `removeDir(profile)`. Restituisce `{ left, others }`;
   - **gestori di uscita**, installati una volta al primo `launch` o `ownedDir`: `SIGINT`, `SIGBREAK`, `SIGHUP`, `uncaughtException`, `unhandledRejection`. Chiudono i browser registrati (al massimo 5 s ciascuno, poi `taskkill /T /F`), rimuovono le cartelle registrate, escono con 130 o 1. Un secondo Ctrl+C durante la pulizia non la interrompe;
   - **CLI:** `--sweep` (con `--legacy` e `--dry-run`) stampa PID chiusi, cartelle rimosse e MB, ed esce con 0.
4. **Lo spazzino** (spec §4.1), in `sweep()`:
   1. cartelle `agent-world-profile-<pid>-*` con il proprietario morto;
   2. una ricerca dei processi (`profileProcesses`); orfani sono i processi che nominano un profilo con il proprietario morto, oppure un profilo con PID che non esiste più su disco;
   3. per ogni profilo orfano: `taskkill /T /F` sul processo principale (quello senza `--type=`), poi i rimasti uno per uno, poi `removeDir`;
   4. `sweepDirs()`.

   Non chiude mai un processo che non nomina `agent-world-profile-` nella riga di comando (H5): la regola è nel codice e nella verifica.
5. **Il runner:**
   - importa `headless.js` e `temp.js`; la home del server diventa `ownedDir('browser')`;
   - il `finally` usa `close()`; la verifica di oggi ("no browser process left with this run's profile") resta, e si aggiunge "no folder left by this run" (V2), controllata dopo la rimozione;
   - **fase `hygiene`** (prima di `views`, nella suite di base, al massimo 30 s), con la sonda `probe.js` (avvia il browser con `launch`, carica `about:blank`, stampa il suo profilo e aspetta):
     - `H4 a probe killed with taskkill /F is swept at the next start`: avvia la sonda A, la uccide con `taskkill /F`, conta i processi rimasti (devono essercene, se no il caso non è stato provato: lo dice), chiama `sweep()`, poi 0 processi e 0 cartelle di A;
     - `H5 a live run is left alone`: con la sonda B viva e il browser del runner stesso vivo, `sweep()` non tocca nessuno dei loro processi né delle loro cartelle; ogni PID chiuso dallo spazzino aveva un profilo con il proprietario morto; `agent-world-preview`, se c'è, resta;
     - `H3 the exit handler closes the browser` (la logica, non il Ctrl+C vero, che si prova a mano): la sonda C con `--emit SIGINT` chiama `process.emit('SIGINT')` dopo 1,5 s; atteso: uscita 130, 0 processi, 0 cartelle;
     - `H6 the sweep takes at most 2 s and reports what it did`: tempo di `sweep()` con un orfano; il comando `npm run sweep` esce con 0 e stampa le righe attese;
     - `H1 one module launches the browser`: in `scripts/` la stringa `--remote-debugging-port` compare solo in `headless.js`.
   - `phaseOf` riconosce `H\d` come fase `hygiene`.
6. **Passaggio avversario:**
   - due runner in parallelo su porte diverse: nessuno dei due spazza l'altro (V4);
   - lo spazzino che parte mentre un'altra esecuzione ha appena creato il profilo e non ha ancora avviato il browser: il proprietario è vivo, quindi niente;
   - PID riusato: errore dalla parte sicura (spec §4.1);
   - `--root` su un altro checkout: il modulo è di questo checkout, la home pure.
7. **Verifiche:** `node --check` sui file nuovi; `npm test`; `node scripts/browser-test.js --only hygiene,checks`; la suite completa una volta, perché il runner cambia.

*(Precisato in T1.)*
- **I gestori di uscita stanno in `scripts/lib/temp.js`**, non in `headless.js`, così valgono anche per gli script senza browser (T2). `headless.js` registra la chiusura del browser con `onExit()`; le pulizie girano dalla più recente, poi si rimuovono le cartelle.
- **H6 alla prima prova era rosso: 2,45 s.** La seconda ricerca dei processi e l'attesa dopo la chiusura costavano più di un secondo. Ora c'è una sola chiamata `taskkill /T /F` con tutti i PID della prima ricerca, e la rimozione del profilo riprova finché gli ultimi processi escono: 1,22–1,23 s con 16 processi chiusi.
- **H3 automatico** con `process.emit('SIGINT')` nella sonda; il Ctrl+C vero resta il tuo QA (V6).
- **La sonda chiude il suo browser anche quando si chiude il suo stdin**, cioè se il runner che l'ha lanciata muore: una sonda non resta mai orfana del runner.
- **Il server di un test ucciso muore con lui** (misurato: smoke ucciso con `taskkill /F`, porta 4399 chiusa entro 1,5 s; la pipe del suo stdout si chiude). Lo spazzino quindi non cerca server orfani; C3 lo controlla a ogni giro.
- **Prova "prima"**, con una modifica temporanea mai committata (nessuno spazzino all'avvio, nessun gestore): H4 rosso (16 processi rimasti anche dopo l'avvio successivo, profilo rimasto), H3 rosso (sonda ancora viva dopo 20 s, 11 processi). Con il codice vero: verdi, due giri di fila; un terzo giro su `--port 4396`, in parallelo alla suite completa, verde e senza toccarla.

**Commit:** `feat(test): one module launches and closes the headless browser, and sweeps orphans (T1)`

**Fatto quando:** V1–V5 verdi; la fase `hygiene` vista rossa sul codice di oggi e verde dopo; suite completa verde.

**Fermata e QA (V6, D11):** in un terminale lanci `npm run test:browser`, premi Ctrl+C a metà, poi `npm run sweep -- --dry-run`. Atteso: nessun processo né cartella da spazzare.

## T2 — N7: le cartelle dei test

**File:** `scripts/smoke.js`, `scripts/flows-test.js`, `scripts/router-test.js`, nuovo `scripts/temp-test.js`, `package.json` (`test` aggiunge `node scripts/temp-test.js` in fondo).

**Attività**
1. **Prima il test, sul codice di oggi.** `temp-test.js` (punto 3) gira sugli script di oggi. Atteso rosso: 3 cartelle lasciate a giro, la cartella di uno smoke fallito ancora lì.
2. **Gli script:**
   - prendono la cartella da `ownedDir('smoke' | 'flows' | 'router')` e chiamano `sweepDirs()` all'avvio;
   - `smoke.js`: `fail()` diventa asincrona: chiude il server, **aspetta l'evento `exit`**, rimuove la home, poi esce con 1; il percorso normale fa lo stesso prima di `OK`;
   - `flows-test.js`: nel `finally`, dopo `server.kill()`, aspetta `exit` e rimuove la home;
   - `router-test.js`: rimuove `dataDir` in fondo, anche con un'asserzione fallita (`try`/`finally`);
   - **una variabile solo per i test**, `AW_TEST_FAIL`: `start` fa fallire lo script subito dopo l'avvio del server; `server` uccide il server subito dopo l'avvio, come un crash. Il commento in testa la documenta.
3. **`scripts/temp-test.js`**, ultimo script di `npm test`:
   - `C1 the scripts before left no folder`: nessuna cartella `agent-world-*` con un proprietario morto;
   - `C1 a failing smoke cleans up` e `C1 a failing flows test cleans up`: con `AW_TEST_FAIL=start` e poi `=server`, lo script esce con 1 e la sua cartella non c'è più;
   - `C3 a killed smoke is swept`: lancia `smoke.js`, lo uccide con `taskkill /F` appena la cartella esiste, controlla che resti, chiama `sweepDirs()`, controlla che sia sparita;
   - `C2 a live owner is left alone`: una cartella propria resta dopo `sweepDirs()`, poi la rimuove.
4. **Passaggio avversario:** `npm test` lanciato due volte in parallelo (porte fisse 4398 e 4399: il secondo fallisce sull'avvio del server, ma non deve cancellare le cartelle del primo); `AW_TEST_FAIL` non letto da nessun file in `server/` o `public/` (grep).
5. **Verifiche:** `npm test` (atteso circa 35 s, D9); `node scripts/browser-test.js --only hygiene`.

*(Precisato in T2.)*
- **`router-test.js` non ha un `try`/`finally`:** un'asserzione fallita al livello più alto del modulo arriva al gestore `uncaughtException` di `temp.js` (misurato: sia un `throw` sia un `await` rifiutato al livello più alto), che rimuove la cartella prima di uscire con 1.
- **C3 usa come "prossimo avvio" `router-test.js`**, il test più rapido, che chiama `sweepDirs()` all'avvio come gli altri; C3 controlla anche che il server dello smoke ucciso non risponda più sulla 4399.
- **Prova "prima"** (gli script di oggi messi da parte con `git stash`): 7 rossi su 8. Gli script ignorano `AW_TEST_FAIL`, escono con 0 e lasciano la cartella (4 casi); il nome non ha il proprietario; lo smoke ucciso lascia la cartella anche dopo il test successivo; la cartella che `npm test` aveva lasciato prima. Poi `npm run sweep -- --legacy` ha tolto i 7 resti (5,6 MB), lasciando le cartelle vive della suite completa che girava accanto.
- **Dopo:** `temp-test.js` verde in 12 s; `npm test` verde tre volte di fila, 35 s ciascuna; in `%TEMP%` solo `agent-world-preview`. Due smoke in parallelo sulla stessa porta: il secondo esce con 1 ("the server exited before it was ready") senza toccare la cartella del primo, che finisce OK.
- **Fuori perimetro, annotato come N11:** `smoke.js` e `flows-test.js` tolgono le chiavi `*_API_KEY` dall'ambiente con `delete`, quindi `server/env.js` le riempirebbe da `.env` se ci fossero. Il runner fa bene (le imposta a `""`). Oggi `.env` imposta solo `PORT`, quindi non ha effetto.

**Commit:** `fix(test): the tests remove their temp folders, also when they fail (T2)`

**Fatto quando:** V7 verde; `npm test` visto rosso sul codice di oggi e verde dopo; dopo tre `npm test` di fila, in `%TEMP%` c'è solo `agent-world-preview`.

## T3 — Baseline dell'app e rossi attesi generati

**Obiettivo:** ogni requisito di N5 e N2 diventa una verifica che oggi fallisce per il motivo giusto, e i segni di `known-red.json` si generano dal JSON della baseline, non a mano.

**File:**
- `scripts/browser-test.js`;
- nuovi: `scripts/browser/memory.js`, `scripts/browser/late.js`, `scripts/browser/mark-reds.js`, `scripts/browser/red-rules.json`, `docs/specs/03-memory-stability.report.md`;
- `scripts/browser/run-probe.js`, `scripts/browser/known-red.json`.

Nessun file in `public/` cambia.

### A. Infrastruttura del runner

1. Fasi predefinite: `hygiene,views,checks,cubes,input,overlaps,labels,memory,late,run`. `soak` solo con `--only soak` o `--soak K` (D5).
2. **Secondo server.** `startServer({ port, fast })`: la fase `late` ne avvia uno in modalità veloce sulla porta `PORT + 1`, con una home `ownedDir('browser')`, e lo chiude a fine fase.
3. **Seconda scheda.** `openPage(url)`: `Target.createTarget`, poi la connessione al suo endpoint; `closePage()` con `Target.closeTarget`. Serve a R3 (pagina caricata da zero) e al confronto del modello (punto D.6).
4. **`--no-marks`:** ignora `known-red.json`, per la baseline.
5. `phaseOf`: `M1`, `M2` → `memory`; `M3` → `run`; `M4` → `soak`; `R\d` → `late`.
6. **Ogni verifica riporta tutti i casi rossi** nei dati (retro 02, azione 3), con la loro descrizione.

### B. Fase `memory` (M1, M2)

Gira dentro `t.session`, a 1920×1080 con LR e la vista completa (⌂), quindi tutto l'ufficio è nel campo visivo. I frame disegnano davvero (il `render` della sessione si sostituisce con quello vero, per caricare le risorse sulla GPU). Durata attesa: al massimo 60 s.

1. **Il rilevatore** (`__checks.memory`):
   - `const THREE = await import('three')`: la stessa mappa di import dell'app, quindi lo stesso modulo;
   - avvolge `dispose` di `BufferGeometry`, `Material` e `Texture` e segna in una `WeakSet` ciò che viene liberato;
   - all'inizio di un percorso registra il prossimo `id` di ogni tipo (crea e libera un oggetto vuoto);
   - a ogni frame visita la scena e raccoglie geometrie, materiali e texture dei materiali con `id` maggiore;
   - alla fine: **perse** = raccolte, non più raggiungibili, non liberate, non condivise (`userData.shared`); **liberate in uso** = raggiungibili e liberate;
   - riporta anche `renderer.info.memory` e `info.programs.length` prima e dopo.
2. **Percorsi**, uno per verifica (nomi della spec, §3.3):

   | Verifica | Percorso | Oggi | Ticket |
   |---|---|---|---|
   | `M1 ring` | 50 anelli | rosso | T4 |
   | `M1 beam` | 50 fasci | rosso | T4 |
   | `M1 burst` | 50 burst | rosso (il suo anello) | T4 |
   | `M1 sparkle`, `M1 confetti` | 50 e 10 | verde | — |
   | `M1 brain particles` | 10 cambi del conteggio delle note (`setBrainCount`) | rosso (il materiale) | T4 |
   | `M1 flow` | 5 s con un team al lavoro | verde | — |
   | `M1 card removeCard`, `M1 card resetRun` | 20 card | rosso | T5 |
   | `M1 card refreshCard` | 20 cambi di stato | verde | — |
   | `M1 cube delivered`, `M1 cube sunk`, `M1 cube split`, `M1 cube resetRun` | 20 cubi | rosso | T5 |
   | `M1 sub-agent` | i 14 posti delle bay, creati e rimossi con `onSpawn` e `onDespawn` | rosso | T6 |
   | `M1 office rebuilt` | 3 ricostruzioni di `build()` (colore di un team), poi la configurazione originale | rosso | T7 |
   | `M2 nothing in use was freed` | dopo tutti i percorsi | verde (oggi non si libera nulla) | — |

3. **Mutazioni permanenti:**
   - `M1 the skipped dispose, put back on purpose, is caught`: `fx.sparkle` con un `dispose` che non libera; M1 deve fallire;
   - `M2 the shared material freed on purpose is caught`: si libera un materiale della cache `mat()` usato da un personaggio; M2 deve fallire, poi lo si ricrea con un `build()`.
4. **Alla fine** la pagina si ricarica: le fasi dopo partono pulite.

### C. Memoria della fase `run` (M3)

`runProbe.start()` registra `renderer.info` dopo 1 s di frame. `report()`, dopo lo smaltimento, chiama `agentWorld.resetRun(null)`, disegna 1 s e confronta. Verifica: `M3 a mission and the next resetRun leave GPU memory as before` (geometrie, texture, programmi identici). In più, `R1` e `R2` dalla missione a ritmo normale: affondamenti di task `done` e sub-agenti rimossi con passi in coda, con le chiavi dei cubi rimasti (la spec, §1.4, non le aveva).

### D. Fase `late` (R1–R6)

Pagina caricata dal server veloce; `wander` sospeso. Il mondo è disegnato da un timer della pagina (`frames(fps)`), che si può fermare (la pausa) e riprendere; finito il run, lo smaltimento si accelera con la pompa a 60 fps e il disegno sostituito, fino a code vuote o 120 s di mondo (che vanno nei dati). Durata attesa: al massimo 3 minuti.

1. **Missioni** (una missione veloce ciascuna):

   | Missione | Frame | Pause | Verifiche |
   |---|---|---|---|
   | A | 60 fps | nessuna | `R1 no done task sunk, 60 fps`, `R1 no cube left, 60 fps`, `R2 … 60 fps` |
   | B | 10 fps | nessuna | come A, a 10 fps |
   | C | 60 fps | 0,5 s a ogni momento | `R5 a short pause does not realign`; R1, R2 |
   | D | 60 fps | 2 s a ogni momento | `R3 <momento>` (equivalenza), `R4 <momento>`, `R6 <momento>` |
   | E | 60 fps | dal piano alla fine del run | `R3 end`, `R1 no cube left, pause to the end` |

   I momenti sono quelli del §3.4: `plan` (primo `onPlan`), `split` (primo `splitWs`), `delivery` (primo stato `delivering`), `despawn` (primo `onDespawn`), `end` (`onRunDone`). Ogni pausa comincia al primo evento del suo tipo dopo la ripresa precedente. Una verifica `R momenti provati` controlla che ogni momento sia stato provato davvero: uno saltato non passa in silenzio (come `inputs` nella spec 02).
2. **R3, equivalenza** (spec §4.6), per ogni pausa di D ed E:
   1. il timer della pagina si ferma;
   2. il runner aspetta 1,5 s di eventi, poi mette in pausa il run (`/api/runs/:id/pause`) e aspetta 1 s senza eventi;
   3. la pagina riprende i frame: con T9, qui avviene il riallineamento;
   4. dopo 2 frame, fotografia della pagina; poi `openPage` della stessa URL, caricamento, fotografia, `closePage`;
   5. confronto: attori (insieme, posizione ±0,05, posa, cubo in mano), cubi (chiave, proprietario, in mano o sulla scrivania), card (chiave, colonna, aspetto), effetti del mondo in corso (0), passi in coda (0);
   6. il run riprende.
3. **R4:** nessun effetto del mondo creato durante una pausa (`fx.add` avvolto; quelli della camera esclusi).
4. **R5, camera:** prima di una pausa di D, un focus su un agente avvia un movimento di camera; dopo il ritorno la camera arriva al suo obiettivo e `autoFrame` non cambia.
5. **R6:** nei 3 s dopo il ritorno, nessun volo su una card che non è più in `world.cards` e nessuna rimozione di un sub-agente che il server ha ancora.
6. **Confronto del modello** (spec §8), una volta per fase: con `openPage` in primo piano, la prima pagina diventa nascosta? Si registrano `visibilityState`, callback di rAF ed eventi SSE ricevuti in 10 s. Se rAF si ferma e gli eventi arrivano, il modello vale; se headless non nasconde la pagina, il report lo dice e il modello si appoggia alla misura del pannello (spec §1.5) e al tuo QA di T9. Se una pagina nascosta vera si comporta in modo diverso dal modello, **T3 si ferma lì**.
7. **Mutazione permanente** (verde dall'inizio): `R5 the realign forced on a short pause is caught`. Prima di T9 non c'è riallineamento da forzare: la mutazione nasce in T9, e qui si annota.

### E. Fase `soak` (M4, opzionale)

K missioni a ritmo normale (`--soak K`, 3 se omesso). Dopo ognuna: smaltimento, `resetRun(null)`, `HeapProfiler.collectGarbage`, poi `Performance.getMetrics` (`JSHeapUsedSize`, `Nodes`, `JSEventListeners`) e `renderer.info`. Verifiche `M4 …` dalla seconda missione: contatori identici; heap, nodi e listener entro la soglia. **La soglia si fissa qui:** almeno 10 volte sotto la crescita misurata oggi (spec §3.3). Si riportano anche fps e velocità del mondo (per N10).

### F. Inizializzazione della baseline e segni generati

1. **Baseline:** `node scripts/browser-test.js --only memory,late,run --no-marks --json docs/specs/img/03-baseline.json` su questo branch (il codice dell'app è ancora quello di `main`); poi `--only soak --soak 3 --no-marks --json …-soak.json`.
2. **Regole:** `scripts/browser/red-rules.json` è la tabella "verifica → ticket" del punto B.2 e della spec §5: `[{ "match": "^M1 (ring|beam|burst|brain particles)$", "ticket": "T4" }, …, { "match": "^M3 ", "ticket": "T6" }, { "match": "^R[12] ", "ticket": "T8" }, { "match": "^R[3-6] ", "ticket": "T9" }, { "match": "^M4 ", "ticket": "T10" }]`. Una verifica rossa per più cause prende il ticket dell'ultima che la chiude (regola della spec 02).
3. **`node scripts/browser/mark-reds.js <baseline.json> [altri.json]`:**
   - legge ogni risultato `{ fase: { verifica: { ok } } }`, prende i rossi;
   - assegna a ognuno il ticket della prima regola che corrisponde;
   - **un rosso senza regola è un difetto nuovo:** lo stampa come `UNEXPLAINED` con i suoi dati ed esce con 1, senza scrivere il file;
   - altrimenti scrive `known-red.json` (le voci delle fasi non lette restano, ordinate per chiave) e stampa la tabella "verifica → ticket → casi rossi", che va nel report;
   - con `--check` non scrive: confronta il file con quello che genererebbe ed esce con 1 se diversi (per rigenerare dopo un cambio delle regole).
4. **Revisione a mano:** ogni segno si spiega con i dati del rosso (quali percorsi, quali casi); i casi rossi di una verifica devono avere tutti la stessa causa, se no la verifica si divide.
5. **Dimostrazione:** la suite completa, con i segni, è verde con i soli rossi attesi; un segno tolto a mano fa fallire la sua verifica; un segno inventato fa fallire "the mark matches a check of this run" (già nel runner).

### G. Report "Prima"

`03-memory-stability.report.md`: riassunto di 5 righe; numeri di `memory` per fonte (devono ritrovare la spec §1.3, salvo le ripetizioni); `run` (M3, R1, R2 con le chiavi dei cubi rimasti); `late` per missione e momento (arretrato, smaltimento, affondamenti, uscite anticipate); confronto del modello; `soak` (crescita per missione, soglia scelta); la tabella dei segni; durata delle fasi.

**Commit:**
- `test(world): memory, late and soak phases, expected reds generated from the baseline (T3)`
- `docs(T3): baseline report`

**Fatto quando:** le fasi girano; ogni rosso è attribuito da una regola e rivisto; nessun `UNEXPLAINED`; il modello della pausa confrontato; la suite completa è verde con i soli rossi attesi; nessun file in `public/` è cambiato.

**Fermata:** rivedi i rossi, i numeri e la soglia del `soak`.

## T4 — N5, effetti

**File:** nuovo `public/js/world/dispose.js`; `public/js/world/fx.js`, `public/js/world/geo.js`, `public/js/world/world.js` (`flowGeo`), `public/js/world/office.js` (`brainParticles`), `scripts/browser/known-red.json`.

**Attività**
1. `dispose.js`: `disposeObject(root, { skip })` (spec §4.3), con un `Set` per liberare ogni risorsa una volta; le texture sono le proprietà dei materiali con `isTexture`; si saltano `userData.shared` e gli oggetti per cui `skip(o)` è vero.
2. Risorse condivise: `mat()` segna i materiali che crea (`userData.shared = true`); `flowGeo` idem.
3. `fx.ring`: `dispose` libera la mesh con `disposeObject`. `fx.beam`: libera `head` (con `glow`) e `line`.
4. `brainParticles`: libera anche il materiale delle particelle vecchie.
5. Passaggio avversario: chi usa `mat()` e `glow()` (grep): nessuno li libera; `Fx.retire` chiama `dispose` una volta sola (`DEAD`); un effetto ritirato prima del primo frame.
6. Verifiche: `npm test`; `--only memory,cubes,run`.

**Commit:** `fix(world): effects free their GPU resources (T4)`

**Fatto quando:** le voci di T4 sono verdi e tolte; M2 resta verde.

## T5 — N5, card e cubi

**File:** `public/js/world/world.js`, `scripts/browser/known-red.json`.

**Attività**
1. Card: `removeCard` e `resetRun` liberano mesh, materiale e texture.
2. Cubi: alla fine del volo di `deliverCube`, alla fine di `sinkCube` (e subito il materiale sostituito), sul cubo grande di `splitWs`, in `resetRun`.
3. Passaggio avversario: tutti i chiamanti (grep) di `removeCard`, `deliverCube`, `sinkCube`, `splitWs`, `resetRun`; un cubo in volo quando arriva `resetRun` (il volo è fermato da `toScene`); `cube-stress.js` (A9) che riusa cubi dopo una consegna.
4. Verifiche: `npm test`; `--only memory,cubes,run` (la fase `cubes` perché cambiano i cubi).

**Commit:** `fix(world): cards and cubes free their GPU resources (T5)`

**Fatto quando:** le voci di T5 verdi e tolte. **QA:** una missione a 1920×1080, card e cubi come prima.

## T6 — N5, sub-agenti; M3

**File:** `public/js/world/world.js`, `scripts/browser/known-red.json`.

**Attività**
1. `removeActor` libera la radice dell'attore con `disposeObject`, saltando i cubi (`userData.cube`) e le risorse condivise.
2. Passaggio avversario: un sub-agente che esce mentre porta un cubo (oggi `onDespawn` lo affonda prima; dopo T8 la regola cambia: il caso si riprova lì); `build()` che toglie attori (T7); la geometria degli occhi, comune ai due occhi.
3. Verifiche: `npm test`; `--only memory,labels,run` (`labels` riempie e svuota le bay).

**Commit:** `fix(world): a sub-agent that leaves frees its GPU resources (T6)`

**Fatto quando:** `M1 sub-agent` e `M3` verdi e tolti. *Precisione rispetto alla spec (V9 a T7):* M3 si chiude qui, perché una missione non ricostruisce l'ufficio. **QA:** bay piene e poi vuote.

## T7 — N5, ricostruzione dell'ufficio (D2)

**File:** `public/js/world/world.js`, `scripts/browser/known-red.json`.

**Attività**
1. `build()` libera il vecchio gruppo dell'ufficio e gli attori con `disposeObject`, saltando le risorse condivise che il nuovo ufficio riusa.
2. Passaggio avversario: i riferimenti che restano dopo la ricostruzione (`hub.stations`, `anim.ghosts`, `brainLabel`); `setTheme` subito dopo; una ricostruzione durante una missione (cubi e card restano: non stanno nel gruppo).
3. Verifiche: `npm test`; `--only memory,views,labels`.

**Commit:** `fix(world): rebuilding the office frees the old one (T7)`

**Fatto quando:** `M1 office rebuilt` verde e tolta; tutte le voci di N5 tolte. **QA:** cambio del colore di un team nelle impostazioni, ufficio ridisegnato.

## T8 — N2, ordine degli eventi (R1, R2)

**File:** `public/js/world/world.js`, `public/js/world/character.js` (se serve un passo di uscita), `scripts/browser/known-red.json`.

**Attività** (spec §4.4)
1. La consegna in coda porta la chiave del cubo (`deliver: key`). Il ramo `idle` di `applyState` e `onDespawn` non affondano un cubo con una consegna in coda nel suo proprietario.
2. `onDespawn` accoda l'uscita (effetti, rimpicciolimento, `removeActor`) dopo i passi dell'attore; niente più `setTimeout`.
3. Passaggio avversario (spec §4.4): tutti i chiamanti di `sinkCube` e `removeActor`; un sub-agente che esce portando un cubo; un `idle` con la consegna già in volo; un `delivering` senza `taskId`; `labels.js` che svuota le bay (ora l'uscita segue i frame).
4. Verifiche: `npm test`; `--only cubes,labels,late,run`.

**Commit:** `fix(world): a queued delivery is never sunk; sub-agents leave after their queue (T8)`

**Fatto quando:** le voci R1 e R2 verdi e tolte. **QA:** una missione a 1920×1080.

## T9 — N2, riallineamento (R3–R6)

**File:** `public/js/world/world.js`, `public/js/world/fx.js` (ritiro degli effetti tranne quelli della camera), `public/js/main.js` (`resync()`, il segno degli eventi in `handle()`), `scripts/browser/late.js`, `scripts/browser/known-red.json`.

**Attività** (spec §4.5)
1. In `frame()`: buco ≥ 1 s (D7) ed eventi arrivati nel frattempo → `onBehind()`.
2. `main.js`: `resync()` estratta da `es.onopen` e usata da entrambi; `world.onBehind = resync`.
3. Il riallineamento: effetti del mondo ritirati (non la camera), `applyState(a, true)`, sub-agenti allineati a `S.agents`, `syncRun` come all'avvio.
4. R4: con l'ultimo frame più vecchio di 1 s, i gestori non creano effetti.
5. R6: i `setTimeout` delle card e i passi in coda controllano che il loro oggetto esista ancora.
6. Nasce la mutazione `R5 the realign forced on a short pause is caught` (soglia forzata a 0,1 s).
7. Passaggio avversario (spec §4.5), più: le sessioni del runner (`t.session`) senza eventi non riallineano (`--only checks,labels` verdi).
8. Verifiche: `npm test`; `--only checks,labels,late,run`; la suite completa (cambiano eventi e `fx`).

**Commit:** `feat(world): back after a pause, the world shows the present at once (T9)`

**Fatto quando:** le voci di T9 verdi e tolte. **QA:** durante una missione nascondi la scheda per un minuto, poi torni: gli agenti sono già al loro posto, nessun replay.

## T10 — Verifica finale, `soak`, report "Dopo"

**Attività**
1. `npm test`, `node --check` sui moduli cambiati, suite completa: 0 errori; `known-red.json` contiene solo le voci `M4` se il `soak` non è ancora verde.
2. `--only soak --soak 3`: M4 verde, voci tolte; `known-red.json` vuoto (`{}`).
3. Report "Dopo": V1–V15 a confronto con il "Prima"; la spec viva con le precisioni dei ticket; `HANDOFF.md`; N10 annotato tra i ticket futuri.
4. **Il tuo QA a 1920×1080:** una missione intera; la scheda nascosta durante una missione; bay piene e vuote; un cambio di colore di un team; **Ctrl+C a metà di `npm run test:browser`** (V6, D11), poi `npm run sweep -- --dry-run` senza niente da spazzare.

**Commit:** `docs(T10): after report, spec as built`

**Fatto quando:** V1–V15 verdi, oppure ogni eccezione motivata e in evidenza, e il QA è superato.

---

Dopo T10: **step 5 (Code-review)** sul diff completo, poi **step 6 (Retro)**.

**Ticket futuro, fuori da questo ciclo (D10): N10 — client lento senza pause.** Con frame oltre i 50 ms il mondo resta indietro (al 78% dell'orologio nella missione 1 della spec). Proposta da valutare: un riallineamento anche quando l'arretrato supera una soglia di tempo di mondo. Il `soak` di T10 ne riporta la misura.
