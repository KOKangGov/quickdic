# QuickDic — 작은 플로팅 사전

화면 위에 작은 사전 창을 띄워 두고, 다른 프로그램에서 **단어를 드래그한 뒤 `Alt + Q`** 를 누르면
바로 뜻·어원·예문을 보여 주는 Windows 사전입니다.

- 오프라인 사전: 위키낱말사전(Wiktionary) 영어판·한국어판 + **국립국어원 표준국어대사전(국어 뜻풀이)** 을 SQLite 로 변환해 PC 에 저장
- 뜻 / 어원 / 예문 탭, 영영 정의 토글, 유의어·반의어
- 한글을 넣으면 한영으로 자동 전환 — **국어 뜻풀이가 맨 위**, 그 아래 영어 대응어
- **오타 추천**: 입력하든 붙여넣든 사전에 없으면 비슷한 단어를 추천 (`recieve → receive`, `사괴 → 사과`, `아릅답다 → 아름답다`)
  - 한/영 키를 잘못 두고 친 것도 바로잡음 (`tkrhk → 사과`, `ㅗ디ㅣㅐ → hello`)
- **웹사전** 버튼 → 네이버·다음·Cambridge·Oxford·Merriam-Webster 검색 결과 바로 열기
- 발음 듣기(Windows 내장 음성, 오프라인), 단어장(★ + CSV 내보내기), 최근 검색 10개
- 항상 위 고정, 투명도 50~100%, 접기/펼치기, 창 위치·크기 기억, Windows 시작 시 자동 실행
- 사전 데이터 **주 1회 자동 업데이트** (GitHub Actions 가 매주 새로 만들어 올림)

> 사용자용 안내는 [RELEASE_NOTES.md](RELEASE_NOTES.md) 를 보세요. 아래는 **배포하는 사람(저장소 주인)** 을 위한 안내입니다.

---

## 어떻게 돌아가나요?

```
 [GitHub Actions: 매주 월요일 새벽]                     [사용자 PC]
  kaikki.org 위키낱말 데이터 내려받기                     QuickDic.exe 실행
  + 'source-data' 릴리스의 국립국어원 사전 zip
        ↓ tools/build_db.py                              ↓ 7일마다 version.json 확인
  quickdic.db 만들기 → 압축                                ↓ 새 버전이면 백그라운드로 받아 교체
        ↓                                                 오프라인 검색 (0.1초 이내)
  'dictionary' 릴리스에 업로드  ─────────────────────▶
```

- 앱(exe)은 **'앱 만들기'** 워크플로가 Windows 에서 만들어 릴리스에 올립니다. 이때 저장소 주소가 exe 안에 자동으로 들어가므로 코드를 고칠 필요가 없습니다.
- 사전 파일은 **'사전 데이터 만들기'** 워크플로가 매주 만들어 `dictionary` 릴리스에 올립니다.
- 저장소는 **공개(Public)** 여야 다른 사람들이 로그인 없이 내려받을 수 있습니다. (공개 저장소는 Actions 사용도 무료)

## 처음 배포하기 (한 번만)

1. GitHub 에 **공개 저장소**를 만들고 이 폴더의 파일을 모두 올립니다. (`.github` 폴더 포함)
2. 저장소 → **Actions** 탭 → 처음이면 "I understand… enable" 버튼으로 Actions 켜기
3. 왼쪽 목록에서 **사전 데이터 만들기 (주 1회)** → **Run workflow** → 초록 버튼
   - 30분~1시간 정도 걸립니다. 끝나면 Releases 에 `사전 데이터 (자동 갱신)` 이 생깁니다.
4. 왼쪽 목록에서 **앱 만들기 (Windows exe)** → **Run workflow** → 버전 `1.0.0` 입력 → 실행
   - 5분 정도 뒤 Releases 에 `QuickDic v1.0.0` 과 `QuickDic.exe` 가 생깁니다.
5. 다른 사람에게는 릴리스 주소만 알려 주면 됩니다:
   `https://github.com/<내아이디>/<저장소이름>/releases/latest`

## 국내 사전(국어 뜻풀이) 원본 올리기

국립국어원 사전은 로그인해야 받을 수 있어서 자동으로 내려받지 못합니다. 저장소 주인이 한 번 받아서 올려 두면
매주 사전 빌드 때 그 파일을 씁니다. (올려 두지 않으면 예전처럼 한국어판 위키낱말사전의 국어 뜻풀이를 씁니다)

1. [표준국어대사전](https://stdict.korean.go.kr) 에 회원 가입·로그인 → **사전 내려받기** 메뉴에서 **JSON** 형식 zip 을 받습니다.
   - 표제어가 더 많은 [우리말샘](https://opendict.korean.go.kr) 의 JSON zip 도 됩니다 (용량은 2~3배). 둘 다 올리면 겹치는 뜻풀이는 한 번만 넣습니다.
2. 저장소 → **Releases** → `source-data` 릴리스(없으면 **Draft a new release** → 태그 `source-data` 로 새로 만들기, *Set as a pre-release* 체크)
   → 받은 zip 파일을 끌어다 놓고 저장
3. **Actions** → **사전 데이터 만들기 (주 1회)** → **Run workflow** 로 바로 다시 만들 수 있습니다.

사전 내용이 바뀌는 것은 몇 달에 한 번이라, 가끔(예: 분기마다) 새 zip 으로 바꿔 올리면 충분합니다.
출판물·신문에서 인용한 예문(출처가 달린 예문)은 저작권 때문에 자동으로 빼고 넣습니다.

## 새 버전 내기

코드를 고친 뒤 **앱 만들기** 를 다시 실행하면서 버전을 올려 주세요(예: `1.0.1`).
이미 앱을 쓰고 있는 사람들의 상태 표시줄에 "새 버전이 나왔어요" 가 뜹니다.

## 폴더 구성

| 경로 | 내용 |
| --- | --- |
| `app/quickdic.py` | 플로팅 창 화면 (tkinter) |
| `app/dictdb.py` | 사전 검색·결과 정리 |
| `app/fuzzy.py` | 오타 추천: 편집 거리, 한글 자모 비교, 한/영 자판 바꾸기 |
| `app/winsys.py` | Windows 연동: 전역 단축키, 선택 글자 복사, 발음, 자동 실행 |
| `app/updater.py` | 사전 자동 업데이트 |
| `app/config.py` | 설정·단어장·검색 기록 저장 |
| `tools/build_db.py` | 위키낱말 데이터 → SQLite 사전 변환 |
| `tools/kodict.py` | 국립국어원 표준국어대사전·우리말샘 JSON 읽기 |
| `tools/package_db.py` | 사전 압축 + `version.json` 생성 |
| `.github/workflows/` | 주간 사전 빌드, exe 빌드 |

사용자 PC 에 저장되는 곳: 설정·단어장 `%APPDATA%\QuickDic`, 사전 파일 `%LOCALAPPDATA%\QuickDic`

## 직접 실행해 보기 (개발용, 선택)

```bat
python app\quickdic.py
```
외부 패키지가 필요 없습니다(Python 3.10 이상, Windows). 사전 파일이 없으면 '설정' → '사전 파일 직접 열기…' 로
릴리스의 `quickdic.db.gz` 를 지정하면 됩니다.

## PRD 대비 현재 범위

| 항목 | 상태 |
| --- | --- |
| 플로팅 창·항상 위·위치 기억·접기 | ✅ |
| Alt+Q 전역 단축키 + 선택 글자 자동 검색, 붙여넣기 검색 | ✅ (단축키 변경 가능) |
| 오프라인 SQLite 사전, 뜻/어원/예문 탭, 영영 토글 | ✅ |
| 한글 입력 시 한영 자동 전환 | ✅ |
| 웹사전 버튼 (네이버 기본, 변경 가능) | ✅ |
| 주 1회 자동 업데이트, 실패 시 24시간 뒤 재시도 | ✅ (변경분만 받는 방식이 아니라 전체 파일 교체) |
| 발음, 단어장·CSV, 최근 검색, 투명도 | ✅ |
| macOS / 안드로이드 태블릿 | ⏳ 다음 단계 (Flutter 등으로 별도 작업 필요) |
| 화면 캡처 OCR (Alt+Shift+Q) | ⏳ 다음 단계 |
| 일한·중한·불한 언어팩 | ⏳ 다음 단계 |

PRD 는 Flutter 를 제안했지만, Windows 우선 배포를 빠르게 하기 위해 1차 버전은 **Python + tkinter 단일 exe** 로 만들었습니다.
(외부 패키지 0개, Windows API 직접 호출 → 가볍고 ARM 노트북에서도 동작)

## 라이선스

- 코드: MIT ([LICENSE](LICENSE))
- 사전 데이터: [Wiktionary](https://www.wiktionary.org/) 기여자들, CC BY-SA 4.0 / GFDL — [kaikki.org](https://kaikki.org/) 의 Wiktextract 추출본 사용
- 국어 뜻풀이: 국립국어원 표준국어대사전·우리말샘, CC BY-SA 2.0 KR
- 오타 추천 순위용 단어 빈도: [wordfreq](https://github.com/rspeer/wordfreq) (CC BY-SA 4.0) — 자세한 내용은 [NOTICE](NOTICE)
