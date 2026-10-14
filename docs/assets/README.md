# Immagini del README

Il [README principale](../../README.md) mostra queste immagini. Si rigenerano tutte con:

```sh
npm run screenshots
```

Lo script (`scripts/readme-shots.js`):
- avvia l'app in modalità demo e fa partire una missione vera, al ritmo normale (circa 3 minuti);
- cattura ogni immagine a 1920×1080 con il browser headless degli strumenti di test;
- usa una cartella home temporanea, così la scheda Skill mostra solo le skill dell'app e non i plugin installati sulla macchina.

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

Puoi anche sostituirle a mano: tieni gli stessi nomi, PNG, ogni file sotto i 5 MB.
