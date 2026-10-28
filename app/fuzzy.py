"""
오타 교정 도우미 (화면·DB 와 무관한 순수 함수)

- 한글은 자모(초성·중성·종성) 단위로 비교해 '사괴 → 사과', '됬다 → 됐다' 같은 오타를 잡는다.
- 한/영 자판을 잘못 두고 친 경우('tkrhk' → '사과', 'ㅁㅔㅔㅣㄷ' → 'apple')를 바꿔 본다.
- 편집 거리는 글자 바꿈·빠짐·더함·이웃 글자 순서 바뀜(transposition)을 모두 1로 센다.
"""

from __future__ import annotations

SBASE, LCOUNT, VCOUNT, TCOUNT = 0xAC00, 19, 21, 28
NCOUNT = VCOUNT * TCOUNT
CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
JONG = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"  # 0번은 받침 없음


def is_syllable(ch: str) -> bool:
    return 0xAC00 <= ord(ch) <= 0xD7A3


def split_syllable(ch: str) -> tuple[int, int, int]:
    code = ord(ch) - SBASE
    return code // NCOUNT, (code % NCOUNT) // TCOUNT, code % TCOUNT


def join_syllable(l: int, v: int, t: int = 0) -> str:
    return chr(SBASE + (l * VCOUNT + v) * TCOUNT + t)


def to_jamo(text: str) -> str:
    """'사과' → 'ㅅㅏㄱㅘ' (받침 없는 자리는 생략). 비교용."""
    out = []
    for ch in text:
        if is_syllable(ch):
            l, v, t = split_syllable(ch)
            out.append(CHO[l])
            out.append(JUNG[v])
            if t:
                out.append(JONG[t])
        else:
            out.append(ch)
    return "".join(out)


# ------------------------------------------------------------------ 편집 거리

def osa_distance(a: str, b: str, limit: int = 3) -> int:
    """Optimal String Alignment 거리. limit 를 넘으면 limit+1 을 돌려준다(빨리 끝냄)."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > limit:
        return limit + 1
    if la == 0 or lb == 0:
        return max(la, lb)
    prev2 = None
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        ai = a[i - 1]
        best = cur[0]
        for j in range(1, lb + 1):
            cost = 0 if ai == b[j - 1] else 1
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if prev2 is not None and i > 1 and j > 1 and ai == b[j - 2] and a[i - 2] == b[j - 1]:
                v = min(v, prev2[j - 2] + 1)
            cur[j] = v
            if v < best:
                best = v
        if best > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[lb]


def ko_distance(a: str, b: str, limit: int = 3) -> int:
    """한글은 자모 단위 거리."""
    return osa_distance(to_jamo(a), to_jamo(b), limit)


# ------------------------------------------------------------------ 후보 만들기

EN_LETTERS = "abcdefghijklmnopqrstuvwxyz-' "


def edits1_en(word: str) -> set[str]:
    splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
    out = set()
    for a, b in splits:
        if b:
            out.add(a + b[1:])  # 빠짐
            if len(b) > 1:
                out.add(a + b[1] + b[0] + b[2:])  # 순서 바뀜
            for c in EN_LETTERS:
                out.add(a + c + b[1:])  # 바꿈
        for c in EN_LETTERS:
            out.add(a + c + b)  # 더함
    out.discard(word)
    return {w for w in out if w.strip() == w and w}


def edits1_ko(word: str) -> set[str]:
    """음절마다 초성·중성·종성 하나를 바꾸거나, 음절을 빼거나, 이웃 음절 순서를 바꾼 후보."""
    out = set()
    n = len(word)
    for i, ch in enumerate(word):
        a, b = word[:i], word[i + 1:]
        if n > 1:
            out.add(a + b)
        if i + 1 < n:
            out.add(a + word[i + 1] + ch + word[i + 2:])
        if not is_syllable(ch):
            continue
        l, v, t = split_syllable(ch)
        for l2 in range(LCOUNT):
            if l2 != l:
                out.add(a + join_syllable(l2, v, t) + b)
        for v2 in range(VCOUNT):
            if v2 != v:
                out.add(a + join_syllable(l, v2, t) + b)
        for t2 in range(TCOUNT):
            if t2 != t:
                out.add(a + join_syllable(l, v, t2) + b)
        # 받침이 다음 글자 초성으로 넘어간 경우 ('갑아' ↔ '가바')
        if i + 1 < n and is_syllable(word[i + 1]):
            l3, v3, t3 = split_syllable(word[i + 1])
            if t and l3 == 11:  # 다음 글자 초성이 ㅇ
                cho = CHO.find(JONG[t])
                if cho >= 0:
                    out.add(a + join_syllable(l, v, 0) + join_syllable(cho, v3, t3) + word[i + 2:])
            if not t:
                jong = JONG.find(CHO[l3])
                if jong > 0:
                    out.add(a + join_syllable(l, v, jong) + join_syllable(11, v3, t3) + word[i + 2:])
    out.discard(word)
    return out


# ------------------------------------------------------------------ 한/영 자판 바꾸기

# 두벌식 자판: 영문 키 → 자모
KEY2JAMO = {
    "q": "ㅂ", "w": "ㅈ", "e": "ㄷ", "r": "ㄱ", "t": "ㅅ", "y": "ㅛ", "u": "ㅕ", "i": "ㅑ", "o": "ㅐ", "p": "ㅔ",
    "a": "ㅁ", "s": "ㄴ", "d": "ㅇ", "f": "ㄹ", "g": "ㅎ", "h": "ㅗ", "j": "ㅓ", "k": "ㅏ", "l": "ㅣ",
    "z": "ㅋ", "x": "ㅌ", "c": "ㅊ", "v": "ㅍ", "b": "ㅠ", "n": "ㅜ", "m": "ㅡ",
    "Q": "ㅃ", "W": "ㅉ", "E": "ㄸ", "R": "ㄲ", "T": "ㅆ", "O": "ㅒ", "P": "ㅖ",
}
JAMO2KEY = {}
for _k, _j in KEY2JAMO.items():
    JAMO2KEY.setdefault(_j, _k)
# 겹모음·겹받침 → 두 키
COMPOUND_V = {"ㅘ": "ㅗㅏ", "ㅙ": "ㅗㅐ", "ㅚ": "ㅗㅣ", "ㅝ": "ㅜㅓ", "ㅞ": "ㅜㅔ", "ㅟ": "ㅜㅣ", "ㅢ": "ㅡㅣ"}
COMPOUND_T = {"ㄳ": "ㄱㅅ", "ㄵ": "ㄴㅈ", "ㄶ": "ㄴㅎ", "ㄺ": "ㄹㄱ", "ㄻ": "ㄹㅁ", "ㄼ": "ㄹㅂ", "ㄽ": "ㄹㅅ",
              "ㄾ": "ㄹㅌ", "ㄿ": "ㄹㅍ", "ㅀ": "ㄹㅎ", "ㅄ": "ㅂㅅ"}
V_JOIN = {v: k for k, v in COMPOUND_V.items()}
T_JOIN = {v: k for k, v in COMPOUND_T.items()}


def kor_to_keys(text: str) -> str:
    """'ㅁㅔㅔㅣㄷ' / '멤ㅣㄷ' → 'apple' (한글 자판 상태로 영어를 친 경우)"""
    out = []
    for ch in text:
        jamo = to_jamo(ch) if is_syllable(ch) else ch
        for j in jamo:
            j = COMPOUND_V.get(j) or COMPOUND_T.get(j) or j
            for x in j:
                out.append(JAMO2KEY.get(x, x))
    return "".join(out)


def keys_to_kor(text: str) -> str:
    """'tkrhk' → '사과' (영문 자판 상태로 한글을 친 경우). 바꿀 수 없으면 ''."""
    jamo = []
    for c in text:
        j = KEY2JAMO.get(c) or KEY2JAMO.get(c.lower())
        if not j:
            if c == " ":
                jamo.append(" ")
                continue
            return ""
        jamo.append(j)
    return compose_jamo(jamo)


def compose_jamo(seq: list[str]) -> str:
    """자모 나열을 두벌식 입력기처럼 음절로 조합."""
    out = []
    i, n = 0, len(seq)

    def is_v(j):
        return j in JUNG

    def is_c(j):
        return j in CHO or j in JONG

    while i < n:
        j = seq[i]
        if j == " " or j not in CHO:
            # 모음으로 시작하거나 조합 불가 → 그대로 (두 모음이 겹모음이면 합침)
            if i + 1 < n and (j + seq[i + 1]) in V_JOIN:
                out.append(V_JOIN[j + seq[i + 1]])
                i += 2
            else:
                out.append(j)
                i += 1
            continue
        # 초성
        if i + 1 >= n or not is_v(seq[i + 1]):
            out.append(j)
            i += 1
            continue
        l = CHO.index(j)
        v_j = seq[i + 1]
        k = i + 2
        if k < n and (v_j + seq[k]) in V_JOIN:
            v_j = V_JOIN[v_j + seq[k]]
            k += 1
        v = JUNG.index(v_j)
        t = 0
        # 받침: 다음이 자음이고, 그 다음이 모음이 아니면 받침으로
        if k < n and is_c(seq[k]) and seq[k] in JONG and not (k + 1 < n and is_v(seq[k + 1])):
            t_j = seq[k]
            k2 = k + 1
            if k2 < n and (t_j + seq[k2]) in T_JOIN and not (k2 + 1 < n and is_v(seq[k2 + 1])):
                t_j = T_JOIN[t_j + seq[k2]]
                k2 += 1
            t = JONG.index(t_j)
            k = k2
        out.append(join_syllable(l, v, t))
        i = k
    return "".join(out)
