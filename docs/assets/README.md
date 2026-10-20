# Immagini del README

Il [README principale](../../README.md) mostra queste immagini. Si rigenerano tutte con:

```sh
npm run screenshots
```

Lo script (`scripts/readme-shots.js`):
- avvia l'app in modalità demo, in italiano, e fa due missioni vere al ritmo normale (circa 8 minuti): un sito da costruire e, dalla spec 11, l'app d'esempio *todo-board* da decodificare e ricostruire in clean-room;
- cattura ogni immagine a 1920×1080 con il browser headless degli strumenti di test, e si ferma con un errore se non vede uno dei momenti attesi;
- usa una cartella home temporanea, così la scheda Skill mostra solo le skill dell'app e non i plugin installati sulla macchina, e la lingua scelta resta lì.

| File | Cosa mostra |
|---|---|
| `office-3d.png` | l'ufficio 3D durante una missione, con i due pannelli aperti |
| `sub-agents.png` | primo piano della sub-agent bay, con i sub-agenti al lavoro |
| `qa-review.png` | primo piano del QA che dà il verdetto alla scrivania |
| `mission-tasks.png` | la scheda **Task** con workstream, sotto-task e revisioni |
| `skill-hub.png` | la scheda **Skill**: fonti, ricerca e libreria |
| `brain.png` | la scheda **Brain**, con lezioni e riassunto della missione |
| `router.png` | la scheda **Router**: provider, media e combo |
| `final-report.png` | il report finale della CEO e i file consegnati |
| `reverse-team.png` | la stanza del team Reverse Engineering: Kira e Zero decodificano l'app d'esempio, accanto allo scanner |
| `clean-room-build.png` | la ricostruzione clean-room in corso, con il badge dell'intento e della fase |
| `clean-room-messages.png` | la scheda **Messaggi**: intento, passaggio di consegne e QA di parità |
| `blueprint.png` | il `blueprint.md` dell'app d'esempio nella scheda **Output** |
| `parity-qa.png` | `PARITY.md`: ogni criterio di parità del blueprint, verificato |

Puoi anche sostituirle a mano: tieni gli stessi nomi, PNG, ogni file sotto i 5 MB.
