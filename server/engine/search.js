// Tiny BM25 index used by the skill library and the brain. No dependencies.

const STOP = new Set('the and for with that this from into your you are not but all any can una uno per con che del della delle dei degli gli le la il lo di da in su tra fra come cosa sono non piu più anche'.split(' '));

export function tokenize(text) {
  return String(text ?? '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .split(/[^a-z0-9]+/)
    .filter((w) => w.length > 2 && !STOP.has(w));
}

export class Bm25 {
  constructor({ k1 = 1.4, b = 0.75 } = {}) {
    this.k1 = k1;
    this.b = b;
    this.docs = [];
    this.df = new Map();
    this.avgLen = 0;
  }

  // fields: [{ text, weight }]
  add(id, fields) {
    const tf = new Map();
    let len = 0;
    for (const { text, weight = 1 } of fields) {
      for (const t of tokenize(text)) {
        tf.set(t, (tf.get(t) ?? 0) + weight);
        len += weight;
      }
    }
    for (const t of tf.keys()) this.df.set(t, (this.df.get(t) ?? 0) + 1);
    this.docs.push({ id, tf, len });
    this.avgLen = this.docs.reduce((n, d) => n + d.len, 0) / this.docs.length;
  }

  search(query, k = 10) {
    const terms = [...new Set(tokenize(query))];
    if (!terms.length) return [];
    const N = this.docs.length;
    const scored = [];
    for (const d of this.docs) {
      let score = 0;
      for (const t of terms) {
        const f = d.tf.get(t);
        if (!f) continue;
        const df = this.df.get(t) ?? 0;
        const idf = Math.log(1 + (N - df + 0.5) / (df + 0.5));
        score += idf * ((f * (this.k1 + 1)) / (f + this.k1 * (1 - this.b + (this.b * d.len) / (this.avgLen || 1))));
      }
      if (score > 0) scored.push({ id: d.id, score });
    }
    return scored.sort((a, b) => b.score - a.score).slice(0, k);
  }
}
