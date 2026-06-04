# parity/reference/ — TradingView CSV 배치 위치

이 폴더에 TradingView Strategy Tester에서 내보낸 CSV 파일을 저장합니다.
내보내기 절차는 [`../GUIDELINE.md`](../GUIDELINE.md) §2 를 참고하세요.

---

## 파일명 규칙

| 파일명 패턴 | 내용 |
|---|---|
| `<strategy>.tv_trades.csv` | Strategy Tester → List of Trades 내보내기 |
| `<strategy>.tv_summary.csv` | Strategy Tester → Performance Summary 내보내기 |

**실제 파일명 예시:**

```
parity/reference/
  ema_cross.tv_trades.csv          ← 사용자가 직접 배치
  ema_cross.tv_summary.csv         ← 사용자가 직접 배치
  supertrend.tv_trades.csv         ← 사용자가 직접 배치
  supertrend.tv_summary.csv        ← 사용자가 직접 배치
  ema_cross.tv_trades.sample.csv   ← 형식 예시 (이 저장소 포함)
  ema_cross.tv_summary.sample.csv  ← 형식 예시 (이 저장소 포함)
```

> `.sample.csv` 파일은 정확한 컬럼 구조와 형식을 보여주는 예시입니다.
> 실제 TradingView export 파일은 `.sample.csv` 를 제외한 이름으로 저장하세요.

---

## List of Trades 스키마

파일명: `<strategy>.tv_trades.csv`

### 헤더 (정확히 이 순서)

```
Trade #,Type,Date/Time,Price USDT,Contracts,Profit USDT,Profit %,Cumulative profit USDT,Cumulative profit %
```

### 컬럼 설명

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `Trade #` | int | 라운드트립 번호 (1부터 시작) |
| `Type` | string | `Entry long` / `Exit long` / `Entry short` / `Exit short` |
| `Date/Time` | `YYYY-MM-DD HH:MM` (UTC) | 체결 시각 |
| `Price USDT` | float | 체결 가격 |
| `Contracts` | float | 체결 수량 |
| `Profit USDT` | float | PnL (진입 행은 비어있거나 0) |
| `Profit %` | float | PnL % |
| `Cumulative profit USDT` | float | 누적 PnL |
| `Cumulative profit %` | float | 누적 PnL % |

**행 구조**: 라운드트립 1회 = **2행** (진입 1행 + 청산 1행). `Trade #` 는 두 행이 동일.

형식 예시는 `ema_cross.tv_trades.sample.csv` 참고.

---

## Performance Summary 스키마

파일명: `<strategy>.tv_summary.csv`

### 컬럼 구조

| 위치 | 내용 |
|---|---|
| **0번 열** | 지표 라벨 (텍스트) |
| **`All USDT` 열** | 절댓값 (순이익 USDT, 낙폭 USDT 등) |
| **`All %` 열** | 퍼센트 값 (수익률 %, 낙폭 % 등) |

### 파서가 읽는 필수 라벨

`parity.compare` 파서는 0번 열에서 아래 라벨을 **대소문자 무시 부분 일치**로 찾습니다.
TradingView 버전에 따라 라벨 표현이 약간 달라도 (`Net profit` vs `Net Profit`) 매칭됩니다.

| TradingView 라벨 (부분 일치) | TickWeaver 대응 지표 | metrics.json 키 |
|---|---|---|
| `Net Profit` | 순이익 | `total_return` (fraction) |
| `Total Closed Trades` | 총 거래수 | `n_trades` |
| `Percent Profitable` | 승률 | `win_rate` (fraction) |
| `Profit Factor` | Profit Factor | `profit_factor` |
| `Max Drawdown` | 최대 낙폭 | `max_drawdown` (negative fraction) |

> **단위 주의**: TickWeaver `metrics.json` 의 `win_rate` 와 `total_return` 은
> **fraction** (예: 0.439 = 43.9%), `max_drawdown` 은 **음수 fraction** (예: -0.0478 = -4.78%).
> `parity.compare` 가 TradingView CSV(%) 와 비교할 때 단위 변환을 자동 처리합니다.

형식 예시는 `ema_cross.tv_summary.sample.csv` 참고.
