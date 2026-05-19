"""tickweaver 도메인 예외 계층 (P6).

타입/스키마/설정 위반은 즉시 raise. OHLCV 봉 결손/중복은 raise 가 아닌 skip (D13).
"""


class TickweaverError(Exception):
    """모든 tickweaver 예외의 루트."""


class ConfigError(TickweaverError):
    """설정 / 인자 위반."""


class OHLCSchemaError(TickweaverError):
    """OHLCV 컬럼/타입/인덱스 스키마 위반."""


class OHLCIntegrityError(TickweaverError):
    """OHLCV 값 무결성 위반 (high < low, 음수 가격 등). gap 은 여기 안 들어옴 (D13)."""


class TickContractError(TickweaverError):
    """합성 tick 의 C1~C7 계약 위반."""


class StrategyError(TickweaverError):
    """전략 로딩 / 훅 실행 실패."""


class OrderError(TickweaverError):
    """주문 검증 / 발주 실패 (잔고 부족, 룰 위반 등)."""


class SpotShortNotAllowedError(OrderError):
    """Spot 모드에서 short 포지션을 열려는 SELL 주문을 거부.

    config의 ``run.mode == "spot"`` 일 때 FLAT 상태에서 SELL 주문을 제출하면
    이 예외가 발생합니다. ``mode="futures"`` 로 전환하거나, 전략이 LONG 포지션을
    먼저 보유한 다음에 SELL (= close) 하도록 수정하세요. OrderError 의 하위 타입
    이므로 기존 ``except OrderError`` 블록도 그대로 잡습니다.
    """
