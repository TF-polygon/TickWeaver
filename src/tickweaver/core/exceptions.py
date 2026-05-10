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
