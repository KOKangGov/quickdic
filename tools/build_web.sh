#!/usr/bin/env bash
# 모바일 웹앱(PWA) 사이트 만들기
#   tools/build_web.sh <모바일 사전 db> <출력 폴더> <앱 버전 표시>
# 필요: python3, npm (sqlite-wasm·pako 를 받아 vendor 폴더에 넣음)
set -euo pipefail
DB="$1"; OUT="$2"; VER="${3:-dev}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SQLITE_WASM_VERSION="3.53.4-build2"
PAKO_VERSION="2.1.0"

rm -rf "$OUT"; mkdir -p "$OUT/vendor/sqlite" "$OUT/data"
cp -r "$ROOT/web/." "$OUT/"

# 라이브러리 (버전 고정)
TMP="$(mktemp -d)"
( cd "$TMP" && npm init -y >/dev/null && npm install --silent --no-audit --no-fund \
    "@sqlite.org/sqlite-wasm@$SQLITE_WASM_VERSION" "pako@$PAKO_VERSION" >/dev/null )
cp "$TMP/node_modules/@sqlite.org/sqlite-wasm/dist/index.mjs" "$TMP/node_modules/@sqlite.org/sqlite-wasm/dist/sqlite3.wasm" "$OUT/vendor/sqlite/"
cp "$TMP/node_modules/pako/dist/pako.esm.mjs" "$OUT/vendor/"
rm -rf "$TMP"

# 앱 버전 표시 (서비스 워커 캐시 이름도 바뀌어 새 화면이 반영됨)
sed -i "s/__APP_VERSION__/$VER/g" "$OUT/app.js" "$OUT/sw.js"

# 사전: gzip 으로 압축해 20MB 조각으로 나눔 (GitHub Pages 파일 크기 제한 대비)
gzip -9 -c "$DB" > "$OUT/data/dict.db.gz"
( cd "$OUT/data" && split -b 20m -d -a 2 dict.db.gz dict.db.gz.part && rm dict.db.gz )
python3 - "$DB" "$OUT/data" <<'PY'
import json, os, sqlite3, sys
db, out = sys.argv[1], sys.argv[2]
meta = dict(sqlite3.connect(f"file:{db}?mode=ro", uri=True).execute("SELECT key, value FROM meta"))
parts = sorted(p for p in os.listdir(out) if ".part" in p)
info = {
    "version": meta.get("version"),
    "built_at": meta.get("built_at"),
    "parts": parts,
    "gz_size": sum(os.path.getsize(os.path.join(out, p)) for p in parts),
    "db_size": os.path.getsize(db),
}
json.dump(info, open(os.path.join(out, "version.json"), "w"), ensure_ascii=False, indent=2)
print(json.dumps(info, ensure_ascii=False))
PY
touch "$OUT/.nojekyll"
echo "웹앱 사이트 완성: $OUT"
