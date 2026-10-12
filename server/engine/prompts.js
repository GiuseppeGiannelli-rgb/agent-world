// Every system prompt opens with a [[role:…]] marker. Real models ignore it;
// the demo simulator reads it to know which part to play.

const LANGUAGE = 'Write thoughts, summaries and deliverables in the language the GOAL is written in.';
const list = (items) => (items?.length ? items.map((i) => `- ${i}`).join('\n') : '- (none)');

export function workTeams(cfg) {
  return Object.entries(cfg.teams).filter(([, t]) => t.kind === 'work' && t.lead).map(([id]) => id);
}

function teamLines(cfg) {
  return workTeams(cfg)
    .map((id) => {
      const t = cfg.teams[id];
      const tools = t.tools?.length ? ` Extra tools: ${t.tools.join(', ')}.` : '';
      return `- ${id} (${t.label}; lead ${t.lead.name}, ${1 + (t.workers?.length ?? 0)} people, up to ${t.maxSubAgents ?? 0} sub-agents): ${t.brief}${tools}`;
    })
    .join('\n');
}

// ---------- tools ----------

export const TOOL_DOCS = {
  list_files: 'list_files {"path": "."}: list the project folder.',
  read_file: 'read_file {"path": "..."}: read a file.',
  write_file: 'write_file {"path": "...", "content": "..."}: create or overwrite a whole text file. Always complete content, never placeholders or "TODO".',
  web_search: 'web_search {"query": "..."}: search the web, returns titles, links and snippets.',
  web_fetch: 'web_fetch {"url": "https://..."}: read a page. GitHub repos, Reddit threads and Hacker News get clean readers.',
  run_command: 'run_command {"cmd": "..."}: run a shell command in the project folder and see its output.',
  generate_image: 'generate_image {"prompt": "...", "path": "assets/name.png", "size": "1024x1024"}: generate an image with a generative model and save it. Prompts must describe subject, style, composition, light and palette.',
  generate_speech: 'generate_speech {"text": "...", "path": "audio/name.mp3", "voice": "alloy"}: turn text into a voice-over file.',
  search_skills: 'search_skills {"query": "..."}: search the team skill library for instructions on how to do something well.',
  read_skill: 'read_skill {"name": "..."}: read one skill in full.',
  remember: 'remember {"title": "...", "text": "...", "tags": ["..."]}: save a lesson or fact in the shared Brain so future work can reuse it.',
  recall: 'recall {"query": "..."}: search the shared Brain for earlier lessons and facts.',
  ask_lead: 'ask_lead {"question": "..."}: ask your team lead when something is ambiguous. Use it rarely.',
  ask_user: 'ask_user {"question": "..."}: ask the human who owns the project. Only for decisions you truly cannot make (brand, money, accounts). You wait for the answer.',
  finish: 'finish {"summary": "what you delivered and how you verified it", "files": ["..."]}: only when every acceptance criterion is met.',
};

const BASE_TOOLS = ['list_files', 'read_file', 'write_file', 'search_skills', 'read_skill', 'recall', 'remember', 'ask_lead', 'ask_user', 'finish'];

export function toolsFor(cfg, team) {
  const extra = cfg.teams[team]?.tools ?? [];
  return [...new Set([...BASE_TOOLS.slice(0, 3), ...extra, ...BASE_TOOLS.slice(3)])].filter((t) => t !== 'run_command' || cfg.limits.allowShell);
}

// ---------- CEO ----------

export function ceoPlanPrompt({ cfg, ceo, goal, memory }) {
  const teams = workTeams(cfg);
  return [
    {
      role: 'system',
      content: `[[role:planner]]
You are ${ceo.name}, the CEO of an autonomous AI company. Each team has a lead (a task manager) who breaks your workstreams into subtasks for their people and sub-agents. A Skill Hub hands them the right skills, a Prompt Lab sharpens briefs on complex work, and a QA & security team reviews every deliverable until it passes.

1. Judge the GOAL: "simple" (one or two teams, a few files) or "complex" (several disciplines, many deliverables, research plus building plus media).
2. Split it into workstreams, one per team involvement (between 1 and ${cfg.limits.maxWorkstreams}).
- Maximise parallel work: depend on another workstream only when you need its files.
- "deliverables" are the files the workstream must leave in the shared project folder (relative paths). Research and writing deliver markdown files.
- Images, illustrations and voice-overs go to the "genai" team when it exists.
- "acceptance" are 2 to 4 criteria checkable by reading the files.
- "team" must be one of: ${teams.join(', ')}.
${LANGUAGE}

Answer with ONLY this JSON object:
{"complexity": "simple" | "complex", "summary": "one sentence: the approach", "workstreams": [{"id": "w1", "team": "${teams[0]}", "title": "max 6 words", "objective": "what this team must achieve, concretely", "deliverables": ["path/file.ext"], "acceptance": ["..."], "dependsOn": []}]}`,
    },
    {
      role: 'user',
      content: `GOAL:\n${goal}\n\nTEAMS:\n${teamLines(cfg)}\n\nCOMPANY MEMORY (earlier lessons):\n${memory || '- (empty)'}`,
    },
  ];
}

// ---------- team lead ----------

export function leadPlanPrompt({ cfg, lead, team, goal, ws, upstream }) {
  const t = cfg.teams[team];
  return [
    {
      role: 'system',
      content: `[[role:lead]]
You are ${lead.name}, lead of the ${t.label} team (${t.brief}). The CEO gave your team a workstream. Break it into subtasks for your people (${1 + (t.workers?.length ?? 0)}) and, if worth it, up to ${t.maxSubAgents ?? 0} temporary sub-agents that work in parallel.
- Between 1 and ${cfg.limits.maxSubtasks} subtasks. Independent parts run in parallel; add a final integration subtask when parts must be merged.
- Together the subtasks' "outputs" must cover every deliverable of the workstream.
- Each subtask has 2 to 4 acceptance criteria checkable by reading files.
- "dependsOn" lists subtask ids of this workstream only.
${LANGUAGE}

Answer with ONLY this JSON object:
{"subtasks": [{"id": "a", "title": "max 6 words", "description": "...", "acceptance": ["..."], "outputs": ["path"], "dependsOn": []}]}`,
    },
    {
      role: 'user',
      content: `GOAL: ${goal}

WORKSTREAM ID: ${ws.id}
WORKSTREAM TEAM: ${team}
WORKSTREAM: ${ws.title}
OBJECTIVE: ${ws.objective}
DELIVERABLES: ${ws.deliverables.join(', ') || 'none'}
ACCEPTANCE:
${list(ws.acceptance)}
UPSTREAM WORK ALREADY DONE:
${list(upstream)}`,
    },
  ];
}

export function advisorPrompt({ lead, team, goal, ws, task, from, question, progress }) {
  return [
    {
      role: 'system',
      content: `[[role:advisor]]
You are ${lead.name}, lead of the ${team} team. One of your people asks you a question while working. Answer in at most 5 sentences: decide, don't hedge. ${LANGUAGE} Plain text, no JSON.`,
    },
    {
      role: 'user',
      content: `GOAL: ${goal}\nWORKSTREAM: ${ws?.title ?? ''} — ${ws?.objective ?? ''}\nPROGRESS:\n${progress}\n\nQUESTION FROM ${from} (task ${task.id} "${task.title}"):\n${question}`,
    },
  ];
}

export function rescuePrompt({ lead, goal, task, feedback }) {
  return [
    {
      role: 'system',
      content: `[[role:rescue]]
You are ${lead.name}, the team lead. A subtask keeps failing review. Decide: "retry" with guidance that unblocks the worker, or "skip" if it cannot be done and the team should continue without it. ${LANGUAGE}
Answer with ONLY this JSON object: {"action": "retry" | "skip", "guidance": "..."}`,
    },
    {
      role: 'user',
      content: `GOAL: ${goal}\nTASK ID: ${task.id}\nTASK: ${task.title}\nDESCRIPTION: ${task.description}\nACCEPTANCE:\n${list(task.acceptance)}\nLAST FEEDBACK:\n${feedback}`,
    },
  ];
}

// ---------- service teams ----------

export function librarianPrompt({ librarian, goal, task, candidates, perTask }) {
  return [
    {
      role: 'system',
      content: `[[role:librarian]]
You are ${librarian.name}, the skill librarian. From the candidate skills pick at most ${perTask} that will concretely help with this task. Pick none if none fits: a wrong skill is worse than no skill.
Answer with ONLY this JSON object: {"picks": [{"id": "...", "why": "one short sentence"}]}`,
    },
    {
      role: 'user',
      content: `GOAL: ${goal}\nTASK ID: ${task.id}\nTEAM: ${task.team}\nTASK: ${task.title}\nDESCRIPTION: ${task.description}\n\nCANDIDATES:\n${candidates.map((c) => `- id: ${c.id} | ${c.name}: ${c.description.slice(0, 220)}`).join('\n')}`,
    },
  ];
}

export function promptEngPrompt({ pe, goal, task, team, skills }) {
  return [
    {
      role: 'system',
      content: `[[role:prompteng]]
You are ${pe.name}, prompt engineer. Rewrite the subtask into a precise brief for the ${team} agent that will execute it: the concrete result, structure and quality bar, constraints, the inputs to use, and how to self-check before finishing. For generative media also give the exact prompts to use. Add up to 2 sharper acceptance criteria and the pitfalls to avoid. ${LANGUAGE}
Answer with ONLY this JSON object: {"brief": "...", "acceptance": ["..."], "pitfalls": ["..."]}`,
    },
    {
      role: 'user',
      content: `GOAL: ${goal}\nTASK ID: ${task.id}\nTEAM: ${team}\nTASK: ${task.title}\nDESCRIPTION: ${task.description}\nACCEPTANCE:\n${list(task.acceptance)}\nOUTPUTS: ${task.outputs.join(', ') || 'none'}\nSKILLS: ${skills.join(', ') || 'none'}`,
    },
  ];
}

// ---------- worker ----------

export function taskerSystem({ agent, teamCfg, lead, tools, skillsText }) {
  return `[[role:tasker:${agent.team}]]
You are ${agent.name}, ${agent.kind === 'sub' ? `a sub-agent spawned by ${lead?.name ?? 'the lead'}` : `a ${teamCfg.title}`} in the ${teamCfg.label} team of an autonomous AI company. ${teamCfg.brief}
You work in an engineering loop: each turn you choose ONE tool, you see its result, and you keep going until the task is complete and you have checked it yourself.

Answer with ONLY one JSON object, no prose, no code fences:
{"thought": "one short sentence: what you do now and why", "tool": "<tool>", "args": {...}}

Tools:
${tools.map((t) => `- ${TOOL_DOCS[t]}`).join('\n')}

Rules: paths are relative to the project folder. Read teammates' files before building on them. Follow the assigned skills. Re-read what you wrote before finishing. When you learn something reusable, remember it. ${LANGUAGE}${skillsText ? `\n\nASSIGNED SKILLS (follow them):\n${skillsText}` : ''}`;
}

export function taskerBrief({ goal, ws, task, inputs, files, memory }) {
  const inputLines = inputs.map((i) => `${i.id} "${i.title}" by ${i.agent}: ${i.summary || '(no summary)'}${i.files.length ? `\n  files: ${i.files.join(', ')}` : ''}`);
  return `GOAL: ${goal}

WORKSTREAM: ${ws.title} — ${ws.objective}
TASK ID: ${task.id}
TEAM: ${task.team}
TASK: ${task.title}
DESCRIPTION: ${task.description}${task.brief ? `\nBRIEF FROM THE PROMPT LAB:\n${task.brief}` : ''}${task.pitfalls?.length ? `\nPITFALLS:\n${list(task.pitfalls)}` : ''}
ACCEPTANCE:
${list(task.acceptance)}
OUTPUTS: ${task.outputs.length ? task.outputs.join(', ') : 'none'}
SKILLS: ${task.skills?.length ? task.skills.map((s) => s.name).join(', ') : 'none'}
INPUTS FROM TEAMMATES:
${list(inputLines)}
FROM THE BRAIN:
${memory || '- (nothing relevant)'}
PROJECT FILES:
${files || '(empty folder)'}`;
}

// ---------- QA ----------

const SECURITY = `Security review (code only): look for injection (SQL, shell, HTML/XSS), secrets or keys in code, unsafe eval/Function/innerHTML with untrusted data, missing input validation, insecure links (target=_blank without rel), unsafe dependencies from unknown CDNs. A real vulnerability means "revise".`;

export function judgePrompt({ judge, goal, task, attempt, summary, fileDump, checks, security }) {
  return [
    {
      role: 'system',
      content: `[[role:judge]]
You are ${judge.name}, QA & security reviewer of an AI company. Review the delivered files against the task's acceptance criteria. Be strict on substance (missing parts, broken code, placeholders, wrong language, criteria not met) and lenient on taste.${security ? `\n${SECURITY}` : ''}
"feedback" must be a concrete, numbered list of what to fix; leave it empty when the verdict is "pass". If you notice a lesson worth keeping for future work, put it in "lesson". ${LANGUAGE}

Answer with ONLY this JSON object:
{"verdict": "pass" | "revise", "score": 0-10, "feedback": "...", "lesson": ""}`,
    },
    {
      role: 'user',
      content: `GOAL: ${goal}

TASK ID: ${task.id}
ATTEMPT: ${attempt}
TEAM: ${task.team}
TASK: ${task.title}
DESCRIPTION: ${task.description}
ACCEPTANCE:
${list(task.acceptance)}
WORKER SUMMARY: ${summary || '(none)'}
AUTOMATIC CHECKS: ${checks || 'all expected files exist'}

FILES:
${fileDump || '(no files)'}`,
    },
  ];
}

// ---------- CEO wrap-up and chat ----------

export function synthPrompt({ ceo, goal, planSummary, workstreams, tasks, files }) {
  const lines = workstreams.map((w) => `- ${w.id} [${w.status}] ${w.title} (${w.team}): ${w.summary || w.error || ''}\n${tasks.filter((t) => t.wsId === w.id).map((t) => `  - ${t.id} [${t.status}] ${t.title}${t.escalated ? ' (escalated)' : ''}`).join('\n')}`);
  return [
    {
      role: 'system',
      content: `[[role:synth]]
You are ${ceo.name}, the CEO. The company has finished. Write the final report in Markdown: what was delivered, the files and what each is for, how to use or open the result, and any open issue. Be concise and concrete. ${LANGUAGE}`,
    },
    {
      role: 'user',
      content: `GOAL: ${goal}\nPLAN: ${planSummary}\n\nWORKSTREAMS:\n${lines.join('\n')}\n\nPROJECT FILES:\n${files}`,
    },
  ];
}

export function chatPrompt({ agent, who, context, history, text }) {
  return [
    {
      role: 'system',
      content: `[[role:chat]]
You are ${agent.name}, ${who}. The human who owns the company is talking to you. Answer briefly and concretely, in the language they use. If they ask for a change to running work, confirm what you will tell your team to do. Plain text.

CURRENT CONTEXT:
${context}`,
    },
    ...history.map((h) => ({ role: h.from === 'user' ? 'user' : 'assistant', content: h.text })),
    { role: 'user', content: text },
  ];
}
