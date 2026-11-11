// 문장 번역 (인터넷 필요) — PC판 app/translate.py 를 옮긴 것. 규칙을 바꾸면 양쪽을 같이 고쳐 주세요.
//  · 기본: 키 없이 쓰는 무료 번역(MyMemory)
//  · 선택: Google 번역(내 API 키), 브라우저 내장 번역(PC Chrome 138 이상, 기기 안에서 번역)
//  (DeepL·파파고 API 는 브라우저에서 직접 부를 수 없어서 PC판에서만 고를 수 있어요)

export const MAX_CHARS = 3000;

export const ENGINES = {
  mymemory: { name: "무료 번역 (MyMemory · 키 필요 없음)", short: "MyMemory" },
  google: { name: "Google 번역 (내 API 키)", short: "Google" },
  builtin: { name: "브라우저 내장 번역 (PC Chrome · 기기 안에서)", short: "브라우저 내장" },
};

export const LANG_NAMES = { ko: "한국어", en: "영어", ja: "일본어", zh: "중국어", ru: "러시아어" };

export class TranslateError extends Error {}

export function normalize(text) {
  if (!text) return "";
  text = text.normalize("NFC").replace(/­/g, "").replace(/\r/g, "");
  text = text.replace(/(\w)-\s*\n\s*(\w)/g, "$1$2");
  return text.split(/\n\s*\n/).map((p) => p.split(/\s+/).filter(Boolean).join(" ")).filter(Boolean).join("\n\n").trim();
}

const count = (re, t) => (t.match(re) || []).length;

export function detectLang(text) {
  const ko = count(/[가-힣ㄱ-ㆎ]/g, text), kana = count(/[぀-ヿ]/g, text);
  const han = count(/[一-鿿]/g, text), cyr = count(/[Ѐ-ӿ]/g, text);
  const lat = count(/[A-Za-zÀ-ɏ]/g, text);
  if (ko && ko >= 0.3 * (lat + kana + han + cyr)) return "ko";
  if (kana) return "ja";
  if (han && han >= lat) return "zh";
  if (cyr && cyr >= lat) return "ru";
  return "en";
}

export const targetFor = (src) => (src === "ko" ? "en" : "ko");

// 사전 대신 바로 번역할 만한 글인지 (단어·짧은 숙어는 사전으로)
export function looksLikeSentence(text) {
  const t = normalize(text);
  if (!t) return false;
  const words = t.split(/\s+/);
  if (t.includes("\n") || [...t].length > 40 || words.length >= 4) return true;
  return words.length >= 2 && /[.!?。？！]\s+\S/.test(t);
}

const bytes = (s) => new TextEncoder().encode(s).length;

export function splitChunks(text, maxBytes) {
  const pieces = [];
  for (const para of text.split("\n\n")) {
    for (let sent of para.split(/(?<=[.!?。？！])\s+/)) {
      if (!sent) continue;
      while (bytes(sent) > maxBytes) {
        let cut = "";
        for (const ch of sent) { if (bytes(cut + ch) > maxBytes) break; cut += ch; }
        const pos = Math.max(cut.lastIndexOf(", "), cut.lastIndexOf(" "));
        if (pos > cut.length / 3) cut = cut.slice(0, pos + 1);
        pieces.push(cut.trim());
        sent = sent.slice(cut.length).trim();
      }
      if (sent) pieces.push(sent);
    }
    pieces.push("\n\n");
  }
  if (pieces[pieces.length - 1] === "\n\n") pieces.pop();
  const chunks = [];
  let cur = "";
  for (const p of pieces) {
    if (p === "\n\n") { if (cur) chunks.push(cur); cur = ""; chunks.push("\n\n"); continue; }
    const joined = cur ? `${cur} ${p}` : p;
    if (bytes(joined) <= maxBytes) cur = joined;
    else { if (cur) chunks.push(cur); cur = p; }
  }
  if (cur) chunks.push(cur);
  return chunks;
}

function join(chunks, outs) {
  let text = "";
  chunks.forEach((c, i) => {
    if (c === "\n\n") text = text.trimEnd() + "\n\n";
    else text += (text && !text.endsWith("\n") ? " " : "") + outs[i].trim();
  });
  return text.trim();
}

async function getJSON(url, init) {
  let r;
  try { r = await fetch(url, init); } catch {
    throw new TranslateError("인터넷에 연결되지 않아 번역하지 못했어요. 단어는 오프라인 사전으로 찾을 수 있어요.");
  }
  if (r.status === 401 || r.status === 403) throw new TranslateError("API 키가 맞지 않거나 사용 권한이 없어요. 메뉴 → 번역 설정에서 확인해 주세요.");
  if (r.status === 429) throw new TranslateError("번역 사용량 한도를 넘었어요. 잠시 뒤에 다시 해 주세요.");
  if (!r.ok) throw new TranslateError(`번역 서비스 오류 (${r.status})`);
  try { return await r.json(); } catch { throw new TranslateError("번역 서비스의 응답을 읽지 못했어요."); }
}

const zh = (lang) => (lang === "zh" ? "zh-CN" : lang);

async function mymemory(text, src, tgt, opts) {
  const chunks = splitChunks(text, 450);
  const outs = [];
  for (const c of chunks) {
    if (c === "\n\n") { outs.push(""); continue; }
    const p = new URLSearchParams({ q: c, langpair: `${zh(src)}|${zh(tgt)}` });
    if (opts.email) p.set("de", opts.email);
    const d = await getJSON("https://api.mymemory.translated.net/get?" + p);
    const out = (d.responseData && d.responseData.translatedText) || "";
    const status = String(d.responseStatus ?? "200");
    if (d.quotaFinished || out.includes("MYMEMORY WARNING") || status === "429") {
      throw new TranslateError("오늘 무료 번역 사용량을 다 썼어요. 내일 다시 쓰거나, 번역 설정에서 이메일을 넣으면 하루 사용량이 10배로 늘어요.");
    }
    if (status !== "200") throw new TranslateError("무료 번역 서비스 오류: " + (d.responseDetails || status));
    outs.push(out);
  }
  return join(chunks, outs);
}

async function google(text, src, tgt, opts) {
  if (!opts.googleKey) throw new TranslateError("메뉴 → 번역 설정에서 Google 번역 API 키를 넣어 주세요.");
  const body = new URLSearchParams({ q: text, target: zh(tgt), format: "text" });
  const d = await getJSON("https://translation.googleapis.com/language/translate/v2?key=" + encodeURIComponent(opts.googleKey),
    { method: "POST", body });
  return ((d.data && d.data.translations) || []).map((t) => t.translatedText).join("");
}

export const builtinSupported = () => typeof self !== "undefined" && "Translator" in self;

async function builtin(text, src, tgt) {
  if (!builtinSupported()) throw new TranslateError("이 브라우저에는 내장 번역 기능이 없어요 (PC용 Chrome 138 이상에서만 돼요). 번역 설정에서 무료 번역을 골라 주세요.");
  const pair = { sourceLanguage: src, targetLanguage: tgt };
  const avail = await self.Translator.availability(pair);
  if (avail === "unavailable") throw new TranslateError(`브라우저 내장 번역이 ${LANG_NAMES[src] || src} → ${LANG_NAMES[tgt]} 를 지원하지 않아요.`);
  const tr = await self.Translator.create(pair);
  try {
    const parts = [];
    for (const para of text.split("\n\n")) parts.push(await tr.translate(para));
    return parts.join("\n\n");
  } finally { tr.destroy && tr.destroy(); }
}

const FUNCS = { mymemory, google, builtin };
const cache = new Map();

// opts: { engine, email, googleKey }
export async function translate(raw, opts) {
  let text = normalize(raw);
  if (!text) throw new TranslateError("번역할 글이 없어요.");
  const truncated = [...text].length > MAX_CHARS;
  if (truncated) text = [...text].slice(0, MAX_CHARS).join("");
  const src = detectLang(text), tgt = targetFor(src);
  const engine = FUNCS[opts.engine] ? opts.engine : "mymemory";
  const key = [engine, src, tgt, text].join("\u0001");
  if (cache.has(key)) return cache.get(key);
  const out = (await FUNCS[engine](text, src, tgt, opts)).trim();
  if (!out) throw new TranslateError("번역 결과가 비어 있어요. 잠시 뒤 다시 해 보세요.");
  const res = { source: text, text: out, src, tgt, engine, engineName: ENGINES[engine].short, truncated };
  cache.set(key, res);
  if (cache.size > 60) cache.delete(cache.keys().next().value);
  return res;
}

export function webUrl(text) {
  const t = [...normalize(text)].slice(0, MAX_CHARS).join("");
  const src = detectLang(t);
  return "https://papago.naver.com/?" + new URLSearchParams({ sk: zh(src), tk: targetFor(src), st: t }).toString().replace(/\+/g, "%20");
}
