from enum import Enum


class TradingMode(str, Enum):
    LIVE = "live"
    PAPER = "paper"
    BACKTEST = "backtest"


class SignalType(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    EXIT_LONG = "EXIT_LONG"
    EXIT_SHORT = "EXIT_SHORT"
    NO_SIGNAL = "NO_SIGNAL"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ExitReason(str, Enum):
    STOP_LOSS = "STOP_LOSS"
    TARGET = "TARGET"
    TRAILING_SL = "TRAILING_SL"
    PARTIAL_PROFIT = "PARTIAL_PROFIT"
    OPPOSITE_SIGNAL = "OPPOSITE_SIGNAL"
    TIME_EXIT = "TIME_EXIT"
    FORCE_EXIT = "FORCE_EXIT"
    KILL_SWITCH = "KILL_SWITCH"
    MANUAL = "MANUAL"


class StopLossType(str, Enum):
    FIXED_POINTS = "fixed_points"
    FIXED_PCT = "fixed_pct"
    SWING = "swing"
    EMA_BREACH = "ema_breach"


class TargetType(str, Enum):
    RISK_REWARD = "risk_reward"
    FIXED_POINTS = "fixed_points"
    FIXED_PCT = "fixed_pct"


class OptionType(str, Enum):
    CALL = "CALL"
    PUT = "PUT"


class StrikeSelection(str, Enum):
    ATM = "atm"
    ITM_1 = "itm_1"
    ITM_2 = "itm_2"
    OTM_1 = "otm_1"
    OTM_2 = "otm_2"
    FIXED = "fixed"


class EntryMode(str, Enum):
    BREAKOUT = "breakout"
    PULLBACK = "pullback"
    BOTH = "both"


class TradeGrade(str, Enum):
    """Trade quality grading — only A_PLUS and A are taken by default."""
    A_PLUS = "A+"
    A = "A"
    B = "B"
    C = "C"


class OISignal(str, Enum):
    LONG_BUILDUP = "LONG_BUILDUP"
    SHORT_BUILDUP = "SHORT_BUILDUP"
    LONG_UNWINDING = "LONG_UNWINDING"
    SHORT_COVERING = "SHORT_COVERING"
    NEUTRAL = "NEUTRAL"


TIMEFRAME_MAP = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
}

EXCHANGE_MAP = {
    "NSE": "NSE_EQ",
    "BSE": "BSE_EQ",
    "NFO": "NSE_FNO",
    "MCX": "MCX_COMM",
    "IDX_I": "IDX_I",
}
