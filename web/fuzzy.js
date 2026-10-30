// 오타 교정 도우미 — app/fuzzy.py 와 같은 규칙 (PC판과 결과가 같도록 유지)
//  - 한글은 자모(초성·중성·종성) 단위로 비교 ('사괴 → 사과')
//  - 한/영 자판을 잘못 두고 친 경우를 바꿔 본다 ('tkrhk' → '사과', 'ㅗ디ㅣㅐ' → 'hello')

const SBASE = 0xac00, LCOUNT = 19, VCOUNT = 21, TCOUNT = 28, NCOUNT = VCOUNT * TCOUNT;
export const CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ";
export const JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ";
export const JONG = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ";

export const isSyllable = (ch) => { const c = ch.codePointAt(0); return c >= 0xac00 && c <= 0xd7a3; };
const split = (ch) => { const c = ch.codePointAt(0) - SBASE; return [Math.floor(c / NCOUNT), Math.floor((c % NCOUNT) / TCOUNT), c % TCOUNT]; };
const join = (l, v, t = 0) => String.fromCodePoint(SBASE + (l * VCOUNT + v) * TCOUNT + t);

export function toJamo(text) {
  let out = "";
  for (const ch of text) {
    if (isSyllable(ch)) {
      const [l, v, t] = split(ch);
      out += CHO[l] + JUNG[v] + (t ? JONG[t] : "");
    } else out += ch;
  }
  return out;
}

// Optimal String Alignment 거리 (limit 를 넘으면 limit+1)
export function osaDistance(a, b, limit = 3) {
  if (a === b) return 0;
  a = [...a]; b = [...b];
  const la = a.length, lb = b.length;
  if (Math.abs(la - lb) > limit) return limit + 1;
  if (!la || !lb) return Math.max(la, lb);
  let prev2 = null, prev = Array.from({ length: lb + 1 }, (_, i) => i);
  for (let i = 1; i <= la; i++) {
    const cur = new Array(lb + 1).fill(0);
    cur[0] = i;
    let best = i;
    const ai = a[i - 1];
    for (let j = 1; j <= lb; j++) {
      const cost = ai === b[j - 1] ? 0 : 1;
      let v = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
      if (prev2 && i > 1 && j > 1 && ai === b[j - 2] && a[i - 2] === b[j - 1]) v = Math.min(v, prev2[j - 2] + 1);
      cur[j] = v;
      if (v < best) best = v;
    }
    if (best > limit) return limit + 1;
    prev2 = prev; prev = cur;
  }
  return prev[lb];
}

export const koDistance = (a, b, limit = 3) => osaDistance(toJamo(a), toJamo(b), limit);

const EN_LETTERS = "abcdefghijklmnopqrstuvwxyz-' ";

export function edits1En(word) {
  const out = new Set();
  for (let i = 0; i <= word.length; i++) {
    const a = word.slice(0, i), b = word.slice(i);
    if (b) {
      out.add(a + b.slice(1));
      if (b.length > 1) out.add(a + b[1] + b[0] + b.slice(2));
      for (const c of EN_LETTERS) out.add(a + c + b.slice(1));
    }
    for (const c of EN_LETTERS) out.add(a + c + b);
  }
  out.delete(word);
  return [...out].filter((w) => w && w.trim() === w);
}

export function edits1Ko(word) {
  const chars = [...word], n = chars.length, out = new Set();
  for (let i = 0; i < n; i++) {
    const ch = chars[i];
    const a = chars.slice(0, i).join(""), b = chars.slice(i + 1).join("");
    if (n > 1) out.add(a + b);
    if (i + 1 < n) out.add(a + chars[i + 1] + ch + chars.slice(i + 2).join(""));
    if (!isSyllable(ch)) continue;
    const [l, v, t] = split(ch);
    for (let x = 0; x < LCOUNT; x++) if (x !== l) out.add(a + join(x, v, t) + b);
    for (let x = 0; x < VCOUNT; x++) if (x !== v) out.add(a + join(l, x, t) + b);
    for (let x = 0; x < TCOUNT; x++) if (x !== t) out.add(a + join(l, v, x) + b);
    // 받침이 다음 글자 초성으로 넘어간 경우 ('갑아' ↔ '가바')
    if (i + 1 < n && isSyllable(chars[i + 1])) {
      const [l3, v3, t3] = split(chars[i + 1]);
      const rest = chars.slice(i + 2).join("");
      if (t && l3 === 11) {
        const cho = CHO.indexOf(JONG[t]);
        if (cho >= 0) out.add(a + join(l, v, 0) + join(cho, v3, t3) + rest);
      }
      if (!t) {
        const jong = JONG.indexOf(CHO[l3]);
        if (jong > 0) out.add(a + join(l, v, jong) + join(11, v3, t3) + rest);
      }
    }
  }
  out.delete(word);
  return [...out];
}

// 두벌식 자판
const KEY2JAMO = {
  q: "ㅂ", w: "ㅈ", e: "ㄷ", r: "ㄱ", t: "ㅅ", y: "ㅛ", u: "ㅕ", i: "ㅑ", o: "ㅐ", p: "ㅔ",
  a: "ㅁ", s: "ㄴ", d: "ㅇ", f: "ㄹ", g: "ㅎ", h: "ㅗ", j: "ㅓ", k: "ㅏ", l: "ㅣ",
  z: "ㅋ", x: "ㅌ", c: "ㅊ", v: "ㅍ", b: "ㅠ", n: "ㅜ", m: "ㅡ",
  Q: "ㅃ", W: "ㅉ", E: "ㄸ", R: "ㄲ", T: "ㅆ", O: "ㅒ", P: "ㅖ",
};
const JAMO2KEY = {};
for (const [k, j] of Object.entries(KEY2JAMO)) if (!(j in JAMO2KEY)) JAMO2KEY[j] = k;
const COMPOUND_V = { ㅘ: "ㅗㅏ", ㅙ: "ㅗㅐ", ㅚ: "ㅗㅣ", ㅝ: "ㅜㅓ", ㅞ: "ㅜㅔ", ㅟ: "ㅜㅣ", ㅢ: "ㅡㅣ" };
const COMPOUND_T = { ㄳ: "ㄱㅅ", ㄵ: "ㄴㅈ", ㄶ: "ㄴㅎ", ㄺ: "ㄹㄱ", ㄻ: "ㄹㅁ", ㄼ: "ㄹㅂ", ㄽ: "ㄹㅅ", ㄾ: "ㄹㅌ", ㄿ: "ㄹㅍ", ㅀ: "ㄹㅎ", ㅄ: "ㅂㅅ" };
const V_JOIN = Object.fromEntries(Object.entries(COMPOUND_V).map(([k, v]) => [v, k]));
const T_JOIN = Object.fromEntries(Object.entries(COMPOUND_T).map(([k, v]) => [v, k]));

// 'ㅁㅔㅔㅣㄷ' → 'apple' (한글 자판 상태로 영어를 친 경우)
export function korToKeys(text) {
  let out = "";
  for (const ch of text) {
    const jamo = isSyllable(ch) ? toJamo(ch) : ch;
    for (const j of jamo) {
      const parts = COMPOUND_V[j] || COMPOUND_T[j] || j;
      for (const x of parts) out += JAMO2KEY[x] ?? x;
    }
  }
  return out;
}

// 'tkrhk' → '사과' (영문 자판 상태로 한글을 친 경우). 바꿀 수 없으면 ''
export function keysToKor(text) {
  const seq = [];
  for (const c of text) {
    const j = KEY2JAMO[c] || KEY2JAMO[c.toLowerCase()];
    if (!j) {
      if (c === " ") { seq.push(" "); continue; }
      return "";
    }
    seq.push(j);
  }
  return composeJamo(seq);
}

export function composeJamo(seq) {
  const isV = (j) => JUNG.includes(j);
  const isC = (j) => CHO.includes(j) || JONG.includes(j);
  let out = "", i = 0;
  const n = seq.length;
  while (i < n) {
    const j = seq[i];
    if (j === " " || !CHO.includes(j)) {
      if (i + 1 < n && V_JOIN[j + seq[i + 1]]) { out += V_JOIN[j + seq[i + 1]]; i += 2; }
      else { out += j; i += 1; }
      continue;
    }
    if (i + 1 >= n || !isV(seq[i + 1])) { out += j; i += 1; continue; }
    const l = CHO.indexOf(j);
    let vj = seq[i + 1], k = i + 2;
    if (k < n && V_JOIN[vj + seq[k]]) { vj = V_JOIN[vj + seq[k]]; k += 1; }
    const v = JUNG.indexOf(vj);
    let t = 0;
    if (k < n && isC(seq[k]) && JONG.slice(1).includes(seq[k]) && !(k + 1 < n && isV(seq[k + 1]))) {
      let tj = seq[k], k2 = k + 1;
      if (k2 < n && T_JOIN[tj + seq[k2]] && !(k2 + 1 < n && isV(seq[k2 + 1]))) { tj = T_JOIN[tj + seq[k2]]; k2 += 1; }
      t = JONG.indexOf(tj);
      k = k2;
    }
    out += join(l, v, t);
    i = k;
  }
  return out;
}
