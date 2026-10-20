"""Spec 11 T09: the intent of a mission (D30).

- direct_build: build something new (the flow of before, unchanged);
- reverse_only: deconstruct an existing application into a blueprint;
- deconstruct_and_build: deconstruct it, then rebuild it clean-room from the
  blueprint alone.

The CEO classifies the goal with a model call, but only when there is a reason
to: a word of reverse engineering or rebuilding in the goal (in any of the five
languages), a target folder, or code among the owner's files. A plain goal is
direct_build without a call, so the missions of before cost and behave exactly
as before. guess() is the rule the demo simulator follows and the fallback when
the CEO's answer is not usable."""

import re

INTENTS = ("direct_build", "reverse_only", "deconstruct_and_build")

REVERSE_RE = re.compile(
    r"reverse[- ]?engineer|ingegneria inversa|ingenier[ií]a inversa|r[ée]tro-?ing[ée]nierie|retro-?ingegneri|retroingenier"
    r"|decompil|d[ée]compil|disassembl|disassembla|d[ée]sassembl|dekompil"
    r"|deconstru|d[ée]construi|decostru|dekonstru|decodific|blueprint"
    # an existing application, in the order of each language
    r"|(?:existing|bestehende[nrs]?)\s+(?:app|application|code|codebase|site|website|program|anwendung|programm|webseite)"
    r"|(?:app|applicazione|aplicaci[oó]n|application|codice|c[oó]digo|code|sito|sitio|site|programma|programa|programme)\s+(?:esistente|existente|existante)"
    r"|analy[sz]e (?:the |this |an |its )?(?:existing )?(?:code|codebase|source|repo|repository|app|application|binary|bundle|program)"
    r"|analizza(?:re)? (?:il |lo |la |l'|questo |questa |quest'|un |una )?(?:codice|repo|repository|progetto esistente|app|applicazione|binario|bundle|programma)"
    r"|analiza(?:r)? (?:el |la |este |esta |un |una )?(?:c[oó]digo|repo|repositorio|app|aplicaci[oó]n|binario|bundle|programa)"
    r"|analyse(?:r)? (?:le |la |l'|ce |cette |un |une )?(?:code|d[ée]p[oô]t|app|application|binaire|bundle|programme)"
    r"|analysiere(?:n)? (?:den |die |das |diesen |diese |dieses )?(?:code|quellcode|repo|repository|app|anwendung|binary|bundle|programm)"
    r"|how (?:does )?(?:this|the) (?:app|application|code|program|binary) works|come funziona (?:questa|questo|il|la|l') ?(?:app|applicazione|codice|programma)",
    re.IGNORECASE,
)
REBUILD_RE = re.compile(
    r"\brebuild|re-?create|re-?implement|rewrite|clean[- ]?room|\bclone\b|\bclon(?:a|are|ala|alo)\b"
    r"|ricostru|ricrea|reimplementa|riscriv"
    r"|reconstru|recrea|reimplementa|reescrib"
    r"|reconstrui|recr[ée]e|r[ée]impl[ée]ment|r[ée][ée]cri"
    r"|nachbau|neu (?:auf)?bau|neu schreib|neu implement|klon|\bneu\b",  # "baue die Anwendung neu": the separable verb
    re.IGNORECASE,
)

# what the owner may give as the target among the attachments: code and builds
CODE_EXT = {
    ".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".rs", ".go", ".java", ".kt", ".rb", ".php", ".c", ".h", ".cpp", ".cs",
    ".swift", ".html", ".htm", ".css", ".scss", ".vue", ".svelte", ".sql", ".sh",
    ".so", ".dll", ".exe", ".dylib", ".wasm", ".jar", ".whl", ".apk", ".class", ".zip", ".tar", ".gz", ".tgz", ".har", ".log",
}


def cue(goal: str, has_target: bool) -> bool:
    """A reason to ask the CEO what kind of mission this is."""
    return has_target or bool(REVERSE_RE.search(goal or "") or REBUILD_RE.search(goal or ""))


def guess(goal: str, has_target: bool) -> str:
    """The intent from the goal's words alone (demo, fallback)."""
    reverse = bool(REVERSE_RE.search(goal or ""))
    rebuild = bool(REBUILD_RE.search(goal or ""))
    if rebuild and (reverse or has_target):
        return "deconstruct_and_build"
    if reverse or has_target:
        return "reverse_only"
    return "direct_build"
