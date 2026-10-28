"""
국립국어원 사전 내려받기 zip → 공개 저장소에 올려도 되는 '정리본' zip

국립국어원 사전 데이터는 CC BY-SA 2.0 KR 이지만, 출판물·신문에서 인용한 예문(출처가 달린 예문)과
사진·소리 등 미디어 파일은 그 라이선스 대상이 아니다. 원본 zip 을 그대로 'source-data' 릴리스에
공개하면 이것까지 재배포하게 되므로, QuickDic 이 쓰는 항목만 남기고 나머지는 지운 정리본을 만든다.

    python tools/clean_kodict.py 원본.zip  stdict-clean.zip
"""

from __future__ import annotations

import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kodict  # noqa: E402

KEEP_WORD = {"word", "word_unit", "word_type", "sup_no", "original_language_info", "pronunciation_info",
             "origin", "lexical_info", "relation_info", "pos_info"}
KEEP_REL = {"word", "type"}


def _rels(lst):
    return [{k: v for k, v in (r or {}).items() if k in KEEP_REL} for r in kodict._as_list(lst)]


def _examples(lst):
    out = []
    for ex in kodict._as_list(lst):
        ex = ex or {}
        if any(str(ex.get(k) or "").strip() for k in ("source", "origin")):
            continue  # 인용 예문 제외
        if ex.get("example"):
            out.append({"example": ex["example"]})
    return out


def _sense(s):
    s = s or {}
    out = {k: s[k] for k in ("definition", "type") if s.get(k)}
    if s.get("cat_info"):
        out["cat_info"] = [{"cat": (c or {}).get("cat")} for c in kodict._as_list(s["cat_info"])]
    if s.get("example_info"):
        ex = _examples(s["example_info"])
        if ex:
            out["example_info"] = ex
    for k in ("lexical_info", "relation_info"):
        if s.get(k):
            out[k] = _rels(s[k])
    return out


def clean_std(it):
    wi = it.get("word_info") or {}
    w = {k: v for k, v in wi.items() if k in KEEP_WORD}
    for k in ("lexical_info", "relation_info"):
        if k in w:
            w[k] = _rels(w[k])
    w["pos_info"] = [{"pos": (p or {}).get("pos", ""), "comm_pattern_info": [
        {"sense_info": [_sense(s) for s in kodict._as_list((cp or {}).get("sense_info"))]}
        for cp in kodict._as_list((p or {}).get("comm_pattern_info"))]} for p in kodict._as_list(wi.get("pos_info"))]
    return {"target_code": it.get("target_code"), "word_info": w}


def clean_open(it):
    wi = it.get("wordinfo") or {}
    return {"target_code": it.get("target_code"),
            "wordinfo": {k: v for k, v in wi.items() if k in KEEP_WORD},
            "senseinfo": dict(_sense(it.get("senseinfo")), pos=(it.get("senseinfo") or {}).get("pos", ""))}


def main(src: str, dst: str, per_file: int = 50000):
    buf, n, part = [], 0, 0
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as out:
        def flush():
            nonlocal buf, part
            if buf:
                part += 1
                out.writestr(f"part{part:03d}.json",
                             json.dumps({"channel": {"item": buf}}, ensure_ascii=False, separators=(",", ":")))
                buf = []
        for fmt, it in kodict.iter_items([src]):
            buf.append(clean_std(it) if fmt == "std" else clean_open(it))
            n += 1
            if len(buf) >= per_file:
                flush()
        flush()
    print(f"정리본: {dst} ({n:,}항목, {os.path.getsize(dst)/1024/1024:.1f} MB)")


if __name__ == "__main__":
    main(*sys.argv[1:3])
