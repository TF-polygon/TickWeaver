# strategies/

사용자 전략 파일이 들어가는 디렉토리입니다 (MT4 EA 스타일).

## 시작하기

1. `_starter.py` 와 `_starter.json` 을 복사해서 자신의 전략으로 만드세요
   ```powershell
   copy strategies\_starter.py    strategies\my_alpha.py
   copy strategies\_starter.json  strategies\my_alpha.json
   ```
2. `my_alpha.py` 의 `on_bar(bar)` 만 수정하면 됩니다.
3. 실행:
   ```powershell
   python scripts/run_backtest.py --strategy strategies/my_alpha.py
   ```

## 레퍼런스

`_reference.md` — MT4 F1 도움말 스타일의 사전형 API 레퍼런스. 라이프사이클 훅, 주입 globals, StrategyAPI/ParamsView 메서드, 타입, 자주 쓰는 패턴, 함정 등을 한 파일에서 찾을 수 있습니다.

## 커밋 규칙

이 디렉토리에서 git 에 커밋되는 파일은 다음 4개뿐입니다 (`.gitignore` 참조):

- `_starter.py` — 보일러플레이트
- `_starter.json` — 파라미터 템플릿
- `_reference.md` — API 레퍼런스
- `README.md` — 본 문서

사용자 전략 (`my_alpha.py`, `my_alpha.json` 등) 은 자동으로 무시됩니다.
