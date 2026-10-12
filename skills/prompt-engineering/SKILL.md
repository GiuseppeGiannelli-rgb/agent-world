---
name: prompt-engineering
description: Turn a vague request into a precise, testable prompt or brief for an AI agent or model. Use when writing briefs, system prompts, agent instructions or evaluation criteria.
---

# Prompt engineering

A strong brief answers six questions, in this order:
1. **Role**: who the model is and what it is good at.
2. **Goal**: the concrete result, in one sentence.
3. **Inputs**: which files, data or context to use, and what to ignore.
4. **Output**: exact format (files, JSON shape, length, language, tone).
5. **Constraints**: what must never happen (placeholders, invented facts, wrong language).
6. **Self-check**: a short checklist the model runs before answering.

## Techniques
- Show one good example when the format is unusual.
- Prefer positive instructions ("write in Italian") over negative ones.
- Put long reference material before the question, the instruction last.
- Ask for reasoning in a separate field when the answer must be JSON.
- Make acceptance criteria observable: "has a section titled Prices" beats "is complete".

## Deliverable format for a prompt library
For each prompt: name, purpose, the prompt itself, variables, an example input and output, known failure modes.
