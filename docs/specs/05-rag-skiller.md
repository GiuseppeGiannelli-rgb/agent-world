# Spec 05 — RAG ibrido, Skiller, download esterni

**In breve:**
1. **Fase 1 (sicurezza): fatta.** History ripulita e pushata, scansione dei segreti a ogni commit, `.gitignore` rinforzato.
2. **Fase 2 (snellimento): fatta.** Codice morto e dipendenze inutili tolti, suite browser 235/235.
3. **RAG ibrido: fatto.** BM25 fuso con la similarità del coseno tramite RRF, chunking semantico, embedding dei provider o vettori locali. La parte Rust è scritta ma **non compilata** su questa macchina.
4. **Skiller: scoperta e valutazione fatte.** Lavora sui soli metadati e non scarica nulla.
5. **Download esterni (`CUSTOM_DOWNLOAD_PATH`): non implementati.** Il §5 è la logica di sicurezza proposta, in attesa del via libera dell'utente.

## 1. RAG ibrido (fatto)

**Moduli e configurazione:**
- `backend/backend/embed.py`: embedder, vettori locali, chunking semantico.
- `backend/backend/search.py`: `cosine_top_k`, `rrf`, `HybridIndex`.
- `crates/aw_core`: `ngram_vector` e `cosine_top_k`.
- Configurazione `rag` in `config/default.json`.

**Modelli.** `rag.embeddings` è una lista ordinata, come una combo; si usa il primo provider pronto, attraverso il suo endpoint `/embeddings` compatibile OpenAI.
- Ogni indice usa un solo modello, e la query usa sempre quello dell'indice.
- Se quel modello smette di rispondere, il Brain ricostruisce i vettori con il primo modello che funziona.
- Senza provider pronti si usa `local/ngram`: hashing firmato (CRC-32) degli n-grammi di 3 e 4 caratteri dei token, in 256 dimensioni.

**Misure** (14/10/2026), da cui `rag.minCosine` = 0,25:

| Coppia | Coseno locale |
|---|---|
| varianti della stessa parola | 0,44–0,76 |
| stessa parola in lingue diverse, testi lunghi | circa 0,16 (debole) |
| 66 coppie senza relazione | massimo 0,241, p90 0,13 |

**Chunking semantico.**
1. Si divide in paragrafi; il titolo resta incollato al paragrafo che lo segue, e un paragrafo troppo lungo si taglia a fine frase.
2. Si uniscono i vicini finché il coseno con il centroide resta ≥ 0,5 e il chunk resta ≤ 1200 caratteri; un titolo apre sempre un chunk nuovo.
3. Ogni skill ha in più il chunk "nome: descrizione".

**Fusione.** RRF con k = 60 e pesi 1:1. I risultati portano `score`, `bm25` e `cosine`. Nelle missioni semplici le skill si scelgono ancora con la soglia BM25.

**Scostamenti:**
- `search()` del Brain e dello Skill Hub ora è asincrona, perché la query può richiedere una chiamata al provider; ho aggiornato tutti i chiamanti.
- `Brain.add` aggiunge la nota all'indice BM25 in modo incrementale; la vecchia ricostruzione completa costava 0,4–0,7 s a 5000 note.
- `summary()` delle skill ha la chiave nuova `vectors`.

**Verifiche:**
- `test_rag.py`: 17 test, visti rossi con 4 mutazioni.
- Parità Rust in `test_search_rust.py`: si salta finché `aw_core` non è compilato. L'algoritmo è verificato con un port bit a bit del CRC-32 (uguale a `zlib.crc32` su 5000 campioni, vettori identici).
- `npm test` verde.

## 2. Skiller (fatto, senza download)

**File e configurazione:** `backend/backend/skiller.py`, configurazione `skills.skiller`. Il ciclo parte dal lifespan (primo giro dopo 10 minuti, poi ogni 24 ore) e si spegne con `AGENT_WORLD_SKILLER=0`, che i test impostano sempre.

**Scoperta.**
- Fonti: l'API di ricerca GitHub e i link a github.com nei risultati della ricerca web.
- Esclude le repo già installate o elencate in `skills.repos` e quelle controllate da meno di 7 giorni.

**Valutazione, solo metadati** (scheda della repo, albero dei file, `package.json` / `pyproject.toml`, registri npm e PyPI).
- Punteggio: stelle fino a 40, recency fino a 25, issue/stelle fino a 15, licenza 10, `SKILL.md` 10.
- Gate, ognuno basta a scartare: archiviata, disattivata, fork, senza licenza, senza `SKILL.md`, descritta come deprecata, pacchetto deprecato, sotto `minStars`, push più vecchio di `maxDaysSinceCommit`.
- Approvata se non tocca nessun gate e ha almeno `minScore` (60) punti.

**API.** `GET /api/skills/skiller` (rapporto), `POST /api/skills/skiller/run` (giro subito).

**Verifiche.**
- `test_skiller.py`: 17 test, visti rossi con 4 mutazioni. Uno dimostra che si contattano solo host di metadati: niente archivi, niente clone.
- Prova reale (metadati GitHub, cartella temporanea): 6 repo valutate, 5 approvate.
  - `anthropics/skills` è scartata per "no license": l'API non dà una licenza a livello di repo.
  - Tra le approvate c'è una repo con 538 `SKILL.md`. Conta per il §5: niente progetti interi senza limiti.

## 3. Fase 1 e Fase 2 (riepilogo)

**Fase 1:**
- `git filter-repo` ha messo un'identità pseudonima su 54 commit, tolto `HANDOFF.md` da tutta la history e rimappato gli id citati nei documenti; poi il force push.
- `scripts/secret-scan.js` gira dagli hook `pre-commit` e `commit-msg`, e `npm run scan:secrets` controlla tutta la history.
- `.gitignore` rinforzato; `.gitattributes` tiene gli hook in LF.

**Fase 2:**
- tolti import inutilizzati e `roomAt()`;
- `browser-test.js` ora usa `demoEnv()`;
- `uvicorn[standard]` diventa `uvicorn` + `httptools` + `watchfiles`: via websockets, pyyaml e python-dotenv.

## 4. Decisioni aperte

| # | Domanda | Consiglio |
|---|---|---|
| D1 | Installazione delle repo approvate | in automatico solo per i proprietari in una allowlist (`skills.skiller.trustedOwners`); per gli altri serve l'approvazione dell'utente da API/UI |
| D2 | Gate della licenza (scarta `anthropics/skills`) | resta, ma con l'allowlist di D1 che lo scavalca |
| D3 | Cosa si estrae | solo le cartelle che contengono uno `SKILL.md`, non il progetto intero |
| D4 | `CUSTOM_DOWNLOAD_PATH` | nessun default: se non è impostato, i download sono spenti |

## 5. Download esterni: logica di sicurezza (proposta, da approvare)

**Minacce:**
- **Path traversal ("zip slip")**: voci come `../`, percorsi assoluti, `C:\`, UNC `\\server\share`, drive-relative `C:foo`.
- **Link** simbolici e hard link verso l'esterno.
- **Nomi speciali di Windows**: dispositivi riservati (`CON`, `NUL`, `COM1`…), alternate data stream (`file:stream`), punti e spazi finali.
- **Bombe di decompressione.**
- **Repo enormi.**
- **SSRF e redirect** verso host imprevisti.
- **Una configurazione pericolosa**, per esempio `CUSTOM_DOWNLOAD_PATH` su una cartella di sistema o sul repo stesso.
- **Prompt injection** nelle skill di terzi.

**Difese, in ordine:**

1. **La cartella di destinazione, controllata all'avvio.**
   - `CUSTOM_DOWNLOAD_PATH` dev'essere assoluto. Si risolve con `Path.resolve()`, poi si rifiuta se:
     - è una radice;
     - è la home stessa;
     - è una cartella di sistema (Windows, Program Files, `/etc`, `/usr`…);
     - sta dentro il repo, dentro `.git` o dentro `data/`;
     - è un symlink o una junction.
   - Il percorso risolto viene fissato e ricontrollato prima di ogni scrittura.
2. **La sorgente.**
   - Solo `https://github.com/<owner>/<repo>` con una regex stretta.
   - Il ramo si risolve in un **commit SHA** con l'API, e si scarica l'archivio di quel SHA da `codeload.github.com`.
   - Allowlist degli host: `api.github.com` e `codeload.github.com`. Solo HTTPS, redirect solo dentro l'allowlist.
   - Limite di dimensione sul flusso: 50 MB compressi, contati in streaming e non presi dall'header.
   - Timeout.
3. **Lo staging.**
   - Il download va in `CUSTOM_DOWNLOAD_PATH/.incoming/<casuale>`, sullo stesso volume per poter fare il rename atomico.
   - Il nome finale `<owner>-<repo>@<sha7>` lo genera il codice, filtrato su `[A-Za-z0-9._-]`; non lo decide mai l'archivio.
4. **Ogni voce dell'archivio si valida prima di scrivere.**
   - `\` vale come separatore. Si rifiutano:
     - i percorsi assoluti, i drive e gli UNC;
     - ogni componente `..`;
     - i caratteri NUL e i `:`;
     - i nomi riservati, con qualsiasi estensione;
     - i componenti che finiscono con un punto o uno spazio;
     - i percorsi oltre 240 caratteri.
   - **Il contenimento si controlla sul percorso risolto**: `target.resolve().is_relative_to(staging.resolve())`, confrontati con `os.path.normcase`. Mai con un prefisso di stringa, che lascerebbe passare `/dl/foo-evil` contro `/dl/foo`.
   - **Tar:** solo file regolari e cartelle, niente symlink, hard link, dispositivi o FIFO, più il filtro `data` di `tarfile` (PEP 706) come secondo livello. **Zip:** si rifiutano le voci marcate come symlink negli attributi Unix.
   - Si scrive con `open(target, "xb")`: creazione esclusiva, quindi niente sovrascritture e niente symlink seguiti. Non si conservano permessi, bit di esecuzione, proprietario o date.
   - **Limiti:** 5000 voci; 200 MB decompressi in tutto; 20 MB per file; rapporto di compressione massimo 100:1 per voce. Si contano copiando, non fidandosi degli header.
   - **Estrazione "solo skill"** (D3): solo le cartelle con uno `SKILL.md`.
5. **Dopo l'estrazione.**
   - **Non si esegue mai niente:** niente `npm install`, niente `setup.py`, niente script.
   - Rename atomico nella destinazione e reindicizzazione dello Skill Hub.
   - In `skiller.json` si registrano SHA, sha256 dell'archivio, numero di file e dimensione.
   - Il cestino di quarantena è `.incoming`, pulito a ogni avvio.
6. **Budget.** Al massimo 3 installazioni per giro e un tetto totale di disco per `CUSTOM_DOWNLOAD_PATH` (2 GB).
7. **Prompt injection.**
   - Le skill di terzi entrano nei prompt degli agenti. Per le repo installate in automatico, il bibliotecario le segnala come "di terzi".
   - Con `AGENT_WORLD_ALLOW_SHELL=1` restano escluse dagli agenti che hanno `run_command`, a meno che l'utente non le approvi.
8. **Perimetro.**
   - `tools.py` espone la funzione di download **solo allo Skiller**, non come tool degli agenti LLM: un agente non deve poter scaricare codice arbitrario da solo.
9. **Test.**
   - Le fixture coprono: `../`, assoluti, `C:\`, UNC, ADS, `CON.txt`, symlink in tar e in zip, bomba zip, cartella "sorella" con lo stesso prefisso, `CUSTOM_DOWNLOAD_PATH` pericolosi.
   - Ogni fixture va rifiutata **senza scrivere nulla fuori dallo staging**, e ogni difesa va vista rossa con una mutazione.
