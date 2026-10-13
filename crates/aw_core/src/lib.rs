//! aw_core — native accelerators for the Agent World backend (P6, Spec 04 D1/D2).
//!
//! First module: BM25 + tokenizer, a faithful port of `backend/search.py`
//! (itself ported 1:1 from `server/engine/search.js`). Same interface:
//! `Bm25(k1, b)` with `add(id, fields)` / `search(query, k)`, plus `tokenize(text)`
//! for direct parity testing. Ranking, scores and edge cases (zero-length docs,
//! stopword-only queries, stable tie order) must match the Python reference —
//! that is what `backend/tests/test_search_rust.py` pins.

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use std::collections::{HashMap, HashSet};
use unicode_normalization::UnicodeNormalization;

/// Same set as `STOP` in backend/search.py. Tokens are accent-stripped before
/// the lookup, so "più" never actually matches; it is kept only to mirror the
/// Python literal exactly.
const STOP: &[&str] = &[
    "the", "and", "for", "with", "that", "this", "from", "into", "your", "you", "are", "not",
    "but", "all", "any", "can", "una", "uno", "per", "con", "che", "del", "della", "delle",
    "dei", "degli", "gli", "le", "la", "il", "lo", "di", "da", "in", "su", "tra", "fra",
    "come", "cosa", "sono", "non", "piu", "più", "anche",
];

fn is_stop(w: &str) -> bool {
    STOP.contains(&w)
}

/// Python: str(text).lower() -> NFD -> strip U+0300..=U+036F -> split [^a-z0-9]+
/// -> keep tokens with len > 2 that are not stopwords.
fn tokenize_str(text: &str) -> Vec<String> {
    let lowered: String = text.chars().flat_map(|c| c.to_lowercase()).collect();
    // Per-char NFD then strip combining marks: equivalent to the Python
    // normalize("NFD") + regex strip, because the stripped marks make the
    // canonical reordering irrelevant.
    let cleaned: String = lowered
        .chars()
        .flat_map(|c| c.nfd())
        .filter(|c| !('\u{0300}'..='\u{036f}').contains(c))
        .collect();
    let mut out = Vec::new();
    let mut cur = String::new();
    for c in cleaned.chars() {
        if c.is_ascii_alphanumeric() {
            cur.push(c);
        } else if !cur.is_empty() {
            // after lowercasing, [a-z0-9] only: byte len == char count
            if cur.len() > 2 && !is_stop(&cur) {
                out.push(std::mem::take(&mut cur));
            } else {
                cur.clear();
            }
        }
    }
    if !cur.is_empty() && cur.len() > 2 && !is_stop(&cur) {
        out.push(cur);
    }
    out
}

struct Doc {
    id: Py<PyAny>,
    tf: HashMap<String, f64>,
    len: f64,
}

/// BM25 index, interface-identical to backend.search.Bm25.
#[pyclass]
struct Bm25 {
    k1: f64,
    b: f64,
    docs: Vec<Doc>,
    df: HashMap<String, u64>,
    total_len: f64,
}

#[pymethods]
impl Bm25 {
    #[new]
    #[pyo3(signature = (k1 = 1.4, b = 0.75))]
    fn new(k1: f64, b: f64) -> Self {
        Bm25 { k1, b, docs: Vec::new(), df: HashMap::new(), total_len: 0.0 }
    }

    /// fields: [{text, weight}] — same contract as the Python add().
    fn add(&mut self, py: Python<'_>, id: Py<PyAny>, fields: Vec<Bound<'_, PyDict>>) -> PyResult<()> {
        // Extract (text, weight) under the GIL first: Python str(text) with
        // None -> "", weight defaults to 1.
        let mut raw: Vec<(String, f64)> = Vec::with_capacity(fields.len());
        for f in &fields {
            let text = match f.get_item("text")? {
                None => String::new(),
                Some(o) if o.is_none() => String::new(),
                Some(o) => o.str()?.to_str()?.to_owned(),
            };
            let weight = match f.get_item("weight")? {
                None => 1.0,
                Some(w) if w.is_none() => 1.0,
                Some(w) => w.extract::<f64>()?,
            };
            raw.push((text, weight));
        }
        // Tokenize without the GIL: pure Rust data from here on.
        let (tf, length) = py.allow_threads(|| {
            let mut tf: HashMap<String, f64> = HashMap::new();
            let mut length = 0.0f64;
            for (text, weight) in &raw {
                for t in tokenize_str(text) {
                    *tf.entry(t).or_insert(0.0) += weight;
                    length += weight;
                }
            }
            (tf, length)
        });
        for t in tf.keys() {
            *self.df.entry(t.clone()).or_insert(0) += 1;
        }
        self.total_len += length;
        self.docs.push(Doc { id, tf, len: length });
        Ok(())
    }

    #[pyo3(signature = (query, k = 10))]
    fn search(&self, py: Python<'_>, query: &str, k: usize) -> PyResult<Py<PyAny>> {
        // Python: terms = list(dict.fromkeys(tokenize(query))) — dedup keeping
        // first-occurrence order.
        let terms = py.allow_threads(|| {
            let mut seen = HashSet::new();
            tokenize_str(query)
                .into_iter()
                .filter(|t| seen.insert(t.clone()))
                .collect::<Vec<_>>()
        });
        let out = PyList::empty(py);
        if terms.is_empty() {
            return Ok(out.into());
        }
        let n = self.docs.len() as f64;
        // Python: self.avg_len or 1 — a 0.0 average (all docs tokenless)
        // degrades to 1.
        let avg = if self.docs.is_empty() {
            1.0
        } else {
            let a = self.total_len / self.docs.len() as f64;
            if a == 0.0 { 1.0 } else { a }
        };
        let k1 = self.k1;
        let b = self.b;
        let df = &self.df;
        let docs = &self.docs;
        let mut scored: Vec<(usize, f64)> = Vec::new();
        py.allow_threads(|| {
            for (i, d) in docs.iter().enumerate() {
                let mut score = 0.0f64;
                for t in &terms {
                    // Python: f = tf.get(t); if not f: continue (skips 0.0 too)
                    let f = match d.tf.get(t) {
                        Some(&f) if f != 0.0 => f,
                        _ => continue,
                    };
                    let dfv = *df.get(t).unwrap_or(&0) as f64;
                    let idf = (1.0 + (n - dfv + 0.5) / (dfv + 0.5)).ln();
                    // Identical operation order as the Python expression.
                    score += idf * ((f * (k1 + 1.0)) / (f + k1 * (1.0 - b + (b * d.len) / avg)));
                }
                if score > 0.0 {
                    scored.push((i, score));
                }
            }
        });
        // Python's sort is stable: equal scores keep insertion (doc) order.
        // Vec::sort_by is stable as well; Equal on NaN keeps it total.
        scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        for (i, score) in scored.into_iter().take(k) {
            let d = PyDict::new(py);
            d.set_item("id", docs[i].id.clone_ref(py))?;
            d.set_item("score", score)?;
            out.append(d)?;
        }
        Ok(out.into())
    }

    #[getter]
    fn doc_count(&self) -> usize {
        self.docs.len()
    }
}

/// Exposed for the parity tests: must equal backend.search.tokenize exactly.
#[pyfunction]
fn tokenize(text: &str) -> Vec<String> {
    tokenize_str(text)
}

#[pymodule]
fn aw_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Bm25>()?;
    m.add_function(wrap_pyfunction!(tokenize, m)?)?;
    Ok(())
}
