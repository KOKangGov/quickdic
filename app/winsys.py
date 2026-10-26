"""
Windows 연동 모듈 — 외부 패키지 없이 ctypes 로 Windows API 를 직접 호출한다.

  * 전역 단축키(Alt+Q 등) 등록 : RegisterHotKey
  * 선택 영역 복사            : Ctrl+C 키 입력 흉내 + 클립보드 읽기/복원
  * 발음 듣기(TTS)            : Windows 내장 음성(System.Speech) — 오프라인
  * Windows 시작 시 자동 실행 : 레지스트리 HKCU\\...\\Run
  * 중복 실행 방지            : 이름 있는 뮤텍스

Windows 가 아닌 환경(개발·테스트용)에서는 모든 기능이 조용히 비활성화된다.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

IS_WIN = sys.platform == "win32"

if IS_WIN:
    import ctypes
    from ctypes import wintypes as wt

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    HANDLE = ctypes.c_void_p
    ULONG_PTR = ctypes.c_size_t

    user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
    user32.RegisterHotKey.restype = wt.BOOL
    user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wt.BOOL
    user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
    user32.GetMessageW.restype = wt.BOOL
    user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.PostThreadMessageW.restype = wt.BOOL
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.keybd_event.argtypes = [wt.BYTE, wt.BYTE, wt.DWORD, ULONG_PTR]
    user32.keybd_event.restype = None
    user32.GetClipboardSequenceNumber.argtypes = []
    user32.GetClipboardSequenceNumber.restype = wt.DWORD
    user32.OpenClipboard.argtypes = [wt.HWND]
    user32.OpenClipboard.restype = wt.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wt.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wt.BOOL
    user32.GetClipboardData.argtypes = [wt.UINT]
    user32.GetClipboardData.restype = HANDLE
    user32.SetClipboardData.argtypes = [wt.UINT, HANDLE]
    user32.SetClipboardData.restype = HANDLE
    user32.IsClipboardFormatAvailable.argtypes = [wt.UINT]
    user32.IsClipboardFormatAvailable.restype = wt.BOOL
    user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
    user32.FindWindowW.restype = wt.HWND
    user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wt.BOOL
    user32.SetForegroundWindow.argtypes = [wt.HWND]
    user32.SetForegroundWindow.restype = wt.BOOL
    kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = HANDLE
    kernel32.GlobalLock.argtypes = [HANDLE]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [HANDLE]
    kernel32.GlobalUnlock.restype = wt.BOOL
    kernel32.GlobalFree.argtypes = [HANDLE]
    kernel32.GlobalFree.restype = HANDLE
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wt.DWORD
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
    kernel32.CreateMutexW.restype = HANDLE

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN = 0x10, 0x11, 0x12, 0x5B, 0x5C
KEYEVENTF_KEYUP = 0x2
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x2
CREATE_NO_WINDOW = 0x08000000

# 설정 화면에서 고를 수 있는 단축키 목록
HOTKEY_CHOICES = ["Alt+Q", "Ctrl+Alt+Q", "Ctrl+Shift+Q", "Alt+W", "Ctrl+Alt+D", "F8", "F9"]


def parse_hotkey(text: str) -> tuple[int, int]:
    """'Ctrl+Alt+Q' → (수정키 비트, 가상키 코드)"""
    mods, vk = 0, 0
    for part in text.replace(" ", "").split("+"):
        p = part.lower()
        if p in ("alt",):
            mods |= MOD_ALT
        elif p in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif p == "shift":
            mods |= MOD_SHIFT
        elif p in ("win", "windows"):
            mods |= MOD_WIN
        elif len(p) == 1 and p.isalnum():
            vk = ord(p.upper())
        elif p.startswith("f") and p[1:].isdigit() and 1 <= int(p[1:]) <= 24:
            vk = 0x70 + int(p[1:]) - 1
        elif p == "space":
            vk = 0x20
    return mods, vk


# ----------------------------------------------------------------- 전역 단축키

class HotkeyListener(threading.Thread):
    """별도 스레드에서 RegisterHotKey 메시지 루프를 돈다."""

    def __init__(self, hotkey: str, on_hotkey):
        super().__init__(daemon=True, name="hotkey")
        self.hotkey = hotkey
        self.on_hotkey = on_hotkey
        self.thread_id = 0
        self.ok = False
        self.ready = threading.Event()

    def run(self):
        if not IS_WIN:
            self.ready.set()
            return
        self.thread_id = kernel32.GetCurrentThreadId()
        mods, vk = parse_hotkey(self.hotkey)
        self.ok = bool(vk) and bool(user32.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, vk))
        self.ready.set()
        if not self.ok:
            return
        msg = wt.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    if mods & (MOD_ALT | MOD_WIN):
                        _mask_menu_key()
                    try:
                        self.on_hotkey()
                    except Exception:
                        pass
        finally:
            user32.UnregisterHotKey(None, 1)

    def stop(self):
        if IS_WIN and self.thread_id:
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)


def _mask_menu_key():
    """
    Alt 를 누른 채 단축키를 쓰면, Alt 를 뗄 때 상대 프로그램이 메뉴/리본(Word 의 단축키 안내 등)을
    여는 문제가 있다. 아무 기능 없는 가상키(0xE8)를 한 번 눌러 'Alt 단독 입력'으로 보이지 않게 한다.
    """
    user32.keybd_event(0xE8, 0, 0, 0)
    user32.keybd_event(0xE8, 0, KEYEVENTF_KEYUP, 0)


# ----------------------------------------------------------------- 클립보드

def _open_clipboard(retries: int = 10) -> bool:
    for _ in range(retries):
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.02)
    return False


def get_clipboard_text() -> str | None:
    if not IS_WIN:
        return None
    if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
        return None
    if not _open_clipboard():
        return None
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = kernel32.GlobalLock(h)
        if not p:
            return None
        try:
            return ctypes.wstring_at(p)
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text: str) -> bool:
    if not IS_WIN or text is None:
        return False
    data = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(data)
    if not _open_clipboard():
        return False
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not h:
            return False
        p = kernel32.GlobalLock(h)
        ctypes.memmove(p, data, size)
        kernel32.GlobalUnlock(h)
        if not user32.SetClipboardData(CF_UNICODETEXT, h):
            kernel32.GlobalFree(h)
            return False
        return True
    finally:
        user32.CloseClipboard()


def _key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def copy_selection(hotkey: str = "Alt+Q", restore: bool = True, timeout: float = 0.7) -> str | None:
    """
    지금 다른 프로그램에서 선택(드래그)된 글자를 가져온다.
    Ctrl+C 를 대신 눌러 복사한 뒤 클립보드에서 읽고, 원래 클립보드 내용을 되돌려 놓는다.
    선택된 글자가 없으면 None.
    """
    if not IS_WIN:
        return None
    # 사용자가 단축키에서 손을 뗄 때까지 잠깐 기다림 (Alt 가 눌린 채로 Ctrl+C 를 보내면 Ctrl+Alt+C 가 됨)
    _, hk_vk = parse_hotkey(hotkey)
    watch = [VK_MENU, VK_CONTROL, VK_SHIFT, VK_LWIN, VK_RWIN] + ([hk_vk] if hk_vk else [])
    deadline = time.time() + 1.5
    while time.time() < deadline and any(_key_down(k) for k in watch):
        time.sleep(0.015)
    time.sleep(0.03)

    old_text = get_clipboard_text() if restore else None
    seq = user32.GetClipboardSequenceNumber()

    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(ord("C"), 0, 0, 0)
    user32.keybd_event(ord("C"), 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

    deadline = time.time() + timeout
    while time.time() < deadline:
        if user32.GetClipboardSequenceNumber() != seq:
            break
        time.sleep(0.02)
    else:
        return None  # 선택된 글자가 없었음

    time.sleep(0.03)
    text = get_clipboard_text()
    if restore and old_text is not None:
        set_clipboard_text(old_text)
    return text


# ----------------------------------------------------------------- 발음 (TTS)

_TTS_SCRIPT = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -like ($env:QD_TTS_LANG + '*') } | Select-Object -First 1
if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }
$s.Rate = -1
$s.Speak($env:QD_TTS_TEXT)
"""

_tts_proc: subprocess.Popen | None = None


def speak(text: str, lang: str = "en") -> bool:
    """Windows 내장 음성으로 읽어 준다(인터넷 불필요). lang: 'en' 또는 'ko'."""
    global _tts_proc
    if not IS_WIN or not text:
        return False
    try:
        if _tts_proc and _tts_proc.poll() is None:
            _tts_proc.kill()
    except Exception:
        pass
    env = dict(os.environ, QD_TTS_TEXT=text[:300], QD_TTS_LANG=lang)
    try:
        _tts_proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _TTS_SCRIPT],
            env=env, creationflags=CREATE_NO_WINDOW,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


# ----------------------------------------------------------------- 자동 실행

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pyw):
        exe = pyw
    return f'"{exe}" "{os.path.abspath(sys.argv[0])}"'


def set_autostart(enabled: bool) -> bool:
    if not IS_WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, "QuickDic", 0, winreg.REG_SZ, _launch_command())
            else:
                try:
                    winreg.DeleteValue(k, "QuickDic")
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def get_autostart() -> bool:
    if not IS_WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "QuickDic")
            return True
    except OSError:
        return False


# ----------------------------------------------------------------- 기타

_mutex = None


def acquire_single_instance(window_title: str) -> bool:
    """이미 실행 중이면 그 창을 앞으로 가져오고 False."""
    global _mutex
    if not IS_WIN:
        return True
    _mutex = kernel32.CreateMutexW(None, False, "Local\\QuickDic_SingleInstance")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        hwnd = user32.FindWindowW(None, window_title)
        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
        return False
    return True


def enable_dpi_awareness():
    if not IS_WIN:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def open_url(url: str):
    import webbrowser
    webbrowser.open(url, new=2)
