"""
사전 조회 모듈 (화면과 무관한 순수 로직)

SQLite 사전 파일을 열어 단어를 찾고, 결과를 화면에 그리기 쉬운
'문서(Doc)' 형태 — 줄(line) 목록, 각 줄은 (글자, 스타일, 링크) 조각 목록 — 로 돌려준다.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
import zlib
from dataclasses import dataclass, field

import fuzzy

# ------------------------------------------------------------------ 표시용 사전

POS_KO = {
    "noun": "명사", "verb": "동사", "adj": "형용사", "adv": "부사", "pron": "대명사",
    "prep": "전치사", "conj": "접속사", "intj": "감탄사", "det": "한정사", "article": "관사",
    "num": "수사", "phrase": "구", "prep_phrase": "전치사구", "adv_phrase": "부사구",
    "proverb": "속담", "prefix": "접두사", "suffix": "접미사", "infix": "접요사",
    "name": "고유명사", "abbrev": "약어", "symbol": "기호", "particle": "불변화사",
    "contraction": "축약형", "postp": "후치사", "affix": "접사", "root": "어근",
    "counter": "단위성 의존명사", "classifier": "분류사", "unknown": "기타",
}
POS_EN = {
    "noun": "Noun", "verb": "Verb", "adj": "Adjective", "adv": "Adverb", "pron": "Pronoun",
    "prep": "Preposition", "conj": "Conjunction", "intj": "Interjection", "det": "Determiner",
    "article": "Article", "num": "Numeral", "phrase": "Phrase", "prep_phrase": "Prepositional phrase",
    "proverb": "Proverb", "prefix": "Prefix", "suffix": "Suffix", "name": "Proper noun",
    "abbrev": "Abbreviation", "symbol": "Symbol", "particle": "Particle", "contraction": "Contraction",
}
TAG_KO = {
    "obsolete": "폐어", "archaic": "고어", "dated": "예스러움", "slang": "속어", "informal": "비격식",
    "formal": "격식", "colloquial": "구어", "rare": "드묾", "vulgar": "비속어", "derogatory": "경멸",
    "figuratively": "비유", "literary": "문어", "humorous": "익살", "British": "영국", "UK": "영국",
    "US": "미국", "Australia": "호주", "countable": "가산", "uncountable": "불가산",
    "transitive": "타동사", "intransitive": "자동사", "plural": "복수", "singular": "단수",
    "abbreviation": "약어",
}

CITATION_RE = re.compile(r"^(c\.\s?)?\d{3,4}(s)?\s*([-–,]|$)")
HANGUL_RE = re.compile(r"[ᄀ-ᇿ㄰-㆏가-힣]")
JAMO_RE = re.compile(r"[ㄱ-ㅣ]")
STRIP_CHARS = " \t\r\n.,;:!?\"'()[]{}<>“”‘’«»…—–-*_/\\|`~@#$%^&+=0123456789"


def norm_key(word: str) -> str:
    return unicodedata.normalize("NFC", word).strip().lower()


def clean_query(text: str) -> str:
    """드래그로 잡힌 텍스트를 검색어로 정리."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("­", "")  # soft hyphen
    text = re.sub(r"-\s*\n\s*", "", text)  # 줄바꿈 하이픈 'ephem-\neral'
    text = " ".join(text.split())
    text = text.strip(STRIP_CHARS)
    # 소유격 's 제거
    text = re.sub(r"['’]s$", "", text)
    return text[:120]


def is_korean(text: str) -> bool:
    return bool(HANGUL_RE.search(text or ""))


def ko_key(word: str) -> str:
    """국어 표제어 검색 키 (띄어쓰기 무시) — tools/kodict.search_key 와 같은 규칙"""
    return "".join(norm_key(word).split()).strip("-")


SUP_DIGITS = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


def english_variants(word: str) -> list[str]:
    """사전에 그대로 없을 때 시도해 볼 원형 후보들."""
    w = word.lower()
    out = [w]

    def add(x):
        if x and len(x) > 1 and x not in out:
            out.append(x)

    if w.endswith("ies"):
        add(w[:-3] + "y")
    if w.endswith("es"):
        add(w[:-2])
    if w.endswith("s") and not w.endswith("ss"):
        add(w[:-1])
    if w.endswith("ied"):
        add(w[:-3] + "y")
    if w.endswith("ed"):
        add(w[:-2])
        add(w[:-1])
        if len(w) > 4 and w[-3] == w[-4]:
            add(w[:-3])
    if w.endswith("ing"):
        add(w[:-3])
        add(w[:-3] + "e")
        if len(w) > 5 and w[-4] == w[-5]:
            add(w[:-4])
    if w.endswith("er"):
        add(w[:-2])
        add(w[:-1])
    if w.endswith("est"):
        add(w[:-3])
        add(w[:-2])
    if w.endswith("ly"):
        add(w[:-2])
        if w.endswith("ily"):
            add(w[:-3] + "y")
    return out


# ------------------------------------------------------------------ 결과 모델

Seg = tuple  # (text, style, link) — style: 'h1','pos','num','ko','en','tag','dim','ex','tr','link','note','sec'


@dataclass
class Doc:
    lines: list = field(default_factory=list)

    def line(self, *segs):
        self.lines.append([s if isinstance(s, tuple) else (s, None, None) for s in segs])

    def blank(self):
        if self.lines and self.lines[-1]:
            self.lines.append([])

    @property
    def empty(self) -> bool:
        return not any(self.lines)

    def plain_text(self) -> str:
        return "\n".join("".join(seg[0] for seg in ln) for ln in self.lines)


@dataclass
class Result:
    query: str
    found: bool = False
    headword: str = ""
    ipa: str = ""
    lang: str = "en"           # 검색어 언어
    meaning: Doc = field(default_factory=Doc)
    meaning_en: Doc = field(default_factory=Doc)  # 영영 정의 (토글)
    etymology: Doc = field(default_factory=Doc)
    examples: Doc = field(default_factory=Doc)
    suggestions: list = field(default_factory=list)  # 못 찾았을 때 '혹시 이 단어?'
    redirected_from: str = ""
    has_ko: bool = False       # 한국어 뜻(뜻풀이/번역어)이 있는지


@dataclass
class Row:
    word: str
    lang: str
    src: str
    data: dict


# ------------------------------------------------------------------ 사전

class Dictionary:
    def __init__(self, path: str):
        self.path = path
        self.con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        self.con.execute("PRAGMA query_only=1")
        self.meta = dict(self.con.execute("SELECT key, value FROM meta").fetchall())
        self.zdict = b""
        try:
            row = self.con.execute("SELECT data FROM blobs WHERE name='zdict'").fetchone()
            self.zdict = bytes(row[0]) if row else b""
        except sqlite3.Error:
            pass
        self.has_freq = self.con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='freq'").fetchone() is not None

    def _unpack(self, data: bytes) -> dict:
        if self.zdict:
            d = zlib.decompressobj(15, self.zdict)
            return json.loads(d.decompress(data) + d.flush())
        return json.loads(zlib.decompress(data))

    @property
    def version(self) -> str:
        return self.meta.get("version", "?")

    def close(self):
        try:
            self.con.close()
        except Exception:
            pass

    # ---------------------------------------------------------- 저수준 조회
    def _rows(self, key: str, lang: str) -> list[Row]:
        cur = self.con.execute(
            "SELECT word, lang, src, data FROM entries WHERE key=? AND lang=? ORDER BY id", (key, lang)
        )
        return [Row(w, lg, src, self._unpack(d)) for w, lg, src, d in cur]

    def _ko_to_en(self, key: str) -> list[tuple[str, str]]:
        cur = self.con.execute("SELECT en, sense FROM ko_en WHERE ko=? LIMIT 60", (key,))
        return cur.fetchall()

    def suggestions(self, prefix: str, lang: str | None = None, limit: int = 8) -> list[str]:
        key = norm_key(prefix)
        if not key:
            return []
        lang = lang or ("ko" if is_korean(key) else "en")
        cur = self.con.execute(
            "SELECT DISTINCT word FROM entries WHERE key >= ? AND key < ? AND lang=? LIMIT ?",
            (key, key + "￿", lang, limit),
        )
        return [r[0] for r in cur]

    # ---------------------------------------------------------- 오타 → 비슷한 단어
    def _existing(self, keys, lang: str) -> list[str]:
        keys = list(keys)
        found = []
        for i in range(0, len(keys), 400):
            chunk = keys[i:i + 400]
            q = ",".join("?" * len(chunk))
            found += [r[0] for r in self.con.execute(
                f"SELECT DISTINCT key FROM entries WHERE lang=? AND key IN ({q})", (lang, *chunk))]
        return found

    def _freq(self, keys) -> dict:
        if not self.has_freq or not keys:
            return {}
        keys = list(keys)
        out = {}
        for i in range(0, len(keys), 400):
            chunk = keys[i:i + 400]
            q = ",".join("?" * len(chunk))
            out.update(self.con.execute(f"SELECT key, z FROM freq WHERE key IN ({q})", chunk).fetchall())
        return out

    def _display(self, key: str, lang: str) -> str:
        rows = self.con.execute("SELECT word FROM entries WHERE key=? AND lang=? ORDER BY id LIMIT 8",
                                (key, lang)).fetchall()
        words = [r[0] for r in rows]
        if not words:
            return key
        # 소문자 표기(일반 단어)를 고유명사 표기보다 우선
        return next((w for w in words if w == key or w.lower() == w), words[0])

    def similar(self, text: str, limit: int = 8, fast: bool = False) -> list[str]:
        """
        오타로 보이는 검색어와 비슷한 사전 단어. 가까운 순 → 자주 쓰는 순.
        fast=True 이면 타이핑 중 자동완성용으로 가볍게만 찾는다.
        """
        q = clean_query(text)
        if not q:
            return []
        scored: dict[tuple, float] = {}  # (lang, key) → 점수(낮을수록 좋음)

        def add(lang, keys, dist_fn, base=0.0):
            freq = self._freq(keys)
            for k in keys:
                d = dist_fn(k)
                if d > 2:
                    continue
                sc = base + d - freq.get(k, 0) * 0.012
                if sc < scored.get((lang, k), 99):
                    scored[(lang, k)] = sc

        if is_korean(q):
            key = ko_key(q)
            # 1) 자모 하나 차이 후보를 직접 만들어 사전에 있는지 확인 (빠름)
            cands = fuzzy.edits1_ko(key)
            if not fast or len(key) <= 6:
                add("ko", self._existing(cands, "ko"), lambda k: fuzzy.ko_distance(key, k, 2))
            # 2) 첫 글자가 같은 단어들 중에서 자모 거리 2 이내
            if not fast and len(key) >= 2:
                first = key[0]
                rows = self.con.execute(
                    "SELECT DISTINCT key FROM entries WHERE lang='ko' AND key >= ? AND key < ? "
                    "AND length(key) BETWEEN ? AND ? LIMIT 6000",
                    (first, chr(ord(first) + 1), max(1, len(key) - 1), len(key) + 1)).fetchall()
                add("ko", [r[0] for r in rows if r[0] != key], lambda k: fuzzy.ko_distance(key, k, 2))
            # 3) 한글 자판으로 영어를 친 경우 ('ㅁㅔㅔㅣㄷ' → apple) — 낱자모가 있거나 한글 후보가 없을 때만
            eng = fuzzy.kor_to_keys(q).lower()
            if ((JAMO_RE.search(q) or not scored) and eng.isascii() and eng.replace(" ", "").isalpha()
                    and (not fast or len(eng) >= 4)):
                for cand in english_variants(eng)[:1]:
                    if self._existing([norm_key(cand)], "en"):
                        scored[("en", norm_key(cand))] = -5
        else:
            key = norm_key(q)
            # 0) 영문 자판으로 한글을 친 경우 ('tkrhk' → 사과)
            kor = fuzzy.keys_to_kor(q)
            if kor and fuzzy.is_syllable(kor[0]) and all(fuzzy.is_syllable(c) or c == " " for c in kor):
                kk = ko_key(kor)
                if self._existing([kk], "ko"):
                    scored[("ko", kk)] = -5
            if len(key) >= 2:
                # 1) 한 글자 차이(빠짐·더함·바꿈·순서 바뀜)
                add("en", self._existing(fuzzy.edits1_en(key), "en"), lambda k: fuzzy.osa_distance(key, k, 2))
                # 2) 앞 두세 글자가 같은 단어들 중 거리 2 이내
                if not fast and len(key) >= 4:
                    pre = key[:3] if len(key) >= 6 else key[:2]
                    rows = self.con.execute(
                        "SELECT DISTINCT key FROM entries WHERE lang='en' AND key >= ? AND key < ? "
                        "AND length(key) BETWEEN ? AND ? LIMIT 6000",
                        (pre, pre + "\uffff", len(key) - 2, len(key) + 2)).fetchall()
                    add("en", [r[0] for r in rows if r[0] != key], lambda k: fuzzy.osa_distance(key, k, 2))
        best = sorted(scored.items(), key=lambda kv: (kv[1], kv[0][1]))
        out = []
        for (lang, k), _ in best:
            if k == norm_key(q) or k == ko_key(q):
                continue
            w = self._display(k, lang)
            if w not in out:
                out.append(w)
            if len(out) >= limit:
                break
        return out

    def exists(self, word: str) -> bool:
        key = norm_key(word)
        lang = "ko" if is_korean(key) else "en"
        return self.con.execute(
            "SELECT 1 FROM entries WHERE key=? AND lang=? LIMIT 1", (key, lang)
        ).fetchone() is not None

    # ---------------------------------------------------------- 검색
    def lookup(self, raw: str) -> Result:
        q = clean_query(raw)
        res = Result(query=q)
        if not q:
            return res
        # 한글 자판 상태로 영어를 친 경우 ('ㅗ디ㅣㅐ' → hello): 낱자모가 섞여 있으면 먼저 영어로 바꿔 본다
        if JAMO_RE.search(q):
            eng = fuzzy.kor_to_keys(q).lower()
            if eng.isascii() and self._existing([norm_key(eng)], "en"):
                res.lang = "en"
                self._lookup_en(eng, res)
                if res.found:
                    res.redirected_from = q
                    return res
                res = Result(query=q)
        if is_korean(q):
            res.lang = "ko"
            self._lookup_ko(q, res)
        else:
            res.lang = "en"
            self._lookup_en(q, res)
            # 영문 자판 상태로 한글을 친 경우 ('dkssud' → 안녕)
            if not res.found:
                kor = fuzzy.keys_to_kor(q)
                if kor and all(fuzzy.is_syllable(c) or c == " " for c in kor) and self._existing([ko_key(kor)], "ko"):
                    res = Result(query=q, lang="ko")
                    self._lookup_ko(kor, res)
                    if res.found:
                        res.redirected_from = q
                        return res
                    res = Result(query=q, lang="en")
        if not res.found and not res.suggestions:
            sim = self.similar(q, limit=8)
            pre = [w for w in self.suggestions(q[: max(3, len(q) - 2)], res.lang) if w not in sim]
            res.suggestions = (sim + pre)[:8]
        return res

    PARTICLES = {
        "이", "가", "을", "를", "은", "는", "에", "의", "도", "만", "와", "과", "로", "으로", "에서", "에게",
        "까지", "부터", "께", "한테", "보다", "처럼", "이다", "다", "요", "이요", "들", "랑", "이랑", "고", "며",
        "에는", "에도", "으로는", "로는", "이나", "나", "든지", "마다", "조차", "밖에", "하다", "했다", "하고",
        "하는", "한", "할", "해", "해서", "하여", "된", "되다", "적", "적인", "적으로", "들이", "들을", "들의",
    }

    @classmethod
    def _looks_like_particle(cls, q: str, head: str) -> bool:
        rest = ko_key(q)[len(ko_key(head)):]
        return rest in cls.PARTICLES

    # ---------------------------------------------------------- 영어 → 한국어
    def _lookup_en(self, q: str, res: Result):
        rows: list[Row] = []
        used = q
        for cand in english_variants(q):
            rows = self._rows(norm_key(cand), "en")
            if rows:
                used = cand
                break
        if not rows:
            return
        if norm_key(used) != norm_key(q):
            res.redirected_from = q

        # 정확히 같은 대소문자 표기를 우선
        exact = [r for r in rows if r.word == q or r.word == used]
        rows.sort(key=lambda r: (r not in exact, r.word))

        res.found = True
        res.headword = rows[0].word
        res.ipa = next((r.data["ipa"][0] for r in rows if r.data.get("ipa")), "")

        # 변화형(복수형·과거형 등)만 있는 경우 원형도 함께 보여줌
        lemmas = []
        for r in rows:
            for s in r.data.get("s", []):
                fo = s.get("fo")
                if fo and fo not in lemmas and norm_key(fo) != norm_key(r.word):
                    lemmas.append(fo)
        lemma_rows: list[Row] = []
        for lm in lemmas[:3]:
            lemma_rows.extend(self._rows(norm_key(lm), "en"))

        res.has_ko = self._has_ko(rows) or bool(lemma_rows and self._has_ko(lemma_rows))
        form_only = all(s.get("fo") for r in rows for s in r.data.get("s", [])) and not self._has_ko(rows)
        show_note = not self._has_ko(rows) and not (lemma_rows and self._has_ko(lemma_rows))
        lemma_ko = bool(lemma_rows) and self._has_ko(lemma_rows)
        if form_only and lemma_ko:
            # 'apples' 처럼 변화형뿐이면 원형의 한국어 뜻을 맨 위에 보여준다
            gloss = next((s.get("g") for r in rows for s in r.data.get("s", []) if s.get("g")), "")
            for lm in lemmas[:3]:
                lr = [r for r in lemma_rows if norm_key(r.word) == norm_key(lm)]
                if not lr:
                    continue
                for d in (res.meaning, res.meaning_en):
                    d.line(("▶ 원형 ", "sec", None), (lm, "link", lm),
                           (f"   ({gloss})" if gloss else "", "dim", None))
                self._render_en_meaning(lr, res, show_note=False)
                for d in (res.meaning, res.meaning_en):
                    d.blank()
            if not res.ipa:
                res.ipa = next((r.data["ipa"][0] for r in lemma_rows if r.data.get("ipa")), "")
            self._render_etymology(rows + lemma_rows, res)
            self._render_examples(lemma_rows + rows, res)
            return
        self._render_en_meaning(rows, res, show_note=show_note, compact=bool(lemma_rows) and form_only)
        if lemma_rows:
            for lm in lemmas[:3]:
                lr = [r for r in lemma_rows if norm_key(r.word) == norm_key(lm)]
                if not lr:
                    continue
                for d in (res.meaning, res.meaning_en):
                    d.blank()
                    d.line(("▶ 원형 ", "sec", None), (lm, "link", lm))
                self._render_en_meaning(lr, res, show_note=False, compact=not form_only)
            if not res.ipa:
                res.ipa = next((r.data["ipa"][0] for r in lemma_rows if r.data.get("ipa")), "")

        self._render_etymology(rows + lemma_rows, res)
        self._render_examples(rows + lemma_rows, res)

    @staticmethod
    def _has_ko(rows: list[Row]) -> bool:
        return any((r.src == "ko" and any(x.get("g") for x in r.data.get("s", []))) or r.data.get("ko")
                   for r in rows)

    def _render_en_meaning(self, rows: list[Row], res: Result, show_note: bool = True, compact: bool = False):
        doc, en = res.meaning, res.meaning_en
        multi_words = len({r.word for r in rows}) > 1

        # 1) 한국어판 위키낱말사전의 한국어 뜻풀이
        ko_rows = [r for r in rows if r.src == "ko"]
        # 2) 영어판의 한국어 번역어
        en_rows = [r for r in rows if r.src == "en"]

        wrote_ko = False
        for r in ko_rows:
            senses = [s for s in r.data.get("s", []) if s.get("g")]
            if not senses:
                continue
            p = r.data.get("p")
            if p in (None, "", "unknown"):
                label = r.data.get("pt") or "한국어 뜻"  # 한국어판에 품사 표시가 없는 경우
            else:
                label = POS_KO.get(p, r.data.get("pt") or p)
            head = [("• " + label, "pos", None)]
            if multi_words:
                head.append(("  " + r.word, "dim", None))
            doc.line(*head)
            for i, s in enumerate(senses, 1):
                doc.line((f"  {i}. ", "num", None), *self._tags(s), (s["g"], "ko", None))
            wrote_ko = True

        trans = []
        for r in en_rows:
            for sense, words in r.data.get("ko", []):
                trans.append((r.data.get("p"), sense, words))
        if trans:
            if wrote_ko:
                doc.blank()
            doc.line(("한국어 번역어", "sec", None))
            for pos, sense, words in trans[:14]:
                segs = [("  · ", "dim", None)]
                if pos in POS_KO:
                    segs.append((f"[{POS_KO[pos]}] ", "tag", None))
                segs.append((", ".join(words), "ko", None))
                if sense:
                    segs.append(("  — " + sense, "dim", None))
                doc.line(*segs)
            wrote_ko = True

        # 3) 영영 정의 (토글 탭용 + 한국어 정보가 없으면 본문에도 표시)
        target_docs = [en] if wrote_ko else [en, doc]
        if not wrote_ko and show_note:
            doc.line(("한국어 뜻풀이가 아직 없는 단어예요. 영어 뜻을 보여드려요. ('웹사전' 버튼으로 포털 사전을 열 수 있어요)", "note", None))
            doc.blank()
        for r in en_rows:
            senses = r.data.get("s", [])
            if not senses:
                continue
            p = r.data.get("p")
            label = f"{POS_KO.get(p, p)} ({POS_EN.get(p, p)})"
            for d in target_docs:
                head = [("• " + label, "pos", None)]
                if multi_words:
                    head.append(("  " + r.word, "dim", None))
                d.line(*head)
                limit = 6 if compact else 20
                for i, s in enumerate(senses[:limit], 1):
                    segs = [(f"  {i}. ", "num", None), *self._tags(s)]
                    if s.get("g"):
                        segs.append((s["g"], "en", None))
                    if s.get("fo"):
                        segs.append(("  → ", "dim", None))
                        segs.append((s["fo"], "link", s["fo"]))
                    d.line(*segs)

        # 유의어 / 반의어
        syn, ant = [], []
        for r in rows:
            for w in r.data.get("syn", []):
                if w not in syn:
                    syn.append(w)
            for w in r.data.get("ant", []):
                if w not in ant:
                    ant.append(w)
        if (syn or ant) and not compact:
            doc.blank()
            for title, words in (("유의어", syn), ("반의어", ant)):
                if not words:
                    continue
                segs = [(title + "  ", "sec", None)]
                for j, w in enumerate(words[:10]):
                    if j:
                        segs.append((", ", "dim", None))
                    segs.append((w, "link", w))
                doc.line(*segs)

    @staticmethod
    def _tags(sense: dict) -> list:
        tags = sense.get("t") or []
        if not tags:
            return []
        return [("(" + ", ".join(TAG_KO.get(t, t) for t in tags) + ") ", "tag", None)]

    # ---------------------------------------------------------- 한국어 → 영어
    def _ko_rows(self, key: str) -> tuple[list, list]:
        """띄어쓴 키와 붙여 쓴 키 모두로 찾는다 (국어사전 표제어는 붙여 쓴 키로 저장됨)."""
        rows, pairs, seen = [], [], set()
        for k in dict.fromkeys((key, ko_key(key))):
            for r in self._rows(k, "ko"):
                sig = (r.word, r.src, json.dumps(r.data, ensure_ascii=False, sort_keys=True)[:200])
                if sig not in seen:
                    seen.add(sig)
                    rows.append(r)
            for p in self._ko_to_en(k):
                if p not in pairs:
                    pairs.append(p)
        return rows, pairs

    def _lookup_ko(self, q: str, res: Result):
        key = norm_key(q)
        rows, pairs = self._ko_rows(key)
        if not rows and not pairs:
            # 조사·어미가 붙은 경우 끝 글자를 하나씩 떼어 보며 재시도
            k0 = ko_key(key)
            for cut in range(1, min(3, len(k0) - 1) + 1):
                k2 = k0[:-cut]
                r2, p2 = self._ko_rows(k2)
                if not (r2 or p2):
                    continue
                if k0[len(k2):] not in self.PARTICLES:
                    # 뗀 부분이 조사·어미가 아니면 오타일 가능성이 크다 → 비슷한 단어가 있으면 그걸 추천
                    sim = self.similar(q, limit=8)
                    if sim:
                        res.suggestions = sim + ([r2[0].word] if r2 and r2[0].word not in sim else [])
                        return
                rows, pairs = r2, p2
                res.redirected_from = q
                key = k2
                break
        if not rows and not pairs:
            return
        res.found = True
        doc = res.meaning

        ko_rows = [r for r in rows if r.src == "ko"]
        en_rows = [r for r in rows if r.src == "en"]
        kodict_rows = [r for r in ko_rows if r.data.get("d")]
        unit_order = {"단어": 0, "": 1, "구": 2, "관용구": 3, "속담": 4}
        kodict_rows = self._sort_homographs(kodict_rows, unit_order)
        wiki_rows = [r for r in ko_rows if not r.data.get("d")]

        res.headword = (kodict_rows or ko_rows or rows)[0].word if rows else key
        first = kodict_rows[0].data if kodict_rows else {}
        hanja = first.get("hj") or next((r.data.get("hj") for r in rows if r.data.get("hj")), "")
        pron = f"[{first['pr']}]" if first.get("pr") else ""
        rom = next((r.data.get("rom") for r in rows if r.data.get("rom")), "")
        ipa = next((r.data["ipa"][0] for r in rows if r.data.get("ipa")), "")
        res.ipa = " · ".join(x for x in (hanja, pron or ipa, rom) if x)

        # 1) 국어 뜻풀이 — 맨 위
        if kodict_rows:
            srcs = sorted({r.data["d"] for r in kodict_rows}, key=lambda d: d != "표준")
            doc.line(("국어 뜻풀이", "sec", None), ("   " + " · ".join(
                "표준국어대사전" if d == "표준" else d for d in srcs), "dim", None))
            last_head, num, shown = None, 0, 0
            for r in kodict_rows:
                d = r.data
                head = (r.word, d.get("n") or 0)
                if head != last_head:
                    if shown >= 15:
                        doc.line(("  … 같은 소리의 단어가 더 있어요. 웹사전에서 확인해 보세요.", "note", None))
                        break
                    shown += 1
                    last_head, num = head, 0
                    segs = [("▪ " + r.word + (str(head[1]).translate(SUP_DIGITS) if head[1] else ""), "pos", None)]
                    extra = " ".join(x for x in (d.get("hj"), d.get("or"), f"[{d['pr']}]" if d.get("pr") else "") if x)
                    if extra:
                        segs.append(("  " + extra, "dim", None))
                    doc.line(*segs)
                label = d.get("p") or d.get("u") or ""
                if label:
                    doc.line(("  「" + label + "」", "tag", None))
                for s in d.get("s", [])[:20]:
                    num += 1
                    doc.line((f"  {num}. ", "num", None), *self._tags(s), (s.get("g", ""), "ko", None))
            self._render_rel(doc, kodict_rows)
            doc.blank()
        elif wiki_rows:
            doc.line(("국어 뜻풀이", "sec", None))
            for r in wiki_rows:
                p = r.data.get("p")
                doc.line(("• " + (r.data.get("pt") or POS_KO.get(p, p or "")), "pos", None))
                for i, s in enumerate(r.data.get("s", [])[:12], 1):
                    doc.line((f"  {i}. ", "num", None), (s.get("g", ""), "ko", None))
            doc.blank()

        # 2) 영어 대응어 (클릭하면 영한 검색)
        en_words: list[tuple[str, str]] = []
        seen = set()
        for en, sense in pairs:
            if en.lower() in seen:
                continue
            seen.add(en.lower())
            en_words.append((en, sense or ""))
        if en_words:
            doc.line(("영어 대응어", "sec", None))
            for en, sense in en_words[:25]:
                segs = [("  · ", "dim", None), (en, "link", en)]
                if sense:
                    segs.append(("  — " + sense, "dim", None))
                doc.line(*segs)
            doc.blank()

        # 3) 영어판: 한국어 단어의 영어 뜻
        if en_rows:
            doc.line(("영어 뜻풀이", "sec", None))
            for r in en_rows:
                p = r.data.get("p")
                doc.line(("• " + POS_KO.get(p, p or ""), "pos", None))
                for i, s in enumerate(r.data.get("s", [])[:12], 1):
                    segs = [(f"  {i}. ", "num", None), *self._tags(s)]
                    if s.get("g"):
                        segs.append((s["g"], "en", None))
                    if s.get("fo"):
                        segs.append(("  → ", "dim", None))
                        segs.append((s["fo"], "link", s["fo"]))
                    doc.line(*segs)

        res.meaning_en = res.meaning
        # 어원 탭: 국어사전의 원어(한자·외래어 원어) 정보
        last = None
        for r in kodict_rows:
            d = r.data
            head = (r.word, d.get("n") or 0)
            if head == last or not (d.get("hj") or d.get("or")):
                continue
            last = head
            res.etymology.line((r.word + (str(head[1]).translate(SUP_DIGITS) if head[1] else ""), "pos", None),
                               ("   " + ("표준국어대사전" if d.get("d") == "표준" else d.get("d", "")), "dim", None))
            res.etymology.line(("원어: " + " ".join(x for x in (d.get("hj"), d.get("or")) if x), "ko", None))
            res.etymology.blank()
        self._render_etymology(rows, res)
        self._render_examples(kodict_rows + [r for r in rows if r not in kodict_rows], res)

    # 전문 분야·고유명사 뜻만 있는 동형어는 뒤로
    SPECIAL_CATS = {"역사", "불교", "가톨릭", "기독교", "종교 일반", "인명", "지명", "책명", "고유명 일반",
                    "민속", "식물", "동물", "광업", "수산업", "임업", "한의", "수의", "북한어", "옛말", "방언"}

    @classmethod
    def _sort_homographs(cls, rows: list[Row], unit_order: dict) -> list[Row]:
        """
        동형어(사과¹, 사과² …)를 자주 쓰일 법한 것부터: 예문이 있고, 뜻이 많고, 전문어가 아닌 것을 앞으로.
        같은 표제어(번호)의 품사 묶음은 붙여 둔다.
        """
        groups: dict[tuple, list[Row]] = {}
        for r in rows:
            groups.setdefault((r.word, r.data.get("n") or 0), []).append(r)

        def score(item):
            (word, n), rs = item
            senses = [s for r in rs for s in r.data.get("s", [])]
            has_ex = any(s.get("ex") for s in senses)
            general = sum(1 for s in senses if not (set(s.get("t") or []) & cls.SPECIAL_CATS))
            redirect = all(s.get("g", "").startswith("→") for s in senses)
            unit = min(unit_order.get(r.data.get("u", ""), 5) for r in rs)
            return (unit, redirect, -(has_ex * 3 + min(general, 6) + 0.2 * min(len(senses), 10)), n)

        out = []
        for _, rs in sorted(groups.items(), key=score):
            out.extend(rs)
        return out

    def _render_rel(self, doc: Doc, rows: list[Row]):
        syn, ant = [], []
        for r in rows:
            for w in r.data.get("syn", []):
                if w not in syn:
                    syn.append(w)
            for w in r.data.get("ant", []):
                if w not in ant:
                    ant.append(w)
        for title, words in (("비슷한말", syn), ("반대말", ant)):
            if not words:
                continue
            segs = [("  " + title + "  ", "sec", None)]
            for j, w in enumerate(words[:10]):
                if j:
                    segs.append((", ", "dim", None))
                segs.append((w, "link", w))
            doc.line(*segs)

    # ---------------------------------------------------------- 어원 / 예문
    def _render_etymology(self, rows: list[Row], res: Result):
        doc = res.etymology
        seen = set()
        for r in rows:
            ety = r.data.get("ety")
            if not ety or ety in seen:
                continue
            seen.add(ety)
            src = "영어판 위키낱말사전" if r.src == "en" else "한국어판 위키낱말사전"
            doc.line((r.word, "pos", None), (f"   {src}", "dim", None))
            doc.line((ety, "en" if r.src == "en" else "ko", None))
            doc.blank()
        if doc.empty:
            doc.line(("이 단어의 어원 정보가 아직 없어요.", "note", None))

    def _render_examples(self, rows: list[Row], res: Result):
        doc = res.examples
        count = 0
        seen = set()
        # 한국어판(번역 포함) 예문을 먼저
        for r in sorted(rows, key=lambda r: r.src != "ko"):
            for s in r.data.get("s", []):
                for ex in s.get("ex", []):
                    text = ex[0]
                    if text in seen or CITATION_RE.match(text):  # '1821, 저자, 책 제목…' 같은 출처 줄은 건너뜀
                        continue
                    seen.add(text)
                    count += 1
                    doc.line((f"{count}. ", "num", None), (text, "ex", None))
                    if len(ex) > 1 and ex[1]:
                        doc.line(("    ", None, None), (ex[1], "tr", None))
                    if s.get("g"):
                        doc.line(("    ", None, None), ("뜻: " + s["g"], "dim", None))
                    doc.blank()
                    if count >= 30:
                        return
        if doc.empty:
            doc.line(("이 단어의 예문이 아직 없어요.", "note", None))
