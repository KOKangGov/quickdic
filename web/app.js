// QuickDic 모바일(웹앱) 화면
import { cleanQuery, isKorean } from "./dict.js";
import {
  looksLikeSentence, translate as runTranslate, webUrl, normalize as trNormalize, detectLang, targetFor,
  LANG_NAMES, ENGINES, builtinSupported, MAX_CHARS,
} from "./translate.js";

const $ = (id) => document.getElementById(id);
const APP_VERSION = "__APP_VERSION__"; // 배포할 때 채워짐

// ------------------------------------------------------------------ 저장 (실패해도 동작하게)
const store = {
  get(k, d) { try { const v = localStorage.getItem("qd." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("qd." + k, JSON.stringify(v)); } catch { /* 무시 */ } },
};

const PORTALS = {
  "네이버 사전": { en: "https://en.dict.naver.com/#/search?query={q}", ko: "https://ko.dict.naver.com/#/search?query={q}" },
  "다음 사전": { en: "https://dic.daum.net/search.do?q={q}", ko: "https://dic.daum.net/search.do?q={q}&dic=kor" },
  "Cambridge": { en: "https://dictionary.cambridge.org/dictionary/english/{q}" },
  "Oxford Learner's": { en: "https://www.oxfordlearnersdictionaries.com/search/english/?q={q}" },
  "Merriam-Webster": { en: "https://www.merriam-webster.com/dictionary/{q}" },
  "Wiktionary": { en: "https://en.wiktionary.org/wiki/{q}" },
};

// ------------------------------------------------------------------ 사전 작업 스레드
const worker = new Worker(new URL("./worker.js", import.meta.url), { type: "module" });
let seq = 0;
const waiting = new Map();
let onProgress = null;
worker.onmessage = (e) => {
  const m = e.data;
  if (m.type === "progress") { onProgress && onProgress(m.got, m.total); return; }
  const w = waiting.get(m.id);
  if (!w) return;
  waiting.delete(m.id);
  m.type === "error" ? w.reject(new Error(m.error)) : w.resolve(m);
};
const call = (type, payload = {}) => new Promise((resolve, reject) => {
  const id = ++seq;
  waiting.set(id, { resolve, reject });
  worker.postMessage({ type, id, ...payload });
});

// ------------------------------------------------------------------ 상태
const state = {
  ready: false, version: "", result: null, tab: "meaning", remote: null,
  // 번역: mode 'dict' 사전 결과 / 'trans' 문장 번역
  mode: "dict", transRaw: "", trans: null, transErr: "", transToken: 0, transWord: null,
};
const trEnabled = () => store.get("trEnabled", true);
const trOpts = () => ({ engine: store.get("trEngine", "mymemory"), email: store.get("trEmail", ""), googleKey: store.get("trGoogleKey", "") });

function show(section) {
  for (const id of ["setup", "home", "result"]) $(id).hidden = id !== section;
}

function toast(msg, ms = 2200) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), ms);
}

const fmtMB = (b) => (b / 1024 / 1024).toFixed(b >= 10 * 1024 * 1024 ? 0 : 1) + "MB";

async function fetchRemoteInfo() {
  try {
    const r = await fetch("data/version.json", { cache: "no-store" });
    if (!r.ok) return null;
    state.remote = await r.json();
    return state.remote;
  } catch { return null; }
}

// ------------------------------------------------------------------ 시작
async function start() {
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
  const slot = store.get("slot", "");
  let init;
  try { init = await call("init", { slot }); } catch (err) {
    show("setup");
    $("setup-error").hidden = false;
    $("setup-error").textContent = "이 브라우저에서는 오프라인 사전을 쓸 수 없어요. Chrome 최신 버전에서 열어 주세요. (" + err.message + ")";
    $("btn-install").disabled = true;
    return;
  }
  if (init.ok) {
    state.ready = true;
    state.version = init.version;
    goHome();
    const q = sharedQuery();
    if (q) search(q, { replace: true });
    checkUpdate(false);
  } else {
    show("setup");
    const info = await fetchRemoteInfo();
    if (info) $("setup-size").textContent = "약 " + fmtMB(info.gz_size);
  }
}

function sharedQuery() {
  const p = new URLSearchParams(location.search);
  const raw = p.get("text") || p.get("title") || p.get("q") || "";
  if (!raw) return "";
  history.replaceState(null, "", location.pathname);
  // 주소는 빼고 넘김 (문장이면 번역, 단어면 사전)
  return raw.replace(/https?:\/\/\S+/g, "").trim();
}

async function install(info) {
  $("btn-install").disabled = true;
  $("progress").hidden = false;
  $("setup-error").hidden = true;
  if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});
  const newSlot = store.get("slot", "") === "/dict-a.db" ? "/dict-b.db" : "/dict-a.db";
  onProgress = (got, total) => {
    const pct = total ? Math.min(100, Math.round((got / total) * 100)) : 0;
    $("progress-bar").style.width = pct + "%";
    $("progress-text").textContent = `${fmtMB(got)} / ${fmtMB(total)} 받는 중… (${pct}%)`;
  };
  try {
    const urls = info.parts.map((p) => "data/" + p);
    const r = await call("install", { urls, slot: newSlot, total: info.gz_size, version: info.version });
    store.set("slot", newSlot);
    state.ready = true;
    state.version = r.version;
    $("progress-text").textContent = "다 됐어요!";
    goHome();
    toast("사전 준비 완료! 이제 인터넷 없이도 찾을 수 있어요.", 3000);
    $("q").focus();
  } catch (err) {
    $("setup-error").hidden = false;
    $("setup-error").textContent = "내려받지 못했어요: " + err.message + " — 인터넷 연결을 확인하고 다시 눌러 주세요.";
    $("btn-install").disabled = false;
  } finally {
    onProgress = null;
  }
}

$("btn-install").onclick = async () => {
  const info = state.remote || (await fetchRemoteInfo());
  if (!info) {
    $("setup-error").hidden = false;
    $("setup-error").textContent = "사전 정보를 가져오지 못했어요. 인터넷 연결을 확인해 주세요.";
    return;
  }
  install(info);
};

async function checkUpdate(manual) {
  const info = await fetchRemoteInfo();
  if (!info) { if (manual) toast("인터넷에 연결되지 않아 확인하지 못했어요."); return; }
  if (info.version && info.version !== state.version) {
    $("update-text").textContent = `새 사전 데이터(${info.version}, ${fmtMB(info.gz_size)})가 있어요.`;
    $("update-banner").hidden = false;
    if (manual) { closeSheet(); goHome(); }
  } else if (manual) toast(`최신 사전이에요 (${state.version}).`);
}

$("btn-update").onclick = () => {
  $("update-banner").hidden = true;
  show("setup");
  $("setup").querySelector("h1").textContent = "새 사전으로 바꿀게요";
  $("btn-install").disabled = false;
  install(state.remote);
};

// ------------------------------------------------------------------ 처음 화면
function goHome() {
  show("home");
  const recent = store.get("recent", []);
  $("recent-block").hidden = !recent.length;
  $("recent").replaceChildren(...recent.map((w) => {
    const b = document.createElement("button");
    b.className = "chip";
    b.textContent = w;
    b.onclick = () => search(w);
    return b;
  }));
}

function addRecent(w) {
  const r = store.get("recent", []).filter((x) => x !== w);
  r.unshift(w);
  store.set("recent", r.slice(0, 12));
}

// ------------------------------------------------------------------ 검색창
const q = $("q");
let suggTimer = null, suggSel = -1;

q.addEventListener("input", () => {
  $("btn-clear").hidden = !q.value;
  clearTimeout(suggTimer);
  suggTimer = setTimeout(updateSuggest, 140);
});
q.addEventListener("keydown", (e) => {
  const items = [...$("sugg").children];
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    if (!items.length) return;
    e.preventDefault();
    suggSel = Math.max(0, Math.min(items.length - 1, suggSel + (e.key === "ArrowDown" ? 1 : -1)));
    items.forEach((li, i) => li.classList.toggle("sel", i === suggSel));
  } else if (e.key === "Escape") hideSuggest();
});
$("search-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const items = [...$("sugg").children];
  if (suggSel >= 0 && items[suggSel]) search(items[suggSel].dataset.w);
  else search(q.value);
});
$("btn-clear").onclick = () => { q.value = ""; $("btn-clear").hidden = true; hideSuggest(); q.focus(); };
$("btn-paste").onclick = async () => {
  try {
    const t = await navigator.clipboard.readText();
    if (t && t.trim()) search(t);
    else toast("클립보드가 비어 있어요.");
  } catch { toast("붙여넣기 권한이 없어요. 검색창을 길게 눌러 붙여넣어 주세요."); q.focus(); }
};
document.addEventListener("click", (e) => { if (!e.target.closest(".search-wrap")) hideSuggest(); });

async function updateSuggest() {
  const text = q.value;
  if (!state.ready || [...cleanQuery(text)].length < 2) return hideSuggest();
  const r = await call("suggest", { q: text }).catch(() => null);
  if (!r || q.value !== text || document.activeElement !== q) return;
  if (!r.words.length) return hideSuggest();
  suggSel = -1;
  $("sugg").replaceChildren(...r.words.map(({ w, fuzzy }) => {
    const li = document.createElement("li");
    li.dataset.w = w;
    if (fuzzy) { const s = document.createElement("span"); s.className = "fz"; s.textContent = "≈"; li.append(s); }
    li.append(w);
    li.onclick = () => search(w);
    return li;
  }));
  $("sugg").hidden = false;
}
function hideSuggest() { $("sugg").hidden = true; $("sugg").replaceChildren(); suggSel = -1; }

// ------------------------------------------------------------------ 검색 / 결과
async function search(raw, { push = true, replace = false } = {}) {
  hideSuggest();
  // 문장(4단어 이상·40자 넘음·여러 줄 등)은 사전 대신 번역
  if (trEnabled() && looksLikeSentence(raw || "")) return translateText(raw, { push, replace });
  const text = cleanQuery(raw || "");
  if (!text) return;
  if (!state.ready) { toast("먼저 사전을 내려받아 주세요."); return; }
  q.value = text;
  $("btn-clear").hidden = false;
  q.blur();
  let r;
  try { r = await call("lookup", { q: text }); } catch (err) { toast("검색 중 오류: " + err.message); return; }
  state.mode = "dict";
  state.transToken++;            // 진행 중이던 번역 결과는 버림
  state.transWord = null; state.trans = null; state.transErr = ""; state.transRaw = "";
  state.result = r.res;
  // 사전에 없는 여러 단어(짧은 구절)나 일본어·중국어 등은 번역해서 보여 줌
  if (!r.res.found && trEnabled() && (text.split(" ").length >= 2 || ["ja", "zh", "ru"].includes(detectLang(text)))) return translateText(text, { push, replace });
  state.tab = "meaning";
  render();
  if (r.res.found) addRecent(r.res.headword);
  if (replace) history.replaceState({ q: text }, "", location.pathname);
  else if (push) history.pushState({ q: text }, "", location.pathname);
  window.scrollTo({ top: 0 });
}

window.addEventListener("popstate", (e) => {
  if (e.state && e.state.q) search(e.state.q, { push: false });
  else { q.value = ""; $("btn-clear").hidden = true; goHome(); }
});

// ------------------------------------------------------------------ 번역
async function translateText(raw, { push = true, replace = false, wordOnly = false } = {}) {
  const text = trNormalize(raw || "");
  if (!text) return;
  if (!trEnabled()) { toast("번역 기능이 꺼져 있어요. 메뉴 → 번역 설정에서 켤 수 있어요.", 3000); return; }
  const token = ++state.transToken;
  state.transRaw = text; state.trans = null; state.transErr = "";
  if (!wordOnly) {
    state.mode = "trans";
    state.result = null;
    q.value = text.replace(/\s+/g, " ");
    $("btn-clear").hidden = false;
    q.blur();
    if (replace) history.replaceState({ q: text }, "", location.pathname);
    else if (push) history.pushState({ q: text }, "", location.pathname);
    window.scrollTo({ top: 0 });
  }
  state.tab = "translate";
  render();
  try { state.trans = await runTranslate(text, trOpts()); } catch (err) { state.transErr = err.message || String(err); }
  if (token !== state.transToken) return; // 그사이 다른 검색을 했으면 버림
  if (state.tab === "translate") render();
}

function transLines() {
  if (!trEnabled()) return [[["번역 기능이 꺼져 있어요. 메뉴 → 번역 설정에서 켤 수 있어요.", "note", null]]];
  const L = [];
  if (state.transErr) {
    L.push([[state.transRaw, "src", null]], [], [[state.transErr, "note", null]], [],
      [["→ 파파고 웹 번역에서 열기", "link", "@webtrans"]], [["→ 번역 설정 바꾸기", "link", "@trsettings"]]);
    return L;
  }
  const t = state.trans;
  if (!t) return [[[state.transRaw, "src", null]], [], [["번역하는 중…", "dim", null]]];
  L.push([[`원문 (${LANG_NAMES[t.src] || t.src})`, "sec", null]], ...t.source.split("\n\n").map((p) => [[p, "src", null]]), []);
  L.push([[`번역 (${LANG_NAMES[t.tgt] || t.tgt})`, "sec", null]], ...t.text.split("\n\n").map((p) => [[p, "out", null]]), []);
  if (t.truncated) L.push([[`글이 길어서 앞부분 ${MAX_CHARS}자만 번역했어요.`, "note", null]]);
  L.push([["번역 결과 복사", "link", "@copytrans"], ["   ·   ", "dim", null], ["파파고 웹 번역에서 보기", "link", "@webtrans"]]);
  L.push([[`${t.engineName} 번역 · 문장은 인터넷의 번역 서비스로 보내져요 (단어 검색은 오프라인)`, "dim", null]]);
  return L;
}

async function copyTrans() {
  if (!state.trans) return;
  try { await navigator.clipboard.writeText(state.trans.text); toast("번역 결과를 복사했어요."); }
  catch { toast("복사하지 못했어요. 글을 길게 눌러 복사해 주세요."); }
}

function render() {
  show("result");
  for (const b of document.querySelectorAll(".tabs [role=tab]")) b.setAttribute("aria-selected", String(b.dataset.tab === state.tab));
  if (state.mode === "trans") {
    const src = detectLang(state.transRaw);
    $("hw").textContent = `번역 ${LANG_NAMES[src] || src} → ${LANG_NAMES[targetFor(src)]}`;
    $("ipa").textContent = "";
    $("btn-star").hidden = true;      // 문장은 단어장에 넣지 않음
    $("btn-speak").hidden = false;    // 원문 읽어 주기
    $("en-toggle").hidden = true;
    $("doc").replaceChildren(...renderLines(currentLines()));
    return;
  }
  $("btn-star").hidden = false;
  const res = state.result;
  $("hw").textContent = res.found ? res.headword : res.query;
  $("ipa").textContent = res.found ? res.ipa : "";
  $("btn-star").classList.toggle("on", isStarred(res.found ? res.headword : res.query));
  $("btn-speak").hidden = !res.found;
  const canEn = res.found && res.lang === "en" && res.hasKo && res.meaningEn.some((l) => l.length);
  $("en-toggle").hidden = !canEn;
  $("show-en").checked = store.get("showEn", false);
  $("doc").replaceChildren(...renderLines(currentLines()));
}

function currentLines() {
  if (state.tab === "translate") return transLines();
  if (state.mode === "trans") return [[["문장을 번역하는 중이에요. 단어 뜻을 보려면 단어 하나만 골라 찾아 주세요.", "note", null]]];
  const res = state.result;
  if (!res.found) {
    const lines = [[[`‘${res.query}’ 은(는) 오프라인 사전에 없어요.`, "h1", null]], []];
    if (state.tab !== "meaning") return [[["검색 결과가 없어요.", "note", null]]];
    if (res.suggestions.length) {
      lines.push([["혹시 이 단어를 찾으셨나요?", "sec", null]]);
      lines.push({ suggestions: res.suggestions });
      lines.push([]);
    }
    lines.push([["→ 포털 사전에서 찾아보기", "link", "@web"]]);
    return lines;
  }
  if (state.tab === "etymology") return res.etymology;
  if (state.tab === "examples") return res.examples;
  const lines = [];
  if (res.redirectedFrom) lines.push([[`‘${res.redirectedFrom}’ → ‘${res.headword}’ 로 찾았어요`, "note", null]]);
  lines.push(...res.meaning);
  if ($("show-en").checked && !$("en-toggle").hidden) {
    lines.push([], [["영영 정의", "sec", null]], ...res.meaningEn);
  }
  return lines;
}

const LEAD_RE = /^(\s+)(\d+\. |· )?$/;
function renderLines(lines) {
  const out = [];
  for (const ln of lines) {
    const div = document.createElement("div");
    div.className = "ln";
    if (!Array.isArray(ln)) { // 추천 단어 목록
      div.className = "sugg-list";
      for (const w of ln.suggestions) div.append(span([w, "link", w]));
      out.push(div);
      continue;
    }
    if (!ln.length) { div.classList.add("blank"); out.push(div); continue; }
    // '  1. ' 같은 머리 조각이 있으면 내어쓰기로 (줄이 바뀌어도 글머리가 맞게)
    if (ln.length > 1 && LEAD_RE.test(ln[0][0])) {
      div.style.display = "flex";
      const lead = span(ln[0]);
      lead.style.whiteSpace = "pre";
      lead.style.flex = "none";
      const body = document.createElement("span");
      body.style.minWidth = "0";
      for (const s of ln.slice(1)) body.append(span(s));
      div.append(lead, body);
    } else for (const s of ln) div.append(span(s));
    out.push(div);
  }
  return out;
}

function span([text, style, link]) {
  const s = document.createElement("span");
  s.textContent = text;
  if (style) s.className = "s-" + style;
  if (link) {
    s.className = "s-link";
    s.onclick = () => {
      if (link === "@web") openWeb();
      else if (link === "@webtrans") window.open(webUrl(state.transRaw), "_blank", "noopener");
      else if (link === "@copytrans") copyTrans();
      else if (link === "@trsettings") { openSheet(); showTrSettings(); }
      else search(link);
    };
  }
  return s;
}

document.querySelector(".tabs").addEventListener("click", (e) => {
  const b = e.target.closest("[role=tab]");
  if (!b) return;
  state.tab = b.dataset.tab;
  // 사전 결과를 보다가 '번역' 탭을 누르면 그 단어를 번역
  if (state.tab === "translate" && state.mode === "dict" && state.result && trEnabled()) {
    const w = state.result.found ? state.result.headword : state.result.query;
    if (w && w !== state.transWord) { state.transWord = w; translateText(w, { wordOnly: true }); return; }
  }
  render();
});
$("show-en").onchange = () => { store.set("showEn", $("show-en").checked); render(); };

// ------------------------------------------------------------------ 발음 / 단어장 / 웹사전
$("btn-speak").onclick = () => {
  const res = state.result;
  const text = state.mode === "trans" ? state.transRaw.slice(0, 300) : res && res.headword;
  if (!text || !("speechSynthesis" in window)) return toast("이 기기에서는 발음 듣기를 쓸 수 없어요.");
  const u = new SpeechSynthesisUtterance(text);
  u.lang = isKorean(text) ? "ko-KR" : "en-US";
  u.rate = 0.9;
  speechSynthesis.cancel();
  speechSynthesis.speak(u);
};

const isStarred = (w) => store.get("words", []).some((x) => x.w === w);
$("btn-star").onclick = () => {
  const res = state.result;
  if (!res) return;
  const w = res.found ? res.headword : res.query;
  let words = store.get("words", []);
  if (isStarred(w)) { words = words.filter((x) => x.w !== w); toast("단어장에서 뺐어요."); }
  else {
    const first = res.meaning.find((l) => l.some((s) => s[1] === "ko")) || res.meaning.find((l) => l.some((s) => s[1] === "en"));
    const summary = first ? first.filter((s) => s[1] === "ko" || s[1] === "en").map((s) => s[0]).join(" ").slice(0, 80) : "";
    words.unshift({ w, m: summary, t: Date.now() });
    toast("단어장에 넣었어요 ★");
  }
  store.set("words", words);
  $("btn-star").classList.toggle("on", isStarred(w));
};

function openWeb() {
  if (state.mode === "trans" && state.transRaw) { window.open(webUrl(state.transRaw), "_blank", "noopener"); return; }
  const res = state.result;
  const word = res ? (res.found ? res.headword : res.query) : q.value;
  const name = store.get("portal", "네이버 사전");
  const p = PORTALS[name] || PORTALS["네이버 사전"];
  const tpl = isKorean(word) ? p.ko || PORTALS["네이버 사전"].ko : p.en;
  window.open(tpl.replace("{q}", encodeURIComponent(word)), "_blank", "noopener");
}
$("btn-web").onclick = openWeb;

// ------------------------------------------------------------------ 메뉴
function openSheet() {
  $("sheet").hidden = false; $("sheet-bg").hidden = false; $("sheet-panel").replaceChildren();
  $("webdict-name").textContent = store.get("portal", "네이버 사전");
  $("tr-name").textContent = trEnabled() ? ENGINES[trOpts().engine]?.short || "MyMemory" : "꺼짐";
}

// 번역 설정: 켜기/끄기, 번역 서비스 고르기, 키·이메일
function showTrSettings() {
  const panel = $("sheet-panel");
  const el = (tag, props = {}, ...kids) => { const e = Object.assign(document.createElement(tag), props); e.append(...kids); return e; };
  const refresh = () => { showTrSettings(); $("tr-name").textContent = trEnabled() ? ENGINES[trOpts().engine]?.short || "MyMemory" : "꺼짐"; };
  const on = el("input", { type: "checkbox", checked: trEnabled() });
  on.onchange = () => { store.set("trEnabled", on.checked); refresh(); };
  const rows = [el("label", { className: "tr-row" }, on, " 문장은 번역하기 (인터넷 필요 · 고른 문장이 번역 서비스로 보내져요)")];
  const cur = trOpts().engine;
  for (const [key, e] of Object.entries(ENGINES)) {
    const o = el("button", { className: "opt" + (key === cur ? " on" : ""), textContent: e.name });
    if (key === "builtin" && !builtinSupported()) { o.disabled = true; o.textContent += " — 이 기기에서는 안 돼요"; }
    o.onclick = () => { store.set("trEngine", key); refresh(); };
    rows.push(o);
  }
  const field = (label, storeKey, placeholder, secret) => {
    const inp = el("input", { type: secret ? "password" : "text", value: store.get(storeKey, ""), placeholder, autocomplete: "off" });
    inp.onchange = () => { store.set(storeKey, inp.value.trim()); toast("저장했어요."); };
    return el("label", { className: "tr-field" }, el("span", { className: "dim", textContent: label }), inp);
  };
  if (cur === "mymemory") rows.push(field("이메일 (선택 · 넣으면 하루 무료 사용량이 약 5,000자 → 50,000자)", "trEmail", "you@example.com"));
  if (cur === "google") rows.push(field("Google Cloud Translation API 키 (이 폰에만 저장돼요)", "trGoogleKey", "AIza...", true));
  rows.push(el("p", { className: "dim", textContent: "DeepL·파파고는 PC판(QuickDic.exe)에서 내 API 키로 쓸 수 있어요." }));
  panel.replaceChildren(...rows);
}
function closeSheet() { $("sheet").hidden = true; $("sheet-bg").hidden = true; }
$("btn-menu").onclick = openSheet;
$("sheet-bg").onclick = closeSheet;

$("sheet").addEventListener("click", (e) => {
  const b = e.target.closest(".sheet-item");
  if (!b) return;
  const panel = $("sheet-panel");
  const act = b.dataset.act;
  if (act === "wordbook") {
    const words = store.get("words", []);
    if (!words.length) { panel.textContent = "아직 단어장이 비어 있어요. 결과 화면의 ☆ 를 눌러 넣어 보세요."; return; }
    const rows = words.map(({ w, m }) => {
      const row = document.createElement("div");
      row.className = "row";
      const left = document.createElement("span");
      const a = span([w, "link", w]);
      a.onclick = () => { closeSheet(); search(w); };
      const meaning = document.createElement("div");
      meaning.className = "dim";
      meaning.textContent = m || "";
      left.append(a, meaning);
      const del = document.createElement("button");
      del.textContent = "삭제";
      del.onclick = () => { store.set("words", store.get("words", []).filter((x) => x.w !== w)); row.remove(); };
      row.append(left, del);
      return row;
    });
    const exp = document.createElement("button");
    exp.className = "opt";
    exp.textContent = "📄 단어장 파일로 저장 (CSV)";
    exp.onclick = () => {
      const csv = "﻿단어,뜻\n" + store.get("words", []).map(({ w, m }) => `"${w.replace(/"/g, '""')}","${(m || "").replace(/"/g, '""')}"`).join("\n");
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
      a.download = "QuickDic_단어장.csv";
      a.click();
    };
    panel.replaceChildren(...rows, exp);
  } else if (act === "webdict") {
    const cur = store.get("portal", "네이버 사전");
    panel.replaceChildren(...Object.keys(PORTALS).map((name) => {
      const o = document.createElement("button");
      o.className = "opt" + (name === cur ? " on" : "");
      o.textContent = name;
      o.onclick = () => { store.set("portal", name); $("webdict-name").textContent = name; panel.replaceChildren(); };
      return o;
    }));
  } else if (act === "translate") {
    showTrSettings();
  } else if (act === "update") {
    if (!state.ready) { closeSheet(); return; }
    checkUpdate(true);
  } else if (act === "about") {
    panel.innerHTML = "";
    const p = document.createElement("div");
    p.innerHTML = `<p><b>QuickDic</b> 모바일 ${APP_VERSION}<br>사전 데이터 ${state.version || "없음"}</p>
      <p class="dim">사전 데이터: 국립국어원 표준국어대사전 (CC BY-SA 2.0 KR), Wiktionary (CC BY-SA 4.0) via kaikki.org, 단어 빈도 wordfreq (CC BY-SA 4.0)</p>
      <p><a href="https://github.com/KOKangGov/quickdic" target="_blank" rel="noopener">GitHub 에서 보기 · Windows 판 받기</a></p>`;
    const reset = document.createElement("button");
    reset.className = "opt";
    reset.textContent = "사전 파일 지우고 다시 받기";
    reset.onclick = async () => {
      if (!confirm("폰에 저장된 사전 파일을 지울까요? 다시 내려받아야 해요.")) return;
      await call("reset");
      store.set("slot", "");
      state.ready = false;
      closeSheet();
      show("setup");
      $("btn-install").disabled = false;
      $("progress").hidden = true;
    };
    panel.replaceChildren(p, reset);
  }
});

start();
