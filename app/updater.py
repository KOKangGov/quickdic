"""
사전 데이터 자동 업데이트

GitHub 저장소의 'dictionary' 릴리스에 매주 새 사전 파일(quickdic.db.gz)과
version.json 이 올라온다. 앱은 7일마다 version.json 을 확인하고,
새 버전이면 백그라운드로 받아 검증한 뒤 교체한다.
실패하면 기존 사전을 그대로 두고 24시간 뒤 다시 시도한다.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import ssl
import threading
import urllib.request
from datetime import datetime, timedelta

import config

UA = {"User-Agent": f"QuickDic/{config.APP_VERSION}"}
CHECK_INTERVAL = timedelta(days=7)
RETRY_INTERVAL = timedelta(hours=24)


def _urlopen(url: str, timeout: int = 30):
    ctx = ssl.create_default_context()
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout, context=ctx)


def release_url(name: str) -> str:
    return f"https://github.com/{config.GITHUB_REPO}/releases/download/{config.DICT_RELEASE_TAG}/{name}"


def local_db_version(path: str = config.DB_PATH) -> str:
    if not os.path.exists(path):
        return ""
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = con.execute("SELECT value FROM meta WHERE key='version'").fetchone()
            return row[0] if row else ""
        finally:
            con.close()
    except sqlite3.Error:
        return ""


def fetch_remote_info() -> dict:
    with _urlopen(release_url("version.json"), timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_latest_app_version() -> tuple[str, str]:
    """(최신 앱 버전 태그, 릴리스 페이지 주소) — 실패 시 ('', '')"""
    if not config.GITHUB_REPO:
        return "", ""
    try:
        with _urlopen(f"https://api.github.com/repos/{config.GITHUB_REPO}/releases/latest", timeout=15) as r:
            info = json.loads(r.read().decode("utf-8"))
        return info.get("tag_name", ""), info.get("html_url", "")
    except Exception:
        return "", ""


class Updater:
    """
    post(kind, payload) 로 화면 쪽에 상황을 알린다.
      ("status", "문구"), ("progress", 0~100), ("db_ready", 새 파일 경로), ("error", "문구")
    """

    def __init__(self, settings, post):
        self.settings = settings
        self.post = post
        self._busy = threading.Lock()

    # ------------------------------------------------------------- 일정
    def is_due(self) -> bool:
        if not os.path.exists(config.DB_PATH):
            return True
        if not self.settings["auto_update"]:
            return False
        nxt = self.settings["next_update_check"]
        try:
            return not nxt or datetime.now() >= datetime.fromisoformat(nxt)
        except ValueError:
            return True

    def _schedule(self, delta: timedelta):
        self.settings["next_update_check"] = (datetime.now() + delta).isoformat(timespec="seconds")
        self.settings.save()

    def check_async(self, force: bool = False):
        threading.Thread(target=self._run, args=(force,), daemon=True, name="updater").start()

    # ------------------------------------------------------------- 본 작업
    def _run(self, force: bool):
        if not self._busy.acquire(blocking=False):
            return
        try:
            if not config.GITHUB_REPO:
                self.post("error", "사전 서버 주소가 설정되지 않았어요 (개발 모드)")
                return
            if not force and not self.is_due():
                return
            self.post("status", "사전 업데이트 확인 중…")
            info = fetch_remote_info()
            self.settings["last_update_check"] = datetime.now().isoformat(timespec="seconds")
            remote = info.get("version", "")
            local = local_db_version()
            if remote and remote == local:
                self._schedule(CHECK_INTERVAL)
                self.post("status", f"사전이 최신이에요 ({local})")
                return
            new_path = self._download(info)
            self._schedule(CHECK_INTERVAL)
            self.post("db_ready", new_path)
        except Exception as e:  # 네트워크 끊김 등 — 기존 사전 유지, 24시간 뒤 재시도
            self._schedule(RETRY_INTERVAL)
            msg = "사전 업데이트 실패 — 내일 다시 시도해요" if os.path.exists(config.DB_PATH) \
                else "사전 데이터를 받지 못했어요. 인터넷 연결을 확인한 뒤 '설정' → '지금 업데이트 확인'을 눌러 주세요"
            self.post("error", f"{msg} ({type(e).__name__})")
        finally:
            self._busy.release()

    def _download(self, info: dict) -> str:
        gz_tmp = config.DB_PATH + ".download.gz"
        db_new = config.DB_PATH + ".new"
        total = int(info.get("gz_size") or 0)
        sha = hashlib.sha256()
        done = 0
        last_pct = -1
        with _urlopen(release_url(info.get("file", "quickdic.db.gz")), timeout=60) as r, open(gz_tmp, "wb") as f:
            total = total or int(r.headers.get("Content-Length") or 0)
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                sha.update(chunk)
                done += len(chunk)
                if total:
                    pct = int(done * 100 / total)
                    if pct != last_pct:
                        last_pct = pct
                        self.post("progress", pct)
                        self.post("status", f"사전 내려받는 중… {done/1048576:,.0f} / {total/1048576:,.0f} MB")
        expected = info.get("gz_sha256")
        if expected and sha.hexdigest() != expected:
            os.remove(gz_tmp)
            raise ValueError("파일 검증 실패(sha256)")

        self.post("status", "사전 압축 푸는 중…")
        with gzip.open(gz_tmp, "rb") as src, open(db_new, "wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
        os.remove(gz_tmp)

        # 열어서 정상인지 확인
        con = sqlite3.connect(f"file:{db_new}?mode=ro", uri=True)
        try:
            ver = con.execute("SELECT value FROM meta WHERE key='version'").fetchone()
            con.execute("SELECT count(*) FROM entries WHERE key='the'").fetchone()
        finally:
            con.close()
        if not ver:
            raise ValueError("사전 파일 형식 오류")
        return db_new


def install_new_db(new_path: str) -> None:
    """(사전 연결을 닫은 뒤 호출) 새 파일로 교체 — 원자적 교체"""
    os.replace(new_path, config.DB_PATH)
