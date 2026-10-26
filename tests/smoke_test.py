"""exe 를 만들기 전에 기본 동작을 점검 (GitHub Actions Windows 환경에서 실행)"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import winsys  # noqa: E402
from dictdb import Dictionary, clean_query  # noqa: E402

db = Dictionary(sys.argv[1])

r = db.lookup("Ephemeral,")
assert r.found and r.headword == "ephemeral", r
assert "덧없는" in r.meaning.plain_text()
assert "Greek" in r.etymology.plain_text()
assert db.lookup("apples").found
r = db.lookup("사과를")
assert r.found and "apple" in r.meaning.plain_text()
assert not db.lookup("zzzzqq").found
assert clean_query("  “fleeting,”\n") == "fleeting"
assert winsys.parse_hotkey("Alt+Q") == (winsys.MOD_ALT, ord("Q"))
assert winsys.parse_hotkey("Ctrl+Shift+Q") == (winsys.MOD_CONTROL | winsys.MOD_SHIFT, ord("Q"))
assert winsys.parse_hotkey("F8") == (0, 0x77)
print("사전 검색 OK")

if winsys.IS_WIN:
    ok = winsys.set_clipboard_text("QuickDic 클립보드 테스트")
    print("클립보드 쓰기:", ok, "/ 읽기:", winsys.get_clipboard_text())
    hk = winsys.HotkeyListener("Ctrl+Alt+F12", lambda: None)
    hk.start()
    hk.ready.wait(3)
    print("전역 단축키 등록:", hk.ok)
    hk.stop()
    hk.join(3)
    print("자동 실행 확인:", winsys.get_autostart())
print("점검 완료")
