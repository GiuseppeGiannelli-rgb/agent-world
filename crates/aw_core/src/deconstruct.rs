//! Spec 11 T06: the twin of `backend/backend/deconstructor.py` (rule 2 of the
//! spec, D26). Every function here has the name of its Python original without
//! the leading underscore, and follows it line by line: the same character
//! scanners, the same ASCII-only rules, the same limits, the same order. The
//! three entry points return JSON; the Python side compares it with its own
//! result on DECONSTRUCT_PROBES at startup and uses this module only when every
//! probe matches (zero tolerance), so a divergence costs speed, never results.

use serde_json::{json, Map, Value};
use std::collections::{HashMap, HashSet};

type C = Vec<char>;

const MAX_LINES: usize = 20000;
const SIG_MAX: usize = 160;
const VALUE_MAX: usize = 60;
const CAP_IMPORTS: usize = 80;
const CAP_EXPORTS: usize = 80;
const CAP_SYMBOLS: usize = 300;
const CAP_ROUTES: usize = 80;
const CAP_STATE: usize = 120;
const CAP_CALLS: usize = 300;

// ---------- small helpers ----------

fn cv(s: &str) -> C {
    s.chars().collect()
}

fn sv(v: &[char]) -> String {
    v.iter().collect()
}

fn is_ws(c: char) -> bool {
    matches!(c, ' ' | '\t' | '\r' | '\n' | '\x0b' | '\x0c')
}

fn strip(v: &[char]) -> &[char] {
    let mut a = 0;
    let mut b = v.len();
    while a < b && is_ws(v[a]) {
        a += 1;
    }
    while b > a && is_ws(v[b - 1]) {
        b -= 1;
    }
    &v[a..b]
}

/// Python's v[a:b] for 0 <= a, b: clamped, never a panic.
fn sl(v: &[char], a: usize, b: usize) -> &[char] {
    let n = v.len();
    let a = a.min(n);
    let b = b.min(n).max(a);
    &v[a..b]
}

fn tail(v: &[char], a: usize) -> &[char] {
    sl(v, a, v.len())
}

fn at(v: &[char], i: usize, pat: &str) -> bool {
    let mut k = i;
    for c in pat.chars() {
        if k >= v.len() || v[k] != c {
            return false;
        }
        k += 1;
    }
    true
}

fn at_chars(v: &[char], i: usize, pat: &[char]) -> bool {
    i + pat.len() <= v.len() && &v[i..i + pat.len()] == pat
}

fn starts(v: &[char], pat: &str) -> bool {
    at(v, 0, pat)
}

fn ends(v: &[char], pat: &str) -> bool {
    let p = cv(pat);
    p.len() <= v.len() && v[v.len() - p.len()..] == p[..]
}

fn find(v: &[char], pat: &str, from: usize) -> Option<usize> {
    let p = cv(pat);
    let n = v.len();
    let m = p.len();
    let mut i = from;
    while i + m <= n {
        if v[i..i + m] == p[..] {
            return Some(i);
        }
        i += 1;
    }
    None
}

fn rfind(v: &[char], pat: &str) -> Option<usize> {
    let p = cv(pat);
    if p.len() > v.len() {
        return None;
    }
    let mut i = v.len() - p.len() + 1;
    while i > 0 {
        i -= 1;
        if v[i..i + p.len()] == p[..] {
            return Some(i);
        }
    }
    None
}

fn has(v: &[char], pat: &str) -> bool {
    find(v, pat, 0).is_some()
}

fn count(v: &[char], c: char) -> usize {
    v.iter().filter(|&&x| x == c).count()
}

fn alower(v: &[char]) -> C {
    v.iter().map(|c| c.to_ascii_lowercase()).collect()
}

fn aupper(v: &[char]) -> C {
    v.iter().map(|c| c.to_ascii_uppercase()).collect()
}

fn collapse(v: &[char]) -> C {
    let mut out: C = Vec::new();
    let mut space = false;
    for &c in v {
        if is_ws(c) {
            space = true;
        } else {
            if space && !out.is_empty() {
                out.push(' ');
            }
            space = false;
            out.push(c);
        }
    }
    out
}

fn clip(v: &[char], n: usize) -> C {
    if v.len() <= n {
        v.to_vec()
    } else {
        let mut out = v[..n - 1].to_vec();
        out.push('…');
        out
    }
}

fn tidy(v: &[char]) -> C {
    cv(&sv(&collapse(v)).replace("( ", "(").replace(" )", ")").replace(",)", ")"))
}

fn no_end(v: &[char]) -> C {
    let s = strip(v);
    if ends(s, ";") || ends(s, ",") {
        strip(&s[..s.len() - 1]).to_vec()
    } else {
        s.to_vec()
    }
}

fn is_ident_start(c: char) -> bool {
    c.is_ascii_alphabetic() || c == '_' || c == '$' || (c as u32) >= 128
}

fn is_digit(c: char) -> bool {
    c.is_ascii_digit()
}

fn is_ident(c: char) -> bool {
    is_ident_start(c) || is_digit(c)
}

fn read_ident(s: &[char], i: usize) -> (C, usize) {
    let mut j = i;
    while j < s.len() && is_ident(s[j]) {
        j += 1;
    }
    (sl(s, i, j).to_vec(), j.max(i))
}

fn read_path(s: &[char], i: usize) -> (C, usize) {
    let mut j = i;
    while j < s.len() && (is_ident(s[j]) || s[j] == '.' || (s[j] == ':' && j + 1 < s.len() && s[j + 1] == ':')) {
        j += if s[j] == ':' { 2 } else { 1 };
    }
    (sl(s, i, j).to_vec(), j.max(i))
}

fn ident_before(s: &[char], end: usize) -> C {
    let mut k = end;
    while k > 0 && is_ident(s[k - 1]) {
        k -= 1;
    }
    s[k..end].to_vec()
}

fn word_at(s: &[char], i: usize, word: &str) -> bool {
    if !at(s, i, word) {
        return false;
    }
    let after = i + word.chars().count();
    (after >= s.len() || !is_ident(s[after])) && (i == 0 || !is_ident(s[i - 1]))
}

fn skip_spaces(s: &[char], i: usize) -> usize {
    let mut i = i;
    while i < s.len() && (s[i] == ' ' || s[i] == '\t') {
        i += 1;
    }
    i
}

fn is_quote(c: char) -> bool {
    c == '\'' || c == '"' || c == '`'
}

fn literal(s: &[char], i: usize) -> Option<(C, usize)> {
    let mut i = i;
    while i < s.len() && !is_quote(s[i]) {
        i += 1;
    }
    if i >= s.len() {
        return None;
    }
    let q = s[i];
    let mut j = i + 1;
    while j < s.len() {
        if s[j] == '\\' {
            j += 2;
            continue;
        }
        if s[j] == q {
            return Some((s[i + 1..j].to_vec(), j + 1));
        }
        j += 1;
    }
    None
}

fn literal_here(s: &[char], i: usize) -> Option<(C, usize)> {
    let j = skip_spaces(s, i);
    if j >= s.len() || !is_quote(s[j]) {
        return None;
    }
    literal(s, j)
}

fn indent(line: &[char]) -> usize {
    let mut n = 0;
    for &c in line {
        if c == ' ' {
            n += 1;
        } else if c == '\t' {
            n += 4;
        } else {
            break;
        }
    }
    n
}

fn upto<'a>(s: &'a [char], stop: &str) -> &'a [char] {
    for (k, &c) in s.iter().enumerate() {
        if stop.contains(c) {
            return &s[..k];
        }
    }
    s
}

fn join(parts: &[C], sep: &str) -> C {
    let mut out: C = Vec::new();
    for (k, p) in parts.iter().enumerate() {
        if k > 0 {
            out.extend(sep.chars());
        }
        out.extend_from_slice(p);
    }
    out
}

fn cat(a: &str, b: &[char]) -> C {
    let mut out = cv(a);
    out.extend_from_slice(b);
    out
}

fn split<'a>(s: &'a [char], sep: char) -> Vec<&'a [char]> {
    s.split(|&c| c == sep).collect()
}

// ---------- comments and strings ----------

fn string_open(t: &[char], i: usize, lang: &str) -> Option<(usize, C, bool, bool)> {
    let n = t.len();
    let c = t[i];
    match lang {
        "python" => {
            if at(t, i, "\"\"\"") || at(t, i, "'''") {
                return Some((3, t[i..i + 3].to_vec(), true, true));
            }
            if c == '"' || c == '\'' {
                return Some((1, vec![c], false, true));
            }
            None
        }
        "javascript" | "typescript" => {
            if c == '"' || c == '\'' {
                Some((1, vec![c], false, true))
            } else if c == '`' {
                Some((1, vec!['`'], true, true))
            } else {
                None
            }
        }
        "css" => {
            if c == '"' || c == '\'' {
                Some((1, vec![c], false, true))
            } else {
                None
            }
        }
        "rust" => {
            if c == '"' {
                return Some((1, vec!['"'], true, true));
            }
            if (c == 'r' || c == 'b') && (i == 0 || !is_ident(t[i - 1])) {
                let mut j = i;
                if t[j] == 'b' {
                    j += 1;
                }
                let mut raw = false;
                if j < n && t[j] == 'r' {
                    raw = true;
                    j += 1;
                }
                let mut hashes = 0;
                while raw && j < n && t[j] == '#' {
                    hashes += 1;
                    j += 1;
                }
                if j < n && t[j] == '"' && (raw || t[i] == 'b') {
                    let mut d = vec!['"'];
                    for _ in 0..hashes {
                        d.push('#');
                    }
                    return Some((j + 1 - i, d, true, !raw));
                }
            }
            None
        }
        _ => None,
    }
}

fn clean(text: &[char], lang: &str) -> (Vec<C>, Vec<C>) {
    let hash_comments = lang == "python";
    let slash_comments = matches!(lang, "javascript" | "typescript" | "rust");
    let block_comments = matches!(lang, "javascript" | "typescript" | "rust" | "css");
    let mut code_lines: Vec<C> = Vec::new();
    let mut kept_lines: Vec<C> = Vec::new();
    let mut code: C = Vec::new();
    let mut kept: C = Vec::new();
    let n = text.len();
    let mut i = 0;
    let mut state = 0u8;
    let mut delim: C = Vec::new();
    let mut multiline = false;
    let mut escapes = true;
    while i < n {
        let c = text[i];
        if c == '\n' {
            code_lines.push(std::mem::take(&mut code));
            kept_lines.push(std::mem::take(&mut kept));
            if state == 2 && !multiline {
                state = 0;
            }
            i += 1;
            continue;
        }
        if c == '\r' {
            i += 1;
            continue;
        }
        if state == 1 {
            if c == '*' && i + 1 < n && text[i + 1] == '/' {
                state = 0;
                i += 2;
            } else {
                i += 1;
            }
            continue;
        }
        if state == 2 {
            if escapes && c == '\\' {
                kept.push(c);
                if i + 1 < n && text[i + 1] != '\r' && text[i + 1] != '\n' {
                    kept.push(text[i + 1]);
                    i += 2;
                } else {
                    i += 1;
                }
                continue;
            }
            if at_chars(text, i, &delim) {
                kept.extend_from_slice(&delim);
                state = 0;
                i += delim.len();
                continue;
            }
            kept.push(c);
            i += 1;
            continue;
        }
        if (hash_comments && c == '#') || (slash_comments && c == '/' && i + 1 < n && text[i + 1] == '/') {
            while i < n && text[i] != '\n' {
                i += 1;
            }
            continue;
        }
        if block_comments && c == '/' && i + 1 < n && text[i + 1] == '*' {
            state = 1;
            i += 2;
            continue;
        }
        if let Some((length, d, ml, esc)) = string_open(text, i, lang) {
            delim = d;
            multiline = ml;
            escapes = esc;
            code.push('"');
            code.push('"');
            kept.extend_from_slice(&text[i..i + length]);
            state = 2;
            i += length;
            continue;
        }
        if lang == "rust" && c == '\'' {
            if i + 2 < n && text[i + 1] != '\\' && text[i + 1] != '\n' && text[i + 2] == '\'' {
                code.push('"');
                code.push('"');
                kept.extend_from_slice(&text[i..i + 3]);
                i += 3;
                continue;
            }
            if i + 1 < n && text[i + 1] == '\\' {
                let mut k = i + 3;
                while k < n && k < i + 12 && text[k] != '\'' && text[k] != '\n' {
                    k += 1;
                }
                if k < n && text[k] == '\'' {
                    code.push('"');
                    code.push('"');
                    kept.extend_from_slice(&text[i..k + 1]);
                    i = k + 1;
                    continue;
                }
            }
        }
        code.push(c);
        kept.push(c);
        i += 1;
    }
    code_lines.push(code);
    kept_lines.push(kept);
    (code_lines, kept_lines)
}

// ---------- the result ----------

struct Sym {
    kind: String,
    name: String,
    line: i64,
    signature: String,
    parent: String,
}

struct Route {
    method: String,
    path: String,
    handler: String,
    line: i64,
    side: String,
}

struct St {
    name: String,
    line: i64,
    value: String,
    parent: String,
}

struct Out {
    language: String,
    lines: i64,
    imports: Vec<String>,
    exports: Vec<String>,
    symbols: Vec<Sym>,
    routes: Vec<Route>,
    state: Vec<St>,
    calls: Vec<(String, String)>,
    truncated: bool,
    seen: HashSet<String>,
}

impl Out {
    fn new(language: &str, lines: usize) -> Out {
        Out {
            language: language.to_string(),
            lines: lines as i64,
            imports: Vec::new(),
            exports: Vec::new(),
            symbols: Vec::new(),
            routes: Vec::new(),
            state: Vec::new(),
            calls: Vec::new(),
            truncated: false,
            seen: HashSet::new(),
        }
    }

    fn room(&mut self, len: usize, cap: usize) -> bool {
        if len >= cap {
            self.truncated = true;
            return false;
        }
        true
    }

    fn add_import(&mut self, text: &[char]) {
        let text = sv(&clip(&no_end(&collapse(text)), SIG_MAX));
        let key = format!("i\u{0}{}", text);
        if !text.is_empty() && !self.seen.contains(&key) && self.room(self.imports.len(), CAP_IMPORTS) {
            self.seen.insert(key);
            self.imports.push(text);
        }
    }

    fn add_export(&mut self, name: &[char]) {
        let name = sv(&clip(&collapse(name), SIG_MAX));
        let key = format!("e\u{0}{}", name);
        if !name.is_empty() && !self.seen.contains(&key) && self.room(self.exports.len(), CAP_EXPORTS) {
            self.seen.insert(key);
            self.exports.push(name);
        }
    }

    fn symbol(&mut self, kind: &str, name: &[char], line: i64, signature: &[char], parent: &[char]) {
        if !name.is_empty() && self.room(self.symbols.len(), CAP_SYMBOLS) {
            self.symbols.push(Sym { kind: kind.to_string(), name: sv(name), line, signature: sv(&clip(&tidy(signature), SIG_MAX)), parent: sv(parent) });
        }
    }

    fn route(&mut self, method: &[char], path: &[char], handler: &[char], line: i64, side: &str) {
        if self.room(self.routes.len(), CAP_ROUTES) {
            self.routes.push(Route { method: sv(method), path: sv(&clip(path, SIG_MAX)), handler: sv(handler), line, side: side.to_string() });
        }
    }

    fn add_state(&mut self, name: &[char], value: &[char], line: i64, parent: &[char]) {
        let key = format!("s\u{0}{}\u{0}{}", sv(parent), sv(name));
        if !name.is_empty() && !self.seen.contains(&key) && self.room(self.state.len(), CAP_STATE) {
            self.seen.insert(key);
            self.state.push(St { name: sv(name), line, value: sv(&clip(&no_end(&collapse(value)), VALUE_MAX)), parent: sv(parent) });
        }
    }

    fn call(&mut self, from: &str, to: &str) {
        let key = format!("c\u{0}{}\u{0}{}", from, to);
        if !self.seen.contains(&key) && self.room(self.calls.len(), CAP_CALLS) {
            self.seen.insert(key);
            self.calls.push((from.to_string(), to.to_string()));
        }
    }

    fn merge(&mut self, other: &Out, offset: i64) {
        for x in &other.imports {
            self.add_import(&cv(x));
        }
        for x in &other.exports {
            self.add_export(&cv(x));
        }
        for s in &other.symbols {
            self.symbol(&s.kind, &cv(&s.name), s.line + offset, &cv(&s.signature), &cv(&s.parent));
        }
        for r in &other.routes {
            self.route(&cv(&r.method), &cv(&r.path), &cv(&r.handler), r.line + offset, &r.side);
        }
        for s in &other.state {
            self.add_state(&cv(&s.name), &cv(&s.value), s.line + offset, &cv(&s.parent));
        }
        for (f, t) in &other.calls {
            self.call(f, t);
        }
        self.truncated = self.truncated || other.truncated;
    }

    fn result(&self) -> Value {
        json!({
            "language": self.language,
            "lines": self.lines,
            "imports": self.imports,
            "exports": self.exports,
            "symbols": self.symbols.iter().map(|s| json!({"kind": s.kind, "name": s.name, "line": s.line, "signature": s.signature, "parent": s.parent})).collect::<Vec<_>>(),
            "routes": self.routes.iter().map(|r| json!({"method": r.method, "path": r.path, "handler": r.handler, "line": r.line, "side": r.side})).collect::<Vec<_>>(),
            "state": self.state.iter().map(|s| json!({"name": s.name, "line": s.line, "value": s.value, "parent": s.parent})).collect::<Vec<_>>(),
            "calls": self.calls.iter().map(|(f, t)| json!({"from": f, "to": t})).collect::<Vec<_>>(),
            "truncated": self.truncated,
        })
    }
}

/// (form, a, b): 0 bare name(, 1 self.name( / this.name( / Self::name(, 2 Type::name(.
fn scan_calls(s: &[char], self_word: &str, rust: bool) -> Vec<(u8, C, C)> {
    let mut res = Vec::new();
    let n = s.len();
    let mut j = 0;
    let sw = cv(self_word);
    while j < n {
        if is_ident_start(s[j]) && (j == 0 || !is_ident(s[j - 1])) {
            let (name, k) = read_ident(s, j);
            let m = skip_spaces(s, k);
            if m < n && s[m] == '(' {
                if j >= 1 && s[j - 1] == '.' {
                    if ident_before(s, j - 1) == sw {
                        res.push((1, name, Vec::new()));
                    }
                } else if rust && j >= 2 && s[j - 1] == ':' && s[j - 2] == ':' {
                    let recv = ident_before(s, j - 2);
                    if recv == cv("Self") {
                        res.push((1, name, Vec::new()));
                    } else if !recv.is_empty() {
                        res.push((2, recv, name));
                    }
                } else {
                    res.push((0, name, Vec::new()));
                }
            }
            j = k;
        } else {
            j += 1;
        }
    }
    res
}

struct Cand {
    caller: String,
    cls: String,
    form: u8,
    a: String,
    b: String,
}

struct Defs {
    functions: HashSet<String>,
    classes: HashSet<String>,
    methods: HashSet<String>,
}

impl Defs {
    fn new() -> Defs {
        Defs { functions: HashSet::new(), classes: HashSet::new(), methods: HashSet::new() }
    }
}

fn resolve(out: &mut Out, cands: &[Cand], defs: &Defs, sep: &str) {
    for c in cands {
        let mut to = String::new();
        if c.form == 1 {
            if !c.cls.is_empty() && defs.methods.contains(&format!("{}\u{0}{}", c.cls, c.a)) {
                to = format!("{}{}{}", c.cls, sep, c.a);
            }
        } else if c.form == 2 {
            if defs.methods.contains(&format!("{}\u{0}{}", c.a, c.b)) {
                to = format!("{}{}{}", c.a, sep, c.b);
            }
        } else if defs.functions.contains(&format!("{}{}{}", c.caller, sep, c.a)) {
            to = format!("{}{}{}", c.caller, sep, c.a);
        } else if defs.functions.contains(&c.a) {
            to = c.a.clone();
        } else if defs.classes.contains(&c.a) {
            to = c.a.clone();
        }
        if !to.is_empty() {
            out.call(&c.caller, &to);
        }
    }
}

fn add_cands(cands: &mut Vec<Cand>, caller: &str, cls: &str, found: Vec<(u8, C, C)>) {
    for (form, a, b) in found {
        cands.push(Cand { caller: caller.to_string(), cls: cls.to_string(), form, a: sv(&a), b: sv(&b) });
    }
}

// ---------- Python ----------

const PY_KEYWORDS: &[&str] = &[
    "if", "elif", "else", "for", "while", "return", "with", "try", "except", "finally", "raise", "assert", "del", "pass", "break",
    "continue", "global", "nonlocal", "lambda", "yield", "await", "not", "and", "or", "in", "is", "import", "from", "class", "def",
    "async", "match", "case", "None", "True", "False", "print", "self",
];
const PY_ROUTE_METHODS: &[&str] = &["get", "post", "put", "patch", "delete", "head", "options", "route", "api_route", "websocket"];

fn py_header(code: &[C], i: usize) -> (usize, C) {
    let mut parts: Vec<C> = Vec::new();
    let mut depth: i64 = 0;
    let mut k = i;
    while k < code.len() && k < i + 12 {
        let line = &code[k];
        for (idx, &c) in line.iter().enumerate() {
            if c == '(' || c == '[' || c == '{' {
                depth += 1;
            } else if c == ')' || c == ']' || c == '}' {
                depth -= 1;
            } else if c == ':' && depth <= 0 {
                parts.push(line[..idx].to_vec());
                return (k, collapse(&join(&parts, " ")));
            }
        }
        parts.push(line.clone());
        k += 1;
    }
    (i, collapse(&code[i]))
}

fn py_assignment(s: &[char]) -> Option<(C, i64)> {
    let (name, j) = read_ident(s, 0);
    if name.is_empty() || PY_KEYWORDS.contains(&sv(&name).as_str()) || is_digit(name[0]) {
        return None;
    }
    let j = skip_spaces(s, j);
    if j < s.len() && s[j] == ':' {
        return match find(s, "=", j) {
            None => Some((name, -1)),
            Some(k) => {
                if k + 1 < s.len() && s[k + 1] == '=' {
                    None
                } else {
                    Some((name, k as i64))
                }
            }
        };
    }
    if j < s.len() && s[j] == '=' && !(j + 1 < s.len() && s[j + 1] == '=') {
        return Some((name, j as i64));
    }
    None
}

fn bracket_end(code: &[C], i: usize, limit: usize) -> usize {
    let mut depth: i64 = 0;
    let mut k = i;
    while k < code.len() && k < i + limit {
        for &c in &code[k] {
            if c == '(' || c == '[' || c == '{' {
                depth += 1;
            } else if c == ')' || c == ']' || c == '}' {
                depth -= 1;
            }
        }
        if depth <= 0 {
            return k;
        }
        k += 1;
    }
    if k > i {
        k.min(code.len()) - 1
    } else {
        i
    }
}

fn py_route(d: &[char], handler: &[char], line: i64, out: &mut Out) {
    let (dotted, j) = read_path(d, 1);
    if !dotted.contains(&'.') || j >= d.len() || d[j] != '(' {
        return;
    }
    let method = alower(&dotted[rfind(&dotted, ".").map(|k| k + 1).unwrap_or(0)..]);
    let ms = sv(&method);
    if !PY_ROUTE_METHODS.contains(&ms.as_str()) {
        return;
    }
    let lit = match literal_here(d, j + 1) {
        Some(l) if starts(&l.0, "/") => l,
        _ => return,
    };
    let verb: C = if ms == "route" || ms == "api_route" {
        match find(d, "methods", 0).and_then(|k| literal(d, k)) {
            Some(m) => aupper(&m.0),
            None => cv("GET"),
        }
    } else if ms == "websocket" {
        cv("WS")
    } else {
        aupper(&method)
    };
    out.route(&verb, &lit.0, handler, line, "server");
}

struct Frame {
    indent: usize,
    is_class: bool,
    qual: String,
}

fn python(code: &[C], kept: &[C], out: &mut Out) {
    let mut stack: Vec<Frame> = Vec::new();
    let mut decorators: Vec<(C, i64)> = Vec::new();
    let mut cands: Vec<Cand> = Vec::new();
    let mut defs = Defs::new();
    let mut all_names: Option<Vec<C>> = None;
    let mut top_level: Vec<C> = Vec::new();
    let n = code.len();
    let mut i = 0;
    while i < n {
        let s = strip(&code[i]).to_vec();
        if s.is_empty() {
            i += 1;
            continue;
        }
        let ind = indent(&code[i]);
        while !stack.is_empty() && ind <= stack.last().unwrap().indent {
            stack.pop();
        }
        if s[0] == '@' {
            decorators.push((strip(&kept[i]).to_vec(), (i + 1) as i64));
            i += 1;
            continue;
        }
        let t: C = if word_at(&s, 0, "async") { strip(tail(&s, 5)).to_vec() } else { s.clone() };
        if word_at(&t, 0, "def") || word_at(&t, 0, "class") {
            let is_def = word_at(&t, 0, "def");
            let word_len = if is_def { 3 } else { 5 };
            let (name, _) = read_ident(&t, skip_spaces(&t, word_len));
            let (end, sig) = py_header(code, i);
            let parent = stack.last().map(|f| f.qual.clone()).unwrap_or_default();
            let qual = if parent.is_empty() { sv(&name) } else { format!("{}.{}", parent, sv(&name)) };
            if !name.is_empty() && !is_def {
                out.symbol("class", &name, (i + 1) as i64, &sig, &cv(&parent));
                defs.classes.insert(qual.clone());
                stack.push(Frame { indent: ind, is_class: true, qual: qual.clone() });
            } else if !name.is_empty() {
                let in_class = stack.last().map(|f| f.is_class).unwrap_or(false);
                out.symbol(if in_class { "method" } else { "function" }, &name, (i + 1) as i64, &sig, &cv(&parent));
                defs.functions.insert(qual.clone());
                if in_class {
                    defs.methods.insert(format!("{}\u{0}{}", parent, sv(&name)));
                }
                for (d, dl) in &decorators {
                    py_route(d, &name, *dl, out);
                }
                stack.push(Frame { indent: ind, is_class: false, qual: qual.clone() });
            }
            if !name.is_empty() && parent.is_empty() {
                top_level.push(name.clone());
            }
            decorators.clear();
            i = end + 1;
            continue;
        }
        decorators.clear();
        if word_at(&s, 0, "import") || (word_at(&s, 0, "from") && has(&s, " import ")) {
            let end = bracket_end(code, i, 30);
            let parts: Vec<C> = (i..=end).map(|k| strip(&kept[k]).to_vec()).collect();
            out.add_import(&join(&parts, " "));
            i = end + 1;
            continue;
        }
        let ks = strip(&kept[i]).to_vec();
        for f in ["path(", "re_path(", "url("] {
            if starts(&ks, f) {
                if let Some(lit) = literal_here(&ks, f.chars().count()) {
                    let rest = tail(&ks, lit.1);
                    let handler = match find(rest, ",", 0) {
                        Some(comma) => read_path(strip(tail(rest, comma + 1)), 0).0,
                        None => Vec::new(),
                    };
                    out.route(&cv("ANY"), &lit.0, &handler, (i + 1) as i64, "server");
                }
                break;
            }
        }
        let top_is_none = stack.is_empty();
        let top_is_class = stack.last().map(|f| f.is_class).unwrap_or(false);
        if top_is_none || top_is_class {
            if let Some((name, eq)) = py_assignment(&s) {
                if sv(&name) == "__all__" && top_is_none {
                    let end = bracket_end(code, i, 60);
                    let parts: Vec<C> = (i..=end).map(|k| kept[k].clone()).collect();
                    let text = join(&parts, " ");
                    let mut names: Vec<C> = Vec::new();
                    let mut p = find(&text, "=", 0).unwrap_or(0);
                    while let Some(lit) = literal(&text, p) {
                        names.push(lit.0);
                        p = lit.1;
                    }
                    all_names = Some(names);
                    i = end + 1;
                    continue;
                }
                let value: C = if eq >= 0 { strip(tail(&ks, eq as usize + 1)).to_vec() } else { Vec::new() };
                let parent = if top_is_none { String::new() } else { stack.last().unwrap().qual.clone() };
                out.add_state(&name, &value, (i + 1) as i64, &cv(&parent));
            }
        }
        let fn_entry = stack.iter().rev().find(|f| !f.is_class).map(|f| f.qual.clone());
        let cls_entry = stack.iter().rev().find(|f| f.is_class).map(|f| f.qual.clone());
        if fn_entry.is_some() && cls_entry.is_some() && starts(&s, "self.") {
            let (name, j) = read_ident(&s, 5);
            let j = skip_spaces(&s, j);
            if !name.is_empty() && j < s.len() && ((s[j] == '=' && !(j + 1 < s.len() && s[j + 1] == '=')) || s[j] == ':') {
                let value: C = match find(&s, "=", j) {
                    Some(eq) if eq < ks.len() => strip(tail(&ks, eq + 1)).to_vec(),
                    _ => Vec::new(),
                };
                out.add_state(&cat("self.", &name), &value, (i + 1) as i64, &cv(cls_entry.as_ref().unwrap()));
            }
        }
        if let Some(caller) = &fn_entry {
            let cls = cls_entry.clone().unwrap_or_default();
            add_cands(&mut cands, caller, &cls, scan_calls(&s, "self", false));
        }
        i += 1;
    }
    match all_names {
        Some(names) => {
            for x in names {
                out.add_export(&x);
            }
        }
        None => {
            for x in top_level {
                if !starts(&x, "_") {
                    out.add_export(&x);
                }
            }
        }
    }
    resolve(out, &cands, &defs, ".");
}

// ---------- JavaScript / TypeScript ----------

const JS_MODIFIERS: &[&str] = &["export", "default", "async", "static", "public", "private", "protected", "readonly", "declare", "abstract", "override", "get", "set"];
const JS_ROUTE_METHODS: &[&str] = &["get", "post", "put", "patch", "delete", "all", "use", "head", "options"];
const JS_CLIENTS: &[&str] = &["axios", "http", "api", "client", "ky", "$http", "request"];
const HTTP_VERBS: &[&str] = &["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"];

fn js_mods(s: &[char]) -> (C, bool, bool) {
    let mut exported = false;
    let mut default = false;
    let mut t = s.to_vec();
    let mut changed = true;
    while changed {
        changed = false;
        for w in JS_MODIFIERS {
            if word_at(&t, 0, w) {
                let wl = w.chars().count();
                let j = skip_spaces(&t, wl);
                if j > wl && j < t.len() && !"(=:<.,;)".contains(t[j]) {
                    if *w == "export" {
                        exported = true;
                    }
                    if *w == "default" {
                        default = true;
                    }
                    t = t[j..].to_vec();
                    changed = true;
                    break;
                }
            }
        }
    }
    (t, exported, default)
}

fn arrow_or_function(v: &[char]) -> bool {
    let mut v = strip(v).to_vec();
    if word_at(&v, 0, "async") {
        v = strip(tail(&v, 5)).to_vec();
    }
    if word_at(&v, 0, "function") {
        return true;
    }
    if starts(&v, "(") {
        let mut depth: i64 = 0;
        for (k, &c) in v.iter().enumerate() {
            if c == '(' {
                depth += 1;
            } else if c == ')' {
                depth -= 1;
                if depth == 0 {
                    let rest = strip(tail(&v, k + 1));
                    if starts(rest, ":") {
                        return has(rest, "=>");
                    }
                    return starts(rest, "=>");
                }
            }
        }
        return false;
    }
    let (name, k) = read_ident(&v, 0);
    !name.is_empty() && starts(strip(tail(&v, k)), "=>")
}

fn js_signature(s: &[char]) -> &[char] {
    if let Some(arrow) = find(s, "=>", 0) {
        return &s[..arrow + 2];
    }
    match find(s, "{", 0) {
        Some(brace) => &s[..brace],
        None => s,
    }
}

fn js_routes(ks: &[char], line: i64, out: &mut Out) {
    let n = ks.len();
    let mut j = 0;
    while j < n {
        if ks[j] == '.' && j > 0 {
            let recv = ident_before(ks, j);
            let (name, k) = read_ident(ks, j + 1);
            if !recv.is_empty() && !name.is_empty() && k < n && ks[k] == '(' {
                let low = sv(&alower(&name));
                let lit = literal_here(ks, k + 1);
                let lit_verb = lit.as_ref().map(|l| HTTP_VERBS.contains(&sv(&aupper(&l.0)).as_str())).unwrap_or(false);
                if low == "open" && lit.is_some() && lit_verb {
                    let l = lit.unwrap();
                    let c = skip_spaces(ks, l.1);
                    let path = if c < n && ks[c] == ',' { literal_here(ks, c + 1) } else { None };
                    if let Some(p) = path {
                        out.route(&aupper(&l.0), &p.0, &[], line, "client");
                    }
                } else if JS_ROUTE_METHODS.contains(&low.as_str()) && lit.as_ref().map(|l| starts(&l.0, "/") || starts(&l.0, "http")).unwrap_or(false) {
                    let l = lit.unwrap();
                    let client = JS_CLIENTS.contains(&sv(&recv).as_str());
                    if client || starts(&l.0, "/") {
                        let mut handler: C = Vec::new();
                        let rest = tail(ks, l.1);
                        if !client && !has(rest, "=>") && !has(rest, "function") {
                            let args: &[char] = match rfind(ks, ")") {
                                Some(close) if close > l.1 => &ks[l.1..close],
                                _ => tail(ks, l.1),
                            };
                            let last: C = if args.contains(&',') { strip(split(args, ',').last().unwrap()).to_vec() } else { Vec::new() };
                            let (path_name, e) = read_path(&last, 0);
                            if !path_name.is_empty() && e == last.len() {
                                handler = path_name;
                            }
                        }
                        out.route(&cv(&low.to_ascii_uppercase()), &l.0, &handler, line, if client { "client" } else { "server" });
                    }
                }
            }
            j = if !name.is_empty() { k } else { j + 1 };
            continue;
        }
        if word_at(ks, j, "fetch") && skip_spaces(ks, j + 5) < n && ks[skip_spaces(ks, j + 5)] == '(' {
            if let Some(l) = literal_here(ks, skip_spaces(ks, j + 5) + 1) {
                if starts(&l.0, "/") || starts(&l.0, "http") {
                    let m = find(ks, "method", l.1).and_then(|k| literal(ks, k));
                    let verb = match m {
                        Some(m) => aupper(&m.0),
                        None => cv("GET"),
                    };
                    out.route(&verb, &l.0, &[], line, "client");
                }
            }
            j += 5;
            continue;
        }
        j += 1;
    }
}

struct Cont {
    kind: String,
    name: String,
    depth: usize,
}

fn javascript(code: &[C], kept: &[C], out: &mut Out) {
    let mut depth: usize = 0;
    let mut conts: Vec<Cont> = Vec::new();
    let mut fns: Vec<(String, usize)> = Vec::new();
    let mut pending: Option<(String, String)> = None;
    let mut cands: Vec<Cand> = Vec::new();
    let mut defs = Defs::new();
    let mut skip_until: i64 = -1;
    for i in 0..code.len() {
        let s = strip(&code[i]).to_vec();
        let ks = strip(&kept[i]).to_vec();
        let start = depth;
        let opens = count(&code[i], '{');
        let closes = count(&code[i], '}');
        if !s.is_empty() && (i as i64) > skip_until {
            if pending.is_some() && s.contains(&'{') {
                let (kind, name) = pending.take().unwrap();
                if kind == "fn" {
                    fns.push((name, start + 1));
                } else {
                    conts.push(Cont { kind, name, depth: start + 1 });
                }
            } else if pending.is_some() && ends(&s, ";") {
                pending = None;
            }
            let cont = conts.last().map(|c| (c.kind.clone(), c.name.clone(), c.depth));
            let in_body = cont.as_ref().map(|c| start == c.2).unwrap_or(false);
            let cls = conts.iter().rev().find(|c| c.kind == "class").map(|c| c.name.clone()).unwrap_or_default();
            let caller = fns.last().map(|f| f.0.clone()).unwrap_or_default();
            let mut scan_from = 0usize;
            let mut new_caller = String::new();
            let (mut t, exported, is_default) = js_mods(&s);
            if in_body && cont.as_ref().unwrap().0 == "interface" {
                t = Vec::new();
            }
            if is_default {
                out.add_export(&cv("default"));
            }
            if !t.is_empty() && word_at(&t, 0, "import") && skip_spaces(&t, 6) < t.len() && !"(.".contains(t[skip_spaces(&t, 6)]) {
                let mut end = i;
                if code[i].contains(&'{') && !code[i].contains(&'}') {
                    end = (i + 1..code.len().min(i + 30)).find(|&k| code[k].contains(&'}')).unwrap_or(i);
                }
                let parts: Vec<C> = (i..=end).map(|k| strip(&kept[k]).to_vec()).collect();
                out.add_import(&join(&parts, " "));
                skip_until = end as i64;
                t = Vec::new();
            }
            if !t.is_empty() && has(&s, "require(") {
                out.add_import(&ks);
            }
            if !t.is_empty() && exported && starts(&t, "{") {
                let inner = upto(tail(&t, 1), "}").to_vec();
                for part in split(&inner, ',') {
                    let part = strip(part);
                    let name = match find(part, " as ", 0) {
                        Some(a) => read_ident(strip(tail(part, a + 4)), 0).0,
                        None => read_ident(part, 0).0,
                    };
                    out.add_export(&name);
                }
                if has(&s, " from ") {
                    out.add_import(&ks);
                }
                t = Vec::new();
            }
            if !t.is_empty() && exported && starts(&t, "*") {
                out.add_export(&cv("*"));
                out.add_import(&ks);
                t = Vec::new();
            }
            if !t.is_empty() && (starts(&t, "module.exports") || starts(&t, "exports.")) {
                let rest: C = if starts(&t, "module.exports") { tail(&t, 14).to_vec() } else { tail(&t, 7).to_vec() };
                if starts(&rest, ".") {
                    out.add_export(&read_ident(&rest, 1).0);
                } else {
                    let value: C = match find(&rest, "=", 0) {
                        Some(eq) => strip(tail(&rest, eq + 1)).to_vec(),
                        None => Vec::new(),
                    };
                    if starts(&value, "{") {
                        for part in split(upto(tail(&value, 1), "}"), ',') {
                            out.add_export(&read_ident(strip(part), 0).0);
                        }
                    } else {
                        let id = read_ident(&value, 0).0;
                        out.add_export(&if id.is_empty() { cv("module.exports") } else { id });
                    }
                }
                t = Vec::new();
            }
            if !t.is_empty() && word_at(&t, 0, "class") {
                let name = read_ident(&t, skip_spaces(&t, 5)).0;
                if !name.is_empty() {
                    out.symbol("class", &name, (i + 1) as i64, upto(&s, "{"), &cv(&caller));
                    defs.classes.insert(sv(&name));
                    if exported {
                        out.add_export(&name);
                    }
                    if s.contains(&'{') {
                        conts.push(Cont { kind: "class".into(), name: sv(&name), depth: start + 1 });
                    } else {
                        pending = Some(("class".into(), sv(&name)));
                    }
                }
                t = Vec::new();
            }
            for word in ["interface", "enum", "type"] {
                if !t.is_empty() && word_at(&t, 0, word) {
                    let (name, k) = read_ident(&t, skip_spaces(&t, word.len()));
                    if !name.is_empty() && (word != "type" || tail(&t, k).contains(&'=')) {
                        out.symbol(word, &name, (i + 1) as i64, upto(&s, if word == "type" { "{=" } else { "{" }), &[]);
                        if exported {
                            out.add_export(&name);
                        }
                        if s.contains(&'{') && count(&code[i], '{') > count(&code[i], '}') {
                            conts.push(Cont { kind: "interface".into(), name: sv(&name), depth: start + 1 });
                        }
                    }
                    t = Vec::new();
                }
            }
            if !t.is_empty() && word_at(&t, 0, "function") {
                let mut j = skip_spaces(&t, 8);
                if j < t.len() && t[j] == '*' {
                    j = skip_spaces(&t, j + 1);
                }
                let name = read_ident(&t, j).0;
                if !name.is_empty() {
                    let qual = if caller.is_empty() { sv(&name) } else { format!("{}.{}", caller, sv(&name)) };
                    out.symbol("function", &name, (i + 1) as i64, upto(&s, "{"), &cv(&caller));
                    defs.functions.insert(qual.clone());
                    if exported {
                        out.add_export(&name);
                    }
                    if s.contains(&'{') {
                        fns.push((qual.clone(), start + 1));
                        new_caller = qual;
                        scan_from = find(&s, "{", 0).unwrap() + 1;
                    } else if !ends(&s, ";") {
                        pending = Some(("fn".into(), qual));
                    }
                    t = Vec::new();
                }
            }
            for word in ["const", "let", "var"] {
                if !t.is_empty() && word_at(&t, 0, word) {
                    let v = strip(tail(&t, word.len())).to_vec();
                    if starts(&v, "[") {
                        if has(&s, "useState(") || has(&s, "useReducer(") {
                            let name = read_ident(strip(tail(&v, 1)), 0).0;
                            let value: C = match find(&ks, "use", 0) {
                                Some(u) => tail(&ks, u).to_vec(),
                                None => Vec::new(),
                            };
                            out.add_state(&name, &value, (i + 1) as i64, &cv(&caller));
                        }
                    } else if !starts(&v, "{") {
                        let (name, k) = read_ident(&v, 0);
                        let mut e = k;
                        while e < v.len() && !(v[e] == '=' && !(e + 1 < v.len() && (v[e + 1] == '=' || v[e + 1] == '>'))) {
                            e += 1;
                        }
                        let value: C = if e < v.len() { strip(tail(&v, e + 1)).to_vec() } else { Vec::new() };
                        if !name.is_empty() && arrow_or_function(&value) {
                            let qual = if caller.is_empty() { sv(&name) } else { format!("{}.{}", caller, sv(&name)) };
                            out.symbol("function", &name, (i + 1) as i64, js_signature(&s), &cv(&caller));
                            defs.functions.insert(qual.clone());
                            if exported {
                                out.add_export(&name);
                            }
                            let arrow = find(&s, "=>", 0);
                            let brace = find(&s, "{", 0);
                            let body: C = match arrow {
                                Some(a) => tail(&s, a + 2).to_vec(),
                                None => match brace {
                                    Some(b) => tail(&s, b + 1).to_vec(),
                                    None => Vec::new(),
                                },
                            };
                            if body.contains(&'{') {
                                fns.push((qual.clone(), start + 1));
                            }
                            new_caller = qual;
                            scan_from = match arrow {
                                Some(a) => a + 2,
                                None => match brace {
                                    Some(b) => b + 1,
                                    None => s.len(),
                                },
                            };
                        } else if !name.is_empty() && word_at(&value, 0, "class") {
                            out.symbol("class", &name, (i + 1) as i64, upto(&s, "{"), &cv(&caller));
                            defs.classes.insert(sv(&name));
                            if s.contains(&'{') {
                                conts.push(Cont { kind: "class".into(), name: sv(&name), depth: start + 1 });
                            }
                        } else if !name.is_empty() && !starts(&value, "require(") {
                            if exported {
                                out.add_export(&name);
                            }
                            if start == 0 && fns.is_empty() {
                                let value: C = match find(&ks, "=", 0) {
                                    Some(kv) if e < v.len() => strip(tail(&ks, kv + 1)).to_vec(),
                                    _ => Vec::new(),
                                };
                                out.add_state(&name, &value, (i + 1) as i64, &[]);
                            }
                        }
                    }
                    t = Vec::new();
                }
            }
            if !t.is_empty() && in_body && cont.as_ref().unwrap().0 == "class" {
                let cname = cont.as_ref().unwrap().1.clone();
                if starts(&t, "*") {
                    t = strip(tail(&t, 1)).to_vec();
                }
                let hash = starts(&t, "#");
                let (mut name, k) = read_ident(&t, if hash { 1 } else { 0 });
                if hash && !name.is_empty() {
                    name = cat("#", &name);
                }
                let k = skip_spaces(&t, k);
                let ns = sv(&name);
                if !name.is_empty() && k < t.len() && (t[k] == '(' || t[k] == '<') && !["if", "for", "while", "switch", "catch", "return"].contains(&ns.as_str()) {
                    let qual = format!("{}.{}", cname, ns);
                    out.symbol("method", &name, (i + 1) as i64, upto(&s, "{"), &cv(&cname));
                    defs.functions.insert(qual.clone());
                    defs.methods.insert(format!("{}\u{0}{}", cname, ns));
                    if s.contains(&'{') {
                        fns.push((qual.clone(), start + 1));
                        new_caller = qual;
                        scan_from = find(&s, "{", 0).unwrap() + 1;
                    } else if !ends(&s, ";") {
                        pending = Some(("fn".into(), qual));
                    }
                } else if !name.is_empty() && k < t.len() && t[k] == '=' && !(k + 1 < t.len() && t[k + 1] == '=') {
                    let value = strip(tail(&t, k + 1)).to_vec();
                    if arrow_or_function(&value) {
                        let qual = format!("{}.{}", cname, ns);
                        out.symbol("method", &name, (i + 1) as i64, js_signature(&s), &cv(&cname));
                        defs.functions.insert(qual.clone());
                        defs.methods.insert(format!("{}\u{0}{}", cname, ns));
                        // Python: s.find("=>") + 2, so 1 when there is no arrow
                        let arrow2 = find(&s, "=>", 0).map(|a| a + 2).unwrap_or(1);
                        if tail(&s, arrow2).contains(&'{') {
                            fns.push((qual.clone(), start + 1));
                        }
                        new_caller = qual;
                        scan_from = arrow2;
                    } else {
                        let value: C = match find(&ks, "=", 0) {
                            Some(kv) => strip(tail(&ks, kv + 1)).to_vec(),
                            None => Vec::new(),
                        };
                        out.add_state(&name, &value, (i + 1) as i64, &cv(&cname));
                    }
                } else if !name.is_empty() && (k >= t.len() || ":;?!".contains(t[k])) {
                    let value: C = match find(&ks, "=", 0) {
                        Some(kv) => strip(tail(&ks, kv + 1)).to_vec(),
                        None => Vec::new(),
                    };
                    out.add_state(&name, &value, (i + 1) as i64, &cv(&cname));
                }
            }
            if !cls.is_empty() && !fns.is_empty() && starts(&s, "this.") {
                let (name, j) = read_ident(&s, 5);
                let j = skip_spaces(&s, j);
                if !name.is_empty() && j < s.len() && s[j] == '=' && !(j + 1 < s.len() && s[j + 1] == '=') {
                    let value: C = match find(&ks, "=", 0) {
                        Some(kv) => strip(tail(&ks, kv + 1)).to_vec(),
                        None => Vec::new(),
                    };
                    out.add_state(&cat("this.", &name), &value, (i + 1) as i64, &cv(&cls));
                }
            }
            js_routes(&ks, (i + 1) as i64, out);
            let who = if new_caller.is_empty() { caller.clone() } else { new_caller.clone() };
            if !who.is_empty() {
                let part: &[char] = if new_caller.is_empty() { &s } else { tail(&s, scan_from) };
                add_cands(&mut cands, &who, &cls, scan_calls(part, "this", false));
            }
        }
        depth = (start as i64 + opens as i64 - closes as i64).max(0) as usize;
        while conts.last().map(|c| c.depth > depth).unwrap_or(false) {
            conts.pop();
        }
        while fns.last().map(|f| f.1 > depth).unwrap_or(false) {
            fns.pop();
        }
    }
    resolve(out, &cands, &defs, ".");
}

// ---------- Rust ----------

const RUST_ROUTE_ATTRS: &[&str] = &["get", "post", "put", "patch", "delete", "head", "options"];
const AXUM_METHODS: &[&str] = &["get", "post", "put", "patch", "delete", "head", "options", "any"];

fn rust_mods(s: &[char]) -> (C, bool) {
    let mut is_pub = false;
    let mut t = s.to_vec();
    let mut changed = true;
    while changed {
        changed = false;
        if word_at(&t, 0, "pub") {
            is_pub = true;
            let mut j = skip_spaces(&t, 3);
            if j < t.len() && t[j] == '(' {
                j = match find(&t, ")", j) {
                    Some(close) => skip_spaces(&t, close + 1),
                    None => t.len(),
                };
            }
            t = tail(&t, j).to_vec();
            changed = true;
            continue;
        }
        for w in ["async", "unsafe", "default"] {
            if word_at(&t, 0, w) && skip_spaces(&t, w.len()) > w.len() {
                t = tail(&t, skip_spaces(&t, w.len())).to_vec();
                changed = true;
                break;
            }
        }
        if changed {
            continue;
        }
        if word_at(&t, 0, "extern") && !word_at(&t, skip_spaces(&t, 6), "crate") {
            let mut j = skip_spaces(&t, 6);
            if at(&t, j, "\"\"") {
                j = skip_spaces(&t, j + 2);
            }
            t = tail(&t, j).to_vec();
            changed = true;
            continue;
        }
        if word_at(&t, 0, "const") {
            let j = skip_spaces(&t, 5);
            if word_at(&t, j, "fn") || word_at(&t, j, "unsafe") || word_at(&t, j, "async") || word_at(&t, j, "extern") {
                t = tail(&t, j).to_vec();
                changed = true;
            }
        }
    }
    (t, is_pub)
}

fn rust_header(code: &[C], i: usize) -> (usize, C, bool) {
    let mut parts: Vec<C> = Vec::new();
    let mut k = i;
    while k < code.len() && k < i + 12 {
        let line = &code[k];
        for (idx, &c) in line.iter().enumerate() {
            if c == '{' || c == ';' {
                parts.push(line[..idx].to_vec());
                return (k, collapse(&join(&parts, " ")), c == '{');
            }
        }
        parts.push(line.clone());
        k += 1;
    }
    (i, collapse(&code[i]), false)
}

fn rust_type_name(text: &[char]) -> C {
    let mut t = strip(text).to_vec();
    while starts(&t, "&") || starts(&t, "dyn ") || starts(&t, "mut ") {
        t = strip(if starts(&t, "&") { tail(&t, 1) } else { tail(&t, 4) }).to_vec();
    }
    let (path, _) = read_path(&t, 0);
    match rfind(&path, "::") {
        Some(cut) => path[cut + 2..].to_vec(),
        None => path,
    }
}

fn rust_attr_route(a: &[char], handler: &[char], line: i64, out: &mut Out) {
    if !starts(a, "#[") {
        return;
    }
    let (name, j) = read_ident(a, 2);
    let low = sv(&alower(&name));
    if j >= a.len() || a[j] != '(' {
        return;
    }
    let lit = match literal_here(a, j + 1) {
        Some(l) if starts(&l.0, "/") => l,
        _ => return,
    };
    if RUST_ROUTE_ATTRS.contains(&low.as_str()) {
        out.route(&cv(&low.to_ascii_uppercase()), &lit.0, handler, line, "server");
    } else if low == "route" {
        let verb = match find(a, "method", lit.1).and_then(|k| literal(a, k)) {
            Some(m) => aupper(&m.0),
            None => cv("ANY"),
        };
        out.route(&verb, &lit.0, handler, line, "server");
    }
}

fn axum_routes(ks: &[char], line: i64, out: &mut Out) {
    let mut p = find(ks, ".route(", 0);
    while let Some(pos) = p {
        let lit = match literal_here(ks, pos + 7) {
            Some(l) => l,
            None => break,
        };
        let nxt = find(ks, ".route(", lit.1);
        let seg: &[char] = match nxt {
            Some(x) => sl(ks, lit.1, x),
            None => tail(ks, lit.1),
        };
        let mut j = 0;
        while j < seg.len() {
            if is_ident_start(seg[j]) && (j == 0 || !is_ident(seg[j - 1])) {
                let (word, k) = read_ident(seg, j);
                let ws = sv(&word);
                if AXUM_METHODS.contains(&ws.as_str()) && k < seg.len() && seg[k] == '(' {
                    let handler = read_path(seg, skip_spaces(seg, k + 1)).0;
                    out.route(&cv(&ws.to_ascii_uppercase()), &lit.0, &handler, line, "server");
                }
                j = k;
            } else {
                j += 1;
            }
        }
        p = nxt;
    }
}

fn rust(code: &[C], kept: &[C], out: &mut Out) {
    let mut depth: usize = 0;
    let mut conts: Vec<Cont> = Vec::new();
    let mut fns: Vec<(String, usize)> = Vec::new();
    let mut pending: Option<(String, String)> = None;
    let mut attrs: Vec<(C, i64)> = Vec::new();
    let mut cands: Vec<Cand> = Vec::new();
    let mut defs = Defs::new();
    let mut skip_until: i64 = -1;
    for i in 0..code.len() {
        let s = strip(&code[i]).to_vec();
        let ks = strip(&kept[i]).to_vec();
        let start = depth;
        let opens = count(&code[i], '{');
        let closes = count(&code[i], '}');
        if !s.is_empty() && pending.is_some() && s.contains(&'{') {
            let (kind, name) = pending.take().unwrap();
            if kind == "fn" {
                fns.push((name, start + 1));
            } else {
                conts.push(Cont { kind, name, depth: start + 1 });
            }
        } else if !s.is_empty() && pending.is_some() && ends(&s, ";") {
            pending = None;
        }
        let attr_line = starts(&s, "#[") || starts(&s, "#![");
        if !s.is_empty() && (i as i64) > skip_until && attr_line {
            attrs.push((ks.clone(), (i + 1) as i64));
        } else if !s.is_empty() && (i as i64) > skip_until {
            let cont = conts.last().map(|c| (c.kind.clone(), c.name.clone(), c.depth));
            let in_body = cont.as_ref().map(|c| start == c.2).unwrap_or(false);
            let top = cont.is_none();
            let caller = fns.last().map(|f| f.0.clone()).unwrap_or_default();
            let imp = conts.iter().rev().find(|c| c.kind == "impl" || c.kind == "trait").map(|c| c.name.clone()).unwrap_or_default();
            let module = conts.iter().rev().find(|c| c.kind == "mod").map(|c| c.name.clone()).unwrap_or_default();
            let (t, is_pub) = rust_mods(&s);
            let mut new_caller = String::new();
            let mut scan_from = 0usize;
            if word_at(&t, 0, "use") || word_at(&t, 0, "extern") {
                let end = (i..code.len().min(i + 20)).find(|&k| code[k].contains(&';')).unwrap_or(i);
                let parts: Vec<C> = (i..=end).map(|k| strip(&kept[k]).to_vec()).collect();
                let mut text = rust_mods(&collapse(&join(&parts, " "))).0;
                if ends(&text, ";") {
                    text = strip(&text[..text.len() - 1]).to_vec();
                }
                out.add_import(&text);
                if is_pub && top {
                    out.add_export(&text);
                }
                skip_until = end as i64;
            } else if word_at(&t, 0, "mod") {
                let name = read_ident(&t, skip_spaces(&t, 3)).0;
                if s.contains(&'{') {
                    out.symbol("module", &name, (i + 1) as i64, upto(&s, "{"), &cv(&module));
                    conts.push(Cont { kind: "mod".into(), name: sv(&name), depth: start + 1 });
                } else if !name.is_empty() {
                    out.add_import(&cat("mod ", &name));
                }
                if is_pub && top && !name.is_empty() {
                    out.add_export(&name);
                }
            } else if word_at(&t, 0, "fn") {
                let name = read_ident(&t, skip_spaces(&t, 2)).0;
                let (end, sig, body) = rust_header(code, i);
                if !name.is_empty() {
                    let ns = sv(&name);
                    let kind: &str;
                    let parent: String;
                    let qual: String;
                    if in_body && (cont.as_ref().unwrap().0 == "impl" || cont.as_ref().unwrap().0 == "trait") {
                        kind = "method";
                        parent = cont.as_ref().unwrap().1.clone();
                        qual = format!("{}::{}", parent, ns);
                        defs.methods.insert(format!("{}\u{0}{}", parent, ns));
                    } else {
                        kind = "function";
                        parent = if caller.is_empty() { module.clone() } else { caller.clone() };
                        qual = if parent.is_empty() { ns.clone() } else { format!("{}::{}", parent, ns) };
                    }
                    out.symbol(kind, &name, (i + 1) as i64, &sig, &cv(&parent));
                    defs.functions.insert(qual.clone());
                    if is_pub && top {
                        out.add_export(&name);
                    }
                    for (a, al) in &attrs {
                        rust_attr_route(a, &name, *al, out);
                    }
                    if body && end == i {
                        fns.push((qual.clone(), start + 1));
                        new_caller = qual;
                        scan_from = find(&s, "{", 0).unwrap() + 1;
                    } else if body {
                        pending = Some(("fn".into(), qual));
                    }
                }
                if end > i {
                    skip_until = end as i64;
                }
            } else if word_at(&t, 0, "impl") {
                let mut j = skip_spaces(&t, 4);
                if j < t.len() && t[j] == '<' {
                    let mut level: i64 = 0;
                    while j < t.len() {
                        if t[j] == '<' {
                            level += 1;
                        } else if t[j] == '>' {
                            level -= 1;
                            if level == 0 {
                                j += 1;
                                break;
                            }
                        }
                        j += 1;
                    }
                }
                let mut head = upto(tail(&t, j), "{").to_vec();
                if let Some(w) = find(&head, " where ", 0) {
                    head.truncate(w);
                }
                let name = match find(&head, " for ", 0) {
                    Some(f) => rust_type_name(tail(&head, f + 5)),
                    None => rust_type_name(&head),
                };
                if !name.is_empty() {
                    out.symbol("impl", &name, (i + 1) as i64, upto(&s, "{"), &cv(&module));
                    defs.classes.insert(sv(&name));
                    if s.contains(&'{') {
                        conts.push(Cont { kind: "impl".into(), name: sv(&name), depth: start + 1 });
                    } else {
                        pending = Some(("impl".into(), sv(&name)));
                    }
                }
            } else {
                let word = ["struct", "enum", "trait", "union", "type", "const", "static", "macro_rules!"]
                    .iter()
                    .find(|w| starts(&t, w) && (w.ends_with('!') || word_at(&t, 0, w)))
                    .copied()
                    .unwrap_or("");
                if !word.is_empty() {
                    let mut j = skip_spaces(&t, word.chars().count());
                    if word == "static" && word_at(&t, j, "mut") {
                        j = skip_spaces(&t, j + 3);
                    }
                    let name = read_ident(&t, j).0;
                    if !name.is_empty() && (word == "const" || word == "static") {
                        let value: C = match find(&ks, "=", 0) {
                            Some(eq) => strip(upto(tail(&ks, eq + 1), ";")).to_vec(),
                            None => Vec::new(),
                        };
                        let in_scope = cont.as_ref().map(|c| (c.0 == "mod" || c.0 == "impl") && in_body).unwrap_or(false);
                        if top || in_scope {
                            let parent = if top { String::new() } else { cont.as_ref().unwrap().1.clone() };
                            out.add_state(&name, &value, (i + 1) as i64, &cv(&parent));
                        }
                        if is_pub && top {
                            out.add_export(&name);
                        }
                    } else if !name.is_empty() {
                        let kind = match word {
                            "macro_rules!" => "macro",
                            "union" => "struct",
                            w => w,
                        };
                        out.symbol(kind, &name, (i + 1) as i64, upto(&s, if word == "type" { "{;=" } else { "{;(" }), &cv(&module));
                        if ["struct", "enum", "trait", "union"].contains(&word) {
                            defs.classes.insert(sv(&name));
                            if s.contains(&'{') && count(&code[i], '{') > count(&code[i], '}') {
                                conts.push(Cont { kind: word.to_string(), name: sv(&name), depth: start + 1 });
                            }
                        }
                        if is_pub && top {
                            out.add_export(&name);
                        }
                    }
                } else if in_body && (cont.as_ref().unwrap().0 == "struct" || cont.as_ref().unwrap().0 == "union") {
                    let (name, k) = read_ident(&t, 0);
                    let k = skip_spaces(&t, k);
                    if !name.is_empty() && k < t.len() && t[k] == ':' && !at(&t, k, "::") {
                        let value = strip(upto(tail(&t, k + 1), ",")).to_vec();
                        out.add_state(&name, &value, (i + 1) as i64, &cv(&cont.as_ref().unwrap().1));
                    }
                }
            }
            if has(&ks, ".route(") {
                axum_routes(&ks, (i + 1) as i64, out);
            }
            attrs.clear();
            let who = if new_caller.is_empty() { caller.clone() } else { new_caller.clone() };
            if !who.is_empty() {
                let part: &[char] = if new_caller.is_empty() { &s } else { tail(&s, scan_from) };
                add_cands(&mut cands, &who, &imp, scan_calls(part, "self", true));
            }
        }
        depth = (start as i64 + opens as i64 - closes as i64).max(0) as usize;
        while conts.last().map(|c| c.depth > depth).unwrap_or(false) {
            conts.pop();
        }
        while fns.last().map(|f| f.1 > depth).unwrap_or(false) {
            fns.pop();
        }
    }
    resolve(out, &cands, &defs, "::");
}

// ---------- HTML and CSS ----------

fn tag(text: &[char], i: usize) -> (String, Vec<(String, C)>, usize) {
    let n = text.len();
    let mut j = i + 1;
    while j < n && (text[j].is_ascii_alphanumeric() || text[j] == '-') {
        j += 1;
    }
    let name = sv(&alower(&text[i + 1..j]));
    let mut attrs: Vec<(String, C)> = Vec::new();
    while j < n {
        while j < n && is_ws(text[j]) {
            j += 1;
        }
        if j >= n {
            break;
        }
        if text[j] == '>' {
            j += 1;
            break;
        }
        if text[j] == '/' {
            j += 1;
            continue;
        }
        let mut k = j;
        while k < n && !is_ws(text[k]) && !"=>/\"'".contains(text[k]) {
            k += 1;
        }
        if k == j {
            j += 1;
            continue;
        }
        let attr = sv(&alower(&text[j..k]));
        j = k;
        while j < n && is_ws(text[j]) {
            j += 1;
        }
        let mut value: C = Vec::new();
        if j < n && text[j] == '=' {
            j += 1;
            while j < n && is_ws(text[j]) {
                j += 1;
            }
            if j < n && (text[j] == '"' || text[j] == '\'') {
                let q = text[j];
                let e = (j + 1..n).find(|&x| text[x] == q).unwrap_or(n);
                value = sl(text, j + 1, e).to_vec();
                j = e + 1;
            } else {
                let mut e = j;
                while e < n && !is_ws(text[e]) && text[e] != '>' {
                    e += 1;
                }
                value = text[j..e].to_vec();
                j = e;
            }
        }
        if !attrs.iter().any(|(a, _)| *a == attr) {
            attrs.push((attr, value));
        }
    }
    (name, attrs, j)
}

fn attr<'a>(attrs: &'a [(String, C)], name: &str) -> Option<&'a C> {
    attrs.iter().find(|(a, _)| a == name).map(|(_, v)| v)
}

fn count_nl(text: &[char], a: usize, b: usize) -> i64 {
    count(sl(text, a, b), '\n') as i64
}

fn html(text: &[char], out: &mut Out) {
    let low = alower(text);
    let n = text.len();
    let mut i = 0;
    let mut line: i64 = 1;
    while i < n {
        let c = text[i];
        if c == '\n' {
            line += 1;
            i += 1;
            continue;
        }
        if c == '<' && at(text, i, "<!--") {
            let end = match find(text, "-->", i + 4) {
                Some(e) => e + 3,
                None => n,
            };
            line += count_nl(text, i, end);
            i = end;
            continue;
        }
        if c == '<' && i + 1 < n && text[i + 1].is_ascii_alphabetic() {
            let (tg, attrs, j) = tag(text, i);
            let line_at = line;
            line += count_nl(text, i, j);
            let id = attr(&attrs, "id").cloned().unwrap_or_default();
            if !id.is_empty() {
                let sig = cv(&format!("<{} id=\"{}\">", tg, sv(&id)));
                out.symbol("element", &id, line_at, &sig, &[]);
            }
            let name_attr = attr(&attrs, "name").cloned().unwrap_or_default();
            if (tg == "input" || tg == "select" || tg == "textarea") && !name_attr.is_empty() {
                let ty = attr(&attrs, "type").cloned().unwrap_or_default();
                out.add_state(&name_attr, &if ty.is_empty() { cv(&tg) } else { ty }, line_at, &[]);
            }
            let href = attr(&attrs, "href").cloned().unwrap_or_default();
            if tg == "link" && !href.is_empty() {
                out.add_import(&href);
            }
            if tg == "form" {
                if let Some(action) = attr(&attrs, "action") {
                    let method = attr(&attrs, "method").cloned().unwrap_or_default();
                    let handler = if !id.is_empty() { id.clone() } else { name_attr.clone() };
                    out.route(&aupper(&if method.is_empty() { cv("GET") } else { method }), action, &handler, line_at, "client");
                }
            }
            let src = attr(&attrs, "src").cloned().unwrap_or_default();
            if tg == "script" && !src.is_empty() {
                out.add_import(&src);
            }
            if (tg == "script" || tg == "style" || tg == "title") && src.is_empty() {
                let close = find(&low, &format!("</{}", tg), j).unwrap_or(n);
                let body = sl(text, j, close).to_vec();
                let ty = alower(&attr(&attrs, "type").cloned().unwrap_or_default());
                if tg == "title" {
                    out.symbol("title", &clip(&collapse(&body), 80), line_at, &[], &[]);
                } else if tg == "style" || !has(&ty, "json") {
                    let sub = extract(&body, if tg == "style" { "css" } else { "javascript" });
                    out.merge(&sub, line - 1);
                }
                line += count_nl(text, j, close);
                i = close;
                continue;
            }
            i = j;
            continue;
        }
        i += 1;
    }
}

fn css(text: &[char], out: &mut Out) {
    let mut buf: C = Vec::new();
    let mut started = false;
    let mut buf_line: i64 = 1;
    let mut line: i64 = 1;
    let mut stack: Vec<C> = Vec::new();
    let n = text.len();
    let mut i = 0;
    while i < n {
        let c = text[i];
        if c == '"' || c == '\'' {
            let e = (i + 1..n).find(|&x| text[x] == c).unwrap_or(n - 1);
            let seg = &text[i..e + 1];
            if !started {
                started = true;
                buf_line = line;
            }
            line += count(seg, '\n') as i64;
            buf.extend_from_slice(seg);
            i = e + 1;
            continue;
        }
        if c == '{' {
            let pre = collapse(&buf);
            let parent = stack.last().cloned().unwrap_or_default();
            if !pre.is_empty() {
                out.symbol(if starts(&pre, "@") { "at-rule" } else { "selector" }, &clip(&pre, 120), buf_line, &pre, &parent);
            }
            stack.push(clip(&pre, 120));
            buf.clear();
            started = false;
            i += 1;
            continue;
        }
        if c == ';' || c == '}' {
            let decl = collapse(&buf);
            let parent = stack.last().cloned().unwrap_or_default();
            if starts(&decl, "@import") {
                out.add_import(strip(tail(&decl, 7)));
            } else if starts(&decl, "--") && decl.contains(&':') {
                let k = find(&decl, ":", 0).unwrap();
                out.add_state(strip(&decl[..k]), strip(tail(&decl, k + 1)), buf_line, &parent);
            }
            buf.clear();
            started = false;
            if c == '}' && !stack.is_empty() {
                stack.pop();
            }
            i += 1;
            continue;
        }
        if c == '\n' {
            line += 1;
        } else if !started && !is_ws(c) {
            started = true;
            buf_line = line;
        }
        buf.push(c);
        i += 1;
    }
}

// ---------- extract_skeleton ----------

fn language(ext: &str) -> &'static str {
    let e = alower(strip(&cv(ext)));
    let e: C = match rfind(&e, ".") {
        Some(dot) => e[dot + 1..].to_vec(),
        None => e,
    };
    match sv(&e).as_str() {
        "py" | "pyw" | "pyi" => "python",
        "js" | "mjs" | "cjs" | "jsx" => "javascript",
        "ts" | "tsx" | "mts" | "cts" => "typescript",
        "rs" => "rust",
        "html" | "htm" | "xhtml" | "vue" | "svelte" => "html",
        "css" | "scss" | "less" => "css",
        _ => "text",
    }
}

fn extract(source: &[char], lang: &str) -> Out {
    let lines = split(source, '\n');
    let mut out = Out::new(lang, lines.len());
    let text: C = if lines.len() > MAX_LINES {
        out.truncated = true;
        let firsts: Vec<C> = lines[..MAX_LINES].iter().map(|l| l.to_vec()).collect();
        join(&firsts, "\n")
    } else {
        source.to_vec()
    };
    if lang == "html" {
        html(&text, &mut out);
        return out;
    }
    if lang == "text" {
        return out;
    }
    let (code, kept) = clean(&text, lang);
    match lang {
        "python" => python(&code, &kept, &mut out),
        "javascript" | "typescript" => javascript(&code, &kept, &mut out),
        "rust" => rust(&code, &kept, &mut out),
        "css" => css(&join(&kept, "\n"), &mut out),
        _ => {}
    }
    out
}

pub fn extract_skeleton_json(source: &str, ext: &str) -> String {
    extract(&cv(source), language(ext)).result().to_string()
}

// ---------- inspect_artifact_metadata ----------

const MAX_STRINGS: usize = 40;
const MAX_SYMBOLS: usize = 60;
const MAX_SECTIONS: usize = 64;
const MAX_ENTRIES: usize = 200;

/// An unsigned integer of `size` bytes at off, or -1 past the end.
fn u(data: &[u8], off: i128, size: i128, le: bool) -> i128 {
    if off < 0 || off + size > data.len() as i128 {
        return -1;
    }
    let o = off as usize;
    let mut v: i128 = 0;
    for k in 0..size as usize {
        let b = data[if le { o + size as usize - 1 - k } else { o + k }] as i128;
        v = (v << 8) | b;
    }
    v
}

fn cstr(data: &[u8], off: i128, limit: i128) -> String {
    if off < 0 || off >= data.len() as i128 {
        return String::new();
    }
    let mut out = String::new();
    let mut k = off;
    while k < data.len() as i128 && k < off + limit && data[k as usize] != 0 {
        let b = data[k as usize];
        out.push(if (32..127).contains(&b) { b as char } else { '?' });
        k += 1;
    }
    out
}

fn entropy_milli(counts: &[u64; 256], total: u64) -> i64 {
    if total == 0 {
        return 0;
    }
    let mut h = 0.0f64;
    for &c in counts.iter() {
        if c > 0 {
            let p = c as f64 / total as f64;
            h -= p * p.log2();
        }
    }
    (h * 1000.0 + 0.5).floor() as i64
}

fn entropy(data: &[u8]) -> f64 {
    let mut counts = [0u64; 256];
    for &b in data {
        counts[b as usize] += 1;
    }
    entropy_milli(&counts, data.len() as u64) as f64 / 1000.0
}

fn clip_s(s: &str, n: usize) -> String {
    sv(&clip(&cv(s), n))
}

fn strings_of(data: &[u8]) -> (Vec<String>, i64) {
    let mut found: Vec<String> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    let mut total = 0i64;
    let mut run = String::new();
    let mut run_len = 0usize;
    for &b in data.iter().chain(std::iter::once(&0u8)) {
        if (32..127).contains(&b) || b == 9 {
            run.push(b as char);
            run_len += 1;
            continue;
        }
        if run_len >= 6 {
            total += 1;
            let s = clip_s(&run, 80);
            if !seen.contains(&s) && found.len() < MAX_STRINGS {
                seen.insert(s.clone());
                found.push(s);
            }
        }
        run.clear();
        run_len = 0;
    }
    (found, total)
}

struct Meta {
    name: String,
    size: i64,
    format: String,
    details: String,
    sections: Vec<(String, i128, i128, f64)>,
    exports: Vec<String>,
    imports: Vec<String>,
    entries: Vec<(String, i128)>,
    strings: Vec<String>,
    string_count: i64,
    entropy: f64,
    notes: Vec<String>,
}

fn section(meta: &mut Meta, data: &[u8], name: &str, off: i128, size: i128) {
    if meta.sections.len() >= MAX_SECTIONS {
        return;
    }
    let len = data.len() as i128;
    let lo = 0i128.max(off.min(len));
    let hi = lo.max((off + size.max(0)).min(len));
    meta.sections.push((name.to_string(), off, size, entropy(&data[lo as usize..hi as usize])));
}

fn add_item(items: &mut Vec<String>, value: &str, cap: usize) {
    if !value.is_empty() && !items.iter().any(|x| x == value) && items.len() < cap {
        items.push(value.to_string());
    }
}

fn elf_machine(m: i128) -> String {
    match m {
        3 => "x86".into(),
        0x3E => "x86-64".into(),
        0x28 => "ARM".into(),
        0xB7 => "AArch64".into(),
        0xF3 => "RISC-V".into(),
        0x08 => "MIPS".into(),
        0x14 => "PowerPC".into(),
        0x15 => "PowerPC64".into(),
        _ => format!("machine {}", m),
    }
}

fn elf_type(t: i128) -> String {
    match t {
        1 => "relocatable".into(),
        2 => "executable".into(),
        3 => "shared object".into(),
        4 => "core".into(),
        _ => format!("type {}", t),
    }
}

fn elf(data: &[u8], meta: &mut Meta) {
    let bits: i128 = if data.get(4) == Some(&2) { 64 } else { 32 };
    let le = data.get(5) != Some(&2);
    let etype = u(data, 16, 2, le);
    let machine = u(data, 18, 2, le);
    meta.details = format!("ELF {}-bit {}, {}, {}", bits, if le { "LSB" } else { "MSB" }, elf_machine(machine), elf_type(etype));
    let w = if bits == 64 { 8 } else { 4 };
    let shoff = u(data, if bits == 64 { 0x28 } else { 0x20 }, w, le);
    let shentsize = u(data, if bits == 64 { 0x3A } else { 0x2E }, 2, le);
    let shnum = u(data, if bits == 64 { 0x3C } else { 0x30 }, 2, le);
    let shstrndx = u(data, if bits == 64 { 0x3E } else { 0x32 }, 2, le);
    if shoff <= 0 || shentsize <= 0 || shnum <= 0 {
        return;
    }
    let mut heads: Vec<(i128, i128, i128, i128, i128)> = Vec::new();
    for k in 0..shnum.min(512) {
        let h = shoff + k * shentsize;
        let name = u(data, h, 4, le);
        let stype = u(data, h + 4, 4, le);
        let off = u(data, h + if bits == 64 { 24 } else { 16 }, w, le);
        let size = u(data, h + if bits == 64 { 32 } else { 20 }, w, le);
        let link = u(data, h + if bits == 64 { 40 } else { 24 }, 4, le);
        if name.min(stype).min(off).min(size).min(link) < 0 {
            break;
        }
        heads.push((name, stype, off, size, link));
    }
    let strtab = if shstrndx >= 0 && (shstrndx as usize) < heads.len() { heads[shstrndx as usize].2 } else { -1 };
    for &(name, stype, off, size, _) in &heads {
        if stype == 0 {
            continue;
        }
        let n = if strtab >= 0 { cstr(data, strtab + name, 256) } else { String::new() };
        section(meta, data, &n, off, size);
    }
    for &(_, stype, off, size, link) in &heads {
        if stype != 11 || !(link >= 0 && (link as usize) < heads.len()) {
            continue;
        }
        let names = heads[link as usize].2;
        let ent: i128 = if bits == 64 { 24 } else { 16 };
        for k in 1..(size / ent).min(4096) {
            let e = off + k * ent;
            let st_name = u(data, e, 4, le);
            let info = u(data, e + if bits == 64 { 4 } else { 12 }, 1, le);
            let shndx = u(data, e + if bits == 64 { 6 } else { 14 }, 2, le);
            if st_name.min(info).min(shndx) < 0 {
                break;
            }
            let sym = cstr(data, names + st_name, 256);
            if sym.is_empty() {
                continue;
            }
            if shndx == 0 {
                add_item(&mut meta.imports, &sym, MAX_SYMBOLS);
            } else if (info >> 4 == 1 || info >> 4 == 2) && (info & 0xF == 1 || info & 0xF == 2) {
                add_item(&mut meta.exports, &sym, MAX_SYMBOLS);
            }
        }
    }
}

fn pe_machine(m: i128) -> String {
    match m {
        0x14C => "x86".into(),
        0x8664 => "x64".into(),
        0xAA64 => "ARM64".into(),
        0x1C0 => "ARM".into(),
        0x1C4 => "ARMv7".into(),
        _ => format!("machine {}", m),
    }
}

fn pe(data: &[u8], meta: &mut Meta) -> bool {
    let p = u(data, 0x3C, 4, true);
    if p < 0 || !(p + 4 <= data.len() as i128 && &data[p as usize..p as usize + 4] == b"PE\x00\x00") {
        return false;
    }
    let machine = u(data, p + 4, 2, true);
    let nsec = u(data, p + 6, 2, true);
    let optsize = u(data, p + 20, 2, true);
    let chars = u(data, p + 22, 2, true);
    let opt = p + 24;
    let magic = u(data, opt, 2, true);
    let plus = magic == 0x20B;
    meta.format = "pe".into();
    meta.details = format!("PE32{} {} {}", if plus { "+" } else { "" }, pe_machine(machine), if chars >= 0 && chars & 0x2000 != 0 { "DLL" } else { "executable" });
    let dirs = opt + if plus { 112 } else { 96 };
    let mut secs: Vec<(i128, i128, i128)> = Vec::new();
    for k in 0..nsec.max(0).min(MAX_SECTIONS as i128) {
        let h = opt + optsize + k * 40;
        if h + 40 > data.len() as i128 {
            break;
        }
        let name = cstr(data, h, 8);
        let vsize = u(data, h + 8, 4, true);
        let va = u(data, h + 12, 4, true);
        let rsize = u(data, h + 16, 4, true);
        let rptr = u(data, h + 20, 4, true);
        secs.push((va, vsize.max(rsize), rptr));
        section(meta, data, &name, rptr, rsize);
    }
    let off_of = |rva: i128| -> i128 {
        for &(va, size, raw) in &secs {
            if va <= rva && rva < va + size {
                return rva - va + raw;
            }
        }
        -1
    };
    let exp = off_of(u(data, dirs, 4, true));
    if exp >= 0 {
        let count = u(data, exp + 24, 4, true);
        let names = off_of(u(data, exp + 32, 4, true));
        for k in 0..count.max(0).min(MAX_SYMBOLS as i128) {
            let rva = if names >= 0 { u(data, names + k * 4, 4, true) } else { -1 };
            if rva < 0 {
                break;
            }
            let s = cstr(data, off_of(rva), 256);
            add_item(&mut meta.exports, &s, MAX_SYMBOLS);
        }
    }
    let imp = off_of(u(data, dirs + 8, 4, true));
    if imp >= 0 {
        for k in 0..64 {
            let d = imp + k * 20;
            let first = u(data, d, 4, true);
            let name_rva = u(data, d + 12, 4, true);
            let thunk = u(data, d + 16, 4, true);
            if first < 0 || name_rva <= 0 || thunk <= 0 {
                break;
            }
            let dll = cstr(data, off_of(name_rva), 256);
            let table = off_of(if first > 0 { first } else { thunk });
            let w: i128 = if plus { 8 } else { 4 };
            for m in 0..512 {
                let entry = if table >= 0 { u(data, table + m * w, w, true) } else { -1 };
                if entry <= 0 || meta.imports.len() >= MAX_SYMBOLS {
                    break;
                }
                if entry >> (if plus { 63 } else { 31 }) != 0 {
                    continue;
                }
                let at = off_of(entry & 0x7FFF_FFFF);
                let f = if at >= 0 { cstr(data, at + 2, 256) } else { String::new() };
                if !f.is_empty() {
                    add_item(&mut meta.imports, &format!("{}!{}", dll, f), MAX_SYMBOLS);
                }
            }
        }
    }
    true
}

fn macho(data: &[u8], meta: &mut Meta) {
    let bits = if data.len() >= 4 && &data[..4] == b"\xcf\xfa\xed\xfe" { 64 } else { 32 };
    let cpu = u(data, 4, 4, true);
    let ncmds = u(data, 16, 4, true);
    meta.details = format!("Mach-O {}-bit, cpu type {}", bits, cpu);
    let mut off: i128 = if bits == 64 { 32 } else { 28 };
    for _ in 0..ncmds.max(0).min(256) {
        let cmd = u(data, off, 4, true);
        let size = u(data, off + 4, 4, true);
        if cmd < 0 || size <= 0 {
            break;
        }
        if cmd == 0x1 || cmd == 0x19 {
            let name = cstr(data, off + 8, 16);
            let seg64 = cmd == 0x19;
            let fileoff = u(data, off + if seg64 { 40 } else { 32 }, if seg64 { 8 } else { 4 }, true);
            let filesize = u(data, off + if seg64 { 48 } else { 36 }, if seg64 { 8 } else { 4 }, true);
            section(meta, data, &name, fileoff, filesize);
        } else if cmd == 0xC || cmd == 0x18 || cmd == 0x8000_001F {
            let s = cstr(data, off + u(data, off + 8, 4, true), 256);
            add_item(&mut meta.imports, &s, MAX_SYMBOLS);
        }
        off += size;
    }
}

const WASM_SECTIONS: &[&str] = &["custom", "type", "import", "function", "table", "memory", "global", "export", "start", "element", "code", "data", "datacount"];

fn leb(data: &[u8], off: i128) -> (i128, i128) {
    let mut result: i128 = 0;
    let mut shift = 0;
    let mut k = off;
    while k >= 0 && k < data.len() as i128 && shift < 35 {
        let b = data[k as usize] as i128;
        result |= (b & 0x7F) << shift;
        k += 1;
        if b & 0x80 == 0 {
            return (result, k);
        }
        shift += 7;
    }
    (-1, off)
}

fn wasm_name(data: &[u8], off: i128) -> (String, i128) {
    let (size, k) = leb(data, off);
    if size < 0 || k + size > data.len() as i128 {
        return (String::new(), -1);
    }
    let s: String = data[k as usize..(k + size) as usize].iter().map(|&b| if (32..127).contains(&b) { b as char } else { '?' }).collect();
    (s, k + size)
}

fn wasm(data: &[u8], meta: &mut Meta) {
    meta.details = format!("WebAssembly module, version {}", u(data, 4, 4, true));
    let len = data.len() as i128;
    let mut off: i128 = 8;
    while off < len && meta.sections.len() < MAX_SECTIONS {
        let sid = data[off as usize] as usize;
        let (size, body) = leb(data, off + 1);
        if size < 0 || body + size > len {
            break;
        }
        let mut name = if sid < WASM_SECTIONS.len() { WASM_SECTIONS[sid].to_string() } else { format!("section {}", sid) };
        if sid == 0 {
            let (custom, _) = wasm_name(data, body);
            name = format!("custom:{}", custom);
        }
        section(meta, data, &name, body, size);
        if sid == 2 || sid == 7 {
            let (count, mut k) = leb(data, body);
            for _ in 0..count.max(0).min(MAX_SYMBOLS as i128) {
                if sid == 2 {
                    let (module, k1) = wasm_name(data, k);
                    k = k1;
                    if k < 0 {
                        break;
                    }
                    let (field, k2) = wasm_name(data, k);
                    k = k2;
                    if k < 0 || k >= len {
                        break;
                    }
                    let kind = data[k as usize];
                    k += 1;
                    if kind == 0 {
                        k = leb(data, k).1;
                    } else if kind == 1 {
                        k += 1;
                        let flag = if k >= 0 && k < len { data[k as usize] } else { 0 };
                        k = leb(data, k + 1).1;
                        if flag & 1 != 0 {
                            k = leb(data, k).1;
                        }
                    } else if kind == 2 {
                        let flag = if k >= 0 && k < len { data[k as usize] } else { 0 };
                        k = leb(data, k + 1).1;
                        if flag & 1 != 0 {
                            k = leb(data, k).1;
                        }
                    } else if kind == 3 {
                        k += 2;
                    } else {
                        break;
                    }
                    add_item(&mut meta.imports, &format!("{}.{}", module, field), MAX_SYMBOLS);
                } else {
                    let (field, k1) = wasm_name(data, k);
                    k = k1;
                    if k < 0 || k >= len {
                        break;
                    }
                    k = leb(data, k + 1).1;
                    add_item(&mut meta.exports, &field, MAX_SYMBOLS);
                }
            }
        }
        off = body + size;
    }
}

fn zip(data: &[u8], meta: &mut Meta) {
    let len = data.len() as i128;
    let mut eocd: i128 = -1;
    let mut k = len - 22;
    while k >= 0i128.max(len - 65557) {
        if k + 4 <= len && &data[k as usize..k as usize + 4] == b"PK\x05\x06" {
            eocd = k;
            break;
        }
        k -= 1;
    }
    let total = if eocd >= 0 { u(data, eocd + 10, 2, true) } else { -1 };
    let cd = if eocd >= 0 { u(data, eocd + 16, 4, true) } else { -1 };
    let mut names: Vec<String> = Vec::new();
    let mut p = cd;
    for _ in 0..total.max(0).min(65535) {
        if p < 0 || !(p + 4 <= len && &data[p as usize..p as usize + 4] == b"PK\x01\x02") {
            break;
        }
        let size = u(data, p + 24, 4, true);
        let nlen = u(data, p + 28, 2, true);
        let xlen = u(data, p + 30, 2, true);
        let clen = u(data, p + 32, 2, true);
        if size.min(nlen).min(xlen).min(clen) < 0 {
            break;
        }
        let a = (p + 46).min(len) as usize;
        let b = (p + 46 + nlen).min(len) as usize;
        let raw = &data[a..b.max(a)];
        let name = match std::str::from_utf8(raw) {
            Ok(s) => s.to_string(),
            Err(_) => raw.iter().map(|&x| if x < 128 { x as char } else { '?' }).collect(),
        };
        if meta.entries.len() < MAX_ENTRIES {
            meta.entries.push((name.clone(), size));
        }
        names.push(name);
        p += 46 + nlen + xlen + clen;
    }
    let mut kind = "zip archive";
    if names.iter().any(|n| n == "META-INF/MANIFEST.MF") {
        kind = "Java archive (jar)";
    }
    if names.iter().any(|n| n == "AndroidManifest.xml") {
        kind = "Android package (apk)";
    }
    if names.iter().any(|n| n.ends_with(".dist-info/WHEEL")) {
        kind = "Python wheel";
    }
    if names.iter().any(|n| n == "[Content_Types].xml") {
        kind = "Office Open XML document";
    }
    meta.details = format!("{}, {} entries", kind, names.len());
}

fn tar(data: &[u8], meta: &mut Meta) {
    let len = data.len() as i128;
    let mut off: i128 = 0;
    let mut n = 0i64;
    while off + 512 <= len && n < 100000 {
        let name = cstr(data, off, 100);
        if name.is_empty() {
            break;
        }
        let size_text = cstr(data, off + 124, 12);
        let size_text = size_text.trim_matches(|c| c == ' ' || c == '\u{0}');
        let mut size: i128 = 0;
        for c in size_text.chars() {
            if ('0'..='7').contains(&c) {
                size = size * 8 + (c as i128 - 48);
            } else {
                break;
            }
        }
        if meta.entries.len() < MAX_ENTRIES {
            meta.entries.push((name, size));
        }
        n += 1;
        off += 512 + (size + 511) / 512 * 512;
    }
    meta.details = format!("tar archive, {} entries", n);
}

fn text_notes(text: &str, name: &str, meta: &mut Meta) {
    let low = name.to_ascii_lowercase();
    let lines: Vec<&str> = text.split('\n').collect();
    let longest = lines.iter().map(|x| x.chars().count()).max().unwrap_or(0);
    if low.ends_with(".js") || low.ends_with(".mjs") || low.ends_with(".cjs") {
        meta.format = "javascript".into();
    } else if low.ends_with(".json") || low.ends_with(".map") {
        meta.format = "json".into();
    }
    if text.contains("__webpack_require__") || text.contains("webpackChunk") {
        meta.notes.push("webpack bundle".into());
    }
    if text.contains("parcelRequire") {
        meta.notes.push("parcel bundle".into());
    }
    if longest > 1000 || (text.chars().count() > 2000 && lines.len() <= 3) {
        meta.notes.push(format!("minified (longest line {} chars)", longest));
    }
    for x in &lines {
        let xc = cv(x);
        if let Some(k) = find(&xc, "sourceMappingURL=", 0) {
            meta.notes.push(format!("source map: {}", sv(&clip(strip(tail(&xc, k + 17)), 120))));
            break;
        }
    }
    meta.details = format!("text, {} lines", lines.len());
}

fn starts_b(data: &[u8], pat: &[u8]) -> bool {
    data.len() >= pat.len() && &data[..pat.len()] == pat
}

pub fn inspect_artifact_json(data: &[u8], name: &str) -> String {
    let mut meta = Meta {
        name: name.to_string(),
        size: data.len() as i64,
        format: "binary".into(),
        details: String::new(),
        sections: Vec::new(),
        exports: Vec::new(),
        imports: Vec::new(),
        entries: Vec::new(),
        strings: Vec::new(),
        string_count: 0,
        entropy: 0.0,
        notes: Vec::new(),
    };
    meta.entropy = entropy(data);
    let head = &data[..data.len().min(16)];
    if data.is_empty() {
        meta.format = "empty".into();
        meta.details = "empty file".into();
    } else if starts_b(head, b"\x7fELF") {
        meta.format = "elf".into();
        elf(data, &mut meta);
    } else if starts_b(head, b"MZ") && pe(data, &mut meta) {
    } else if starts_b(head, b"MZ") {
        meta.format = "dos".into();
        meta.details = "MS-DOS executable".into();
    } else if starts_b(head, b"\xce\xfa\xed\xfe") || starts_b(head, b"\xcf\xfa\xed\xfe") {
        meta.format = "macho".into();
        macho(data, &mut meta);
    } else if starts_b(head, b"\xca\xfe\xba\xbe") && (45..100).contains(&u(data, 6, 2, false)) {
        meta.format = "java-class".into();
        meta.details = format!("Java class file, version {}.{}", u(data, 6, 2, false), u(data, 4, 2, false));
    } else if starts_b(head, b"\xca\xfe\xba\xbe") {
        meta.format = "macho".into();
        meta.details = format!("Mach-O universal binary, {} architectures", u(data, 4, 4, false));
    } else if starts_b(head, b"\x00asm") {
        meta.format = "wasm".into();
        wasm(data, &mut meta);
    } else if starts_b(head, b"PK\x03\x04") || starts_b(head, b"PK\x05\x06") {
        meta.format = "zip".into();
        zip(data, &mut meta);
    } else if starts_b(head, b"\x1f\x8b") {
        meta.format = "gzip".into();
        let flags = if data.len() > 3 { data[3] } else { 0 };
        let mut original = String::new();
        if flags & 8 != 0 {
            let mut k: i128 = 10;
            if flags & 4 != 0 {
                k += 2 + u(data, 10, 2, true).max(0);
            }
            original = cstr(data, k, 256);
        }
        meta.details = format!("gzip compressed{}", if original.is_empty() { String::new() } else { format!(", original name {}", original) });
    } else if data.len() >= 262 && &data[257..262] == b"ustar" {
        meta.format = "tar".into();
        tar(data, &mut meta);
    } else if starts_b(head, b"%PDF-") {
        meta.format = "pdf".into();
        let v = cstr(data, 5, 8);
        let v = v.split('\r').next().unwrap_or("").split('\n').next().unwrap_or("").to_string();
        meta.details = format!("PDF {}", v);
    } else if starts_b(head, b"\x89PNG\r\n\x1a\n") {
        meta.format = "png".into();
        meta.details = format!("PNG image, {} x {}", u(data, 16, 4, false), u(data, 20, 4, false));
    } else if starts_b(head, b"\xff\xd8\xff") {
        meta.format = "jpeg".into();
        meta.details = "JPEG image".into();
    } else if starts_b(head, b"GIF87a") || starts_b(head, b"GIF89a") {
        meta.format = "gif".into();
        meta.details = format!("GIF image, {} x {}", u(data, 6, 2, true), u(data, 8, 2, true));
    } else if starts_b(head, b"SQLite format 3\x00") {
        meta.format = "sqlite".into();
        meta.details = format!("SQLite 3 database, page size {}", u(data, 16, 2, false));
    } else if let Ok(text) = std::str::from_utf8(data) {
        let control = text.chars().filter(|&c| (c as u32) < 32 && !"\t\n\r\x0c".contains(c)).count();
        if control * 100 <= text.chars().count() {
            meta.format = "text".into();
            text_notes(text, name, &mut meta);
        }
    }
    let (strings, total) = strings_of(data);
    meta.strings = strings;
    meta.string_count = total;
    if meta.entropy > 7.2 && !["zip", "gzip", "png", "jpeg", "gif"].contains(&meta.format.as_str()) {
        meta.notes.push("high entropy: packed, compressed or encrypted".into());
    }
    json!({
        "name": meta.name,
        "size": meta.size,
        "format": meta.format,
        "details": meta.details,
        "sections": meta.sections.iter().map(|(n, o, s, e)| json!({"name": n, "offset": (*o).min(i64::MAX as i128) as i64, "size": (*s).min(i64::MAX as i128) as i64, "entropy": e})).collect::<Vec<_>>(),
        "exports": meta.exports,
        "imports": meta.imports,
        "entries": meta.entries.iter().map(|(n, s)| json!({"name": n, "size": *s as i64})).collect::<Vec<_>>(),
        "strings": meta.strings,
        "stringCount": meta.string_count,
        "entropy": meta.entropy,
        "notes": meta.notes,
    })
    .to_string()
}

// ---------- summarize_runtime_trace ----------

const MAX_ENDPOINTS: usize = 60;
const MAX_STATES: usize = 60;
const MAX_ERRORS: usize = 20;
const SCHEMA_KEYS: usize = 30;
const SCHEMA_DEPTH: usize = 4;
const STATE_KEYS: &[&str] = &["state", "status", "event", "type", "name", "action", "phase", "step"];

fn schema(v: &Value, depth: usize) -> Value {
    match v {
        Value::Bool(_) => json!("boolean"),
        Value::Null => json!("null"),
        Value::Number(_) => json!("number"),
        Value::String(_) => json!("string"),
        Value::Array(a) => {
            if depth >= SCHEMA_DEPTH {
                json!("array")
            } else if a.is_empty() {
                json!([])
            } else {
                json!([schema(&a[0], depth + 1)])
            }
        }
        Value::Object(o) => {
            if depth >= SCHEMA_DEPTH {
                return json!("object");
            }
            let mut keys: Vec<&String> = o.keys().collect();
            keys.sort();
            let mut m = Map::new();
            for k in keys.into_iter().take(SCHEMA_KEYS) {
                m.insert(k.clone(), schema(&o[k], depth + 1));
            }
            Value::Object(m)
        }
    }
}

fn norm_path(url: &str) -> (String, String) {
    let u = cv(url);
    let mut host: C = Vec::new();
    let mut rest: C = u.clone();
    if let Some(k) = find(&rest, "://", 0) {
        rest = tail(&rest, k + 3).to_vec();
        match find(&rest, "/", 0) {
            Some(slash) => {
                host = rest[..slash].to_vec();
                rest = rest[slash..].to_vec();
            }
            None => {
                host = rest.clone();
                rest = cv("/");
            }
        }
    }
    let rest = upto(&rest, "?#").to_vec();
    let mut parts: Vec<C> = Vec::new();
    for seg in split(&rest, '/') {
        let hexish = seg.len() >= 8 && seg.iter().all(|&c| c.is_ascii_digit() || ('a'..='f').contains(&c.to_ascii_lowercase()) || c == '-') && seg.iter().any(|c| c.is_ascii_digit());
        let digits = !seg.is_empty() && seg.iter().all(|c| c.is_ascii_digit());
        parts.push(if digits || hexish { cv("{id}") } else { seg.to_vec() });
    }
    let path = join(&parts, "/");
    (sv(&host), if path.is_empty() { "/".to_string() } else { sv(&path) })
}

struct Endpoint {
    method: String,
    path: String,
    count: i64,
    statuses: Vec<i64>,
    request: Option<Value>,
    response: Option<Value>,
}

struct Trace {
    format: String,
    requests: i64,
    endpoints: Vec<Endpoint>,
    index: HashMap<String, usize>,
    states: Vec<String>,
    errors: Vec<String>,
    hosts: Vec<String>,
}

impl Trace {
    fn new(format: &str) -> Trace {
        Trace { format: format.into(), requests: 0, endpoints: Vec::new(), index: HashMap::new(), states: Vec::new(), errors: Vec::new(), hosts: Vec::new() }
    }

    fn request(&mut self, method: &str, url: &str, status: i64, req_body: Option<&Value>, resp_body: Option<&Value>) {
        let (host, path) = norm_path(url);
        let method = if method.is_empty() { "GET".to_string() } else { method.to_ascii_uppercase() };
        self.requests += 1;
        if !host.is_empty() {
            add_item(&mut self.hosts, &host, 20);
        }
        let key = format!("{} {}", method, path);
        let mut ep = self.index.get(&key).copied();
        if ep.is_none() && self.endpoints.len() < MAX_ENDPOINTS {
            self.endpoints.push(Endpoint { method: method.clone(), path: path.clone(), count: 0, statuses: Vec::new(), request: None, response: None });
            ep = Some(self.endpoints.len() - 1);
            self.index.insert(key.clone(), self.endpoints.len() - 1);
        }
        if let Some(k) = ep {
            let e = &mut self.endpoints[k];
            e.count += 1;
            if status >= 0 && !e.statuses.contains(&status) {
                e.statuses.push(status);
                e.statuses.sort();
            }
            if e.request.is_none() {
                if let Some(b) = req_body {
                    e.request = Some(schema(b, 0));
                }
            }
            if e.response.is_none() {
                if let Some(b) = resp_body {
                    e.response = Some(schema(b, 0));
                }
            }
        }
        if status >= 0 {
            self.state(&format!("{} → {}", key, status));
        } else {
            self.state(&key);
        }
        if status >= 400 {
            self.error(&format!("{} → {}", key, status));
        }
    }

    fn state(&mut self, label: &str) {
        let label = sv(&clip(&collapse(&cv(label)), 80));
        if !label.is_empty() && self.states.last() != Some(&label) && self.states.len() < MAX_STATES {
            self.states.push(label);
        }
    }

    fn error(&mut self, text: &str) {
        let text = sv(&clip(&collapse(&cv(text)), 120));
        if !text.is_empty() && self.errors.len() < MAX_ERRORS {
            self.errors.push(text);
        }
    }

    fn result(&self) -> Value {
        json!({
            "format": self.format,
            "requests": self.requests,
            "endpoints": self.endpoints.iter().map(|e| json!({
                "method": e.method, "path": e.path, "count": e.count, "statuses": e.statuses,
                "requestSchema": e.request.clone().unwrap_or(Value::Null), "responseSchema": e.response.clone().unwrap_or(Value::Null),
            })).collect::<Vec<_>>(),
            "states": self.states,
            "errors": self.errors,
            "hosts": self.hosts,
        })
    }
}

fn parse(text: &str) -> Option<Value> {
    serde_json::from_str::<Value>(text).ok()
}

fn body_of(text: Option<&Value>, mime: Option<&Value>) -> Option<Value> {
    let t = match text {
        Some(Value::String(s)) if !s.is_empty() => s,
        _ => return None,
    };
    let m = match mime {
        Some(Value::String(s)) => s.to_ascii_lowercase(),
        _ => String::new(),
    };
    if !m.contains("json") {
        return None;
    }
    // Python: json "null" is None, so no schema either
    parse(t).filter(|v| !v.is_null())
}

fn int_of(v: Option<&Value>) -> i64 {
    match v {
        Some(Value::Number(n)) => n.as_i64().unwrap_or(-1),
        _ => -1,
    }
}

fn stripped(s: &str) -> String {
    sv(strip(&cv(s)))
}

fn first_str(e: &Map<String, Value>, keys: &[&str]) -> String {
    for k in keys {
        let mut v: Option<&Value> = None;
        let mut cur: Option<&Map<String, Value>> = Some(e);
        for part in k.split('.') {
            v = cur.and_then(|m| m.get(part));
            cur = match v {
                Some(Value::Object(m)) => Some(m),
                _ => None,
            };
        }
        if let Some(Value::String(s)) = v {
            let t = stripped(s);
            if !t.is_empty() {
                return t;
            }
        }
    }
    String::new()
}

fn truthy(v: Option<&Value>) -> bool {
    match v {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64().map(|x| x != 0.0).unwrap_or(true),
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Array(a)) => !a.is_empty(),
        Some(Value::Object(o)) => !o.is_empty(),
    }
}

fn container(v: Option<&Value>) -> Option<&Value> {
    match v {
        Some(x @ Value::Object(_)) | Some(x @ Value::Array(_)) => Some(x),
        _ => None,
    }
}

fn event(tr: &mut Trace, ev: &Value) {
    let e = match ev {
        Value::Object(m) => m,
        _ => return,
    };
    let url = first_str(e, &["url", "path", "route", "uri", "request.url"]);
    let mut status = int_of(e.get("statusCode"));
    if status < 0 {
        status = int_of(e.get("status"));
    }
    if status < 0 {
        if let Some(Value::Object(r)) = e.get("response") {
            status = int_of(r.get("status"));
        }
    }
    if !url.is_empty() && (url.starts_with('/') || url.contains("://")) {
        let mut req: Option<&Value> = if e.contains_key("body") {
            e.get("body")
        } else if e.contains_key("payload") {
            e.get("payload")
        } else {
            e.get("data")
        };
        if matches!(req, None | Some(Value::Null)) {
            if let Some(Value::Object(r)) = e.get("request") {
                req = r.get("body");
            }
        }
        let resp: Option<&Value> = match e.get("response") {
            Some(Value::Object(r)) => r.get("body"),
            _ => None,
        };
        let method = first_str(e, &["method", "httpMethod", "request.method"]);
        tr.request(if method.is_empty() { "GET" } else { method.as_str() }, &url, status, container(req), container(resp));
    } else if let (Some(Value::String(a)), Some(Value::String(b))) = (e.get("from"), e.get("to")) {
        tr.state(&format!("{} → {}", stripped(a), stripped(b)));
    } else {
        tr.state(&first_str(e, STATE_KEYS));
    }
    let level = first_str(e, &["level", "severity"]).to_ascii_lowercase();
    if level == "error" || level == "fatal" || level == "critical" || truthy(e.get("error")) {
        let msg = first_str(e, &["message", "msg", "error", "error.message"]);
        let alt = first_str(e, STATE_KEYS);
        tr.error(if !msg.is_empty() { msg.as_str() } else if !alt.is_empty() { alt.as_str() } else { "error" });
    }
}

fn log_line(tr: &mut Trace, line: &str) {
    let replaced = line.replace('"', " ");
    let words: Vec<&str> = replaced.split(' ').collect();
    let mut matched = false;
    for (k, w) in words.iter().enumerate() {
        if HTTP_VERBS.contains(w) && k + 1 < words.len() && (words[k + 1].starts_with('/') || words[k + 1].starts_with("http")) {
            let mut status = -1i64;
            for x in words.iter().skip(k + 2).take(6) {
                if x.chars().count() == 3 && x.chars().all(|c| c.is_ascii_digit()) {
                    let v: i64 = x.parse().unwrap();
                    if (100..=599).contains(&v) {
                        status = v;
                        break;
                    }
                }
            }
            tr.request(w, words[k + 1], status, None, None);
            matched = true;
            break;
        }
    }
    let lc = cv(line);
    if !matched {
        let low = alower(&lc);
        let (arrow, width) = match find(&lc, "->", 0) {
            Some(a) => (Some(a), 2),
            None => (find(&lc, "→", 0), 1),
        };
        if let Some(a) = arrow.filter(|&a| a > 0) {
            let left = strip(&lc[..a]).to_vec();
            let right = strip(tail(&lc, a + width)).to_vec();
            let x = split(&left, ' ').last().map(|p| p.to_vec()).unwrap_or_default();
            let y = if right.is_empty() { Vec::new() } else { split(&right, ' ')[0].to_vec() };
            if !x.is_empty() && !y.is_empty() {
                tr.state(&format!("{} → {}", sv(&x), sv(&y)));
            }
        } else {
            for word in ["state", "status"] {
                if let Some(k) = find(&low, word, 0) {
                    if k == 0 || !is_ident(low[k - 1]) {
                        let mut j = skip_spaces(&lc, k + word.len());
                        if j < lc.len() && (lc[j] == '=' || lc[j] == ':') {
                            j = skip_spaces(&lc, j + 1);
                            let mut e = j;
                            while e < lc.len() && (is_ident(lc[e]) || lc[e] == '-' || lc[e] == '.') {
                                e += 1;
                            }
                            let token = &lc[j..e];
                            if !token.is_empty() && !token.iter().all(|c| c.is_ascii_digit()) {
                                tr.state(&sv(token));
                                break;
                            }
                        }
                    }
                }
            }
        }
    }
    let low = sv(&alower(&lc));
    if low.contains("error") || low.contains("exception") || low.contains("fatal") || low.contains("traceback") {
        tr.error(line);
    }
}

pub fn summarize_trace_json(text: &str) -> String {
    let text = text.strip_prefix('\u{feff}').unwrap_or(text);
    if strip(&cv(text)).is_empty() {
        return Trace::new("empty").result().to_string();
    }
    let doc = parse(text);
    if let Some(Value::Object(d)) = &doc {
        if let Some(Value::Object(log)) = d.get("log") {
            if let Some(Value::Array(entries)) = log.get("entries") {
                let mut tr = Trace::new("har");
                let empty = Map::new();
                for e in entries {
                    let e = match e {
                        Value::Object(m) => m,
                        _ => continue,
                    };
                    let req = match e.get("request") {
                        Some(Value::Object(m)) => m,
                        _ => &empty,
                    };
                    let resp = match e.get("response") {
                        Some(Value::Object(m)) => m,
                        _ => &empty,
                    };
                    let post = match req.get("postData") {
                        Some(Value::Object(m)) => m,
                        _ => &empty,
                    };
                    let content = match resp.get("content") {
                        Some(Value::Object(m)) => m,
                        _ => &empty,
                    };
                    let url = match req.get("url") {
                        Some(Value::String(s)) => s.clone(),
                        _ => continue,
                    };
                    let resp_body = if content.get("encoding") == Some(&Value::String("base64".into())) { None } else { body_of(content.get("text"), content.get("mimeType")) };
                    let req_body = body_of(post.get("text"), post.get("mimeType"));
                    let method = match req.get("method") {
                        Some(Value::String(s)) => s.clone(),
                        _ => "GET".to_string(),
                    };
                    tr.request(&method, &url, int_of(resp.get("status")), req_body.as_ref(), resp_body.as_ref());
                }
                return tr.result().to_string();
            }
        }
    }
    if let Some(d @ (Value::Array(_) | Value::Object(_))) = &doc {
        let mut fmt = "json-events";
        let events: Vec<Value> = match d {
            Value::Object(m) => match m.get("traceEvents") {
                Some(Value::Array(a)) => {
                    fmt = "chrome-trace";
                    a.clone()
                }
                _ => vec![d.clone()],
            },
            Value::Array(a) => a.clone(),
            _ => Vec::new(),
        };
        let mut tr = Trace::new(fmt);
        for e in &events {
            event(&mut tr, e);
        }
        return tr.result().to_string();
    }
    let lines: Vec<String> = text.split('\n').map(stripped).filter(|x| !x.is_empty()).collect();
    let mut parsed: Vec<Value> = Vec::new();
    for x in &lines {
        if x.starts_with('{') {
            if let Some(v @ Value::Object(_)) = parse(x) {
                parsed.push(v);
            }
        }
    }
    if !parsed.is_empty() && parsed.len() * 2 >= lines.len() {
        let mut tr = Trace::new("jsonl");
        for e in &parsed {
            event(&mut tr, e);
        }
        return tr.result().to_string();
    }
    let mut tr = Trace::new("text-log");
    for x in &lines {
        log_line(&mut tr, x);
    }
    tr.result().to_string()
}
