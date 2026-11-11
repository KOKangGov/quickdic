"""
문장 번역 (인터넷 필요)

  · 단어는 오프라인 사전으로, 문장은 번역 서비스로 보낸다.
  · 기본은 키 없이 쓰는 무료 번역(MyMemory). 설정에서 내 API 키를 넣으면
    DeepL · 네이버 파파고 · Google 번역으로 바꿀 수 있다.
  · 외부 패키지 없이 표준 라이브러리(urllib)만 쓴다.
"""

from __future__ import annotations

import json
import re
import ssl
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass

MAX_CHARS = 3000          # 한 번에 번역하는 최대 글자 수 (너무 긴 글은 앞부분만)
TIMEOUT = 15

# 번역 엔진: 설정 화면에 보이는 이름과 필요한 설정값
ENGINES = {
    "mymemory": {"name": "무료 번역 (MyMemory · 키 필요 없음)", "short": "MyMemory", "keys": []},
    "deepl": {"name": "DeepL (내 API 키)", "short": "DeepL", "keys": ["deepl_key"]},
    "papago": {"name": "네이버 파파고 (내 API 키)", "short": "파파고", "keys": ["papago_id", "papago_secret"]},
    "google": {"name": "Google 번역 (내 API 키)", "short": "Google", "keys": ["google_key"]},
}

LANG_NAMES = {"ko": "한국어", "en": "영어", "ja": "일본어", "zh": "중국어", "ru": "러시아어"}


class TranslateError(Exception):
    """사용자에게 그대로 보여 줄 수 있는 한국어 오류 메시지"""


@dataclass
class Translation:
    source: str          # 번역한 원문(정리된 것)
    text: str            # 번역 결과
    src: str             # 원문 언어 코드
    tgt: str             # 번역 언어 코드
    engine: str          # ENGINES 키
    truncated: bool = False

    @property
    def engine_name(self) -> str:
        return ENGINES.get(self.engine, {}).get("short", self.engine)


# ---------------------------------------------------------------------- 글 정리·판단

def normalize(text: str) -> str:
    """드래그로 잡힌 글을 번역용으로 정리: 줄바꿈 하이픈 잇기, 문단은 남기고 줄 안 공백은 하나로."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text).replace("­", "")
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)        # 'ephem-\neral'
    paras = re.split(r"\n\s*\n", text.replace("\r", ""))
    paras = [" ".join(p.split()) for p in paras]
    return "\n\n".join(p for p in paras if p).strip()


_HANGUL = re.compile(r"[가-힣ㄱ-ㆎ]")
_KANA = re.compile(r"[぀-ヿ]")
_HAN = re.compile(r"[一-鿿]")
_CYR = re.compile(r"[Ѐ-ӿ]")
_LATIN = re.compile(r"[A-Za-zÀ-ɏ]")


def detect_lang(text: str) -> str:
    """글자 종류로 원문 언어를 어림한다 (ko / ja / zh / ru / en)."""
    ko, kana, han = len(_HANGUL.findall(text)), len(_KANA.findall(text)), len(_HAN.findall(text))
    cyr, lat = len(_CYR.findall(text)), len(_LATIN.findall(text))
    if ko and ko >= 0.3 * (lat + kana + han + cyr):
        return "ko"
    if kana:
        return "ja"
    if han and han >= lat:
        return "zh"
    if cyr and cyr >= lat:
        return "ru"
    return "en"


def target_for(src: str) -> str:
    """한국어는 영어로, 나머지는 한국어로"""
    return "en" if src == "ko" else "ko"


_SENT_END = re.compile(r"[.!?。？！]\s+\S")


def looks_like_sentence(text: str) -> bool:
    """사전 대신 바로 번역할 만한 글인지 (단어·짧은 숙어는 사전으로)."""
    t = normalize(text)
    if not t:
        return False
    words = t.split()
    if "\n" in t or len(t) > 40 or len(words) >= 4:
        return True
    return len(words) >= 2 and bool(_SENT_END.search(t))


def split_chunks(text: str, max_bytes: int) -> list[str]:
    """번역 서비스 한 번 요청 크기(바이트)에 맞게 문장 단위로 나눈다."""
    def size(s):
        return len(s.encode("utf-8"))

    pieces: list[str] = []
    for para in text.split("\n\n"):
        for sent in re.split(r"(?<=[.!?。？！])\s+", para):
            if not sent:
                continue
            while size(sent) > max_bytes:          # 한 문장이 너무 길면 쉼표·공백에서 자름
                cut = sent.encode("utf-8")[:max_bytes].decode("utf-8", "ignore")
                pos = max(cut.rfind(", "), cut.rfind(" "))
                if pos > len(cut) // 3:
                    cut = cut[:pos + 1]
                pieces.append(cut.strip())
                sent = sent[len(cut):].strip()
            if sent:
                pieces.append(sent)
        pieces.append("\n\n")
    if pieces and pieces[-1] == "\n\n":
        pieces.pop()

    chunks: list[str] = []
    cur = ""
    for p in pieces:
        if p == "\n\n":
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append("\n\n")
            continue
        joined = f"{cur} {p}" if cur else p
        if size(joined) <= max_bytes:
            cur = joined
        else:
            if cur:
                chunks.append(cur)
            cur = p
    if cur:
        chunks.append(cur)
    return chunks


def _join(chunks: list[str], outs: list[str]) -> str:
    text = ""
    for c, o in zip(chunks, outs):
        if c == "\n\n":
            text = text.rstrip() + "\n\n"
        else:
            text += (" " if text and not text.endswith("\n") else "") + o.strip()
    return text.strip()


# ---------------------------------------------------------------------- 인터넷 요청

def _request(url: str, *, data: bytes | None = None, headers: dict | None = None) -> dict:
    h = {"User-Agent": "QuickDic", "Accept": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl.create_default_context()) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "ignore")[:300]
        except Exception:
            body = ""
        if e.code in (401, 403):
            raise TranslateError("API 키가 맞지 않거나 사용 권한이 없어요. 설정에서 키를 확인해 주세요.") from e
        if e.code in (429, 456):
            raise TranslateError("번역 사용량 한도를 넘었어요. 잠시 뒤에 다시 하거나 다른 번역 서비스를 골라 주세요.") from e
        raise TranslateError(f"번역 서비스 오류 ({e.code}) {body}".strip()) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise TranslateError("인터넷에 연결되지 않아 번역하지 못했어요. 단어는 오프라인 사전으로 찾을 수 있어요.") from e
    except ValueError as e:
        raise TranslateError("번역 서비스의 응답을 읽지 못했어요.") from e


def _code(lang: str, engine: str) -> str:
    if lang == "zh":
        return {"deepl": "ZH", "google": "zh-CN", "papago": "zh-CN", "mymemory": "zh-CN"}[engine]
    if engine == "deepl":
        return "EN-US" if lang == "en" else lang.upper()
    return lang


def _mymemory(text: str, src: str, tgt: str, settings) -> str:
    chunks = split_chunks(text, 450)          # MyMemory 는 한 번에 500바이트까지
    outs = []
    for c in chunks:
        if c == "\n\n":
            outs.append("")
            continue
        q = {"q": c, "langpair": f"{_code(src, 'mymemory')}|{_code(tgt, 'mymemory')}"}
        email = (settings["mymemory_email"] or "").strip()
        if email:
            q["de"] = email
        d = _request("https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(q))
        out = (d.get("responseData") or {}).get("translatedText") or ""
        status = str(d.get("responseStatus", "200"))
        if d.get("quotaFinished") or "MYMEMORY WARNING" in out or status == "429":
            raise TranslateError("오늘 무료 번역 사용량을 다 썼어요. 내일 다시 쓰거나, 설정에서 이메일을 넣으면 "
                                 "하루 사용량이 10배로 늘어요. (또는 내 API 키로 다른 번역 서비스를 골라 주세요)")
        if status != "200":
            raise TranslateError(f"무료 번역 서비스 오류: {d.get('responseDetails') or status}")
        outs.append(out)
    return _join(chunks, outs)


def _deepl(text: str, src: str, tgt: str, settings) -> str:
    key = (settings["deepl_key"] or "").strip()
    if not key:
        raise TranslateError("설정에서 DeepL API 키를 넣어 주세요.")
    host = "https://api-free.deepl.com" if key.endswith(":fx") else "https://api.deepl.com"
    body = json.dumps({"text": [text], "target_lang": _code(tgt, "deepl")}).encode("utf-8")
    d = _request(host + "/v2/translate", data=body,
                 headers={"Authorization": f"DeepL-Auth-Key {key}", "Content-Type": "application/json"})
    return "".join(t.get("text", "") for t in d.get("translations", []))


def _papago(text: str, src: str, tgt: str, settings) -> str:
    cid, secret = (settings["papago_id"] or "").strip(), (settings["papago_secret"] or "").strip()
    if not cid or not secret:
        raise TranslateError("설정에서 파파고 Client ID 와 Client Secret 을 넣어 주세요.")
    body = urllib.parse.urlencode({"source": _code(src, "papago"), "target": _code(tgt, "papago"),
                                   "text": text}).encode("utf-8")
    d = _request("https://papago.apigw.ntruss.com/nmt/v1/translation", data=body, headers={
        "X-NCP-APIGW-API-KEY-ID": cid, "X-NCP-APIGW-API-KEY": secret,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
    return d.get("message", {}).get("result", {}).get("translatedText", "")


def _google(text: str, src: str, tgt: str, settings) -> str:
    key = (settings["google_key"] or "").strip()
    if not key:
        raise TranslateError("설정에서 Google 번역 API 키를 넣어 주세요.")
    body = urllib.parse.urlencode({"q": text, "target": _code(tgt, "google"), "format": "text"}).encode("utf-8")
    d = _request("https://translation.googleapis.com/language/translate/v2?key=" + urllib.parse.quote(key),
                 data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    return "".join(t.get("translatedText", "") for t in d.get("data", {}).get("translations", []))


_ENGINE_FUNCS = {"mymemory": _mymemory, "deepl": _deepl, "papago": _papago, "google": _google}


# ---------------------------------------------------------------------- 바깥에서 쓰는 곳

class Translator:
    def __init__(self, settings):
        self.settings = settings
        self._cache: OrderedDict[tuple, Translation] = OrderedDict()

    @property
    def engine(self) -> str:
        e = self.settings["translate_engine"]
        return e if e in ENGINES else "mymemory"

    def translate(self, raw: str) -> Translation:
        """시간이 걸리므로 화면 스레드가 아닌 곳에서 부를 것"""
        text = normalize(raw)
        if not text:
            raise TranslateError("번역할 글이 없어요.")
        truncated = len(text) > MAX_CHARS
        if truncated:
            text = text[:MAX_CHARS]
        src = detect_lang(text)
        tgt = target_for(src)
        engine = self.engine
        key = (engine, src, tgt, text)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        out = _ENGINE_FUNCS[engine](text, src, tgt, self.settings).strip()
        if not out:
            raise TranslateError("번역 결과가 비어 있어요. 잠시 뒤 다시 해 보세요.")
        res = Translation(text, out, src, tgt, engine, truncated)
        self._cache[key] = res
        while len(self._cache) > 60:
            self._cache.popitem(last=False)
        return res


def web_url(text: str) -> str:
    """파파고 웹 번역기에서 열기"""
    t = normalize(text)[:MAX_CHARS]
    src = detect_lang(t)
    code = {"zh": "zh-CN"}
    return ("https://papago.naver.com/?" +
            urllib.parse.urlencode({"sk": code.get(src, src), "tk": target_for(src), "st": t},
                                   quote_via=urllib.parse.quote))
