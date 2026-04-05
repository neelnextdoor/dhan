from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# --- Auth ---
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --- Engine Status ---
class EngineStatus(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    ERROR = "ERROR"


class EngineStatusResponse(BaseModel):
    status: EngineStatus
    mode: str = "paper"
    uptime_seconds: float = 0
    last_tick: Optional[str] = None
    error: Optional[str] = None
    symbol: str = ""
    strategy: str = ""


# --- Trading Control ---
class StartRequest(BaseModel):
    mode: str = "paper"
    config_path: Optional[str] = None


# --- PnL / Stats ---
class TradingStats(BaseModel):
    daily_pnl: float = 0
    total_pnl: float = 0
    win_rate: float = 0
    total_trades_today: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    capital_deployed: float = 0
    risk_usage_pct: float = 0
    max_drawdown: float = 0
    current_position: Optional[dict] = None


# --- Trade ---
class TradeResponse(BaseModel):
    trade_id: str
    symbol: str
    side: str
    option_type: Optional[str] = None
    strike: float = 0
    entry_price: float
    exit_price: float = 0
    quantity: int
    stop_loss: float
    target: float
    entry_time: str
    exit_time: Optional[str] = None
    exit_reason: Optional[str] = None
    pnl: float = 0
    status: str = "OPEN"
    underlying_price: float = 0


# --- Config ---
class ConfigUpdate(BaseModel):
    config: dict[str, Any]


class ConfigPreset(BaseModel):
    name: str
    config: dict[str, Any]
    created_at: Optional[str] = None


# --- Backtest ---
class BacktestRequest(BaseModel):
    start_date: str = "2025-01-01"
    end_date: str = "2025-12-31"
    csv_path: Optional[str] = None
    config_overrides: Optional[dict[str, Any]] = None


class BacktestResult(BaseModel):
    summary: dict[str, Any]
    trades: list[dict[str, Any]]
    equity_curve: list[dict[str, Any]]


# --- Logs ---
class LogEntry(BaseModel):
    timestamp: str
    level: str
    module: str
    message: str


# --- WebSocket Messages ---
class WSMessage(BaseModel):
    type: str
    data: Any
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
