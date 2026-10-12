import { extractJson } from './json.js';
import { TOOL_DOCS, taskerBrief, taskerSystem, toolsFor } from './prompts.js';

const KEEP_RECENT = 16;
const ALL_TOOLS = Object.keys(TOOL_DOCS);

function describeStep(content) {
  const a = extractJson(content);
  if (!a) return '- (unreadable step)';
  const target = a.args?.path ?? a.args?.url ?? a.args?.query ?? a.args?.cmd ?? a.args?.question ?? a.args?.name ?? '';
  return `- ${a.tool} ${String(target).slice(0, 80)}`;
}

function shrinkStep(content) {
  const a = extractJson(content);
  if (a?.tool === 'write_file' && typeof a.args?.content === 'string' && a.args.content.length > 300) {
    return JSON.stringify({ ...a, args: { ...a.args, content: `[${a.args.content.length} chars written]` } });
  }
  return content;
}

// Keeps the context bounded: the brief stays, old steps become a one-line log,
// and the content of old file writes is replaced by its length.
function compact(messages) {
  const head = messages.slice(0, 2);
  let tail = messages.slice(2);
  let dropped = [];
  if (tail.length > KEEP_RECENT) {
    let cut = tail.length - KEEP_RECENT;
    while (cut < tail.length && tail[cut].role !== 'assistant') cut++;
    dropped = tail.slice(0, cut);
    tail = tail.slice(cut);
  }
  const assistantAt = tail.flatMap((m, i) => (m.role === 'assistant' ? [i] : []));
  const keepFullFrom = assistantAt.at(-2) ?? 0;
  tail = tail.map((m, i) => (m.role === 'assistant' && i < keepFullFrom ? { role: m.role, content: shrinkStep(m.content) } : m));
  if (dropped.length) {
    const log = dropped.filter((m) => m.role === 'assistant').map((m) => describeStep(m.content));
    const keep = dropped.filter((m) => m.role === 'user' && /^(REVISION REQUESTED|MESSAGE FROM THE USER)/.test(m.content)).map((m) => m.content.slice(0, 1500));
    head[1] = { role: 'user', content: `${head[1].content}\n\nEARLIER STEPS (compacted):\n${log.join('\n')}${keep.length ? `\n\nEARLIER INSTRUCTIONS STILL VALID:\n${keep.join('\n---\n')}` : ''}` };
  }
  return [...head, ...tail];
}

export function parseAction(text, allowed = ALL_TOOLS) {
  const obj = extractJson(text);
  if (!obj) return null;
  const tool = obj.tool ?? obj.action?.tool ?? obj.name ?? obj.action;
  if (typeof tool !== 'string' || !allowed.includes(tool)) return null;
  const args = obj.args ?? obj.arguments ?? obj.action?.args ?? obj.parameters ?? {};
  return { thought: String(obj.thought ?? obj.reasoning ?? '').slice(0, 400), tool, args: typeof args === 'object' && args ? args : {} };
}

// One worker on one subtask. The conversation survives revisions, so a worker
// sent back by review keeps everything it already learned.
export class Tasker {
  constructor(run, task, agent) {
    this.run = run;
    this.task = task;
    this.agent = agent;
    this.messages = null;
    this.use = null; // combo override after an escalation
    this.tools = toolsFor(run.cfg, task.team);
  }

  async init() {
    const { run, task, agent } = this;
    const cfg = run.cfg;
    const ws = run.wsById(task.wsId);
    const inputs = run.inputsFor(task);
    const memory = run.ctx.brain
      .search(`${task.title} ${task.description}`, 3, { agentId: agent.id })
      .map((n) => `- ${n.title}: ${n.text.slice(0, 280)}`)
      .join('\n');
    this.messages = [
      { role: 'system', content: taskerSystem({ agent, teamCfg: cfg.teams[task.team], lead: run.team.lead(task.team), tools: this.tools, skillsText: await run.skillsText(task) }) },
      { role: 'user', content: taskerBrief({ goal: run.data.goal, ws, task, inputs, files: await run.ws.listText(), memory }) },
    ];
  }

  async work(feedback) {
    const { run, task, agent } = this;
    if (!this.messages) await this.init();
    if (feedback) {
      this.messages.push({ role: 'user', content: `REVISION REQUESTED (attempt ${task.attempts}):\n${feedback}\n\nFix every point, check the files, then call finish again.` });
    }
    const maxSteps = run.cfg.limits.maxSteps;
    for (let step = 0; step < maxSteps; step++) {
      await run.gate(agent);
      for (const note of run.takeSteering(task, agent)) {
        this.messages.push({ role: 'user', content: `MESSAGE FROM THE USER (the owner): ${note}\nTake it into account from now on.` });
      }
      run.team.set(agent.id, { state: 'thinking', tool: null, toolTarget: null });
      const res = await run.chat({ role: task.team, use: this.use, messages: compact(this.messages), json: true, maxTokens: 8000, agent, task });
      const action = parseAction(res.text, this.tools);
      if (!action) {
        this.messages.push({ role: 'assistant', content: res.text.slice(0, 2000) });
        this.messages.push({ role: 'user', content: `FORMAT ERROR: reply with exactly one JSON object {"thought": "...", "tool": "one of ${this.tools.join(', ')}", "args": {...}} and nothing else.` });
        run.note(task, agent, 'error', 'Risposta non valida, riprovo');
        continue;
      }
      this.messages.push({ role: 'assistant', content: JSON.stringify(action) });
      run.step(task, agent, action);

      if (action.tool === 'finish') {
        const missing = await run.missingOutputs(task);
        if (missing.length) {
          this.messages.push({ role: 'user', content: `CANNOT FINISH YET: these expected files are missing or empty: ${missing.join(', ')}. Create them first.` });
          continue;
        }
        return { summary: String(action.args.summary ?? '').slice(0, 2000), files: Array.isArray(action.args.files) ? action.args.files.map(String) : task.outputs };
      }
      const observation = await run.execTool(task, agent, action);
      this.messages.push({ role: 'user', content: `RESULT of ${action.tool}:\n${observation}` });
    }
    return { stepLimit: true };
  }
}
