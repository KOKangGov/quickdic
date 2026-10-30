// 사전 작업 담당 (화면이 멈추지 않도록 별도 스레드에서 실행)
//  - 사전 파일을 내려받아 폰 저장소(OPFS)에 넣기
//  - SQLite(WebAssembly)로 사전을 열고 검색하기

import sqlite3InitModule from "./vendor/sqlite/index.mjs";
import { inflate } from "./vendor/pako.esm.mjs";
import { Dictionary, serialize, cleanQuery } from "./dict.js";

let sqlite3 = null;
let pool = null;
let db = null;
let dict = null;

const post = (msg) => self.postMessage(msg);

async function ensurePool() {
  if (pool) return pool;
  sqlite3 = await sqlite3InitModule({ print: () => {}, printErr: () => {} });
  pool = await sqlite3.installOpfsSAHPoolVfs({ name: "quickdic-pool", directory: ".quickdic", initialCapacity: 4 });
  return pool;
}

function closeDb() {
  if (db) { try { db.close(); } catch { /* 무시 */ } }
  db = null; dict = null;
}

function openDb(slot) {
  closeDb();
  if (!pool.getFileNames().includes(slot)) return false;
  db = new pool.OpfsSAHPoolDb(slot, "r");
  const adapter = {
    all(sql, bind = []) {
      const opt = { sql, rowMode: "array", returnValue: "resultRows" };
      if (bind.length) opt.bind = bind;
      return db.exec(opt);
    },
    inflate(bytes) { return inflate(bytes, { to: "string" }); },
  };
  dict = new Dictionary(adapter);
  dict.lookup("test"); // 첫 검색을 미리 한 번 (색인을 메모리에 올림)
  return true;
}

// 여러 조각으로 나눈 .gz 파일을 차례로 받아 하나의 스트림으로 이어 붙인다
function partsStream(urls, onBytes) {
  let i = 0, reader = null;
  return new ReadableStream({
    async pull(ctrl) {
      for (;;) {
        if (!reader) {
          if (i >= urls.length) { ctrl.close(); return; }
          const resp = await fetch(urls[i++], { cache: "no-store" });
          if (!resp.ok) throw new Error(`내려받기 실패 (${resp.status})`);
          reader = resp.body.getReader();
        }
        const { done, value } = await reader.read();
        if (done) { reader = null; continue; }
        onBytes(value.byteLength);
        ctrl.enqueue(value);
        return;
      }
    },
  });
}

async function install({ urls, slot, total, version }) {
  await ensurePool();
  let got = 0, lastSent = 0;
  const stream = partsStream(urls, (n) => {
    got += n;
    const now = Date.now();
    if (now - lastSent > 200) { lastSent = now; post({ type: "progress", got, total }); }
  }).pipeThrough(new DecompressionStream("gzip"));
  const reader = stream.getReader();
  if (pool.getFileNames().includes(slot)) pool.unlink(slot);
  await pool.importDb(slot, async () => {
    const { done, value } = await reader.read();
    return done ? undefined : value;
  });
  post({ type: "progress", got: total, total });
  if (!openDb(slot)) throw new Error("사전 파일을 열지 못했어요");
  if (version && dict.version !== version) console.warn("version mismatch", dict.version, version);
  // 예전 사전 파일 정리
  for (const name of pool.getFileNames()) if (name !== slot) pool.unlink(name);
}

self.onmessage = async (e) => {
  const m = e.data;
  try {
    switch (m.type) {
      case "init": {
        await ensurePool();
        const ok = m.slot ? openDb(m.slot) : false;
        post({ type: "init", id: m.id, ok, version: ok ? dict.version : "", meta: ok ? dict.meta : null });
        break;
      }
      case "install": {
        await install(m);
        post({ type: "installed", id: m.id, version: dict.version, meta: dict.meta });
        break;
      }
      case "lookup": {
        const t = performance.now();
        const res = dict.lookup(m.q);
        post({ type: "lookup", id: m.id, res: serialize(res), ms: performance.now() - t });
        break;
      }
      case "suggest": {
        const text = cleanQuery(m.q);
        let words = [];
        if (dict && [...text].length >= 2) {
          words = dict.suggestions(text, null, 8).filter((w) => w.toLowerCase() !== text.toLowerCase()).slice(0, 7);
          if (words.length < 3 && !dict.exists(text)) {
            const fz = dict.similar(text, 7 - words.length, true).filter((w) => !words.includes(w));
            words = [...words.map((w) => ({ w })), ...fz.map((w) => ({ w, fuzzy: true }))];
          } else words = words.map((w) => ({ w }));
        }
        post({ type: "suggest", id: m.id, q: m.q, words });
        break;
      }
      case "reset": {
        await ensurePool();
        closeDb();
        for (const name of pool.getFileNames()) pool.unlink(name);
        post({ type: "reset", id: m.id });
        break;
      }
      default:
        post({ type: "error", id: m.id, error: "unknown message" });
    }
  } catch (err) {
    post({ type: "error", id: m.id, error: String(err && err.message ? err.message : err) });
  }
};
