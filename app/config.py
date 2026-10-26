"""설정·경로·저장 데이터(기록, 단어장) 관리"""

from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime

APP_NAME = "QuickDic"

# GitHub Actions 가 exe 를 만들 때 build_info.py 를 자동 생성해 저장소 주소와 버전을 넣는다.
try:
    from build_info import APP_VERSION, GITHUB_REPO  # type: ignore
except Exception:  # 개발 중 직접 실행할 때
    APP_VERSION = "dev"
    GITHUB_REPO = os.environ.get("QUICKDIC_REPO", "")

DICT_RELEASE_TAG = "dictionary"


def _base_dir(env: str, fallback: str) -> str:
    root = os.environ.get(env) if sys.platform == "win32" else None
    root = root or os.path.join(os.path.expanduser("~"), fallback)
    path = os.path.join(root, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


CONFIG_DIR = _base_dir("APPDATA", ".config")
DATA_DIR = _base_dir("LOCALAPPDATA", ".local/share")
DB_PATH = os.path.join(DATA_DIR, "quickdic.db")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")
HISTORY_PATH = os.path.join(CONFIG_DIR, "history.json")
BOOKMARKS_PATH = os.path.join(CONFIG_DIR, "bookmarks.json")


def resource_path(rel: str) -> str:
    """PyInstaller 로 묶인 exe 안의 파일 경로"""
    base = getattr(sys, "_MEIPASS", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    return os.path.join(base, rel)


PORTALS = {
    "네이버 영어사전": "https://en.dict.naver.com/#/search?query={q}",
    "다음 사전": "https://dic.daum.net/search.do?q={q}",
    "Cambridge": "https://dictionary.cambridge.org/dictionary/english/{q}",
    "Oxford Learner's": "https://www.oxfordlearnersdictionaries.com/search/english/?q={q}",
    "Merriam-Webster": "https://www.merriam-webster.com/dictionary/{q}",
    "Wiktionary": "https://en.wiktionary.org/wiki/{q}",
}
# 한글 검색어일 때 쓰는 주소 (영어 전용 사전은 네이버 국어/영어로 대체)
PORTALS_KO = {
    "네이버 영어사전": "https://en.dict.naver.com/#/search?query={q}",
    "다음 사전": "https://dic.daum.net/search.do?q={q}",
}

DEFAULTS = {
    "bar_x": None,          # 검색 막대 위치(화면 좌표)
    "bar_y": None,
    "width": 420,           # 창 너비
    "panel_height": 520,    # 결과창 높이
    "topmost": True,
    "opacity": 100,
    "hotkey": "Alt+Q",
    "portal": "네이버 영어사전",
    "show_english": False,
    "restore_clipboard": True,
    "auto_hide": True,      # 다른 곳을 누르면 결과창 자동으로 닫기
    "auto_update": True,
    "last_update_check": "",
    "next_update_check": "",
    "font_size": 11,
    "welcomed": False,
}


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


class Settings:
    def __init__(self):
        self._lock = threading.Lock()
        self.data = dict(DEFAULTS)
        saved = _read_json(SETTINGS_PATH, {})
        for old_key in ("geometry", "expanded_height", "collapsed", "auto_collapse"):
            saved.pop(old_key, None)
        self.data.update(saved)

    def __getitem__(self, k):
        return self.data.get(k, DEFAULTS.get(k))

    def __setitem__(self, k, v):
        self.data[k] = v

    def save(self):
        with self._lock:
            try:
                _write_json(SETTINGS_PATH, self.data)
            except OSError:
                pass


class History:
    LIMIT = 10

    def __init__(self):
        self.items: list[str] = _read_json(HISTORY_PATH, [])

    def add(self, word: str):
        word = word.strip()
        if not word:
            return
        self.items = [w for w in self.items if w.lower() != word.lower()]
        self.items.insert(0, word)
        self.items = self.items[: self.LIMIT]
        try:
            _write_json(HISTORY_PATH, self.items)
        except OSError:
            pass

    def clear(self):
        self.items = []
        try:
            _write_json(HISTORY_PATH, self.items)
        except OSError:
            pass


class Bookmarks:
    def __init__(self):
        self.items: list[dict] = _read_json(BOOKMARKS_PATH, [])

    def has(self, word: str) -> bool:
        return any(b["word"].lower() == word.lower() for b in self.items)

    def toggle(self, word: str, summary: str) -> bool:
        if self.has(word):
            self.remove(word)
            return False
        self.items.insert(0, {"word": word, "meaning": summary,
                              "added": datetime.now().strftime("%Y-%m-%d %H:%M")})
        self._save()
        return True

    def remove(self, word: str):
        self.items = [b for b in self.items if b["word"].lower() != word.lower()]
        self._save()

    def _save(self):
        try:
            _write_json(BOOKMARKS_PATH, self.items)
        except OSError:
            pass

    def export_csv(self, path: str):
        import csv
        with open(path, "w", newline="", encoding="utf-8-sig") as f:  # 엑셀에서 한글 안 깨지게
            w = csv.writer(f)
            w.writerow(["단어", "뜻", "저장일"])
            for b in self.items:
                w.writerow([b["word"], b.get("meaning", ""), b.get("added", "")])
