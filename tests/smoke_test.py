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

if db.lookup("아름답다").found:  # 국내 사전(표준국어대사전 샘플)을 넣어 만든 경우
    r = db.lookup("사과")
    t = r.meaning.plain_text()
    assert t.startswith("국어 뜻풀이"), t          # 한글 뜻풀이가 맨 위
    assert "沙果" in t and "謝過" in t and "사과¹" in t
    assert "<FL>" not in t and t.index("국어 뜻풀이") < t.index("영어 대응어")
    assert "사죄" in t
    assert "사과를 깎다" in r.examples.plain_text()
    assert "인용 예문" not in r.examples.plain_text()  # 출처 달린 인용 예문은 저작권 때문에 제외
    assert "沙果" in r.etymology.plain_text()
    assert db.lookup("가게 기둥에 입춘").found and db.lookup("가게기둥에입춘").found
    assert db.lookup("누리소통망").found and "(정보·통신)" in db.lookup("누리소통망").meaning.plain_text()
    assert t.count("사과나무의 열매") == 1, "우리말샘 중복이 걸러지지 않음"
    # 오타 추천
    r = db.lookup("아름답따")
    assert not r.found and r.suggestions[0] == "아름답다", r
    assert "아름답다" in db.similar("아름답따")
    assert "됐다" in db.similar("됬다")
    assert "사과" in db.similar("tkrhk")            # 영문 자판으로 친 한글
    r = db.lookup("사괴")
    assert not r.found and "사과" in r.suggestions, r
    r = db.lookup("tkrhk")                           # 영문 자판 → 한글로 바로 찾기
    assert r.found and r.headword == "사과" and r.redirected_from == "tkrhk", r
assert "ephemeral" in db.similar("ephemral")
assert "ephemeral" in db.similar("ephmeeral")
assert "apple" in db.lookup("appel").suggestions
assert "apple" in db.similar("ㅁㅔㅔㅣㄷ")            # 한글 자판으로 친 영어
r = db.lookup("ㅁㅔㅔㅣㄷ")
assert r.found and r.headword == "apple", r
r = db.lookup("apples")
assert r.meaning.plain_text().lstrip().startswith("▶ 원형 apple"), r.meaning.plain_text()
t = r.meaning.plain_text()
assert "사과" in t.split("\n")[2], t                   # 원형의 한국어 뜻이 바로 아래
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
