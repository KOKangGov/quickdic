"""
QuickDic 사전 DB 빌더
=====================

kaikki.org 에서 내려받은 Wiktionary 추출 데이터(JSONL)를
QuickDic 앱이 쓰는 SQLite 사전 파일(quickdic.db)로 변환합니다.

입력
  --en  영어판 위키낱말사전 raw 데이터 (raw-wiktextract-data.jsonl.gz)
        → 영어 단어의 영영 뜻·어원·예문·발음·한국어 번역, 한국어 단어의 영어 뜻
  --ko  한국어판 위키낱말사전 데이터 (ko-extract.jsonl.gz)
        → 영어 단어의 한국어 뜻풀이, 한국어 단어의 국어 뜻풀이

출력
  --out quickdic.db

GitHub Actions(주 1회)에서 자동 실행되며, 직접 돌릴 필요는 없습니다.
"""

from __future__ import annotations

import argparse
import gzip
import io
import os
import sqlite3
import sys
import time
import unicodedata
import zlib
from datetime import datetime, timezone

try:  # 훨씬 빠른 JSON 파서 (CI 에서는 설치됨)
    import orjson

    def jloads(s):
        return orjson.loads(s)

    def jdumps(o) -> bytes:
        return orjson.dumps(o)
except ImportError:  # pragma: no cover
    import json

    def jloads(s):
        return json.loads(s)

    def jdumps(o) -> bytes:
        return json.dumps(o, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


SCHEMA_VERSION = 2  # 2: zdict 공용 압축 사전

MAX_SENSES = 20
MAX_EXAMPLES_PER_SENSE = 3
MAX_GLOSS_LEN = 600
MAX_EXAMPLE_LEN = 240
MAX_QUOTE_LEN = 160  # 인용문(quotation)은 짧은 것만
MAX_WORD_LEN = 80
MAX_REL = 12  # 유의어/반의어 최대 개수
MAX_ETY_LEN = 2500

# 영어 고유명사는 한국어 번역이 있을 때만 수록 (용량 절약)
SKIP_EN_POS_UNLESS_KO = {"name"}
SKIP_POS = {"character", "punct", "romanization"}


def norm_key(word: str) -> str:
    return unicodedata.normalize("NFC", word).strip().lower()


def open_text(path: str):
    """.gz 이든 일반 파일이든 한 줄씩 읽는다."""
    if path.endswith(".gz"):
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8")
    return open(path, encoding="utf-8")


def clip(text: str | None, n: int) -> str:
    if not text:
        return ""
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def compact(obj: dict) -> bytes:
    """빈 값은 지운 JSON 바이트 (압축은 EntryWriter 가 공용 사전(zdict)으로 수행)."""
    return jdumps({k: v for k, v in obj.items() if v not in (None, "", [], {})})


# ---------------------------------------------------------------- 공통 파서

def sense_gloss(sense: dict) -> str:
    glosses = sense.get("glosses") or sense.get("raw_glosses") or []
    if not glosses:
        return ""
    return clip(glosses[-1], MAX_GLOSS_LEN)


def sense_examples(sense: dict) -> list:
    out = []
    exs = sense.get("examples") or []
    # 짧은 예문(example)을 인용문(quotation)보다 우선
    exs = sorted(exs, key=lambda e: (e.get("type") == "quotation", len(e.get("text") or "")))
    for ex in exs:
        text = clip(ex.get("text"), MAX_EXAMPLE_LEN)
        if not text:
            continue
        if ex.get("type") == "quotation" and (out or len(text) > MAX_QUOTE_LEN):
            continue
        tr = clip(ex.get("english") or ex.get("translation") or "", MAX_EXAMPLE_LEN)
        out.append([text, tr] if tr else [text])
        if len(out) >= MAX_EXAMPLES_PER_SENSE:
            break
    return out


def rel_words(*lists) -> list:
    seen, out = set(), []
    for lst in lists:
        for item in lst or []:
            w = item.get("word") if isinstance(item, dict) else item
            if w and w not in seen:
                seen.add(w)
                out.append(w)
                if len(out) >= MAX_REL:
                    return out
    return out


def ipa_list(entry: dict) -> list:
    out = []
    for snd in entry.get("sounds") or []:
        ipa = snd.get("ipa")
        if ipa and ipa not in out:
            out.append(ipa)
        if len(out) >= 3:
            break
    return out


SHORT_TAGS = {
    "obsolete", "archaic", "dated", "slang", "informal", "formal", "colloquial",
    "rare", "vulgar", "derogatory", "figuratively", "literary", "humorous",
    "British", "US", "UK", "Australia", "countable", "uncountable",
    "transitive", "intransitive", "plural", "singular", "abbreviation",
}


def sense_tags(sense: dict) -> list:
    return [t for t in (sense.get("tags") or []) if t in SHORT_TAGS][:4]


def build_senses(entry: dict) -> list:
    senses = []
    for s in entry.get("senses") or []:
        g = sense_gloss(s)
        fo = None
        for key in ("form_of", "alt_of"):
            if s.get(key):
                fo = (s[key][0] or {}).get("word")
                break
        if not g and not fo:
            continue
        item = {"g": g}
        t = sense_tags(s)
        if t:
            item["t"] = t
        ex = sense_examples(s)
        if ex:
            item["ex"] = ex
        if fo:
            item["fo"] = fo
        senses.append(item)
        if len(senses) >= MAX_SENSES:
            break
    return senses


def ko_translations(entry: dict) -> list:
    """영어판 엔트리에서 한국어 번역만 모아 [[뜻구분, [단어,...]], ...] 로."""
    groups: dict[str, list] = {}
    pools = list(entry.get("translations") or [])
    for s in entry.get("senses") or []:
        pools.extend(s.get("translations") or [])
    for tr in pools:
        code = tr.get("lang_code") or tr.get("code")
        if code != "ko":
            continue
        w = (tr.get("word") or "").strip()
        if not w:
            continue
        sense = clip(tr.get("sense") or "", 120)
        lst = groups.setdefault(sense, [])
        if w not in lst:
            lst.append(w)
    return [[k, v[:8]] for k, v in groups.items()][:12]


def korean_forms(entry: dict) -> tuple[str, str]:
    rom, hanja = "", ""
    for f in entry.get("forms") or []:
        tags = f.get("tags") or []
        if not rom and "romanization" in tags:
            rom = f.get("form") or ""
        if not hanja and "hanja" in tags:
            hanja = f.get("form") or ""
    return rom, hanja


# ---------------------------------------------------------------- DB

def create_db(path: str) -> sqlite3.Connection:
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    con.executescript(
        """
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        PRAGMA page_size=4096;
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
        -- lang: 표제어의 언어(en/ko), src: 출처 위키낱말사전 판(en/ko)
        CREATE TABLE entries(
            id   INTEGER PRIMARY KEY,
            word TEXT NOT NULL,
            key  TEXT NOT NULL,
            lang TEXT NOT NULL,
            src  TEXT NOT NULL,
            data BLOB NOT NULL
        );
        -- 한국어 → 영어 역방향 색인 (영어판 번역표에서 생성)
        CREATE TABLE ko_en(ko TEXT NOT NULL, en TEXT NOT NULL, sense TEXT);
        CREATE TABLE blobs(name TEXT PRIMARY KEY, data BLOB);
        """
    )
    return con


def finish_db(con: sqlite3.Connection, meta: dict):
    print("색인 생성 중...", flush=True)
    con.executescript(
        """
        CREATE INDEX idx_entries_key ON entries(key, lang);
        CREATE INDEX idx_ko_en ON ko_en(ko);
        """
    )
    con.executemany("INSERT INTO meta VALUES(?,?)", [(k, str(v)) for k, v in meta.items()])
    con.commit()
    print("압축(VACUUM) 중...", flush=True)
    con.execute("VACUUM")
    con.close()


class EntryWriter:
    """
    작은 JSON 조각을 각각 zlib 으로 압축하면 효율이 낮다. 처음 일부 항목으로
    공용 압축 사전(zdict, 32KB)을 만들어 모든 항목 압축에 함께 쓴다 → 용량 대폭 감소.
    zdict 는 blobs 테이블에 저장되어 앱이 풀 때 사용한다.
    """

    TRAIN_EN = 6000

    def __init__(self, con):
        self.con = con
        self.pending: list = []
        self.zdict: bytes | None = None
        self.en_seen = 0
        self.batch = Batch(con, "INSERT INTO entries(word,key,lang,src,data) VALUES(?,?,?,?,?)")

    def add(self, row):
        if self.zdict is None:
            self.pending.append(row)
            if row[3] == "en":
                self.en_seen += 1
                if self.en_seen >= self.TRAIN_EN:
                    self._train()
            return
        self.batch.add(self._pack(row))

    def _pack(self, row):
        c = zlib.compressobj(9, zlib.DEFLATED, 15, 9, zlib.Z_DEFAULT_STRATEGY, self.zdict)
        return (*row[:4], c.compress(row[4]) + c.flush())

    def _train(self):
        en = [r[4] for r in self.pending if r[3] == "en"]
        ko = [r[4] for r in self.pending if r[3] == "ko"]
        # 앞쪽보다 뒤쪽 내용이 더 잘 참조되므로 영어판 샘플을 뒤에 둔다
        sample = b"".join(ko[:: max(1, len(ko) // 80)][:80]) + b"".join(en[:: max(1, len(en) // 300)][:300])
        self.zdict = sample[-32768:] if sample else b" "
        self.con.execute("INSERT INTO blobs VALUES('zdict', ?)", (self.zdict,))
        for row in self.pending:
            self.batch.add(self._pack(row))
        self.pending = []

    def flush(self):
        if self.zdict is None and self.pending:
            self._train()
        self.batch.flush()


class Batch:
    def __init__(self, con, sql, size=5000):
        self.con, self.sql, self.size, self.rows = con, sql, size, []

    def add(self, row):
        self.rows.append(row)
        if len(self.rows) >= self.size:
            self.flush()

    def flush(self):
        if self.rows:
            self.con.executemany(self.sql, self.rows)
            self.rows = []


# ---------------------------------------------------------------- 단계별 처리

def process_ko_edition(path: str, entries: "EntryWriter", stats: dict):
    """한국어판: 영어 단어의 한국어 뜻풀이 + 한국어 단어의 국어 뜻풀이."""
    t0 = time.time()
    with open_text(path) as fh:
        for n, line in enumerate(fh, 1):
            if '"en"' not in line and '"ko"' not in line:
                continue
            try:
                e = jloads(line)
            except Exception:
                continue
            lang = e.get("lang_code")
            if lang not in ("en", "ko"):
                continue
            word = (e.get("word") or "").strip()
            pos = e.get("pos") or ""
            if not word or len(word) > MAX_WORD_LEN or pos in SKIP_POS:
                continue
            senses = build_senses(e)
            if not senses:
                continue
            data = {
                "p": pos,
                "pt": e.get("pos_title") or "",
                "s": senses,
                "ipa": ipa_list(e),
                "syn": rel_words(e.get("synonyms")),
                "ant": rel_words(e.get("antonyms")),
                "ety": clip(e.get("etymology_text"), MAX_ETY_LEN),
            }
            entries.add((word, norm_key(word), lang, "ko", compact(data)))
            stats[f"ko_{lang}"] = stats.get(f"ko_{lang}", 0) + 1
            if n % 100000 == 0:
                print(f"  [한국어판] {n:,}줄 처리 ({time.time()-t0:.0f}s)", flush=True)
    # (압축 사전 학습을 위해 여기서는 flush 하지 않음 — 영어판 처리 후 한꺼번에)


def process_en_edition(path: str, entries: "EntryWriter", rev: "Batch", stats: dict, limit: int = 0):
    """영어판: 영어 단어 전체 + 한국어 단어(영어 뜻)."""
    t0 = time.time()
    with open_text(path) as fh:
        for n, line in enumerate(fh, 1):
            if limit and n > limit:
                break
            if n % 500000 == 0:
                print(f"  [영어판] {n:,}줄 처리, 영어 {stats.get('en_en',0):,} / 한국어 {stats.get('en_ko',0):,} "
                      f"({time.time()-t0:.0f}s)", flush=True)
            # 빠른 사전 필터: 영어·한국어 엔트리만 JSON 파싱
            if ('"lang_code": "en"' not in line and '"lang_code":"en"' not in line
                    and '"lang_code": "ko"' not in line and '"lang_code":"ko"' not in line):
                continue
            try:
                e = jloads(line)
            except Exception:
                continue
            lang = e.get("lang_code")
            if lang not in ("en", "ko"):
                continue
            word = (e.get("word") or "").strip()
            pos = e.get("pos") or ""
            if not word or len(word) > MAX_WORD_LEN or pos in SKIP_POS:
                continue

            if lang == "en":
                ko = ko_translations(e)
                if pos in SKIP_EN_POS_UNLESS_KO and not ko:
                    continue
                senses = build_senses(e)
                if not senses and not ko:
                    continue
                syn = rel_words(e.get("synonyms"), *[s.get("synonyms") for s in e.get("senses") or []])
                ant = rel_words(e.get("antonyms"), *[s.get("antonyms") for s in e.get("senses") or []])
                data = {
                    "p": pos,
                    "s": senses,
                    "ipa": ipa_list(e),
                    "ety": clip(e.get("etymology_text"), MAX_ETY_LEN),
                    "syn": syn,
                    "ant": ant,
                    "ko": ko,
                }
                entries.add((word, norm_key(word), "en", "en", compact(data)))
                stats["en_en"] = stats.get("en_en", 0) + 1
                for sense, words in ko:
                    for kw in words:
                        rev.add((norm_key(kw), word, sense))
                        stats["ko_en_pairs"] = stats.get("ko_en_pairs", 0) + 1
            else:  # 한국어 단어 (뜻은 영어)
                senses = build_senses(e)
                if not senses:
                    continue
                rom, hanja = korean_forms(e)
                data = {
                    "p": pos,
                    "s": senses,
                    "ipa": ipa_list(e),
                    "ety": clip(e.get("etymology_text"), MAX_ETY_LEN),
                    "rom": rom,
                    "hj": hanja,
                    "syn": rel_words(e.get("synonyms")),
                    "ant": rel_words(e.get("antonyms")),
                }
                entries.add((word, norm_key(word), "ko", "en", compact(data)))
                stats["en_ko"] = stats.get("en_ko", 0) + 1
    entries.flush()
    rev.flush()


def main(argv=None):
    ap = argparse.ArgumentParser(description="QuickDic 사전 DB 빌더")
    ap.add_argument("--en", required=True, help="영어판 raw-wiktextract-data.jsonl(.gz)")
    ap.add_argument("--ko", required=True, help="한국어판 ko-extract.jsonl(.gz)")
    ap.add_argument("--out", default="quickdic.db")
    ap.add_argument("--version", default=datetime.now(timezone.utc).strftime("%Y.%m.%d"))
    ap.add_argument("--en-date", default="", help="영어판 원본 날짜(표시용)")
    ap.add_argument("--ko-date", default="", help="한국어판 원본 날짜(표시용)")
    ap.add_argument("--limit", type=int, default=0, help="테스트용: 영어판 처리 줄 수 제한")
    args = ap.parse_args(argv)

    t0 = time.time()
    tmp = args.out + ".building"
    con = create_db(tmp)
    entries = EntryWriter(con)
    rev = Batch(con, "INSERT INTO ko_en(ko,en,sense) VALUES(?,?,?)")
    stats: dict = {}

    print("1/2 한국어판 처리 중...", flush=True)
    process_ko_edition(args.ko, entries, stats)
    print("2/2 영어판 처리 중... (가장 오래 걸립니다)", flush=True)
    process_en_edition(args.en, entries, rev, stats, args.limit)

    meta = {
        "schema": SCHEMA_VERSION,
        "version": args.version,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "en_source": args.en_date,
        "ko_source": args.ko_date,
        "license": "Wiktionary (CC BY-SA 4.0 / GFDL) via kaikki.org",
        **{f"count_{k}": v for k, v in stats.items()},
    }
    finish_db(con, meta)
    os.replace(tmp, args.out)
    size = os.path.getsize(args.out) / 1024 / 1024
    print(f"완료: {args.out} ({size:,.1f} MB, {time.time()-t0:.0f}초)")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
