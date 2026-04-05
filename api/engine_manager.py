from __future__ import annotations

import asyncio
import threading
import time
import traceback
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Optional

from api.log_capture import log_capture
from api.schemas import EngineStatus
from api.ws_manager import ws_manager

import logging

logger = logging.getLogger("engine_manager")


@dataclass
class EngineState:
    status: EngineStatus = EngineStatus.STOPPED
    mode: str = "paper"
    started_at: Optional[datetime] = None
    last_tick: Optional[datetime] = None
    error: Optional[str] = None
    symbol: str = ""
    strategy_name: str = ""
    daily_pnl: float = 0
    total_pnl: float = 0
    trades_today: int = 0
    active_trade: Optional[dict] = None
    all_trades: list[dict] = field(default_factory=list)
    candle_data: list[dict] = field(default_factory=list)


class EngineManager:
    """Manages the lifecycle of the LiveEngine in a background thread."""

    def __init__(self):
        self.state = EngineState()
        self._engine = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._config = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def get_status(self) -> dict:
        uptime = 0.0
        if self.state.started_at and self.state.status == EngineStatus.RUNNING:
            uptime = (datetime.now() - self.state.started_at).total_seconds()

        return {
            "status": self.state.status.value,
            "mode": self.state.mode,
            "uptime_seconds": round(uptime, 1),
            "last_tick": self.state.last_tick.isoformat() if self.state.last_tick else None,
            "error": self.state.error,
            "symbol": self.state.symbol,
            "strategy": self.state.strategy_name,
        }

    def get_stats(self) -> dict:
        trades = self.state.all_trades
        closed = [t for t in trades if t.get("status") == "CLOSED"]
        wins = [t for t in closed if t.get("pnl", 0) > 0]
        losses = [t for t in closed if t.get("pnl", 0) <= 0]

        daily_pnl = sum(t.get("pnl", 0) for t in closed)
        win_rate = (len(wins) / len(closed) * 100) if closed else 0

        capital = self._config.risk.capital_per_trade if self._config else 0
        max_loss = self._config.risk.max_loss_per_day if self._config else 0
        risk_usage = (abs(min(daily_pnl, 0)) / max_loss * 100) if max_loss > 0 else 0

        return {
            "daily_pnl": round(daily_pnl, 2),
            "total_pnl": round(daily_pnl, 2),
            "win_rate": round(win_rate, 1),
            "total_trades_today": len(trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "capital_deployed": capital,
            "risk_usage_pct": round(min(risk_usage, 100), 1),
            "max_drawdown": 0,
            "current_position": self.state.active_trade,
        }

    def start(self, mode: str = "paper", config_path: str | None = None):
        if self.state.status in (EngineStatus.RUNNING, EngineStatus.STARTING):
            raise RuntimeError(f"Engine already {self.state.status.value}")

        self.state = EngineState(status=EngineStatus.STARTING, mode=mode)

        self._thread = threading.Thread(
            target=self._run_engine, args=(mode, config_path), daemon=True
        )
        self._thread.start()

    def stop(self):
        if self.state.status != EngineStatus.RUNNING:
            raise RuntimeError(f"Engine is {self.state.status.value}, cannot stop")

        self.state.status = EngineStatus.STOPPING
        if self._engine:
            self._engine._running = False
        self._broadcast("engine_status", {"status": "STOPPING"})

    def kill(self):
        """Emergency kill switch — force-stops everything."""
        if self._engine:
            self._engine._running = False
            if hasattr(self._engine, 'risk_manager'):
                self._engine.risk_manager._kill_switch_active = True
        self.state.status = EngineStatus.STOPPED
        self.state.error = "KILL SWITCH activated"
        self._broadcast("engine_status", {"status": "STOPPED", "error": "KILL SWITCH activated"})
        logger.critical("KILL SWITCH activated")

    def _run_engine(self, mode: str, config_path: str | None):
        try:
            import sys, os
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if project_root not in sys.path:
                sys.path.insert(0, project_root)

            from src.core.config import AppConfig
            from src.core.logger import setup_logging
            from src.strategy.ema_strategy import EMAStrategy
            from src.live.engine import LiveEngine

            config = AppConfig.load(config_path)
            config.trading_mode = mode
            os.environ["TRADING_MODE"] = mode

            setup_logging(config)

            root_logger = logging.getLogger()
            if log_capture not in root_logger.handlers:
                log_capture.setLevel(logging.DEBUG)
                root_logger.addHandler(log_capture)

            self._config = config

            strategy = EMAStrategy(config)
            engine = LiveEngine(config, strategy)
            self._engine = engine

            self.state.status = EngineStatus.RUNNING
            self.state.started_at = datetime.now()
            self.state.symbol = config.symbol
            self.state.strategy_name = strategy.name()
            self._broadcast("engine_status", {"status": "RUNNING", "symbol": config.symbol})

            original_tick = engine._tick

            def instrumented_tick():
                original_tick()
                self._on_tick(engine)

            engine._tick = instrumented_tick

            engine.start()

        except Exception as e:
            self.state.status = EngineStatus.ERROR
            self.state.error = str(e)
            logger.exception("Engine crashed")
            self._broadcast("engine_status", {"status": "ERROR", "error": str(e)})
        finally:
            if self.state.status != EngineStatus.ERROR:
                self.state.status = EngineStatus.STOPPED
            self._engine = None
            self._broadcast("engine_status", {"status": self.state.status.value})

    def _on_tick(self, engine):
        self.state.last_tick = datetime.now()

        pm = engine.position_manager
        trades_data = []
        for t in pm.get_all_trades():
            td = {
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "side": t.side.value,
                "option_type": t.option_type.value if t.option_type else None,
                "strike": t.strike,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "quantity": t.quantity,
                "stop_loss": t.stop_loss,
                "target": t.target,
                "entry_time": t.entry_time.isoformat() if t.entry_time else "",
                "exit_time": t.exit_time.isoformat() if t.exit_time else None,
                "exit_reason": t.exit_reason.value if t.exit_reason else None,
                "pnl": round(t.pnl, 2),
                "status": t.status.value,
                "underlying_price": t.underlying_price_at_entry,
            }
            trades_data.append(td)

        self.state.all_trades = trades_data
        self.state.trades_today = pm.daily_trade_count

        if pm.has_open_position and pm.active_trade:
            at = pm.active_trade
            self.state.active_trade = {
                "trade_id": at.trade_id,
                "symbol": at.symbol,
                "option_type": at.option_type.value if at.option_type else None,
                "strike": at.strike,
                "entry_price": at.entry_price,
                "quantity": at.quantity,
                "stop_loss": at.stop_loss,
                "target": at.target,
                "trailing_sl": at.trailing_sl,
                "peak_price": at.peak_price,
            }
        else:
            self.state.active_trade = None

        self.state.daily_pnl = pm.daily_pnl

        if engine.market_data:
            candles = engine.market_data.candles
            if candles is not None and not candles.empty:
                recent = candles.tail(200)
                self.state.candle_data = [
                    {
                        "time": idx.isoformat() if hasattr(idx, 'isoformat') else str(idx),
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row.get("volume", 0)),
                    }
                    for idx, row in recent.iterrows()
                ]

        self._broadcast("tick", {
            "pnl": self.state.daily_pnl,
            "trades_today": self.state.trades_today,
            "active_trade": self.state.active_trade,
            "candles": self.state.candle_data[-5:] if self.state.candle_data else [],
        })

    def _broadcast(self, msg_type: str, data: Any):
        if self._loop:
            asyncio.run_coroutine_threadsafe(
                ws_manager.broadcast("live", msg_type, data), self._loop
            )


engine_manager = EngineManager()
