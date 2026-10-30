// 사전 검색 — PC판 app/dictdb.py 를 그대로 옮긴 것 (모바일 사전 형식: words + blocks)
// db 어댑터: { all(sql, params) → 행 배열(각 행은 배열), inflate(Uint8Array) → 문자열 }

import * as fuzzy from "./fuzzy.js";

export const POS_KO = {
  noun: "명사", verb: "동사", adj: "형용사", adv: "부사", pron: "대명사",
  prep: "전치사", conj: "접속사", intj: "감탄사", det: "한정사", article: "관사",
  num: "수사", phrase: "구", prep_phrase: "전치사구", adv_phrase: "부사구",
  proverb: "속담", prefix: "접두사", suffix: "접미사", infix: "접요사",
  name: "고유명사", abbrev: "약어", symbol: "기호", particle: "불변화사",
  contraction: "축약형", postp: "후치사", affix: "접사", root: "어근",
  counter: "단위성 의존명사", classifier: "분류사", unknown: "기타",
};
const POS_EN = {
  noun: "Noun", verb: "Verb", adj: "Adjective", adv: "Adverb", pron: "Pronoun",
  prep: "Preposition", conj: "Conjunction", intj: "Interjection", det: "Determiner",
  article: "Article", num: "Numeral", phrase: "Phrase", prep_phrase: "Prepositional phrase",
  proverb: "Proverb", prefix: "Prefix", suffix: "Suffix", name: "Proper noun",
  abbrev: "Abbreviation", symbol: "Symbol", particle: "Particle", contraction: "Contraction",
};
const TAG_KO = {
  obsolete: "폐어", archaic: "고어", dated: "예스러움", slang: "속어", informal: "비격식",
  formal: "격식", colloquial: "구어", rare: "드묾", vulgar: "비속어", derogatory: "경멸",
  figuratively: "비유", literary: "문어", humorous: "익살", British: "영국", UK: "영국",
  US: "미국", Australia: "호주", countable: "가산", uncountable: "불가산",
  transitive: "타동사", intransitive: "자동사", plural: "복수", singular: "단수",
  abbreviation: "약어",
};

const CITATION_RE = /^(c\.\s?)?\d{3,4}(s)?\s*([-–,]|$)/;
const HANGUL_RE = /[ᄀ-ᇿ㄰-㆏가-힣]/;
const JAMO_RE = /[ㄱ-ㅣ]/;
const STRIP_CHARS = " \t\r\n.,;:!?\"'()[]{}<>“”‘’«»…—–-*_/\\|`~@#$%^&+=0123456789";
const SUP = "⁰¹²³⁴⁵⁶⁷⁸⁹";
const sup = (n) => String(n).replace(/\d/g, (d) => SUP[d]);

export const normKey = (w) => (w || "").normalize("NFC").trim().toLowerCase();
export const koKey = (w) => normKey(w).split(/\s+/).join("").replace(/^-+|-+$/g, "");
export const isKorean = (t) => HANGUL_RE.test(t || "");

function stripChars(s) {
  let a = 0, b = s.length;
  while (a < b && STRIP_CHARS.includes(s[a])) a++;
  while (b > a && STRIP_CHARS.includes(s[b - 1])) b--;
  return s.slice(a, b);
}

export function cleanQuery(text) {
  if (!text) return "";
  text = text.normalize("NFC").replace(/­/g, "");
  text = text.replace(/-\s*\n\s*/g, "");
  text = text.split(/\s+/).filter(Boolean).join(" ");
  text = stripChars(text);
  text = text.replace(/['’]s$/, "");
  return [...text].slice(0, 120).join("");
}

export function englishVariants(word) {
  const w = word.toLowerCase(), out = [w];
  const add = (x) => { if (x && x.length > 1 && !out.includes(x)) out.push(x); };
  if (w.endsWith("ies")) add(w.slice(0, -3) + "y");
  if (w.endsWith("es")) add(w.slice(0, -2));
  if (w.endsWith("s") && !w.endsWith("ss")) add(w.slice(0, -1));
  if (w.endsWith("ied")) add(w.slice(0, -3) + "y");
  if (w.endsWith("ed")) {
    add(w.slice(0, -2)); add(w.slice(0, -1));
    if (w.length > 4 && w.at(-3) === w.at(-4)) add(w.slice(0, -3));
  }
  if (w.endsWith("ing")) {
    add(w.slice(0, -3)); add(w.slice(0, -3) + "e");
    if (w.length > 5 && w.at(-4) === w.at(-5)) add(w.slice(0, -4));
  }
  if (w.endsWith("er")) { add(w.slice(0, -2)); add(w.slice(0, -1)); }
  if (w.endsWith("est")) { add(w.slice(0, -3)); add(w.slice(0, -2)); }
  if (w.endsWith("ly")) { add(w.slice(0, -2)); if (w.endsWith("ily")) add(w.slice(0, -3) + "y"); }
  return out;
}

// ------------------------------------------------------------------ 결과 모델
// Doc: 줄 배열, 각 줄은 [글자, 스타일, 링크] 조각 배열
export class Doc {
  constructor() { this.lines = []; }
  line(...segs) { this.lines.push(segs.map((s) => (Array.isArray(s) ? [s[0], s[1] ?? null, s[2] ?? null] : [s, null, null]))); }
  blank() { if (this.lines.length && this.lines.at(-1).length) this.lines.push([]); }
  get empty() { return !this.lines.some((l) => l.length); }
  plainText() { return this.lines.map((l) => l.map((s) => s[0]).join("")).join("\n"); }
}

function newResult(query, lang = "en") {
  return { query, found: false, headword: "", ipa: "", lang, meaning: new Doc(), meaningEn: new Doc(),
    etymology: new Doc(), examples: new Doc(), suggestions: [], redirectedFrom: "", hasKo: false };
}

const PARTICLES = new Set([
  "이", "가", "을", "를", "은", "는", "에", "의", "도", "만", "와", "과", "로", "으로", "에서", "에게",
  "까지", "부터", "께", "한테", "보다", "처럼", "이다", "다", "요", "이요", "들", "랑", "이랑", "고", "며",
  "에는", "에도", "으로는", "로는", "이나", "나", "든지", "마다", "조차", "밖에", "하다", "했다", "하고",
  "하는", "한", "할", "해", "해서", "하여", "된", "되다", "적", "적인", "적으로", "들이", "들을", "들의",
]);
const SPECIAL_CATS = new Set(["역사", "불교", "가톨릭", "기독교", "종교 일반", "인명", "지명", "책명", "고유명 일반",
  "민속", "식물", "동물", "광업", "수산업", "임업", "한의", "수의", "북한어", "옛말", "방언"]);

const first = (arr, fn) => { for (const x of arr) { const v = fn(x); if (v) return v; } return ""; };

// ------------------------------------------------------------------ 사전
export class Dictionary {
  constructor(db) {
    this.db = db;
    this.meta = Object.fromEntries(db.all("SELECT key, value FROM meta"));
    this.blockCache = new Map();
  }

  get version() { return this.meta.version || "?"; }

  _block(id) {
    let b = this.blockCache.get(id);
    if (b) { this.blockCache.delete(id); this.blockCache.set(id, b); return b; }
    const row = this.db.all("SELECT data FROM blocks WHERE id=?", [id])[0];
    b = JSON.parse(this.db.inflate(row[0]));
    this.blockCache.set(id, b);
    if (this.blockCache.size > 80) this.blockCache.delete(this.blockCache.keys().next().value);
    return b;
  }

  _rows(key, lang) {
    return this.db.all("SELECT blk, pos FROM words WHERE key=? AND lang=? ORDER BY id", [key, lang]).map(([blk, pos]) => {
      const [word, src, data] = this._block(blk)[pos];
      return { word, lang, src, data };
    });
  }

  _koToEn(key) { return this.db.all("SELECT en, sense FROM ko_en WHERE ko=? LIMIT 60", [key]); }

  suggestions(prefix, lang = null, limit = 8) {
    const key = normKey(prefix);
    if (!key) return [];
    lang = lang || (isKorean(key) ? "ko" : "en");
    return this.db.all("SELECT DISTINCT word FROM words WHERE key >= ? AND key < ? AND lang=? LIMIT ?",
      [key, key + "￿", lang, limit]).map((r) => r[0]);
  }

  _existing(keys, lang) {
    keys = [...keys];
    const found = [];
    for (let i = 0; i < keys.length; i += 400) {
      const chunk = keys.slice(i, i + 400);
      const q = chunk.map(() => "?").join(",");
      for (const r of this.db.all(`SELECT DISTINCT key FROM words WHERE lang=? AND key IN (${q})`, [lang, ...chunk])) found.push(r[0]);
    }
    return found;
  }

  _freq(keys) {
    const out = new Map();
    keys = [...keys];
    for (let i = 0; i < keys.length; i += 400) {
      const chunk = keys.slice(i, i + 400);
      const q = chunk.map(() => "?").join(",");
      for (const [k, z] of this.db.all(`SELECT key, z FROM freq WHERE key IN (${q})`, chunk)) out.set(k, z);
    }
    return out;
  }

  _display(key, lang) {
    const words = this.db.all("SELECT word FROM words WHERE key=? AND lang=? ORDER BY id LIMIT 8", [key, lang]).map((r) => r[0]);
    if (!words.length) return key;
    return words.find((w) => w === key || w.toLowerCase() === w) || words[0];
  }

  exists(word) {
    const key = normKey(word), lang = isKorean(key) ? "ko" : "en";
    return this.db.all("SELECT 1 FROM words WHERE key=? AND lang=? LIMIT 1", [key, lang]).length > 0;
  }

  // 오타로 보이는 검색어와 비슷한 단어 (가까운 순 → 자주 쓰는 순)
  similar(text, limit = 8, fast = false) {
    const q = cleanQuery(text);
    if (!q) return [];
    const scored = new Map(); // "lang\tkey" → 점수
    const add = (lang, keys, distFn) => {
      const freq = this._freq(keys);
      for (const k of keys) {
        const d = distFn(k);
        if (d > 2) continue;
        const sc = d - (freq.get(k) || 0) * 0.012;
        const id = lang + "\t" + k;
        if (sc < (scored.get(id) ?? 99)) scored.set(id, sc);
      }
    };
    if (isKorean(q)) {
      const key = koKey(q), klen = [...key].length;
      if (!fast || klen <= 6) add("ko", this._existing(fuzzy.edits1Ko(key), "ko"), (k) => fuzzy.koDistance(key, k, 2));
      if (!fast && klen >= 2) {
        const f = [...key][0];
        const rows = this.db.all(
          "SELECT DISTINCT key FROM words WHERE lang='ko' AND key >= ? AND key < ? AND length(key) BETWEEN ? AND ? LIMIT 6000",
          [f, String.fromCodePoint(f.codePointAt(0) + 1), Math.max(1, klen - 1), klen + 1]);
        add("ko", rows.map((r) => r[0]).filter((k) => k !== key), (k) => fuzzy.koDistance(key, k, 2));
      }
      const eng = fuzzy.korToKeys(q).toLowerCase();
      if ((JAMO_RE.test(q) || !scored.size) && /^[a-z ]+$/.test(eng) && /[a-z]/.test(eng) && (!fast || eng.length >= 4)) {
        const cand = englishVariants(eng)[0];
        if (this._existing([normKey(cand)], "en").length) scored.set("en\t" + normKey(cand), -5);
      }
    } else {
      const key = normKey(q);
      const kor = fuzzy.keysToKor(q);
      if (kor && fuzzy.isSyllable(kor[0]) && [...kor].every((c) => fuzzy.isSyllable(c) || c === " ")) {
        const kk = koKey(kor);
        if (this._existing([kk], "ko").length) scored.set("ko\t" + kk, -5);
      }
      if (key.length >= 2) {
        add("en", this._existing(fuzzy.edits1En(key), "en"), (k) => fuzzy.osaDistance(key, k, 2));
        if (!fast && key.length >= 4) {
          const pre = key.length >= 6 ? key.slice(0, 3) : key.slice(0, 2);
          const rows = this.db.all(
            "SELECT DISTINCT key FROM words WHERE lang='en' AND key >= ? AND key < ? AND length(key) BETWEEN ? AND ? LIMIT 6000",
            [pre, pre + "￿", key.length - 2, key.length + 2]);
          add("en", rows.map((r) => r[0]).filter((k) => k !== key), (k) => fuzzy.osaDistance(key, k, 2));
        }
      }
    }
    const best = [...scored.entries()].sort((a, b) => a[1] - b[1] || (a[0].split("\t")[1] < b[0].split("\t")[1] ? -1 : 1));
    const out = [];
    for (const [id] of best) {
      const [lang, k] = id.split("\t");
      if (k === normKey(q) || k === koKey(q)) continue;
      const w = this._display(k, lang);
      if (!out.includes(w)) out.push(w);
      if (out.length >= limit) break;
    }
    return out;
  }

  // ---------------------------------------------------------- 검색
  lookup(raw) {
    const q = cleanQuery(raw);
    let res = newResult(q);
    if (!q) return res;
    if (JAMO_RE.test(q)) {
      const eng = fuzzy.korToKeys(q).toLowerCase();
      if (/^[\x00-\x7f]+$/.test(eng) && this._existing([normKey(eng)], "en").length) {
        res.lang = "en";
        this._lookupEn(eng, res);
        if (res.found) { res.redirectedFrom = q; return res; }
        res = newResult(q);
      }
    }
    if (isKorean(q)) {
      res.lang = "ko";
      this._lookupKo(q, res);
    } else {
      res.lang = "en";
      this._lookupEn(q, res);
      if (!res.found) {
        const kor = fuzzy.keysToKor(q);
        if (kor && [...kor].every((c) => fuzzy.isSyllable(c) || c === " ") && this._existing([koKey(kor)], "ko").length) {
          const r2 = newResult(q, "ko");
          this._lookupKo(kor, r2);
          if (r2.found) { r2.redirectedFrom = q; return r2; }
        }
      }
    }
    if (!res.found && !res.suggestions.length) {
      const sim = this.similar(q, 8);
      const pre = this.suggestions(q.slice(0, Math.max(3, q.length - 2)), res.lang).filter((w) => !sim.includes(w));
      res.suggestions = [...sim, ...pre].slice(0, 8);
    }
    return res;
  }

  // ---------------------------------------------------------- 영어 → 한국어
  _lookupEn(q, res) {
    let rows = [], used = q;
    for (const cand of englishVariants(q)) {
      rows = this._rows(normKey(cand), "en");
      if (rows.length) { used = cand; break; }
    }
    if (!rows.length) return;
    if (normKey(used) !== normKey(q)) res.redirectedFrom = q;
    const exact = new Set(rows.filter((r) => r.word === q || r.word === used));
    rows.sort((a, b) => (exact.has(a) ? 0 : 1) - (exact.has(b) ? 0 : 1) || (a.word < b.word ? -1 : a.word > b.word ? 1 : 0));

    res.found = true;
    res.headword = rows[0].word;
    res.ipa = first(rows, (r) => r.data.ipa?.[0]);

    const lemmas = [];
    for (const r of rows) for (const s of r.data.s || []) {
      const fo = s.fo;
      if (fo && !lemmas.includes(fo) && normKey(fo) !== normKey(r.word)) lemmas.push(fo);
    }
    const lemmaRows = [];
    for (const lm of lemmas.slice(0, 3)) lemmaRows.push(...this._rows(normKey(lm), "en"));

    const hasKo = Dictionary._hasKo;
    res.hasKo = hasKo(rows) || (lemmaRows.length > 0 && hasKo(lemmaRows));
    const formOnly = rows.every((r) => (r.data.s || []).every((s) => s.fo)) && !hasKo(rows);
    const showNote = !hasKo(rows) && !(lemmaRows.length && hasKo(lemmaRows));
    const lemmaKo = lemmaRows.length > 0 && hasKo(lemmaRows);
    if (formOnly && lemmaKo) {
      const gloss = first(rows, (r) => first(r.data.s || [], (s) => s.g));
      for (const lm of lemmas.slice(0, 3)) {
        const lr = lemmaRows.filter((r) => normKey(r.word) === normKey(lm));
        if (!lr.length) continue;
        for (const d of [res.meaning, res.meaningEn]) d.line(["▶ 원형 ", "sec"], [lm, "link", lm], [gloss ? `   (${gloss})` : "", "dim"]);
        this._renderEnMeaning(lr, res, false);
        for (const d of [res.meaning, res.meaningEn]) d.blank();
      }
      if (!res.ipa) res.ipa = first(lemmaRows, (r) => r.data.ipa?.[0]);
      this._renderEtymology([...rows, ...lemmaRows], res);
      this._renderExamples([...lemmaRows, ...rows], res);
      return;
    }
    this._renderEnMeaning(rows, res, showNote, lemmaRows.length > 0 && formOnly);
    if (lemmaRows.length) {
      for (const lm of lemmas.slice(0, 3)) {
        const lr = lemmaRows.filter((r) => normKey(r.word) === normKey(lm));
        if (!lr.length) continue;
        for (const d of [res.meaning, res.meaningEn]) { d.blank(); d.line(["▶ 원형 ", "sec"], [lm, "link", lm]); }
        this._renderEnMeaning(lr, res, false, !formOnly);
      }
      if (!res.ipa) res.ipa = first(lemmaRows, (r) => r.data.ipa?.[0]);
    }
    this._renderEtymology([...rows, ...lemmaRows], res);
    this._renderExamples([...rows, ...lemmaRows], res);
  }

  static _hasKo(rows) {
    return rows.some((r) => (r.src === "ko" && (r.data.s || []).some((x) => x.g)) || (r.data.ko && r.data.ko.length));
  }

  static _tags(sense) {
    const tags = sense.t || [];
    if (!tags.length) return [];
    return [["(" + tags.map((t) => TAG_KO[t] || t).join(", ") + ") ", "tag"]];
  }

  _renderEnMeaning(rows, res, showNote = true, compact = false) {
    const doc = res.meaning, en = res.meaningEn;
    const multi = new Set(rows.map((r) => r.word)).size > 1;
    const koRows = rows.filter((r) => r.src === "ko"), enRows = rows.filter((r) => r.src === "en");
    let wroteKo = false;
    for (const r of koRows) {
      const senses = (r.data.s || []).filter((s) => s.g);
      if (!senses.length) continue;
      const p = r.data.p;
      const label = !p || p === "unknown" ? r.data.pt || "한국어 뜻" : POS_KO[p] || r.data.pt || p;
      const head = [["• " + label, "pos"]];
      if (multi) head.push(["  " + r.word, "dim"]);
      doc.line(...head);
      senses.forEach((s, i) => doc.line([`  ${i + 1}. `, "num"], ...Dictionary._tags(s), [s.g, "ko"]));
      wroteKo = true;
    }
    const trans = [];
    for (const r of enRows) for (const [sense, words] of r.data.ko || []) trans.push([r.data.p, sense, words]);
    if (trans.length) {
      if (wroteKo) doc.blank();
      doc.line(["한국어 번역어", "sec"]);
      for (const [pos, sense, words] of trans.slice(0, 14)) {
        const segs = [["  · ", "dim"]];
        if (POS_KO[pos]) segs.push([`[${POS_KO[pos]}] `, "tag"]);
        segs.push([words.join(", "), "ko"]);
        if (sense) segs.push(["  — " + sense, "dim"]);
        doc.line(...segs);
      }
      wroteKo = true;
    }
    const targets = wroteKo ? [en] : [en, doc];
    if (!wroteKo && showNote) {
      doc.line(["한국어 뜻풀이가 아직 없는 단어예요. 영어 뜻을 보여드려요. ('웹사전' 버튼으로 포털 사전을 열 수 있어요)", "note"]);
      doc.blank();
    }
    for (const r of enRows) {
      const senses = r.data.s || [];
      if (!senses.length) continue;
      const p = r.data.p;
      const label = `${POS_KO[p] || p} (${POS_EN[p] || p})`;
      for (const d of targets) {
        const head = [["• " + label, "pos"]];
        if (multi) head.push(["  " + r.word, "dim"]);
        d.line(...head);
        senses.slice(0, compact ? 6 : 20).forEach((s, i) => {
          const segs = [[`  ${i + 1}. `, "num"], ...Dictionary._tags(s)];
          if (s.g) segs.push([s.g, "en"]);
          if (s.fo) segs.push(["  → ", "dim"], [s.fo, "link", s.fo]);
          d.line(...segs);
        });
      }
    }
    const syn = [], ant = [];
    for (const r of rows) {
      for (const w of r.data.syn || []) if (!syn.includes(w)) syn.push(w);
      for (const w of r.data.ant || []) if (!ant.includes(w)) ant.push(w);
    }
    if ((syn.length || ant.length) && !compact) {
      doc.blank();
      for (const [title, words] of [["유의어", syn], ["반의어", ant]]) {
        if (!words.length) continue;
        const segs = [[title + "  ", "sec"]];
        words.slice(0, 10).forEach((w, j) => { if (j) segs.push([", ", "dim"]); segs.push([w, "link", w]); });
        doc.line(...segs);
      }
    }
  }

  // ---------------------------------------------------------- 한국어 → 영어
  _koRows(key) {
    const rows = [], pairs = [], seen = new Set(), pseen = new Set();
    for (const k of new Set([key, koKey(key)])) {
      for (const r of this._rows(k, "ko")) {
        const sig = r.word + "\t" + r.src + "\t" + JSON.stringify(r.data);
        if (!seen.has(sig)) { seen.add(sig); rows.push(r); }
      }
      for (const p of this._koToEn(k)) {
        const ps = p.join("\t");
        if (!pseen.has(ps)) { pseen.add(ps); pairs.push(p); }
      }
    }
    return [rows, pairs];
  }

  _lookupKo(q, res) {
    let key = normKey(q);
    let [rows, pairs] = this._koRows(key);
    if (!rows.length && !pairs.length) {
      const k0 = [...koKey(key)];
      for (let cut = 1; cut <= Math.min(3, k0.length - 1); cut++) {
        const k2 = k0.slice(0, -cut).join("");
        const [r2, p2] = this._koRows(k2);
        if (!r2.length && !p2.length) continue;
        if (!PARTICLES.has(k0.slice(-cut).join(""))) {
          const sim = this.similar(q, 8);
          if (sim.length) {
            res.suggestions = [...sim, ...(r2.length && !sim.includes(r2[0].word) ? [r2[0].word] : [])];
            return;
          }
        }
        rows = r2; pairs = p2; res.redirectedFrom = q; key = k2;
        break;
      }
    }
    if (!rows.length && !pairs.length) return;
    res.found = true;
    const doc = res.meaning;
    const koRows = rows.filter((r) => r.src === "ko"), enRows = rows.filter((r) => r.src === "en");
    const unitOrder = { 단어: 0, "": 1, 구: 2, 관용구: 3, 속담: 4 };
    const kodictRows = Dictionary._sortHomographs(koRows.filter((r) => r.data.d), unitOrder);
    const wikiRows = koRows.filter((r) => !r.data.d);

    res.headword = rows.length ? (kodictRows[0] || koRows[0] || rows[0]).word : key;
    const f = kodictRows[0]?.data || {};
    const hanja = f.hj || first(rows, (r) => r.data.hj);
    const pron = f.pr ? `[${f.pr}]` : "";
    const rom = first(rows, (r) => r.data.rom);
    const ipa = first(rows, (r) => r.data.ipa?.[0]);
    res.ipa = [hanja, pron || ipa, rom].filter(Boolean).join(" · ");

    if (kodictRows.length) {
      const srcs = [...new Set(kodictRows.map((r) => r.data.d))].sort((a, b) => (a !== "표준") - (b !== "표준"));
      doc.line(["국어 뜻풀이", "sec"], ["   " + srcs.map((d) => (d === "표준" ? "표준국어대사전" : d)).join(" · "), "dim"]);
      let last = null, num = 0, shown = 0;
      for (const r of kodictRows) {
        const d = r.data, head = r.word + "\t" + (d.n || 0);
        if (head !== last) {
          if (shown >= 15) { doc.line(["  … 같은 소리의 단어가 더 있어요. 웹사전에서 확인해 보세요.", "note"]); break; }
          shown++; last = head; num = 0;
          const segs = [["▪ " + r.word + (d.n ? sup(d.n) : ""), "pos"]];
          const extra = [d.hj, d.or, d.pr ? `[${d.pr}]` : ""].filter(Boolean).join(" ");
          if (extra) segs.push(["  " + extra, "dim"]);
          doc.line(...segs);
        }
        const label = d.p || d.u || "";
        if (label) doc.line(["  「" + label + "」", "tag"]);
        for (const s of (d.s || []).slice(0, 20)) { num++; doc.line([`  ${num}. `, "num"], ...Dictionary._tags(s), [s.g || "", "ko"]); }
      }
      this._renderRel(doc, kodictRows);
      doc.blank();
    } else if (wikiRows.length) {
      doc.line(["국어 뜻풀이", "sec"]);
      for (const r of wikiRows) {
        const p = r.data.p;
        doc.line(["• " + (r.data.pt || POS_KO[p] || p || ""), "pos"]);
        (r.data.s || []).slice(0, 12).forEach((s, i) => doc.line([`  ${i + 1}. `, "num"], [s.g || "", "ko"]));
      }
      doc.blank();
    }

    const enWords = [], seenEn = new Set();
    for (const [en, sense] of pairs) {
      if (seenEn.has(en.toLowerCase())) continue;
      seenEn.add(en.toLowerCase());
      enWords.push([en, sense || ""]);
    }
    if (enWords.length) {
      doc.line(["영어 대응어", "sec"]);
      for (const [en, sense] of enWords.slice(0, 25)) {
        const segs = [["  · ", "dim"], [en, "link", en]];
        if (sense) segs.push(["  — " + sense, "dim"]);
        doc.line(...segs);
      }
      doc.blank();
    }
    if (enRows.length) {
      doc.line(["영어 뜻풀이", "sec"]);
      for (const r of enRows) {
        const p = r.data.p;
        doc.line(["• " + (POS_KO[p] || p || ""), "pos"]);
        (r.data.s || []).slice(0, 12).forEach((s, i) => {
          const segs = [[`  ${i + 1}. `, "num"], ...Dictionary._tags(s)];
          if (s.g) segs.push([s.g, "en"]);
          if (s.fo) segs.push(["  → ", "dim"], [s.fo, "link", s.fo]);
          doc.line(...segs);
        });
      }
    }
    res.meaningEn = res.meaning;

    let lastE = null;
    for (const r of kodictRows) {
      const d = r.data, head = r.word + "\t" + (d.n || 0);
      if (head === lastE || !(d.hj || d.or)) continue;
      lastE = head;
      res.etymology.line([r.word + (d.n ? sup(d.n) : ""), "pos"], ["   " + (d.d === "표준" ? "표준국어대사전" : d.d || ""), "dim"]);
      res.etymology.line(["원어: " + [d.hj, d.or].filter(Boolean).join(" "), "ko"]);
      res.etymology.blank();
    }
    this._renderEtymology(rows, res);
    this._renderExamples([...kodictRows, ...rows.filter((r) => !kodictRows.includes(r))], res);
  }

  static _sortHomographs(rows, unitOrder) {
    const groups = new Map();
    for (const r of rows) {
      const k = r.word + "\t" + (r.data.n || 0);
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(r);
    }
    const score = (rs) => {
      const senses = rs.flatMap((r) => r.data.s || []);
      const hasEx = senses.some((s) => s.ex && s.ex.length);
      const general = senses.filter((s) => !(s.t || []).some((t) => SPECIAL_CATS.has(t))).length;
      const redirect = senses.every((s) => (s.g || "").startsWith("→"));
      const unit = Math.min(...rs.map((r) => unitOrder[r.data.u || ""] ?? 5));
      return [unit, redirect ? 1 : 0, -(hasEx * 3 + Math.min(general, 6) + 0.2 * Math.min(senses.length, 10)), rs[0].data.n || 0];
    };
    const items = [...groups.values()].map((rs) => [score(rs), rs]);
    items.sort((a, b) => { for (let i = 0; i < 4; i++) if (a[0][i] !== b[0][i]) return a[0][i] - b[0][i]; return 0; });
    return items.flatMap(([, rs]) => rs);
  }

  _renderRel(doc, rows) {
    const syn = [], ant = [];
    for (const r of rows) {
      for (const w of r.data.syn || []) if (!syn.includes(w)) syn.push(w);
      for (const w of r.data.ant || []) if (!ant.includes(w)) ant.push(w);
    }
    for (const [title, words] of [["비슷한말", syn], ["반대말", ant]]) {
      if (!words.length) continue;
      const segs = [["  " + title + "  ", "sec"]];
      words.slice(0, 10).forEach((w, j) => { if (j) segs.push([", ", "dim"]); segs.push([w, "link", w]); });
      doc.line(...segs);
    }
  }

  _renderEtymology(rows, res) {
    const doc = res.etymology, seen = new Set();
    for (const r of rows) {
      const ety = r.data.ety;
      if (!ety || seen.has(ety)) continue;
      seen.add(ety);
      const src = r.data.d ? (r.data.d === "표준" ? "표준국어대사전" : r.data.d)
        : r.src === "en" ? "영어판 위키낱말사전" : "한국어판 위키낱말사전";
      doc.line([r.word, "pos"], [`   ${src}`, "dim"]);
      doc.line([ety, r.src === "en" ? "en" : "ko"]);
      doc.blank();
    }
    if (doc.empty) doc.line(["이 단어의 어원 정보가 아직 없어요.", "note"]);
  }

  _renderExamples(rows, res) {
    const doc = res.examples, seen = new Set();
    let count = 0;
    const sorted = [...rows].sort((a, b) => (a.src !== "ko") - (b.src !== "ko"));
    for (const r of sorted) for (const s of r.data.s || []) for (const ex of s.ex || []) {
      const text = ex[0];
      if (seen.has(text) || CITATION_RE.test(text)) continue;
      seen.add(text);
      count++;
      doc.line([`${count}. `, "num"], [text, "ex"]);
      if (ex.length > 1 && ex[1]) doc.line(["    "], [ex[1], "tr"]);
      if (s.g) doc.line(["    "], ["뜻: " + s.g, "dim"]);
      doc.blank();
      if (count >= 30) return;
    }
    if (doc.empty) doc.line(["이 단어의 예문이 아직 없어요.", "note"]);
  }
}

// 화면으로 보낼 수 있게 (Doc → 줄 배열)
export function serialize(res) {
  const out = { ...res };
  for (const k of ["meaning", "meaningEn", "etymology", "examples"]) out[k] = res[k].lines;
  return out;
}
