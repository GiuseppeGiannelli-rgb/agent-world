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
use std::cmp::Ordering;
use std::collections::{HashMap, HashSet};
use unicode_general_category::get_general_category;
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

/// Python: c == "_" or unicodedata.category(c)[0] in "LNM" (spec 11 T03, D12).
fn is_wordish(c: char) -> bool {
    c == '_' || matches!(get_general_category(c).abbreviation().as_bytes().first(), Some(b'L' | b'N' | b'M'))
}

/// Python: search._scan -- runs of word chars and "_", joined by "::" or "@"
/// when a word char follows; a token may start with "@".
fn scan(s: &[char]) -> Vec<String> {
    let n = s.len();
    let mut out = Vec::new();
    let mut i = 0;
    while i < n {
        let c = s[i];
        if is_wordish(c) || (c == '@' && i + 1 < n && is_wordish(s[i + 1])) {
            let mut j = i;
            while j < n {
                let ch = s[j];
                if is_wordish(ch) {
                    j += 1;
                } else if ch == '@' && j + 1 < n && is_wordish(s[j + 1]) {
                    j += 1;
                } else if ch == ':' && j > i && j + 2 < n && s[j + 1] == ':' && is_wordish(s[j + 2]) {
                    j += 2;
                } else {
                    break;
                }
            }
            out.push(s[i..j].iter().collect());
            i = j;
        } else {
            i += 1;
        }
    }
    out
}

/// Python: len(w) > 2 and w not in STOP -- len counts characters, not bytes.
fn keep(w: &str) -> bool {
    w.chars().count() > 2 && !is_stop(w)
}

fn is_joiner(c: char) -> bool {
    c == '_' || c == ':' || c == '@'
}

/// Python: str(text).lower() -> NFD -> strip U+0300..=U+036F -> "ς" to "σ" ->
/// the tokens of _scan, each followed by its parts when it holds a joiner.
/// Python reads ASCII chunks with a regex of the same grammar: same tokens.
fn tokenize_str(text: &str) -> Vec<String> {
    // str::to_lowercase, like Python's lower() on the whole string; the NFD of the
    // whole string reorders the marks it keeps (T03 keeps the marks outside
    // U+0300..U+036F, so the canonical order matters now)
    let folded: Vec<char> = text
        .to_lowercase()
        .nfd()
        .filter(|c| !('\u{0300}'..='\u{036f}').contains(c))
        .map(|c| if c == 'ς' { 'σ' } else { c })
        .collect();
    let mut out = Vec::new();
    for raw in scan(&folded) {
        if keep(&raw) {
            out.push(raw.clone());
        }
        if raw.chars().any(is_joiner) {
            for part in raw.split(is_joiner) {
                if !part.is_empty() && keep(part) {
                    out.push(part.to_string());
                }
            }
        }
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

// ---------- Spec 05: vectors ----------

/// CRC-32 (IEEE 802.3, reflected, polynomial 0xEDB88320), bit by bit:
/// equal to Python's zlib.crc32 for the same bytes.
fn crc32(bytes: &[u8]) -> u32 {
    let mut crc: u32 = 0xFFFF_FFFF;
    for &b in bytes {
        crc ^= b as u32;
        for _ in 0..8 {
            let mask = (crc & 1).wrapping_neg();
            crc = (crc >> 1) ^ (0xEDB8_8320 & mask);
        }
    }
    !crc
}

/// Mirrors backend.embed.ngram_vector: signed feature hashing of "w:<token>"
/// and of the 3- and 4-grams of " <token> ", then L2 normalization. Spec 11
/// T03: tokens may be any script, so the grams are cut by characters (Python
/// slices str) and hashed as UTF-8 bytes.
fn ngram_vector_str(text: &str, dim: usize) -> Vec<f64> {
    let mut vec = vec![0.0f64; dim];
    if dim == 0 {
        return vec;
    }
    for token in tokenize_str(text) {
        let mut grams: Vec<String> = vec![format!("w:{}", token)];
        let padded: Vec<char> = format!(" {} ", token).chars().collect();
        for n in [3usize, 4] {
            if padded.len() >= n {
                for i in 0..=(padded.len() - n) {
                    grams.push(padded[i..i + n].iter().collect());
                }
            }
        }
        for g in grams {
            let h = crc32(g.as_bytes());
            vec[(h as usize) % dim] += if h & 0x8000_0000 != 0 { -1.0 } else { 1.0 };
        }
    }
    // Python: n = sqrt(sum(x * x)), then x / n -- same order of operations.
    let norm = vec.iter().map(|x| x * x).sum::<f64>().sqrt();
    if norm > 0.0 {
        for x in vec.iter_mut() {
            *x /= norm;
        }
    }
    vec
}

#[pyfunction]
#[pyo3(signature = (text, dim = 256))]
fn ngram_vector(py: Python<'_>, text: &str, dim: usize) -> Vec<f64> {
    let text = text.to_owned();
    py.allow_threads(move || ngram_vector_str(&text, dim))
}

/// [(row, cosine)] best first, ties by row, for unit vectors stored row-major
/// in `matrix` (rows of `dim` values). Mirrors backend.search._cosine_top_k_py,
/// summing in the same order, so the scores are bit-identical.
#[pyfunction]
fn cosine_top_k(py: Python<'_>, query: Vec<f64>, matrix: Vec<f64>, dim: usize, k: usize) -> PyResult<Vec<(usize, f64)>> {
    if dim == 0 || query.len() != dim || matrix.len() % dim != 0 {
        return Err(pyo3::exceptions::PyValueError::new_err("cosine_top_k: query and matrix shapes do not match"));
    }
    Ok(py.allow_threads(move || {
        let mut scored: Vec<(usize, f64)> = matrix
            .chunks(dim)
            .enumerate()
            .map(|(i, row)| {
                let mut s = 0.0f64;
                for (q, v) in query.iter().zip(row) {
                    s += q * v;
                }
                (i, s)
            })
            .collect();
        scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(Ordering::Equal).then(a.0.cmp(&b.0)));
        scored.truncate(k);
        scored
    }))
}

#[pymodule]
fn aw_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Bm25>()?;
    m.add_function(wrap_pyfunction!(tokenize, m)?)?;
    m.add_function(wrap_pyfunction!(ngram_vector, m)?)?;
    m.add_function(wrap_pyfunction!(cosine_top_k, m)?)?;
    Ok(())
}
