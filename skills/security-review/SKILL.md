---
name: security-review
description: Review web code (HTML, JavaScript, Node, Python) for common vulnerabilities before delivery - XSS, injection, secrets, unsafe dependencies. Use for any code deliverable and for QA of developer work.
---

# Security review

Check each item and report the file and line of every problem.

## Injection
- User or external data inserted into HTML with `innerHTML`, `outerHTML`, `document.write` or template strings without escaping (XSS).
- SQL built by string concatenation instead of parameters.
- Shell commands built from input (`exec`, `spawn` with `shell: true`, `os.system`).
- `eval`, `new Function`, `setTimeout(string)`.

## Secrets and data
- API keys, tokens or passwords in code, config committed to the repo, or front-end bundles.
- Personal data logged or sent to third parties.

## Web specifics
- `target="_blank"` links without `rel="noopener noreferrer"`.
- Forms posting to `http://` or to unknown domains.
- Scripts loaded from unknown CDNs without a pinned version.

## Verdict
A real, exploitable problem means the work goes back with a precise fix. Style issues are not security issues.
