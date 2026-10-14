# Spec 02 — Retro (SDD step 6)

| | |
|---|---|
| **Ciclo** | spec 02, "Sovrapposizioni dell'interfaccia", 2026-10-13 |
| **Branch** | `feat/ui-overlaps`: 13 commit sopra `main` (`0914146`) prima di questa retro, 14 con essa. Niente è su `origin` |
| **Esito** | V1–V13 verdi; le due eccezioni di D8 come previste; QA visivo superato su T1, T2, T3 e T4; review senza difetti nel codice dell'app |

**In breve**
1. Il pattern dei **rossi attesi** (`known-red.json`) ha fatto quello che doveva: 42 rossi spiegati a T0, chiusi ticket per ticket (24, 9, 6, 3), mai un commit con la suite rossa. Ha anche reso visibile ogni rosso nuovo.
2. **Ogni difetto è venuto dalle misure, nessuno dal QA:** Q4, Q5 e i clic sul corpo di lead e worker (E5) prima di scrivere codice, Q6 in T2. Il codice dell'app cambia di sole 48 righe; i test di 1140.
3. **La scelta di D8** è stata presa su numeri e screenshot di tre varianti. Il calcolo era validato al pixel contro il disegno vero, e T3 ha riprodotto esattamente quello che T0 aveva previsto.
4. **Il limite più serio del ciclo** sta negli strumenti, non nel codice. Le sonde usa e getta della review, interrotte da un limite di tempo della shell, hanno lasciato 41 processi Edge. Sono stati chiusi, ma la regola di V12 valeva solo per il runner.
5. **Azioni per il prossimo ciclo** (§4): un modulo condiviso per avviare e chiudere il browser, usato da runner e sonde; il caso peggiore dei contenuti scritto nella spec; le misure chiamate per quello che misurano; i testi lunghi scritti con un file invece che con il heredoc della shell.

## 1. Il ciclo in numeri

| Voce | Valore |
|---|---|
| Sessioni di lavoro | 2: la prima per il Plan, la seconda dalla spec alla retro |
| Commit | 14 con la retro: 6 di produzione (T1–T4), 1 di test (T0), 7 di documenti (compreso il commento di R7) |
| Codice di produzione | 3 file in `public/`, +48 / −21 |
| Test | 6 file in `scripts/`, +1140 / −61. Verifiche nel browser da 130 a 226; 1604 casi della matrice dei pannelli e 180 stati delle etichette a ogni giro |
| Documenti | spec, ticket, report, review e questa retro; 24 screenshot |
| Correzioni alla spec durante il ciclo | 7: Q4 col contenuto reale, E5 ed E6 misurati (T0); D8 con le eccezioni; Q6 (T2); la scansione dell'inspector (T2); le verifiche di T3 e la deriva di E7 (T4), annotate nei ticket |
| Difetti in perimetro, corretti | N6, Q1, Q2, Q3, Q4, Q5, Q6, N4 (con E5 sul corpo di lead e worker), la rotella sopra le etichette (D7) |
| Fuori perimetro, annotati | N8, il pinch su touch screen sopra le etichette: ipotesi, non misurata |
| Rossi attesi | 42 a T0, 0 a T4 |
| Suite complete | 5, una per ticket compreso T0: tra 4 min 31 s e 6 min (con gli screenshot). Più circa 20 giri mirati con `--only` |
| QA dell'utente | 4 giri (T1–T4), nessun difetto segnalato |

**Tempi** (orari dei commit nella seconda sessione, quindi comprese le attese per il tuo QA):

| Passo | Da | A | Durata |
|---|---|---|---|
| T0: runner, baseline, varianti | 13:57 | 14:30 | 33 min, la parte più lunga |
| D8 nella spec, T1 | 14:30 | 14:40 | 10 min |
| T2 (Q6, poi la colonna) | 14:40 | 14:55 | 15 min |
| T3 | 14:55 | 15:09 | 14 min |
| T4 e report "Dopo" | 15:09 | 15:24 | 15 min |
| Code-review | 15:24 | 16:07 | 43 min, di cui circa 15 persi con le sonde bloccate (§3) |

Le fasi nuove del runner durano 55–68 s (`overlaps`) e 19–44 s (`labels`). Con gli screenshot `overlaps` sale a 126 s. La suite completa resta sotto i 6 minuti, come nella spec 01, con 96 verifiche in più. Non ho misurato da dove venga il tempo risparmiato; un candidato è il caricamento della pagina, che ora controlla ogni 100 ms invece di 200.

## 2. Le azioni della retro 01, applicate

| # | Azione della retro 01 | Com'è andata |
|---|---|---|
| 1 | Matrice ingresso × stato, attese scritte dal punto di vista dell'utente | Fatta nella spec. Ha guidato le fasi `overlaps` e `labels`; le passeggiate casuali hanno coperto gli ordini non previsti |
| 2 | Passaggio avversario prima del commit | In ogni commit di T1–T4, scritto nel messaggio. Ha trovato poco, perché le modifiche erano piccole; il valore è stato escludere |
| 3 | Un limite nel report solo con il caso peggiore misurato | Inspector a 193 px (il più stretto), scritta della bay al 26,68%, costo dell'inoltro al 95° percentile. Il pinch touch (N8) è scritto come ipotesi |
| 4 | Il runner nasce a T0 | Sì, e ha misurato le varianti prima di scegliere |
| 5 | Verifiche a livelli | `--only` per i ticket, la suite completa una volta per ticket; nessun browser per i commit di soli documenti |
| 6 | La suite fallisce se restano processi Edge | V12, vista fallire a T0 con 17 processi. Vale solo per il runner: vedi §3 |
| 7 | `preview.env` in `.claude/` | Fatto; `autoPort` perché la 4310 era occupata da un'altra chat |
| 8 | HANDOFF snello, la storia nei documenti | Da circa 235 a circa 170 righe |
| 9 | Nessun nome di API nei requisiti | Rispettato; i nomi sono nel §4 della spec e nei ticket |
| 10 | Profondità proporzionata al rischio, riassunto in testa | Riassunti di 5 righe in tutti i documenti; i commit di documenti senza browser |

## 3. Cosa ha funzionato, cosa no

### Il pattern dei rossi attesi

**Come funziona.** A T0 ogni verifica che falliva sul codice di oggi è stata spiegata con un difetto noto e segnata in `known-red.json` con il ticket che la chiude.

| Ticket | Rossi chiusi | Restanti |
|---|---|---|
| T0 | — | 42 |
| T1 | 24 | 18 |
| T2 | 9 | 9 |
| T3 | 6 | 3 |
| T4 | 3 | 0 |

**Cosa ha dato:**
- **ogni verifica ha dimostrato di saper fallire** già alla baseline. Per quelle verdi dall'inizio sono servite mutazioni (gli ingombri congelati, l'ordine delle etichette al contrario, gli ingressi senza precondizione, la deriva di E7, la chiusura del browser saltata);
- **nessun commit ha lasciato la suite rossa**, a differenza di un approccio "test prima, correzione dopo" con i test committati in T0;
- **i segni non si dimenticano:** un segno che diventa verde fa fallire la suite, quindi ogni ticket ha dovuto togliere i propri nello stesso commit. Anche un segno che non corrisponde più a nessuna verifica fa fallire;
- **un rosso nuovo resta visibile.** Q6 è emerso in T2 come rosso non segnato, è stato corretto nello stesso ticket e non è mai stato aggiunto al file.

**Cosa non ha funzionato del tutto:**
- **attribuire i rossi è stato manuale.** Le passeggiate casuali riportavano solo il primo passo rosso, e per assegnarle a T1 o T2 è servito un secondo giro dopo averle cambiate perché riportassero tutti i passi rossi. Va fatto così da subito;
- **la granularità è una verifica per criterio e dimensione.** Quando una verifica è rossa per cause di due ticket, prende il ticket dell'ultima. Ha funzionato perché ho separato le verifiche con l'inspector da quelle senza; senza quella separazione, T1 non avrebbe potuto mostrare i suoi verdi.

**Verdetto:** da tenere per i prossimi cicli, con due ritocchi:
- le verifiche riportano tutti i casi rossi, non solo il primo;
- i segni iniziali si generano dal JSON della baseline, poi si rivedono a mano.

### Le misure al posto delle stime

- **D8.** Il calcolo delle varianti, validato contro le etichette disegnate (0,52 px) e contro le varianti disegnate dal CSS (0,81 px), ha permesso di scegliere su numeri e immagini. T3 ha riprodotto esattamente la previsione: 3 sub-agenti in 2 stati, 26,68%.
- **La review.** Le domande su `:has()` e sulla rotella hanno avuto risposte misurate, non opinioni. Una correzione plausibile, le variabili sui tre elementi, è stata misurata e scartata invece che applicata.
- **I difetti nuovi** (Q4, Q5, Q6, E5 sui corpi) li hanno trovati le misure, come nella spec 01; il QA ha confermato senza segnalazioni.

### Il limite: le sonde della review e i processi Edge rimasti

**Cosa è successo.**
- Per la review ho scritto due sonde usa e getta nella cartella temporanea: `perf-probe.mjs` e `wheel-regions.mjs`. Lanciano un server e un Edge headless.
- Tre giri sono stati interrotti: due dal limite di tempo della shell (`timeout 240` e `timeout 150`), uno a mano (`taskkill` sul processo node, dopo 8 minuti).
- Le sonde chiudevano il browser solo alla fine normale. Uccidere il processo node non chiude Edge, perché su Windows Edge passa il controllo a un altro processo, che non è figlio di quello lanciato: è la stessa causa documentata nel runner a T8 della spec 01.
- Risultato: **41 processi Edge** con un profilo `agent-world-profile` rimasti aperti.

**Come è stato scoperto e chiuso.**
- Li ho trovati controllando i processi a mano dopo l'interruzione, con la stessa query di V12. Il runner li avrebbe comunque segnalati come avviso al giro successivo, perché V12 annota i profili delle altre esecuzioni.
- Li ho chiusi tutti (0 rimasti, verificato), senza toccare il tuo server sulla 4300 né la 4310 dell'altra chat.
- **Costo:** circa 15 minuti della review e una misura da rifare (60 clic su `main`).

**Perché è successo.**
- La regola della retro 01 (azione 6) è entrata nel runner, non negli strumenti in generale. Le sonde hanno ricopiato la parte "avvia il browser" del runner, ma non la sua chiusura robusta (DevTools `Browser.close`, attesa, `taskkill` dell'albero del processo del browser vero).
- In più, i limiti di tempo della shell uccidono il processo senza dargli modo di chiudere.

**Azione:**
- estrarre da `scripts/browser-test.js` un modulo (`scripts/browser/headless.js`) con avvio, chiusura e controllo dei processi rimasti, usato sia dal runner sia da ogni sonda;
- far chiudere il browser alla sonda anche su `SIGINT`/`SIGTERM` e in un `finally`;
- una misura che vale la pena di riportare diventa una fase opzionale del runner (per esempio `--only perf`), fuori dalla suite predefinita, così è anche riproducibile dopo la sessione. Le sonde di questa review vivevano nella cartella temporanea della sessione, che sparirà: i loro numeri restano solo nel report.

### Altri attriti

- **Il contenuto di prova all'inizio era troppo gentile.** L'inspector "peggiore" di T0 aveva testi con spazi e trattini, e il browser andava a capo lì. Q6 è emerso solo in T2, quando hai chiesto una verifica spietata di P2. **Azione:** nella spec, accanto alle dimensioni della matrice, va scritto il caso peggiore dei contenuti (stringhe senza punti di a capo, lunghezze massime).
- **Una misura legata al tempo.** La colonna "E1 ordine di oggi" della tabella delle varianti, dopo T3, misurava l'ordine nuovo dell'app; l'ho rinominata. **Azione:** le misure si chiamano per quello che misurano, non per "oggi".
- **La spec misurata su contenuti sintetici.** Q4 era 42 × 96 px nella spec e 42 × 46 con il contenuto reale. **Azione:** si misura con il contenuto reale; se si usa un contenuto sintetico, lo si scrive.
- **Il heredoc della shell.** Tre comandi sono falliti per apostrofi e backtick dentro testi lunghi (report, script di modifica). **Azione:** per i testi lunghi un file scritto con lo strumento di scrittura e applicato da uno script, come ho fatto dopo.
- **Una guardia poco portabile.** La copertura della scritta della bay (26,68% contro un limite del 27%) dipende dal font. Oggi la suite gira solo qui; su un'altra macchina va ritarata.

## 4. Azioni per il prossimo ciclo

1. **Modulo condiviso per il browser headless** (avvio, chiusura robusta, processi rimasti), usato dal runner e da ogni sonda. Le misure da riportare diventano fasi opzionali del runner. → ticket **N9**.
2. **Il caso peggiore dei contenuti** scritto nella spec, accanto alla matrice delle dimensioni.
3. **Le verifiche riportano tutti i casi rossi**; i segni dei rossi attesi si generano dal JSON della baseline.
4. **Le misure si chiamano per quello che misurano**, e si fanno con contenuti reali.
5. **I testi lunghi si scrivono con un file**, non con il heredoc della shell.
6. **Si tengono:** i rossi attesi, la validazione al pixel di un modello prima di usarlo per decidere, la fermata con i numeri per ogni decisione.

## 5. Ticket aperti

| Ticket | Cosa | Dimensione | Nota |
|---|---|---|---|
| N5 | risorse GPU non liberate: effetti, card, cubi | media | spec 03 proposta, con N2 |
| N2 | client in ritardo con la scheda nascosta | grande | spec 03 |
| N7 | cartelle temporanee di `smoke.js` e `flows-test.js` | piccola | insieme al primo ciclo che tocca gli strumenti |
| N8 | pinch su touch screen sopra le etichette | piccola | ipotesi da misurare (eventi touch via DevTools) |
| N9 | modulo condiviso per il browser headless; sonde come fasi opzionali | piccola | nasce da questa retro; si lega bene a N7 |

C'è poi il backlog precedente alla spec 01, nell'handoff.

## 6. Decisione per te

**Push e merge.** Il branch `feat/ui-overlaps` ha 14 commit sopra `main` e non esiste su `origin`. Due strade:
- **(a)** push del branch e pull request verso `main`;
- **(b)** merge diretto in `main` (fast-forward, perché `main` non si è mosso da `0914146`) e push di `main`.

Il push apre la finestra "Select an account" di Git Credential Manager: lo lancio in background e ti avviso quando aspetta la tua scelta.
