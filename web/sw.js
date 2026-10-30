// 오프라인에서도 앱 화면이 열리도록 앱 파일을 저장해 두는 서비스 워커
// (사전 데이터는 여기서 다루지 않고, 폰 저장소(OPFS)에 따로 저장됨)
const CACHE = "quickdic-__APP_VERSION__";
const SHELL = [
  "./", "index.html", "app.css", "app.js", "dict.js", "fuzzy.js", "worker.js",
  "vendor/sqlite/index.mjs", "vendor/sqlite/sqlite3.wasm", "vendor/pako.esm.mjs",
  "manifest.webmanifest", "icons/icon-192.png", "icons/icon-512.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("quickdic-") && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.includes("/data/")) return; // 사전 데이터·버전 정보는 늘 네트워크에서
  // 공유하기로 열린 주소(?text=...)도 같은 index.html 로
  const req = e.request.mode === "navigate" ? new Request(new URL("index.html", self.registration.scope)) : e.request;
  e.respondWith(
    caches.match(req, { ignoreSearch: e.request.mode === "navigate" }).then((hit) => hit || fetch(e.request)),
  );
});
