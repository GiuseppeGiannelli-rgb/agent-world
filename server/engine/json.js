// Models wrap JSON in fences, add prose around it, or put raw newlines inside
// strings. Take the first balanced {...} object and repair what is cheap to repair.

function escapeControlCharsInStrings(src) {
  let out = '';
  let inString = false;
  let escaped = false;
  for (const ch of src) {
    if (inString) {
      if (escaped) escaped = false;
      else if (ch === '\\') escaped = true;
      else if (ch === '"') inString = false;
      else if (ch === '\n') { out += '\\n'; continue; }
      else if (ch === '\r') { out += '\\r'; continue; }
      else if (ch === '\t') { out += '\\t'; continue; }
    } else if (ch === '"') inString = true;
    out += ch;
  }
  return out;
}

function tryParse(src) {
  const attempts = [
    (s) => s,
    (s) => s.replace(/,\s*([}\]])/g, '$1'),
    (s) => escapeControlCharsInStrings(s),
    (s) => escapeControlCharsInStrings(s).replace(/,\s*([}\]])/g, '$1'),
  ];
  for (const fix of attempts) {
    try {
      const value = JSON.parse(fix(src));
      if (value && typeof value === 'object' && !Array.isArray(value)) return value;
    } catch {
      // next repair
    }
  }
  return null;
}

export function extractJson(text) {
  if (typeof text !== 'string') return null;
  const s = text.replace(/<think>[\s\S]*?<\/think>/gi, '');
  let from = s.indexOf('{');
  while (from >= 0) {
    let depth = 0;
    let inString = false;
    let escaped = false;
    for (let i = from; i < s.length; i++) {
      const c = s[i];
      if (inString) {
        if (escaped) escaped = false;
        else if (c === '\\') escaped = true;
        else if (c === '"') inString = false;
        continue;
      }
      if (c === '"') inString = true;
      else if (c === '{') depth++;
      else if (c === '}' && --depth === 0) {
        const parsed = tryParse(s.slice(from, i + 1));
        if (parsed) return parsed;
        break;
      }
    }
    if (depth > 0) {
      const parsed = tryParse(s.slice(from));
      if (parsed) return parsed;
    }
    from = s.indexOf('{', from + 1);
  }
  return null;
}
