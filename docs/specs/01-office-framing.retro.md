# Spec 01 — Retro (SDD step 6)

| | |
|---|---|
| **Ciclo** | spec 01, "Inquadratura dell'ufficio v3 e cubi", dal 2026-10-12 al 2026-10-13 |
| **Branch** | `feat/office-framing`: 18 commit sopra `main` (`33d9361`) prima di questa retro, 19 con essa |
| **Esito** | A1–A11 verdi; QA visivo dell'utente superato per T5–T8 e per la code-review |

## 1. Il ciclo in numeri

| Voce | Valore |
|---|---|
| Sessioni di lavoro | 3, collegate da `HANDOFF.md` |
| Tempo dei commit | spec e ticket alle 21:42 del 12/10; T0–T8 fino alle 02:34; review dalle 09:54 alle 10:22 del 13/10 |
| Codice di produzione | 5 file in `public/`, +456 / −81 |
| Test | 9 file in `scripts/`, +1791: 13 casi in `world-test.js`, 130 controlli nel browser |
| Documenti | spec, ticket, report, review e questa retro, più 13 screenshot |
| Correzioni alla spec durante il ciclo | 9: S4.5 (T0), S2.1 (T3), S3.6 (T5), S3.7 e S4.6 (T6), S2.5 e S2.6 riviste (T7), S4.6 precisata (R1), tabella §4 (R7) |
| Difetti trovati | **in perimetro e corretti:** N1, N3, ⌂ annullato durante un focus (T4), R1, R2, R4, R5. **Fuori perimetro e annotati:** N2, N4, N5, N6, N7 |
| Pavimento sotto l'interfaccia | da 21,2% a 0% (1920×1080, LR); da 38,4% a 0% (1440×900, LR) |
| Cubi | da 5/5 casi di stress falliti a 0; da 1 anomalia e 314 effetti congelati per run a 0 |

**Quanto ha pesato ciascuna parte.** Il rapporto tra test e codice di produzione è circa 4 a 1. I test non sono un contorno: sono la parte che ha trovato i difetti. Nei QA registrati (T5–T8 e la review) l'utente ha **confermato** ogni passo senza segnalare difetti: tutti i difetti di questo ciclo sono venuti dalle misure.

## 2. Il commit iniziale `33d9361`

L'`HANDOFF.md` della prima fase descriveva il repo come "repo git inizializzato, **nessun commit**". Poco prima di aprire la spec 01, l'utente ha fatto il commit iniziale `33d9361` "prima fase" e l'ha pushato su `origin/main`:
- 44 file, +8824 righe;
- dentro c'è tutta la fase 1: server, motore, router, front-end, ufficio 3D e test.

Il branch `feat/office-framing` parte da lì, e da lì sono partite tutte le misure "Prima": T0, poi lo stesso runner rilanciato su `git archive 33d9361` in T8.

**Tre conseguenze da sistemare:**
1. **La frase "nessun commit" non è più vera.** È ancora scritta nell'`HANDOFF.md` committato dentro `33d9361`. La copia di lavoro è già corretta, ma su `origin/main` resta la versione vecchia.
2. **`HANDOFF.md` è tracciato da git, mentre la regola di lavoro dice di non committarlo.** È entrato in git con `33d9361`, quindi `git status` lo mostra sempre come modificato, e un `git commit -a` lo includerebbe. Serve una decisione dell'utente (sezione 6).
3. **`33d9361` è un commit unico.** La fase 1 non ha una storia granulare: `git blame` e `git log` sul codice della fase 1 portano tutti a "prima fase". La storia leggibile del progetto inizia con `8b29350`. È accettabile, ma va saputo quando si cerca l'origine di un difetto preesistente: N2, N4, N6 e N7 sono tutti in `33d9361`.

## 3. Cosa ha funzionato

### Il flusso SDD

- **Misurare prima di toccare il codice (T0).** La baseline ha dato numeri invece di impressioni (21% e 38% di pavimento coperto), ha riprodotto R1–R4 alla lettera e ha trovato N1 *prima* di implementare. N1 è diventato S4.5 e T1 l'ha coperto fin dall'inizio, invece di scoprirlo a fine ciclo.
- **Criteri di accettazione misurabili (A1–A11).** Ogni ticket aveva un "fatto quando" verificabile, e il report "Dopo" li ha chiusi uno per uno con lo stesso strumento del "Prima".
- **Decisioni lasciate all'utente, con le opzioni misurate:**
  - D1: ufficio sempre intero;
  - D2: 1920×1080 come riferimento;
  - soglia `far` a 0,55;
  - N4 con l'opzione 1;
  - R3 rimandato a N5;
  - R5 adottato.

  Nessuna di queste scelte è stata presa al posto dell'utente, e ognuna è arrivata con i numeri per decidere.
- **Perimetro tenuto (S6.3).** Cinque difetti preesistenti (N2, N4, N5, N6, N7) sono stati annotati con misura e proposta, senza allargare il branch. Il diff è rimasto leggibile: 456 righe di produzione.
- **Commit atomici e fermate dopo ogni step.** Ogni commit ha un messaggio che spiega il perché e riporta le misure prima/dopo. Ogni fermata ha permesso il QA dell'utente. Nella review l'ordine dei commit è stato cambiato una volta (R4 prima di R2) proprio per non lasciare mai `npm test` rosso tra un commit e l'altro.
- **Spec viva.** Le 9 correzioni sono annotate nel punto in cui valgono, con il ticket che le ha generate. La spec finale descrive il codice com'è, non com'era stato immaginato.

### La modalità "Ultra Code"

- **Leggere i sorgenti di three.js invece di supporre.** Quattro risultati del ciclo vengono da lì:
  - la trappola del limite di zoom: `OrbitControls.update()` lo applica a ogni frame (T7);
  - il pan "verso il punto afferrato" di `MapControls`, origine di N3 e R1;
  - la matematica di `setViewOffset` per la lente;
  - in r186, `setAnimationLoop` richiede il frame successivo *prima* di chiamare il loop. Senza questo dato R4 sarebbe stato classificato come più grave di quanto è.
- **"Dimostrare che i test sanno fallire".** Ogni test nuovo della review è stato visto fallire sul codice vecchio. Nella review questa abitudine ha anche salvato un test: con lo zoom interpolato in rapporto (R5), lo scenario della trappola a 2 frame non coglieva più la mutazione. Senza il controllo della mutazione il test sarebbe diventato vuoto in silenzio.
- **Misurare invece di stimare, anche nei dettagli:**
  - la soglia `far` è stata misurata (0,55) invece di ereditata (0,95), il che ha evitato di nascondere 8 etichette su 16;
  - l'instabilità di A6 è stata confermata ripetendo i giri, prima di toccare il test.
- **Un runner versionato (T8).** Con 130 controlli in circa 6 minuti, ogni correzione della review è stata verificata per intero. Senza runner la review avrebbe richiesto il QA manuale per ogni commit.

## 4. Cosa si può ottimizzare

1. **I test d'interazione fissavano il comportamento attuale invece dell'intenzione dell'utente.** Entrambi i difetti in perimetro sfuggiti fino alla review (R1, R2) stavano in aree coperte da test:
   - A7 "drag during an automatic re-frame" verificava proprio il richiamo di `MapControls`;
   - lo scenario della stanza apriva sempre il pannello destro prima del clic.

   **Azione:** scrivere le attese d'interazione dal punto di vista dell'utente ("la vista si sposta di quanto si sposta il puntatore") e coprirle con una matrice, come si è fatto per A1 con le risoluzioni. La matrice incrocia ogni ingresso (clic, trascinamento, rotella, etichetta, roster, minimappa) con ogni stato (pannelli, modalità automatica o manuale, durante o dopo un movimento).
2. **I difetti sfuggiti nascono tutti nel ticket più interattivo (T6).** S3.7 ha reso difettoso un ordine di chiamate in `main.js` che prima era innocuo, e nessuno ha cercato gli altri chiamanti di `focusRoom`.

   **Azione:** quando un ticket cambia la semantica di una funzione, fare un passaggio "avversario" prima del commit, invece di aspettare lo Step 5:
   - elencare tutti i chiamanti (grep);
   - chiedersi "e se succede durante un'animazione?";
   - chiedersi "e se la precondizione è diversa?".
3. **Un "limite noto" va misurato, non solo descritto.** Il limite di T6 ("pressione tenuta, meno di 5 px") descriveva il caso minore. Misurato nella review, il caso tipico valeva fino a 687 px, ed era R1.

   **Azione:** un limite entra nel report solo con il caso peggiore misurato. Altrimenti è un'ipotesi, e va scritto come tale.
4. **Il runner del browser è arrivato tardi (T8).** Da T0 a T7 le verifiche erano snippet da console, poi convertiti in file. Il pannello browser dell'app (476 px, spesso nascosto, senza `requestAnimationFrame` né `ResizeObserver`) ha costretto a pompe manuali.

   **Azione:** nel prossimo ciclo il runner headless nasce a T0. Il pannello dell'app serve solo per guardare, con `resize_window` a 1920×1080 per i casi con i pannelli.
5. **Costo dei test.** Nella review sono state lanciate 8 suite complete da circa 6 minuti, quasi 50 minuti, e circa 2,5 minuti di ciascuna sono la missione demo.

   **Azione:** dividere le verifiche in livelli:
   - `--only checks` (circa 1 minuto) per le correzioni di camera e input;
   - la suite completa quando cambiano cubi, eventi o `fx`, e sempre a fine step;
   - nessuna suite del browser per i commit di soli documenti, come già fatto in questo ciclo.

   Il runner accetta `--port`, quindi in teoria se ne possono lanciare due insieme. Non l'ho provato: in questo ciclo le suite sono sempre girate una alla volta, e la missione è sensibile al carico.
6. **Igiene del runner.** In questo ciclo il runner ha lasciato processi Edge aperti due volte: 85 processi in T8, 9 nella riproduzione di R8. In più c'è stata un'instabilità da occlusione (A6). Tutte e tre le cose sono corrette.

   **Azione:** a fine suite contare i processi `msedge.exe` con `agent-world-profile` e far fallire la suite se ne restano. Così la regola è nel codice, non nella memoria.
7. **Ambiente di prova legato alla sessione.** `.claude/launch.json` punta a un file nello scratchpad della sessione, quindi ogni sessione nuova deve ricrearlo.

   **Azione:** tenere `preview.env` dentro `.claude/` (non tracciata), con `AGENT_WORLD_HOME` in una cartella fissa di `%TEMP%`. Non dipende più dalla sessione.
8. **La memoria tra sessioni ha retto grazie all'handoff, non a claude-mem.** L'observer di claude-mem era disconnesso da circa 37 ore. Il contesto è passato tutto da `HANDOFF.md` e da `work_state`: la disciplina dell'handoff ha funzionato, ma il file è cresciuto fino a oltre 250 righe.

   **Azione:**
   - `HANDOFF.md` tiene solo stato, prossimi passi e regole;
   - la storia dei ticket resta nei documenti della spec, a cui l'handoff rimanda;
   - claude-mem va ricollegato con `/login`.
9. **La spec era troppo precisa sui nomi e troppo vaga sulle interazioni.** La tabella §4 nominava `VIEW_DIR` e `VIEW_DIST`, che non sono mai esistiti (R7). S3.7 e S4.6 sono nate solo in T6.

   **Azione:** nello step To-spec, lasciare i nomi dell'API ai ticket e descrivere invece la matrice delle interazioni attese (punto 1).
10. **Calibrare la profondità di "Ultra Code".** Il ragionamento profondo ha reso molto su matematica e input, meno sui commit di documenti e strumenti, dove ha prodotto testo più lungo del necessario. Il report della spec supera le 500 righe.

    **Azione:** profondità massima dove il rischio è alto (matematica, input, stato condiviso), passaggio leggero sul resto, e un riassunto di 5 righe in testa a ogni documento lungo.

## 5. Ticket aperti

| Ticket | Cosa | Dimensione | Proposta di raggruppamento |
|---|---|---|---|
| N6 | `switchTab()` non aggiorna `body.right-closed`: roster e minimappa finiscono sotto il pannello destro | piccola | spec 02, "sovrapposizioni dell'interfaccia" |
| N4 | etichette delle stanze sul bordo anteriore (opzione 1, già decisa) | media | spec 02 |
| N5 | risorse GPU non liberate: effetti, card, cubi | media | spec 03, "sessioni lunghe" |
| N2 | client in ritardo con la scheda nascosta: cubi affondati, sub-agenti rimossi presto | grande | spec 03 |
| N7 | cartelle temporanee di `smoke.js` e `flows-test.js` non rimosse | piccola | insieme al primo ciclo che tocca gli strumenti |

C'è poi il backlog precedente alla spec 01, nell'handoff: stile v3, repo e skill, "Claude setup", test con modelli veri, nomi dei modelli, idee.

## 6. Decisioni per l'utente

1. **Push.**
   - Gli 8 commit della review e questa retro sono solo in locale. Il push porterebbe `origin/feat/office-framing` da `da55a4d` a `HEAD`.
   - Poi va scelto se aprire una pull request verso `main` o fare il merge direttamente.
2. **`HANDOFF.md` e git.** Due strade:
   - (a) toglierlo dal tracking con `git rm --cached HANDOFF.md`, più una riga in `.gitignore`. La copia locale resta, e la regola "non si committa" diventa vera. Su `main` la versione vecchia sparisce al merge;
   - (b) committarlo di proposito a fine ciclo, come documento di stato del progetto. In quel caso la regola va cambiata.
3. **`.claude/` in `.gitignore`.** Contiene solo configurazione locale (`launch.json`) ed è sempre "non tracciata" in `git status`.
