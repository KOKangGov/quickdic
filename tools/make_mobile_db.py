"""
PC용 사전(quickdic.db) → 모바일(웹앱)용 작은 사전(quickdic-mobile.db)

폰에 내려받아 오프라인으로 쓰려면 크기를 줄여야 한다. 한국어 사용자에게 쓸모가 큰 것만 남긴다.
  - 한국어 표제어 전부 (국어 뜻풀이 + 영어 뜻)
  - 한국어 뜻·번역어가 있는 영어 단어 전부
  - 한국어 정보는 없지만 자주 쓰는 영어 단어 (빈도표 기준) — 영영 뜻만 짧게
  - 위 단어들의 변화형(복수형·과거형 등) 중 자주 쓰는 것
  - 한→영 색인, 빈도표, 압축 사전(zdict)
영어 단어는 뜻·예문 수를 줄이고 어원을 짧게 자른다.

    python tools/make_mobile_db.py quickdic.db quickdic-mobile.db
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import zlib

MIN_Z_EN = 28        # 한국어 정보가 없는 영어 단어는 zipf 2.8 이상만
MIN_Z_FORM = 25      # 변화형은 zipf 2.5 이상만
EN_SENSES = 6
EN_EX = 1
ETY_LEN = 300
BLOCK = 64           # 한 묶음에 넣을 항목 수


def main(src: str, dst: str):
    if os.path.exists(dst):
        os.remove(dst)
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    zdict = bytes(s.execute("SELECT data FROM blobs WHERE name='zdict'").fetchone()[0])
    has_freq = s.execute("SELECT 1 FROM sqlite_master WHERE name='freq'").fetchone() is not None
    freq = dict(s.execute("SELECT key, z FROM freq")) if has_freq else {}

    def unpack(b):
        d = zlib.decompressobj(15, zdict)
        return json.loads(d.decompress(b) + d.flush())

    def pack(obj):
        c = zlib.compressobj(9, zlib.DEFLATED, 15, 9, zlib.Z_DEFAULT_STRATEGY, zdict)
        raw = json.dumps({k: v for k, v in obj.items() if v not in (None, "", [], {})},
                         ensure_ascii=False, separators=(",", ":")).encode()
        return c.compress(raw) + c.flush()

    def trim_en(d):
        senses = []
        for sn in d.get("s", [])[:EN_SENSES]:
            sn = dict(sn)
            if sn.get("ex"):
                sn["ex"] = sn["ex"][:EN_EX]
            senses.append(sn)
        d["s"] = senses
        if d.get("ety"):
            e = d["ety"]
            d["ety"] = e if len(e) <= ETY_LEN else e[: ETY_LEN - 1] + "…"
        d["syn"] = (d.get("syn") or [])[:6]
        d["ant"] = (d.get("ant") or [])[:6]
        return d

    d = sqlite3.connect(dst)
    d.executescript(
        """
        PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA page_size=4096;
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
        -- 표제어 색인: 실제 내용은 blocks 의 blk 번째 묶음 안 pos 번째 항목
        CREATE TABLE words(id INTEGER PRIMARY KEY, word TEXT NOT NULL, key TEXT NOT NULL,
                           lang TEXT NOT NULL, blk INTEGER NOT NULL, pos INTEGER NOT NULL);
        -- 항목 BLOCK 개를 JSON 배열 [[word, src, data], ...] 로 묶어 zlib 압축
        -- (항목마다 따로 압축하는 것보다 훨씬 작다. 브라우저에서 pako 로 푼다)
        CREATE TABLE blocks(id INTEGER PRIMARY KEY, data BLOB NOT NULL);
        CREATE TABLE ko_en(ko TEXT NOT NULL, en TEXT NOT NULL, sense TEXT);
        CREATE TABLE freq(key TEXT PRIMARY KEY, z INTEGER NOT NULL) WITHOUT ROWID;
        """
    )

    # 1차: 남길 항목 고르기
    keep_en_keys = set()
    form_rows = []
    rows_out = []  # (key, lang, 원래 순서, word, src, data(dict))
    n = {"ko": 0, "en_ko": 0, "en_common": 0, "en_form": 0}
    for oid, word, key, lang, src_, data in s.execute(
            "SELECT id, word, key, lang, src, data FROM entries ORDER BY id"):
        obj = unpack(data)
        if lang == "ko":
            rows_out.append((key, lang, oid, word, src_, obj))
            n["ko"] += 1
            continue
        if src_ == "ko":  # 한국어판 위키낱말사전의 영어 단어 한국어 뜻
            rows_out.append((key, lang, oid, word, src_, obj))
            keep_en_keys.add(key)
            n["en_ko"] += 1
            continue
        senses = obj.get("s", [])
        if senses and all(sn.get("fo") for sn in senses) and not obj.get("ko"):
            form_rows.append((oid, word, key, obj))
            continue
        if obj.get("ko"):
            rows_out.append((key, lang, oid, word, src_, trim_en(obj)))
            keep_en_keys.add(key)
            n["en_ko"] += 1
        elif freq.get(key, 0) >= MIN_Z_EN:
            rows_out.append((key, lang, oid, word, src_, trim_en(obj)))
            keep_en_keys.add(key)
            n["en_common"] += 1
    # 2차: 변화형은 원형이 남아 있고 자주 쓰는 것만
    for oid, word, key, obj in form_rows:
        if freq.get(key, 0) < MIN_Z_FORM:
            continue
        if not any((sn.get("fo") or "").lower() in keep_en_keys for sn in obj.get("s", [])):
            continue
        obj["s"] = obj["s"][:3]
        for sn in obj["s"]:
            sn.pop("ex", None)
        obj.pop("ety", None)
        rows_out.append((key, "en", oid, word, "en", obj))
        n["en_form"] += 1

    # 같은 키끼리 같은 묶음에 들어가도록 키 순서로 정렬 (같은 키 안에서는 원래 순서 유지)
    rows_out.sort(key=lambda r: (r[0], r[1], r[2]))
    words, blk_rows, cur = [], [], []
    for key, lang, _oid, word, src_, obj in rows_out:
        if len(cur) >= BLOCK:
            blk_rows.append((len(blk_rows), zlib.compress(json.dumps(cur, ensure_ascii=False, separators=(",", ":")).encode(), 9)))
            cur = []
        words.append((word, key, lang, len(blk_rows), len(cur)))
        cur.append([word, src_, {k: v for k, v in obj.items() if v not in (None, "", [], {})}])
    if cur:
        blk_rows.append((len(blk_rows), zlib.compress(json.dumps(cur, ensure_ascii=False, separators=(",", ":")).encode(), 9)))

    d.executemany("INSERT INTO words(word,key,lang,blk,pos) VALUES(?,?,?,?,?)", words)
    d.executemany("INSERT INTO blocks VALUES(?,?)", blk_rows)
    d.executemany("INSERT INTO ko_en VALUES(?,?,?)", s.execute("SELECT ko, en, sense FROM ko_en"))
    d.executemany("INSERT INTO freq VALUES(?,?)", freq.items())
    meta = dict(s.execute("SELECT key, value FROM meta"))
    meta["edition"] = "mobile"
    meta["mobile_format"] = "1"
    for k, v in n.items():
        meta[f"mobile_{k}"] = v
    d.executemany("INSERT INTO meta VALUES(?,?)", [(k, str(v)) for k, v in meta.items()])
    d.executescript(
        """
        CREATE INDEX idx_words_key ON words(key, lang);
        CREATE INDEX idx_ko_en ON ko_en(ko);
        """
    )
    d.commit()
    d.execute("VACUUM")
    d.close()
    print(f"모바일 사전: {dst} ({os.path.getsize(dst)/1024/1024:.1f} MB)", n)


if __name__ == "__main__":
    main(*sys.argv[1:3])
