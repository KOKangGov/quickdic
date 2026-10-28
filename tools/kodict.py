"""
국립국어원 사전(표준국어대사전 · 우리말샘) 내려받기 파일 읽기
==============================================================

국립국어원 누리집의 '사전 내려받기'에서 받은 JSON 묶음(zip)을 읽어
QuickDic 사전 항목(국어 뜻풀이)으로 바꿉니다.

- 표준국어대사전  https://stdict.korean.go.kr  (약 43만 표제어)
    item → word_info → pos_info[] → comm_pattern_info[] → sense_info[]
- 우리말샘        https://opendict.korean.go.kr (약 110만 표제어)
    item → wordinfo + senseinfo   (뜻 하나가 item 하나, target_code 로 묶음)

두 형식은 자동으로 구분합니다. 입력은 zip 파일, 폴더, .json 파일 아무거나 됩니다.

저작권: 국립국어원 사전 데이터는 2019-03-11 부터 CC BY-SA 2.0 KR 로 배포됩니다.
단, 출판물·신문에서 인용한 예문과 발음·그림 등 미디어 파일은 제외되므로
출처가 달린 예문은 넣지 않습니다 (미디어 파일은 처음부터 다루지 않음).
"""

from __future__ import annotations

import html
import io
import json
import os
import re
import zipfile
from collections import OrderedDict

MAX_SENSES = 40
MAX_EX = 3
MAX_GLOSS = 600
MAX_EX_LEN = 240
MAX_REL = 12

TAG_RE = re.compile(r"<[^>]+>")
HOMO_RE = re.compile(r"\d+$")
HANGUL = re.compile(r"[가-힣]")

# 뜻 구분(type) 중 따로 표시할 것
SENSE_TYPE_TAG = {"방언": "방언", "옛말": "옛말", "북한어": "북한어"}


def clean_text(s, n: int = MAX_GLOSS) -> str:
    if not s:
        return ""
    s = html.unescape(str(s))
    s = TAG_RE.sub("", s)
    s = s.replace("{", "").replace("}", "")
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def display_word(raw: str) -> tuple[str, int]:
    """'사과02' / '가는-귀' / '가게^기둥에^입춘' → ('사과', 2) / ('가는귀', 0) / ('가게 기둥에 입춘', 0)"""
    raw = (raw or "").strip()
    sup = 0
    m = HOMO_RE.search(raw)
    if m and HANGUL.search(raw[: m.start()] or ""):
        sup = int(m.group())
        raw = raw[: m.start()]
    raw = raw.replace("^", " ")
    core = raw.strip("-")
    lead, trail = raw[: len(raw) - len(raw.lstrip("-"))], raw[len(raw.rstrip("-")):]
    core = core.replace("-", "")
    return (lead + core + trail).strip(), sup


def search_key(word: str) -> str:
    """국어 표제어 검색 키: 띄어쓰기·붙임표 없이 (앱도 같은 방식으로 찾음)"""
    return "".join(word.split()).strip("-").lower()


# ------------------------------------------------------------------ 파일 읽기

def _iter_json_blobs(path: str):
    if os.path.isdir(path):
        for name in sorted(os.listdir(path)):
            p = os.path.join(path, name)
            if name.lower().endswith((".json", ".zip")) or os.path.isdir(p):
                yield from _iter_json_blobs(p)
        return
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            for info in sorted(zf.infolist(), key=lambda i: i.filename):
                low = info.filename.lower()
                if low.endswith(".json"):
                    yield info.filename, zf.read(info)
                elif low.endswith(".zip"):  # zip 안의 zip
                    inner = zipfile.ZipFile(io.BytesIO(zf.read(info)))
                    for ii in sorted(inner.infolist(), key=lambda i: i.filename):
                        if ii.filename.lower().endswith(".json"):
                            yield ii.filename, inner.read(ii)
        return
    if path.lower().endswith(".json"):
        with open(path, "rb") as f:
            yield os.path.basename(path), f.read()


def _decode(b: bytes):
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return json.loads(b.decode(enc))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return None


def _items(doc):
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict):
        ch = doc.get("channel")
        if isinstance(ch, list):
            out = []
            for c in ch:
                out.extend((c or {}).get("item") or [])
            return out
        if isinstance(ch, dict):
            return ch.get("item") or []
        return doc.get("item") or []
    return []


def iter_items(paths: list[str]):
    """(형식, item) — 형식: 'std'(표준국어대사전) / 'open'(우리말샘)"""
    for path in paths:
        for name, blob in _iter_json_blobs(path):
            doc = _decode(blob)
            if doc is None:
                print(f"  ! JSON 을 읽지 못했어요: {name}", flush=True)
                continue
            for it in _items(doc):
                if not isinstance(it, dict):
                    continue
                if "word_info" in it:
                    yield "std", it
                elif "wordinfo" in it:
                    yield "open", it


# ------------------------------------------------------------------ 항목 변환

def _as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _examples(sense: dict) -> list:
    out = []
    for ex in _as_list(sense.get("example_info")):
        ex = ex or {}
        # 출판물·신문에서 인용한 예문(출처가 있는 예문)은 자유 이용 대상이 아니라서 넣지 않는다.
        # (국립국어원 사전 데이터는 CC BY-SA 2.0 KR 이지만 인용 예문은 원 문헌의 저작권을 따름)
        if any(str(ex.get(k) or "").strip() for k in ("source", "origin")):
            continue
        t = clean_text(ex.get("example"), MAX_EX_LEN)
        if t and [t] not in out:
            out.append([t])
        if len(out) >= MAX_EX:
            break
    return out


def _rels(sense: dict) -> tuple[list, list]:
    syn, ant = [], []
    for key in ("lexical_info", "relation_info"):
        for r in _as_list(sense.get(key)):
            r = r or {}
            w, _ = display_word(r.get("word") or "")
            typ = r.get("type") or ""
            if not w:
                continue
            if "비슷한말" in typ or "동의어" in typ or "유의어" in typ:
                if w not in syn:
                    syn.append(w)
            elif "반대말" in typ or "반의어" in typ:
                if w not in ant:
                    ant.append(w)
    return syn, ant


def _sense(sense: dict) -> dict | None:
    g = clean_text(sense.get("definition") or sense.get("definition_original"))
    if not g:
        return None
    item = {"g": g}
    tags = []
    typ = sense.get("type") or ""
    if typ in SENSE_TYPE_TAG:
        tags.append(SENSE_TYPE_TAG[typ])
    for c in _as_list(sense.get("cat_info")):
        cat = clean_text((c or {}).get("cat"), 20)
        if cat and cat not in tags:
            tags.append(cat)
    if tags:
        item["t"] = tags[:3]
    ex = _examples(sense)
    if ex:
        item["ex"] = ex
    return item


def _word_meta(wi: dict) -> dict:
    hanja, orig = [], []
    for o in _as_list(wi.get("original_language_info")):
        o = o or {}
        lang = o.get("language_type") or ""
        text = clean_text(o.get("original_language"), 60)
        if not text:
            continue
        if lang == "한자":
            hanja.append(text)
        elif lang not in ("고유어",):
            orig.append(f"{text}({lang})" if lang else text)
    pron = []
    for p in _as_list(wi.get("pronunciation_info")):
        t = clean_text((p or {}).get("pronunciation"), 40)
        if t and t not in pron:
            pron.append(t)
    return {
        "hj": "".join(hanja),
        "or": ", ".join(orig[:3]),
        "pr": " / ".join(pron[:3]),
        "u": wi.get("word_unit") or "",
    }


class KoDictCollector:
    """
    item 들을 표제어(동형어 번호까지) 단위로 모아 앱이 쓰는 형태로 만든다.
    우리말샘은 뜻마다 item 이 따로 있어 target_code 로 묶는다.
    표준국어대사전과 우리말샘을 함께 넣으면, 표준에 이미 있는 뜻풀이는 우리말샘에서 건너뛴다.
    """

    def __init__(self):
        self.entries: "OrderedDict[tuple, dict]" = OrderedDict()
        self.std_defs: set = set()
        self.stats = {"std": 0, "open": 0, "open_dup": 0}

    def add_std(self, it: dict):
        wi = it.get("word_info") or {}
        word, sup = display_word(wi.get("word"))
        if not word:
            return
        try:
            sup = int(wi.get("sup_no") or sup or 0)
        except (TypeError, ValueError):
            pass
        meta = _word_meta(wi)
        syn, ant = _rels(wi)
        groups = []  # [(품사, [뜻...])]
        for pi in _as_list(wi.get("pos_info")):
            pi = pi or {}
            pos = (pi.get("pos") or "").strip()
            senses = []
            for cp in _as_list(pi.get("comm_pattern_info")):
                for s in _as_list((cp or {}).get("sense_info")):
                    s = s or {}
                    item = _sense(s)
                    if item:
                        senses.append(item)
                        self.std_defs.add((search_key(word), item["g"][:40]))
                    a, b = _rels(s)
                    syn += [w for w in a if w not in syn]
                    ant += [w for w in b if w not in ant]
            if senses:
                groups.append((pos, senses))
        if not groups:
            return
        key = ("std", it.get("target_code") or f"{word}#{sup}")
        self.entries[key] = {"word": word, "sup": sup, "meta": meta, "groups": groups,
                             "syn": syn[:MAX_REL], "ant": ant[:MAX_REL], "d": "표준"}
        self.stats["std"] += 1

    def add_open(self, it: dict):
        wi = it.get("wordinfo") or {}
        si = it.get("senseinfo") or {}
        word, sup = display_word(wi.get("word"))
        if not word:
            return
        try:
            sup = int(wi.get("sup_no") or sup or 0)
        except (TypeError, ValueError):
            pass
        item = _sense(si)
        if not item:
            return
        if (search_key(word), item["g"][:40]) in self.std_defs:
            self.stats["open_dup"] += 1
            return
        key = ("open", it.get("target_code") or f"{word}#{sup}")
        e = self.entries.get(key)
        if e is None:
            e = self.entries[key] = {"word": word, "sup": sup, "meta": _word_meta(wi), "groups": [],
                                     "syn": [], "ant": [], "d": "우리말샘"}
            self.stats["open"] += 1
        pos = (si.get("pos") or "").strip()
        if e["groups"] and e["groups"][-1][0] == pos:
            e["groups"][-1][1].append(item)
        else:
            e["groups"].append((pos, [item]))
        a, b = _rels(si)
        e["syn"] += [w for w in a if w not in e["syn"]][:MAX_REL]
        e["ant"] += [w for w in b if w not in e["ant"]][:MAX_REL]

    def load(self, paths: list[str]):
        # 표준국어대사전을 먼저 읽어야 우리말샘 중복을 걸러낼 수 있어 두 번에 나눠 읽는다
        has_open = False
        for fmt, it in iter_items(paths):
            if fmt == "std":
                self.add_std(it)
            else:
                has_open = True
        if has_open:
            for fmt, it in iter_items(paths):
                if fmt == "open":
                    self.add_open(it)

    def rows(self):
        """(표제어, 검색키, data) — data 는 앱의 국어 뜻풀이 형식 (src='ko')"""
        for e in self.entries.values():
            for pos, senses in e["groups"]:
                m = e["meta"]
                data = {
                    "p": pos,
                    "pt": pos or m["u"] or "",
                    "s": senses[:MAX_SENSES],
                    "n": e["sup"],
                    "u": m["u"],
                    "hj": m["hj"],
                    "or": m["or"],
                    "pr": m["pr"],
                    "syn": e["syn"],
                    "ant": e["ant"],
                    "d": e["d"],
                }
                yield e["word"], search_key(e["word"]), data
