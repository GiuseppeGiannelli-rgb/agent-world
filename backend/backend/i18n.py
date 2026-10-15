"""Spec 06: the backend's own texts -- run messages, speech bubbles, task
errors, Brain titles -- in every supported language. Agents write in the
run's language because prompts.language_rule() tells them to; these tables
cover what run.py writes itself. HTTP errors stay Italian (N13)."""

LANGUAGES = {"it": "Italian", "en": "English"}
DEFAULT = "it"


def check(lang: str | None) -> str | None:
    """None means "not chosen" (the legacy rules); anything else must be supported."""
    if lang is None or (isinstance(lang, str) and lang in LANGUAGES):
        return lang
    raise ValueError(f"Unsupported language: {lang!r}")


MESSAGES = {
    "it": {
        "paused": "Run in pausa: il lavoro in corso termina il passo attuale.",
        "resumed": "Si riparte.",
        "answer_approved": "Approvato",
        "answer_rejected": "Rifiutato",
        "run_failed": "Il run si è fermato: {err}",
        "mission_done": "Missione compiuta!",
        "ceo_studying": "Studio l'obiettivo e organizzo i team…",
        "after": " (dopo {deps})",
        "plan_complex": "Missione complessa",
        "plan_simple": "Missione semplice",
        "plan_bubble": "Piano: {n} workstream",
        "plan_question": "Approvi il piano?",
        "plan_waiting": "Aspetto la tua approvazione del piano",
        "plan_rejected": "Piano rifiutato",
        "plan_rejected_because": "Piano rifiutato: {reason}",
        "plan_approved": "Piano approvato",
        "depends_on_failed": "Dipende da {blocker}, che non è stato completato",
        "ws_done": "{id} completato: {title}",
        "ws_failed": "{id} chiuso con task non completati",
        "ws_prepare_failed": "Non riesco a organizzare {id}: {err}",
        "spawned": "Ti ho creato per {id} · {title}",
        "task_failed": "Non riesco a completare \"{title}\": {err}",
        "lead_splitting": "Divido il lavoro del team…",
        "split_many": "{id} diviso in {n} sotto-task:\n{listing}",
        "split_one": "{id}: lo affido al team così com'è.",
        "subtasks_ready": "{n} sotto-task pronti",
        "skills_searching": "Cerco le skill giuste per {n} task",
        "skills_none": "Nessuna skill adatta: meglio niente che una sbagliata.",
        "briefs_rewriting": "Riscrivo {n} brief",
        "briefs_done": "Brief affinati per {ids}",
        "step_limit": "Hai esaurito i {n} passi disponibili senza chiamare finish. Concentrati sui file richiesti e consegna.",
        "awaiting_review": "In attesa di revisione",
        "delivered": "Consegnato!",
        "task_delivered": "{id} consegnato: {summary}",
        "default_feedback": "Il revisore chiede di migliorare il lavoro rispetto ai criteri di accettazione.",
        "escalation_note": "Escalation al modello \"{combo}\"",
        "escalation_msg": "Dopo {n} revisioni passo {id} al modello più forte ({combo}).",
        "still_failing": "Ancora non approvato dopo l'aiuto del lead. Ultimo feedback: {feedback}",
        "lead_skipped": "Il lead ha deciso di saltarlo: {guidance}",
        "lead_guidance": "Indicazioni del lead: {guidance}\n\nUltimo feedback del revisore:\n{feedback}",
        "retry_stronger": "Riprovo con un modello più forte…",
        "fixing": "Correggo seguendo il feedback…",
        "missing_files": "File mancanti o vuoti: {files}",
        "review_security": "Qualità e sicurezza: \"{title}\"",
        "review_check": "Controllo: \"{title}\"",
        "ready_for_review": "Pronto per la revisione: {title}",
        "lesson_title": "Lezione · {title}",
        "approved_score": "Approvato ({score}/10)",
        "approved_bubble": "Approvato! {score}/10",
        "to_revise": "Da rivedere",
        "got_answer": "Ho la risposta, continuo",
        "no_answer": "Nessuna risposta, decido io",
        "stuck": "Bloccato su \"{title}\" dopo {n} revisioni.",
        "rescue_default": "Riparti dai criteri di accettazione uno per uno.",
        "guidance_skip": "Saltiamo questo task: {guidance}",
        "guidance_retry": "Riprova: {guidance}",
        "writing_report": "Scrivo il report finale…",
        "mission_title": "Missione · {goal}",
        "report_ready": "Report finale pronto: REPORT.md",
    },
    "en": {
        "paused": "Run paused: work in progress finishes its current step.",
        "resumed": "Back to work.",
        "answer_approved": "Approved",
        "answer_rejected": "Rejected",
        "run_failed": "The run stopped: {err}",
        "mission_done": "Mission accomplished!",
        "ceo_studying": "Studying the goal and organising the teams…",
        "after": " (after {deps})",
        "plan_complex": "Complex mission",
        "plan_simple": "Simple mission",
        "plan_bubble": "Plan: {n} workstreams",
        "plan_question": "Do you approve the plan?",
        "plan_waiting": "Waiting for you to approve the plan",
        "plan_rejected": "Plan rejected",
        "plan_rejected_because": "Plan rejected: {reason}",
        "plan_approved": "Plan approved",
        "depends_on_failed": "Depends on {blocker}, which was not completed",
        "ws_done": "{id} completed: {title}",
        "ws_failed": "{id} closed with unfinished tasks",
        "ws_prepare_failed": "I can't organise {id}: {err}",
        "spawned": "I created you for {id} · {title}",
        "task_failed": "I can't complete \"{title}\": {err}",
        "lead_splitting": "Splitting the team's work…",
        "split_many": "{id} split into {n} subtasks:\n{listing}",
        "split_one": "{id}: handing it to the team as it is.",
        "subtasks_ready": "{n} subtasks ready",
        "skills_searching": "Looking for the right skills for {n} tasks",
        "skills_none": "No fitting skill: better none than a wrong one.",
        "briefs_rewriting": "Rewriting {n} briefs",
        "briefs_done": "Sharpened briefs for {ids}",
        "step_limit": "You used all {n} available steps without calling finish. Focus on the required files and deliver.",
        "awaiting_review": "Waiting for review",
        "delivered": "Delivered!",
        "task_delivered": "{id} delivered: {summary}",
        "default_feedback": "The reviewer asks to improve the work against the acceptance criteria.",
        "escalation_note": "Escalated to the \"{combo}\" model",
        "escalation_msg": "After {n} revisions I'm moving {id} to the stronger model ({combo}).",
        "still_failing": "Still not approved after the lead's help. Last feedback: {feedback}",
        "lead_skipped": "The lead decided to skip it: {guidance}",
        "lead_guidance": "Guidance from the lead: {guidance}\n\nLast reviewer feedback:\n{feedback}",
        "retry_stronger": "Retrying with a stronger model…",
        "fixing": "Fixing it from the feedback…",
        "missing_files": "Missing or empty files: {files}",
        "review_security": "Quality and security: \"{title}\"",
        "review_check": "Review: \"{title}\"",
        "ready_for_review": "Ready for review: {title}",
        "lesson_title": "Lesson · {title}",
        "approved_score": "Approved ({score}/10)",
        "approved_bubble": "Approved! {score}/10",
        "to_revise": "Needs another pass",
        "got_answer": "Got the answer, carrying on",
        "no_answer": "No answer, I'll decide myself",
        "stuck": "Stuck on \"{title}\" after {n} revisions.",
        "rescue_default": "Start again from the acceptance criteria, one by one.",
        "guidance_skip": "Let's skip this task: {guidance}",
        "guidance_retry": "Try again: {guidance}",
        "writing_report": "Writing the final report…",
        "mission_title": "Mission · {goal}",
        "report_ready": "Final report ready: REPORT.md",
    },
}

# D3 mirror: the frontend translates team labels by id; the backend needs the
# same names for the listings it writes into run messages.
TEAM_LABELS = {
    "en": {"research": "Research", "dev": "Development", "content": "Content", "design": "Design", "genai": "Generative AI", "prompt": "Prompt Lab", "skills": "Skill Hub", "qa": "Quality & Security"},
}


def tr(lang: str | None, key: str, **vars) -> str:
    return MESSAGES[check(lang) or DEFAULT][key].format(**vars)


def team_label(cfg: dict, team: str, lang: str | None) -> str:
    translated = TEAM_LABELS.get(check(lang) or DEFAULT, {}).get(team)
    return translated or (cfg["teams"].get(team) or {}).get("label") or team
