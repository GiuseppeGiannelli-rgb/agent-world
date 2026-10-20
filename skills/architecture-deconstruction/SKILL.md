---
name: architecture-deconstruction
description: Deconstruct an existing application (source folder, repository, built artifact, bundle or execution trace) into a neutral, clean-room blueprint - architecture, data models, endpoints, business rules, edge cases and checkable parity criteria - without running it and without copying its code. Use for reverse engineering, audits of an unknown codebase and any rebuild that must start from a specification.
---

# Architecture deconstruction

You turn an application you did not write into a document another team can rebuild it from without ever seeing the original. The document describes behaviour; it never carries code.

## Method (in this order)

1. **Map before reading.** `scan_target_tree` on the target (usually `target/`, or `attachments/` for files the owner gave). Note the languages, the manifests, the entry points and the dependencies. The largest files are rarely the most important ones: start from the entry points.
2. **X-ray, don't read.** `extract_code_skeleton` on each entry point, then on the files they import. The skeleton gives signatures, routes, state and the internal call graph at a tenth of the size of the file. Use `read_file` only for a function whose behaviour the skeleton cannot tell (a validation rule, a calculation), and read just that part.
3. **Follow the data.** For every route: who calls it (front-end `fetch`, forms), what it receives, what it returns, which state it changes. For every piece of state: who writes it, who reads it.
4. **Use the evidence of execution.** Logs, HAR files and traces (`extract_code_skeleton` reads them too) show the real payloads and the real order of states: they settle what the code leaves ambiguous.
5. **Built artifacts.** For binaries, archives and bundles the X-ray gives the format, sections, exported and imported symbols, readable strings and entropy. High entropy means packed or encrypted: say so, do not guess what is inside.
6. **Write the blueprint** with `write_blueprint`. It validates the document and refuses copied code: fix what it lists and call it again.

## What a good blueprint holds

- **summary**: what the application does and for whom, in 2-5 sentences.
- **architecture**: the style (e.g. "single-page front-end + JSON API"), the stack, and every component with its responsibility.
- **dataModels**: every entity with its fields, types and which are required.
- **endpoints**: method, path, purpose, request and response shapes (field names and types, not example values), auth.
- **businessRules**: the rules the code enforces, each one testable ("a title is required and at most 120 characters").
- **edgeCases**: what happens with empty, too long, missing or duplicate input, unknown ids, concurrent changes.
- **parityCriteria**: checkable statements the rebuild must satisfy, one behaviour each ("POST /api/todos with an empty title answers 400"). The QA checks the rebuild against exactly these.

## Clean-room rules

- Describe behaviour and contracts, never implementation: no code, no copied comments, no private constant names unless they are part of a public contract (an endpoint path, a JSON field).
- Do not include secrets, keys, personal data or hostnames you find: note that they exist ("an API key is read from the environment").
- When something cannot be known without running the code, put it in `openQuestions` instead of guessing.
