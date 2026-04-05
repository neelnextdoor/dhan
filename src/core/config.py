from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()


@dataclass
class EMAConfig:
    primary_period: int = 7
    short_period: int = 9
    long_period: int = 21
    trend_period: int = 50
    use_crossover_confirmation: bool = True


@dataclass
class MultiTimeframeConfig:
    enabled: bool = True
    higher_tf_minutes: int = 15
    require_htf_alignment: bool = True
    htf_ema_period: int = 21


@dataclass
class EntryConfig:
    mode: str = "both"
    confirm_candle_close: bool = True
    volume_confirmation: bool = False
    volume_multiplier: float = 1.5
    min_grade: str = "A"
    cooldown_bars: int = 3
    max_entries_per_direction: int = 2


@dataclass
class SidewaysFilterConfig:
    enabled: bool = True
    method: str = "combined"
    atr_period: int = 14
    atr_threshold: float = 0.1
    candle_range_min: float = 0.05
    ema_flat_lookback: int = 10
    ema_flat_threshold: float = 0.005
    range_bound_lookback: int = 20
    range_bound_pct: float = 1.0
    atr_expansion_lookback: int = 5
    atr_expansion_factor: float = 1.1


@dataclass
class StopLossConfig:
    type: str = "fixed_points"
    value: float = 50.0


@dataclass
class TargetConfig:
    type: str = "risk_reward"
    risk_reward_ratio: float = 2.0
    value: float = 100.0


@dataclass
class TrailingSLConfig:
    enabled: bool = True
    activation_pct: float = 10.0
    trail_pct: float = 5.0


@dataclass
class PartialExitConfig:
    enabled: bool = False
    first_target_pct: float = 15.0
    first_exit_fraction: float = 0.5
    move_sl_to_cost: bool = True


@dataclass
class TimeExitConfig:
    enabled: bool = True
    exit_time: str = "15:15"


@dataclass
class ExitConfig:
    stop_loss: StopLossConfig = field(default_factory=StopLossConfig)
    target: TargetConfig = field(default_factory=TargetConfig)
    trailing_sl: TrailingSLConfig = field(default_factory=TrailingSLConfig)
    partial_exit: PartialExitConfig = field(default_factory=PartialExitConfig)
    time_based_exit: TimeExitConfig = field(default_factory=TimeExitConfig)
    exit_on_opposite_signal: bool = True


@dataclass
class RiskConfig:
    max_trades_per_day: int = 5
    max_loss_per_day: float = 2000.0
    capital_per_trade: float = 20000.0
    lot_size: int = 65
    max_open_positions: int = 1
    risk_per_trade_pct: float = 2.0
    cooldown_after_loss: int = 2
    max_consecutive_losses: int = 3


@dataclass
class BrokerageConfig:
    """Indian brokerage model for realistic backtesting."""
    enabled: bool = True
    brokerage_per_order: float = 20.0
    stt_pct: float = 0.0625
    exchange_txn_pct: float = 0.0019
    gst_pct: float = 18.0
    sebi_per_crore: float = 10.0
    stamp_duty_pct: float = 0.003


@dataclass
class TradingHoursConfig:
    start: str = "09:20"
    end: str = "14:30"
    force_exit: str = "15:25"


@dataclass
class LoggingConfig:
    level: str = "INFO"
    console: bool = True
    file: bool = True
    log_dir: str = "logs"


@dataclass
class TelegramConfig:
    enabled: bool = False
    on_entry: bool = True
    on_exit: bool = True
    on_error: bool = True
    daily_summary: bool = True


@dataclass
class PaperTradingConfig:
    initial_capital: float = 20000.0
    slippage_pct: float = 0.1


@dataclass
class OptionsConfig:
    enabled: bool = True
    strike_selection: str = "atm"
    strike_offset: int = 0
    fixed_strike: float = 0.0
    expiry_preference: str = "weekly"
    strike_interval: float = 50.0
    premium_sl_pct: float = 20.0
    premium_target_pct: float = 30.0
    use_premium_based_sl: bool = True
    min_premium: float = 50.0
    max_premium: float = 500.0
    avoid_last_hour_entry: bool = True
    theta_decay_exit_minutes: int = 45


@dataclass
class WebhookConfig:
    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8443
    auth_token: str = ""
    log_all_updates: bool = True


@dataclass
class BacktestConfig:
    data_source: str = "dhan"
    csv_path: str = ""
    start_date: str = "2025-01-01"
    end_date: str = "2025-12-31"
    initial_capital: float = 20000.0
    commission_per_trade: float = 20.0
    next_candle_entry: bool = True
    slippage_pct: float = 0.1


@dataclass
class AppConfig:
    symbol: str = "NIFTY"
    exchange: str = "NSE"
    instrument_type: str = "INDEX"
    security_id: str = "13"
    expiry: str = ""
    timeframe: str = "5m"
    lookback_candles: int = 200

    ema: EMAConfig = field(default_factory=EMAConfig)
    multi_timeframe: MultiTimeframeConfig = field(default_factory=MultiTimeframeConfig)
    entry: EntryConfig = field(default_factory=EntryConfig)
    sideways_filter: SidewaysFilterConfig = field(default_factory=SidewaysFilterConfig)
    exit: ExitConfig = field(default_factory=ExitConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    brokerage: BrokerageConfig = field(default_factory=BrokerageConfig)
    trading_hours: TradingHoursConfig = field(default_factory=TradingHoursConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    options: OptionsConfig = field(default_factory=OptionsConfig)
    webhook: WebhookConfig = field(default_factory=WebhookConfig)
    paper_trading: PaperTradingConfig = field(default_factory=PaperTradingConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)

    dhan_client_id: str = ""
    dhan_access_token: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    trading_mode: str = "paper"

    @classmethod
    def load(cls, config_path: str | None = None) -> AppConfig:
        path = config_path or os.getenv("CONFIG_PATH", "config/default.yaml")
        resolved = Path(path)
        if not resolved.is_absolute():
            resolved = Path(__file__).parent.parent.parent / resolved

        raw: dict[str, Any] = {}
        if resolved.exists():
            with open(resolved) as f:
                raw = yaml.safe_load(f) or {}

        cfg = cls(
            symbol=raw.get("symbol", cls.symbol),
            exchange=raw.get("exchange", cls.exchange),
            instrument_type=raw.get("instrument_type", cls.instrument_type),
            security_id=str(raw.get("security_id", cls.security_id)),
            expiry=raw.get("expiry", cls.expiry) or "",
            timeframe=raw.get("timeframe", cls.timeframe),
            lookback_candles=raw.get("lookback_candles", cls.lookback_candles),
        )

        if "ema" in raw:
            cfg.ema = _from_dict(EMAConfig, raw["ema"])
        if "multi_timeframe" in raw:
            cfg.multi_timeframe = _from_dict(MultiTimeframeConfig, raw["multi_timeframe"])
        if "entry" in raw:
            cfg.entry = _from_dict(EntryConfig, raw["entry"])
        if "sideways_filter" in raw:
            cfg.sideways_filter = _from_dict(SidewaysFilterConfig, raw["sideways_filter"])
        if "exit" in raw:
            ex = raw["exit"]
            cfg.exit = ExitConfig(
                stop_loss=_from_dict(StopLossConfig, ex.get("stop_loss", {})),
                target=_from_dict(TargetConfig, ex.get("target", {})),
                trailing_sl=_from_dict(TrailingSLConfig, ex.get("trailing_sl", {})),
                partial_exit=_from_dict(PartialExitConfig, ex.get("partial_exit", {})),
                time_based_exit=_from_dict(TimeExitConfig, ex.get("time_based_exit", {})),
                exit_on_opposite_signal=ex.get("exit_on_opposite_signal", True),
            )
        if "risk" in raw:
            cfg.risk = _from_dict(RiskConfig, raw["risk"])
        if "brokerage" in raw:
            cfg.brokerage = _from_dict(BrokerageConfig, raw["brokerage"])
        if "trading_hours" in raw:
            cfg.trading_hours = _from_dict(TradingHoursConfig, raw["trading_hours"])
        if "logging" in raw:
            cfg.logging = _from_dict(LoggingConfig, raw["logging"])
        if "telegram" in raw:
            cfg.telegram = _from_dict(TelegramConfig, raw["telegram"])
        if "options" in raw:
            cfg.options = _from_dict(OptionsConfig, raw["options"])
        if "webhook" in raw:
            cfg.webhook = _from_dict(WebhookConfig, raw["webhook"])
        if "paper_trading" in raw:
            cfg.paper_trading = _from_dict(PaperTradingConfig, raw["paper_trading"])
        if "backtest" in raw:
            cfg.backtest = _from_dict(BacktestConfig, raw["backtest"])

        cfg.dhan_client_id = os.getenv("DHAN_CLIENT_ID", "")
        cfg.dhan_access_token = os.getenv("DHAN_ACCESS_TOKEN", "")
        cfg.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        cfg.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        cfg.trading_mode = os.getenv("TRADING_MODE", "paper").lower()

        env_webhook_token = os.getenv("WEBHOOK_AUTH_TOKEN", "")
        if env_webhook_token:
            cfg.webhook.auth_token = env_webhook_token

        return cfg


def _from_dict(cls, data: dict) -> Any:
    if not data:
        return cls()
    filtered = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
    return cls(**filtered)
