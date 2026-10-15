// Spec 06: the words of the UI in Italian and English. t('key', { vars }) reads the
// current language and falls back to Italian, then to the key itself; label('status',
// x) reads a map entry and falls back to x. The language comes from the config
// (ui.language): main.js calls setLang() at boot and whenever the config changes.

export const LANGS = { it: 'Italiano', en: 'English' };
const LOCALE = { it: 'it-IT', en: 'en-US' };

const DICT = {
  it: {
    'status.planning': 'Pianificazione', 'status.awaiting_approval': 'Attende te', 'status.running': 'In corso', 'status.synthesizing': 'Report finale', 'status.completed': 'Completato', 'status.completed_with_failures': 'Completato con errori', 'status.failed': 'Fallito', 'status.stopped': 'Fermato',
    'task.queued': 'in coda', 'task.assigned': 'assegnato', 'task.working': 'al lavoro', 'task.review': 'in revisione', 'task.revise': 'da correggere', 'task.done': 'fatto', 'task.failed': 'fallito', 'task.skipped': 'saltato',
    'ws.queued': 'in coda', 'ws.preparing': 'il lead organizza', 'ws.running': 'in corso', 'ws.done': 'fatto', 'ws.failed': 'non completato', 'ws.skipped': 'saltato',
    'state.idle': 'libero', 'state.fetching': 'prende il workstream', 'state.assigned': 'prende il task', 'state.thinking': 'ragiona', 'state.tool': 'lavora', 'state.waiting': 'attende revisione', 'state.reviewing': 'revisiona', 'state.verdict': 'dà il verdetto', 'state.delivering': 'consegna', 'state.paused': 'in pausa', 'state.asking': 'ti fa una domanda', 'state.celebrating': 'festeggia',
    'kind.goal': 'obiettivo', 'kind.plan': 'piano', 'kind.brief': 'brief', 'kind.split': 'scomposizione', 'kind.skills': 'skill', 'kind.prompt': 'prompt lab', 'kind.spawn': 'sub-agente', 'kind.assign': 'incarico', 'kind.question': 'domanda', 'kind.answer': 'risposta', 'kind.review': 'revisione', 'kind.pass': 'approvato', 'kind.revise': 'da rivedere', 'kind.deliver': 'consegna', 'kind.escalate': 'escalation', 'kind.stuck': 'bloccato', 'kind.guidance': 'indicazioni', 'kind.error': 'errore', 'kind.system': 'sistema', 'kind.report': 'report', 'kind.chat': 'chat', 'kind.ask_user': 'domanda per te', 'kind.reply': 'tua risposta',
    'tool.list_files': '📂 elenca file', 'tool.read_file': '📖 legge', 'tool.write_file': '✍️ scrive', 'tool.web_search': '🔎 cerca sul web', 'tool.web_fetch': '🌐 legge una pagina', 'tool.run_command': '⚙️ esegue', 'tool.generate_image': '🎨 genera immagine', 'tool.generate_speech': '🎙️ genera voce', 'tool.search_skills': '📚 cerca skill', 'tool.read_skill': '📘 legge skill', 'tool.remember': '🧠 salva nel Brain', 'tool.recall': '🧠 consulta il Brain', 'tool.ask_lead': '❓ chiede al lead', 'tool.ask_user': '🙋 chiede a te', 'tool.finish': '✅ consegna',
    'note.lesson': 'lezione QA', 'note.run': 'missione', 'note.note': 'nota agente', 'note.user': 'tua nota',
    examples: [
      'Il sito completo per il lancio di una pizzeria napoletana a Milano, con brand, immagini e testi',
      'Una landing page per il mio studio di yoga',
      'Ricerca: confronto tra i principali framework JavaScript nel 2026, con copertina',
      'Uno spot audio di 20 secondi per una palestra, con testo e voce',
    ],
    'team.ceo': 'Regia',
    you: 'Tu', everyone: 'Tutti',
    'ago.s': '{n}s fa', 'ago.min': '{n} min fa', 'ago.h': '{n} h fa',
    'error.status': 'Errore {n}',
    'voice.unavailable': 'Il riconoscimento vocale non è disponibile in questo browser (prova Chrome o Edge).',
    'voice.mic': 'Microfono: {error}',
    'top.live': 'Almeno un provider ha una chiave: i modelli sono veri.',
    'top.demo': 'Nessuna chiave nel file .env: un simulatore interpreta ogni ruolo.',
    'top.agents': '<b>{n}</b> agenti · <b>{busy}</b> al lavoro',
    'top.calls': 'Chiamate', 'top.subs': 'Sub-agenti',
    'wait.title': '🙋 In attesa di te · {n}', 'wait.plan': 'approvazione del piano', 'wait.question': 'domanda su {task}',
    'wait.notes': 'Note facoltative per la squadra…', 'wait.answer': 'La tua risposta…',
    'wait.approve': 'Approva', 'wait.reject': 'Rifiuta', 'wait.reply': 'Rispondi',
    'current.busy': 'L\'azienda è al lavoro…', 'current.start': 'Avvia l\'azienda',
    'current.empty': 'Scrivi un obiettivo: la CEO lo divide tra i team, i lead scompongono il lavoro, lo Skill Hub assegna le skill e il QA rivede tutto.',
    'current.resume': '▶ Riprendi', 'current.pause': '⏸ Pausa', 'current.stop': '■ Ferma',
    'current.selected': 'Run selezionato', 'current.back': 'torna al live', 'current.title': 'Missione attuale',
    'current.paused': ' · pausa', 'current.complex': 'complessa', 'current.simple': 'semplice', 'current.calls': '{n} chiamate',
    'runs.empty': 'Ancora nessun run.',
    'card.attempt': 'tentativo {n}', 'card.security': ' · sicurezza', 'card.files': 'File:', 'card.skills': 'Skill:', 'card.after': 'Dopo:', 'card.delivery': 'Consegna:', 'card.sub': ' (sub)', 'card.rev': '{n} rev.',
    'board.planning': '🧠 La CEO sta pianificando…', 'board.empty': 'Il lavoro dell\'azienda apparirà qui.',
    'board.all': 'Tutti', 'board.running': 'In corso', 'board.queued': 'In coda', 'board.done': 'Fatti',
    'board.splitting': 'Il lead sta scomponendo il lavoro…', 'board.waitingDeps': 'In attesa dei workstream da cui dipende.',
    'board.waitingYou': '🙋 In attesa di te {n}', 'board.nothing': 'Niente in questa vista.',
    'comms.empty': 'Qui passano i messaggi tra CEO, lead, agenti, Skill Hub, Prompt Lab e QA.',
    'teams.all': '← Tutti i team', 'teams.room': 'Vai alla stanza', 'teams.service': 'servizio', 'teams.work': 'team operativo',
    'teams.runTasks': 'Task del run', 'teams.running': 'In corso', 'teams.avg': 'Tempo medio', 'teams.agents': 'Agenti', 'teams.upTo': 'fino a {n} sub-agenti',
    'teams.lead': 'lead', 'teams.sub': 'sub-agente', 'teams.tools': 'Strumenti', 'teams.skillsUsed': 'Skill usate in questo run',
    'teams.talk': 'Parla con il team', 'teams.talkHint': 'Scrivi al lead: durante un run il messaggio arriva a tutto il team.', 'teams.openChat': 'Apri la chat con {name}',
    'teams.members': '{n} agenti · {busy} al lavoro', 'teams.tasks': '{n} task · {running} in corso',
    'skills.intro': 'Lo <b>Skill Hub</b> indicizza ogni <code>SKILL.md</code> delle cartelle qui sotto. Per ogni task il bibliotecario sceglie le skill più utili; gli agenti possono cercarne altre.',
    'skills.search': 'Cerca tra {n} skill…', 'search': 'Cerca', 'skills.sources': 'Fonti', 'skills.reindex': 'Reindicizza', 'skills.count': '{n} skill', 'skills.missing': 'non trovata',
    'skills.addRepo': 'Aggiungi una repo GitHub di skill', 'skills.repoPlaceholder': 'https://github.com/utente/repo', 'skills.add': 'Aggiungi',
    'skills.results': 'Risultati per “{q}”', 'skills.library': 'Libreria', 'skills.none': 'Nessuna skill trovata.',
    'skills.reindexing': 'Reindicizzo le skill…', 'skills.cloning': 'Clono la repo…', 'skills.added': '{repo}: +{added} skill (totale {total})',
    'brain.intro': '<b>The Brain</b> è la memoria condivisa: lezioni del QA, note degli agenti e riassunti delle missioni. Ogni nuovo task riceve le note più pertinenti.',
    'brain.search': 'Cerca tra {n} note…', 'brain.add': '+ Aggiungi una nota per la squadra', 'brain.titlePlaceholder': 'Titolo',
    'brain.textPlaceholder': 'Es. Il nostro brand usa sempre il tu, mai il lei.', 'brain.save': 'Salva nel Brain', 'brain.empty': 'Il Brain è ancora vuoto: si riempie lavorando.', 'brain.saved': 'Nota salvata nel Brain',
    'router.ready': 'pronto', 'router.missing': 'manca {key}', 'router.key': 'chiave', 'router.off': 'disattivato', 'router.escalation': ' · escalation', 'router.test': 'Prova', 'router.cooling': 'pausa {n}s',
    'router.live': 'Modelli veri: ogni team usa la sua combo, passa al modello successivo se uno fallisce e sale alla combo di escalation dopo troppe bocciature.',
    'router.demo': 'Demo: nessuna chiave in <code>.env</code>, un simulatore interpreta i ruoli. Aggiungi una chiave e riavvia per andare live.',
    'router.text': 'Provider di testo', 'router.media': 'Media generativi', 'router.images': 'Immagini', 'router.voice': 'Voce', 'router.teams': 'Team → combo', 'router.combos': 'Combo',
    'router.recent': 'Ultime chiamate', 'router.noCalls': 'Nessuna chiamata ancora.', 'router.gateway': 'Gateway compatibile OpenAI: <code>POST {origin}/v1/chat/completions</code> con <code>"model": "combo:smart"</code>.',
    'router.answers': '{combo}: risponde {target} in {ms} ms{demo}',
    'output.empty': 'File, immagini, audio e report finale appariranno qui.', 'output.loading': 'Carico i file…', 'output.preview': '▶ Apri l\'anteprima del sito',
    'output.images': 'Immagini generate', 'output.audio': 'Audio', 'output.files': 'File del progetto', 'output.noFiles': 'Nessun file ancora.', 'output.report': 'Report finale',
    'output.reportLater': 'Arriva alla fine del run.', 'output.noReport': 'Nessun report.', 'output.folder': 'Cartella: {path}', 'open': 'Apri',
    'inspector.lead': 'Lead · {team}', 'inspector.sub': 'Sub-agente · {team}', 'inspector.task': 'Task <b>{id}</b>: {title}',
    'inspector.chat': 'Chat', 'inspector.steers': ' · i tuoi messaggi guidano il lavoro', 'inspector.speak': 'Leggi ad alta voce le risposte',
    'inspector.empty': 'Scrivi o parla con l\'agente.', 'inspector.write': 'Scrivi a {name}…', 'inspector.talk': 'Parla', 'inspector.send': 'Invia',
    'chat.steered': 'Messaggio inoltrato al lavoro in corso ({name})',
    'settings.title': 'Impostazioni', 'settings.language': 'Lingua dell\'interfaccia e degli agenti',
    'settings.languageHint': 'Vale per la UI, la voce e i nuovi run; un run già partito resta nella sua lingua.',
    'settings.keys': 'Le chiavi API stanno solo nel file <code>.env</code> della cartella dell\'app, mai qui. Le modifiche finiscono in <code>config/local.json</code>.',
    'settings.teams': 'Team → combo e sub-agenti', 'settings.team': 'Team', 'settings.people': 'Persone', 'settings.combo': 'Combo', 'settings.subMax': 'Sub max', 'settings.subMaxTitle': 'Sub-agenti massimi',
    'settings.how': 'Come lavora l\'azienda', 'settings.parallel': 'Task in parallelo', 'settings.steps': 'Passi per tentativo', 'settings.revisions': 'Revisioni max', 'settings.escalateAfter': 'Escalation dopo',
    'settings.workstreams': 'Workstream max', 'settings.subtasks': 'Sotto-task max', 'settings.escalationCombo': 'Combo di escalation', 'settings.alwaysApprove': 'Chiedi sempre l\'approvazione del piano',
    'settings.shell': 'Comandi shell per gli agenti: <b>{state}</b> (si cambia con <code>AGENT_WORLD_ALLOW_SHELL=1</code> nel file <code>.env</code>).', 'settings.shellOn': 'attivi', 'settings.shellOff': 'disattivati',
    'settings.pacing': 'Ritmo dell\'animazione (ms)', 'settings.textProviders': 'Provider di testo', 'settings.mediaProviders': 'Provider media (immagini e voce)',
    'settings.noKey': 'nessuna chiave', 'settings.keyless': 'senza chiave', 'settings.on': 'attivo',
    'settings.pollinations': 'Pollinations genera immagini gratis senza chiave ma invia i prompt a un servizio esterno: è spento finché non lo attivi.',
    'settings.combosHint': 'Liste ordinate di <code>provider/modello</code>: il router prova il primo con la chiave e passa al successivo se fallisce. <code>strategy</code>: <code>fallback</code> o <code>round-robin</code>.',
    'settings.cancel': 'Annulla', 'settings.save': 'Salva', 'settings.badCombos': 'Il JSON delle combo non è valido', 'settings.saved': 'Impostazioni salvate',
    'lang.saved': 'Lingua: {name}',
    'start.noGoal': 'Scrivi un obiettivo per l\'azienda',
    'answer.approved': 'Piano approvato: si parte!', 'answer.rejected': 'Piano rifiutato', 'answer.sent': 'Risposta inviata',
    'toast.asks': '🙋 {name} ti fa una domanda', 'toast.done': '🎉 Missione completata!', 'toast.over': 'Run terminato: {status}',
    'boot.failed': 'Impossibile caricare lo stato: {error}',
    'world.brain': '{n} note · memoria condivisa', 'world.spawned': '✨ creato dal lead', 'world.waiting': '⏳ attendo la revisione',
    'world.column.todo': 'DA FARE', 'world.column.running': 'IN CORSO', 'world.column.review': 'REVISIONE', 'world.column.done': 'FATTO',
    // index.html
    'html.theme': 'Giorno / notte', 'html.home': 'Vista completa', 'html.left': 'Missione', 'html.right': 'Pannello', 'html.settings': 'Impostazioni', 'html.language': 'Lingua',
    'html.newMission': 'Nuova missione', 'html.goal': 'Cosa deve fare l\'azienda? Es. il sito completo per il lancio del mio studio di yoga, con immagini e testi',
    'html.dictate': 'Detta l\'obiettivo', 'html.approve': 'Voglio approvare il piano prima che partano', 'html.history': 'Run precedenti',
    'html.tab.board': 'Task', 'html.tab.comms': 'Messaggi', 'html.tab.teams': 'Team', 'html.tab.skills': 'Skill', 'html.tab.brain': 'Brain', 'html.tab.router': 'Router', 'html.tab.output': 'Output',
    'html.minimap': 'Mappa: clicca per spostarti',
  },
  en: {
    'status.planning': 'Planning', 'status.awaiting_approval': 'Waiting for you', 'status.running': 'Running', 'status.synthesizing': 'Final report', 'status.completed': 'Completed', 'status.completed_with_failures': 'Completed with errors', 'status.failed': 'Failed', 'status.stopped': 'Stopped',
    'task.queued': 'queued', 'task.assigned': 'assigned', 'task.working': 'working', 'task.review': 'in review', 'task.revise': 'to fix', 'task.done': 'done', 'task.failed': 'failed', 'task.skipped': 'skipped',
    'ws.queued': 'queued', 'ws.preparing': 'the lead is organising', 'ws.running': 'running', 'ws.done': 'done', 'ws.failed': 'not completed', 'ws.skipped': 'skipped',
    'state.idle': 'free', 'state.fetching': 'fetching the workstream', 'state.assigned': 'taking the task', 'state.thinking': 'thinking', 'state.tool': 'working', 'state.waiting': 'waiting for review', 'state.reviewing': 'reviewing', 'state.verdict': 'giving the verdict', 'state.delivering': 'delivering', 'state.paused': 'paused', 'state.asking': 'has a question for you', 'state.celebrating': 'celebrating',
    'kind.goal': 'goal', 'kind.plan': 'plan', 'kind.brief': 'brief', 'kind.split': 'breakdown', 'kind.skills': 'skills', 'kind.prompt': 'prompt lab', 'kind.spawn': 'sub-agent', 'kind.assign': 'assignment', 'kind.question': 'question', 'kind.answer': 'answer', 'kind.review': 'review', 'kind.pass': 'approved', 'kind.revise': 'to revise', 'kind.deliver': 'delivery', 'kind.escalate': 'escalation', 'kind.stuck': 'stuck', 'kind.guidance': 'guidance', 'kind.error': 'error', 'kind.system': 'system', 'kind.report': 'report', 'kind.chat': 'chat', 'kind.ask_user': 'question for you', 'kind.reply': 'your reply',
    'tool.list_files': '📂 lists files', 'tool.read_file': '📖 reads', 'tool.write_file': '✍️ writes', 'tool.web_search': '🔎 searches the web', 'tool.web_fetch': '🌐 reads a page', 'tool.run_command': '⚙️ runs', 'tool.generate_image': '🎨 generates an image', 'tool.generate_speech': '🎙️ generates a voice', 'tool.search_skills': '📚 searches skills', 'tool.read_skill': '📘 reads a skill', 'tool.remember': '🧠 saves to the Brain', 'tool.recall': '🧠 asks the Brain', 'tool.ask_lead': '❓ asks the lead', 'tool.ask_user': '🙋 asks you', 'tool.finish': '✅ delivers',
    'note.lesson': 'QA lesson', 'note.run': 'mission', 'note.note': 'agent note', 'note.user': 'your note',
    examples: [
      'The complete launch website for a Neapolitan pizzeria in Milan, with brand, images and copy',
      'A landing page for my yoga studio',
      'Research: a comparison of the main JavaScript frameworks in 2026, with a cover image',
      'A 20-second audio ad for a gym, with script and voice',
    ],
    'team.ceo': 'Leadership', 'team.ceo.title': 'CEO · Leadership',
    'team.research': 'Research', 'team.dev': 'Development', 'team.content': 'Content', 'team.design': 'Design', 'team.genai': 'Generative AI', 'team.prompt': 'Prompt Lab', 'team.skills': 'Skill Hub', 'team.qa': 'Quality & Security',
    you: 'You', everyone: 'Everyone',
    'ago.s': '{n}s ago', 'ago.min': '{n} min ago', 'ago.h': '{n} h ago',
    'error.status': 'Error {n}',
    'voice.unavailable': 'Speech recognition is not available in this browser (try Chrome or Edge).',
    'voice.mic': 'Microphone: {error}',
    'top.live': 'At least one provider has a key: the models are real.',
    'top.demo': 'No key in the .env file: a simulator plays every role.',
    'top.agents': '<b>{n}</b> agents · <b>{busy}</b> working',
    'top.calls': 'Calls', 'top.subs': 'Sub-agents',
    'wait.title': '🙋 Waiting for you · {n}', 'wait.plan': 'plan approval', 'wait.question': 'question on {task}',
    'wait.notes': 'Optional notes for the team…', 'wait.answer': 'Your answer…',
    'wait.approve': 'Approve', 'wait.reject': 'Reject', 'wait.reply': 'Reply',
    'current.busy': 'The company is at work…', 'current.start': 'Start the company',
    'current.empty': 'Write a goal: the CEO splits it among the teams, the leads break the work down, the Skill Hub assigns the skills and QA reviews everything.',
    'current.resume': '▶ Resume', 'current.pause': '⏸ Pause', 'current.stop': '■ Stop',
    'current.selected': 'Selected run', 'current.back': 'back to live', 'current.title': 'Current mission',
    'current.paused': ' · paused', 'current.complex': 'complex', 'current.simple': 'simple', 'current.calls': '{n} calls',
    'runs.empty': 'No runs yet.',
    'card.attempt': 'attempt {n}', 'card.security': ' · security', 'card.files': 'Files:', 'card.skills': 'Skills:', 'card.after': 'After:', 'card.delivery': 'Delivery:', 'card.sub': ' (sub)', 'card.rev': '{n} rev.',
    'board.planning': '🧠 The CEO is planning…', 'board.empty': 'The company\'s work will appear here.',
    'board.all': 'All', 'board.running': 'Running', 'board.queued': 'Queued', 'board.done': 'Done',
    'board.splitting': 'The lead is breaking the work down…', 'board.waitingDeps': 'Waiting for the workstreams it depends on.',
    'board.waitingYou': '🙋 Waiting for you {n}', 'board.nothing': 'Nothing in this view.',
    'comms.empty': 'Messages between the CEO, leads, agents, Skill Hub, Prompt Lab and QA show up here.',
    'teams.all': '← All teams', 'teams.room': 'Go to the room', 'teams.service': 'service', 'teams.work': 'working team',
    'teams.runTasks': 'Run tasks', 'teams.running': 'Running', 'teams.avg': 'Average time', 'teams.agents': 'Agents', 'teams.upTo': 'up to {n} sub-agents',
    'teams.lead': 'lead', 'teams.sub': 'sub-agent', 'teams.tools': 'Tools', 'teams.skillsUsed': 'Skills used in this run',
    'teams.talk': 'Talk to the team', 'teams.talkHint': 'Write to the lead: during a run the message reaches the whole team.', 'teams.openChat': 'Open the chat with {name}',
    'teams.members': '{n} agents · {busy} working', 'teams.tasks': '{n} tasks · {running} running',
    'skills.intro': 'The <b>Skill Hub</b> indexes every <code>SKILL.md</code> in the folders below. For each task the librarian picks the most useful skills; agents can search for more.',
    'skills.search': 'Search {n} skills…', 'search': 'Search', 'skills.sources': 'Sources', 'skills.reindex': 'Reindex', 'skills.count': '{n} skills', 'skills.missing': 'not found',
    'skills.addRepo': 'Add a GitHub repo of skills', 'skills.repoPlaceholder': 'https://github.com/user/repo', 'skills.add': 'Add',
    'skills.results': 'Results for “{q}”', 'skills.library': 'Library', 'skills.none': 'No skills found.',
    'skills.reindexing': 'Reindexing the skills…', 'skills.cloning': 'Cloning the repo…', 'skills.added': '{repo}: +{added} skills ({total} in total)',
    'brain.intro': '<b>The Brain</b> is the shared memory: QA lessons, agent notes and mission summaries. Every new task receives the most relevant notes.',
    'brain.search': 'Search {n} notes…', 'brain.add': '+ Add a note for the team', 'brain.titlePlaceholder': 'Title',
    'brain.textPlaceholder': 'E.g. Our brand always speaks informally.', 'brain.save': 'Save to the Brain', 'brain.empty': 'The Brain is still empty: it fills up as the team works.', 'brain.saved': 'Note saved to the Brain',
    'router.ready': 'ready', 'router.missing': '{key} missing', 'router.key': 'key', 'router.off': 'disabled', 'router.escalation': ' · escalation', 'router.test': 'Test', 'router.cooling': 'cooling {n}s',
    'router.live': 'Real models: each team uses its combo, moves to the next model when one fails and climbs to the escalation combo after too many rejections.',
    'router.demo': 'Demo: no key in <code>.env</code>, a simulator plays the roles. Add a key and restart to go live.',
    'router.text': 'Text providers', 'router.media': 'Generative media', 'router.images': 'Images', 'router.voice': 'Voice', 'router.teams': 'Team → combo', 'router.combos': 'Combos',
    'router.recent': 'Latest calls', 'router.noCalls': 'No calls yet.', 'router.gateway': 'OpenAI-compatible gateway: <code>POST {origin}/v1/chat/completions</code> with <code>"model": "combo:smart"</code>.',
    'router.answers': '{combo}: {target} answers in {ms} ms{demo}',
    'output.empty': 'Files, images, audio and the final report will appear here.', 'output.loading': 'Loading the files…', 'output.preview': '▶ Open the site preview',
    'output.images': 'Generated images', 'output.audio': 'Audio', 'output.files': 'Project files', 'output.noFiles': 'No files yet.', 'output.report': 'Final report',
    'output.reportLater': 'It arrives at the end of the run.', 'output.noReport': 'No report.', 'output.folder': 'Folder: {path}', 'open': 'Open',
    'inspector.lead': 'Lead · {team}', 'inspector.sub': 'Sub-agent · {team}', 'inspector.task': 'Task <b>{id}</b>: {title}',
    'inspector.chat': 'Chat', 'inspector.steers': ' · your messages steer the work', 'inspector.speak': 'Read the replies aloud',
    'inspector.empty': 'Write or talk to the agent.', 'inspector.write': 'Write to {name}…', 'inspector.talk': 'Talk', 'inspector.send': 'Send',
    'chat.steered': 'Message forwarded to the running work ({name})',
    'settings.title': 'Settings', 'settings.language': 'Language of the interface and the agents',
    'settings.languageHint': 'It applies to the UI, the voice and new runs; a run already started keeps its language.',
    'settings.keys': 'API keys live only in the <code>.env</code> file of the app folder, never here. Changes go to <code>config/local.json</code>.',
    'settings.teams': 'Team → combo and sub-agents', 'settings.team': 'Team', 'settings.people': 'People', 'settings.combo': 'Combo', 'settings.subMax': 'Max subs', 'settings.subMaxTitle': 'Maximum sub-agents',
    'settings.how': 'How the company works', 'settings.parallel': 'Parallel tasks', 'settings.steps': 'Steps per attempt', 'settings.revisions': 'Max revisions', 'settings.escalateAfter': 'Escalate after',
    'settings.workstreams': 'Max workstreams', 'settings.subtasks': 'Max subtasks', 'settings.escalationCombo': 'Escalation combo', 'settings.alwaysApprove': 'Always ask to approve the plan',
    'settings.shell': 'Shell commands for the agents: <b>{state}</b> (change it with <code>AGENT_WORLD_ALLOW_SHELL=1</code> in the <code>.env</code> file).', 'settings.shellOn': 'enabled', 'settings.shellOff': 'disabled',
    'settings.pacing': 'Animation pace (ms)', 'settings.textProviders': 'Text providers', 'settings.mediaProviders': 'Media providers (images and voice)',
    'settings.noKey': 'no key', 'settings.keyless': 'keyless', 'settings.on': 'on',
    'settings.pollinations': 'Pollinations generates images for free without a key but sends the prompts to an external service: it stays off until you turn it on.',
    'settings.combosHint': 'Ordered lists of <code>provider/model</code>: the router tries the first one with a key and moves to the next if it fails. <code>strategy</code>: <code>fallback</code> or <code>round-robin</code>.',
    'settings.cancel': 'Cancel', 'settings.save': 'Save', 'settings.badCombos': 'The combos JSON is not valid', 'settings.saved': 'Settings saved',
    'lang.saved': 'Language: {name}',
    'start.noGoal': 'Write a goal for the company',
    'answer.approved': 'Plan approved: off we go!', 'answer.rejected': 'Plan rejected', 'answer.sent': 'Answer sent',
    'toast.asks': '🙋 {name} has a question for you', 'toast.done': '🎉 Mission completed!', 'toast.over': 'Run over: {status}',
    'boot.failed': 'Could not load the state: {error}',
    'world.brain': '{n} notes · shared memory', 'world.spawned': '✨ created by the lead', 'world.waiting': '⏳ waiting for review',
    'world.column.todo': 'TO DO', 'world.column.running': 'IN PROGRESS', 'world.column.review': 'REVIEW', 'world.column.done': 'DONE',
    'html.theme': 'Day / night', 'html.home': 'Full view', 'html.left': 'Mission', 'html.right': 'Panel', 'html.settings': 'Settings', 'html.language': 'Language',
    'html.newMission': 'New mission', 'html.goal': 'What should the company do? E.g. the complete launch website for my yoga studio, with images and copy',
    'html.dictate': 'Dictate the goal', 'html.approve': 'I want to approve the plan before they start', 'html.history': 'Previous runs',
    'html.tab.board': 'Tasks', 'html.tab.comms': 'Messages', 'html.tab.teams': 'Teams', 'html.tab.skills': 'Skills', 'html.tab.brain': 'Brain', 'html.tab.router': 'Router', 'html.tab.output': 'Output',
    'html.minimap': 'Map: click to move there',
  },
};

let lang = 'it';

export const getLang = () => lang;
export const locale = () => LOCALE[lang];
// the dictionaries themselves, for the checks: same keys in every language
export const dictionaries = () => DICT;

export function setLang(next) {
  lang = DICT[next] ? next : 'it';
  document.documentElement.lang = lang;
  return lang;
}

export function t(key, vars = {}) {
  const s = DICT[lang][key] ?? DICT.it[key] ?? key;
  return typeof s === 'string' ? s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m)) : s;
}

// a map entry (status, task, ws, state, kind, tool, note), or the raw value
export function label(map, value) {
  const key = `${map}.${value}`;
  return DICT[lang][key] ?? DICT.it[key] ?? value;
}

// D3: teams by id from the dictionary, the config label as fallback
export const teamName = (id, fallback) => DICT[lang][`team.${id}`] ?? fallback ?? id;

// the static words of index.html: data-i18n (text), data-i18n-title, data-i18n-placeholder
export function applyStatic(root = document) {
  root.querySelectorAll('[data-i18n]').forEach((el) => (el.textContent = t(el.dataset.i18n)));
  root.querySelectorAll('[data-i18n-title]').forEach((el) => (el.title = t(el.dataset.i18nTitle)));
  root.querySelectorAll('[data-i18n-placeholder]').forEach((el) => (el.placeholder = t(el.dataset.i18nPlaceholder)));
}
