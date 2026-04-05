"""
Dhan Algo Trading — API Server
Provides REST APIs and WebSocket for the trading terminal UI.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.auth import authenticate, create_token, get_current_user, verify_token
from api.engine_manager import engine_manager
from api.log_capture import log_capture
from api.schemas import (
    BacktestRequest,
    BacktestResult,
    ConfigPreset,
    ConfigUpdate,
    EngineStatusResponse,
    LoginRequest,
    LogEntry,
    StartRequest,
    TokenResponse,
    TradingStats,
    TradeResponse,
)
from api.ws_manager import ws_manager

logger = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_event_loop()
    engine_manager.set_event_loop(loop)

    root_logger = logging.getLogger()
    if log_capture not in root_logger.handlers:
        log_capture.setLevel(logging.DEBUG)
        root_logger.addHandler(log_capture)

    logger.info("API server started")
    yield
    logger.info("API server shutting down")


app = FastAPI(
    title="Dhan Algo Trading Terminal",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CONFIG_DIR = PROJECT_ROOT / "config"
PRESETS_DIR = CONFIG_DIR / "presets"
PRESETS_DIR.mkdir(parents=True, exist_ok=True)


# ── Auth ──────────────────────────────────────────────────────────────
@app.post("/api/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    token = authenticate(req.username, req.password)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return TokenResponse(access_token=token)


@app.get("/api/auth/me")
async def me(user: str = Depends(get_current_user)):
    return {"username": user}


# ── Engine Control ────────────────────────────────────────────────────
@app.get("/api/trading/status", response_model=EngineStatusResponse)
async def get_status(user: str = Depends(get_current_user)):
    return engine_manager.get_status()


@app.post("/api/trading/start")
async def start_trading(req: StartRequest, user: str = Depends(get_current_user)):
    try:
        engine_manager.start(mode=req.mode, config_path=req.config_path)
        return {"message": f"Engine starting in {req.mode} mode"}
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/api/trading/stop")
async def stop_trading(user: str = Depends(get_current_user)):
    try:
        engine_manager.stop()
        return {"message": "Engine stopping"}
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/api/trading/kill")
async def kill_trading(user: str = Depends(get_current_user)):
    engine_manager.kill()
    return {"message": "KILL SWITCH activated"}


@app.get("/api/trading/stats", response_model=TradingStats)
async def get_stats(user: str = Depends(get_current_user)):
    return engine_manager.get_stats()


# ── Trades ────────────────────────────────────────────────────────────
@app.get("/api/trades")
async def get_trades(
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    result: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    user: str = Depends(get_current_user),
):
    trades = list(engine_manager.state.all_trades)

    if status:
        trades = [t for t in trades if t.get("status") == status.upper()]
    if result == "win":
        trades = [t for t in trades if t.get("pnl", 0) > 0]
    elif result == "loss":
        trades = [t for t in trades if t.get("pnl", 0) <= 0]
    if date_from:
        trades = [t for t in trades if t.get("entry_time", "") >= date_from]
    if date_to:
        trades = [t for t in trades if t.get("entry_time", "") <= date_to]

    return trades[-limit:]


@app.get("/api/trades/active")
async def get_active_trade(user: str = Depends(get_current_user)):
    return engine_manager.state.active_trade


# ── Config ────────────────────────────────────────────────────────────
def _load_yaml(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


def _save_yaml(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


@app.get("/api/config")
async def get_config(user: str = Depends(get_current_user)):
    return _load_yaml(CONFIG_DIR / "default.yaml")


@app.put("/api/config")
async def update_config(req: ConfigUpdate, user: str = Depends(get_current_user)):
    current = _load_yaml(CONFIG_DIR / "default.yaml")
    _deep_merge(current, req.config)
    _save_yaml(CONFIG_DIR / "default.yaml", current)
    return {"message": "Config updated", "config": current}


@app.post("/api/config/reset")
async def reset_config(user: str = Depends(get_current_user)):
    backup = CONFIG_DIR / "default.yaml.bak"
    default = CONFIG_DIR / "default.yaml"
    if backup.exists():
        import shutil
        shutil.copy(backup, default)
        return {"message": "Config reset to backup"}
    return {"message": "No backup found, config unchanged"}


@app.get("/api/config/presets")
async def list_presets(user: str = Depends(get_current_user)):
    presets = []
    for f in PRESETS_DIR.glob("*.yaml"):
        data = _load_yaml(f)
        presets.append({"name": f.stem, "config": data})
    return presets


@app.post("/api/config/presets")
async def save_preset(preset: ConfigPreset, user: str = Depends(get_current_user)):
    path = PRESETS_DIR / f"{preset.name}.yaml"
    _save_yaml(path, preset.config)
    return {"message": f"Preset '{preset.name}' saved"}


@app.post("/api/config/presets/{name}/load")
async def load_preset(name: str, user: str = Depends(get_current_user)):
    path = PRESETS_DIR / f"{name}.yaml"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Preset '{name}' not found")
    data = _load_yaml(path)
    _save_yaml(CONFIG_DIR / "default.yaml", data)
    return {"message": f"Preset '{name}' loaded", "config": data}


# ── Backtest ──────────────────────────────────────────────────────────
@app.post("/api/backtest/run", response_model=BacktestResult)
async def run_backtest(req: BacktestRequest, user: str = Depends(get_current_user)):
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, _run_backtest_sync, req
        )
        return result
    except Exception as e:
        logger.exception("Backtest failed")
        raise HTTPException(status_code=500, detail=str(e))


def _run_backtest_sync(req: BacktestRequest) -> dict:
    from src.core.config import AppConfig
    from src.strategy.ema_strategy import EMAStrategy
    from src.backtest.engine import BacktestEngine
    from src.backtest.report import BacktestReport

    config = AppConfig.load()
    config.trading_mode = "backtest"
    config.backtest.start_date = req.start_date
    config.backtest.end_date = req.end_date

    if req.csv_path:
        config.backtest.data_source = "csv"
        config.backtest.csv_path = req.csv_path

    if req.config_overrides:
        _apply_overrides(config, req.config_overrides)

    import pandas as pd
    if config.backtest.data_source == "csv" and config.backtest.csv_path:
        df = pd.read_csv(config.backtest.csv_path, parse_dates=["timestamp"])
        if "timestamp" in df.columns:
            df.set_index("timestamp", inplace=True)
    else:
        from src.data.dhan_client import DhanClient
        client = DhanClient(config)
        df = client.get_historical_data(
            from_date=config.backtest.start_date,
            to_date=config.backtest.end_date,
        )

    if df.empty:
        return {"summary": {"error": "No data"}, "trades": [], "equity_curve": []}

    strategy = EMAStrategy(config)
    engine = BacktestEngine(config, strategy)
    trades = engine.run(df)

    report = BacktestReport(
        trades=trades,
        equity_curve=engine.equity_curve,
        initial_capital=config.backtest.initial_capital,
        commission=config.backtest.commission_per_trade,
    )

    summary = report.summary()
    trades_data = [t.to_dict() for t in trades]

    for td in trades_data:
        for k, v in td.items():
            if hasattr(v, 'isoformat'):
                td[k] = v.isoformat()

    eq_data = []
    for e in engine.equity_curve[::max(1, len(engine.equity_curve) // 500)]:
        ts = e["timestamp"]
        eq_data.append({
            "timestamp": ts.isoformat() if hasattr(ts, 'isoformat') else str(ts),
            "equity": round(e["equity"], 2),
            "price": round(e["price"], 2),
        })

    return {"summary": summary, "trades": trades_data, "equity_curve": eq_data}


# ── Candle Data ───────────────────────────────────────────────────────
@app.get("/api/candles")
async def get_candles(user: str = Depends(get_current_user)):
    return engine_manager.state.candle_data


# ── Logs ──────────────────────────────────────────────────────────────
@app.get("/api/logs")
async def get_logs(
    limit: int = Query(200, ge=1, le=2000),
    level: Optional[str] = None,
    module: Optional[str] = None,
    user: str = Depends(get_current_user),
):
    return log_capture.get_logs(limit=limit, level=level, module=module)


@app.delete("/api/logs")
async def clear_logs(user: str = Depends(get_current_user)):
    log_capture.clear()
    return {"message": "Logs cleared"}


# ── Health ────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {
        "status": "healthy",
        "service": "dhan_algo_trading_api",
        "engine": engine_manager.state.status.value,
        "ws_connections": ws_manager.connection_count,
        "timestamp": datetime.now().isoformat(),
    }


# ── WebSocket ─────────────────────────────────────────────────────────
@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket, token: Optional[str] = Query(None)):
    if token:
        user = verify_token(token)
        if not user:
            await websocket.close(code=4001, reason="Unauthorized")
            return

    await ws_manager.connect(websocket, "live")

    await websocket.send_text(json.dumps({
        "type": "init",
        "data": {
            "status": engine_manager.get_status(),
            "stats": engine_manager.get_stats(),
            "candles": engine_manager.state.candle_data,
        },
        "timestamp": datetime.now().isoformat(),
    }))

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong", "timestamp": datetime.now().isoformat()}))
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket, "live")
    except Exception:
        await ws_manager.disconnect(websocket, "live")


@app.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket, token: Optional[str] = Query(None)):
    if token:
        user = verify_token(token)
        if not user:
            await websocket.close(code=4001, reason="Unauthorized")
            return

    await ws_manager.connect(websocket, "logs")

    def on_new_log(entry):
        asyncio.run_coroutine_threadsafe(
            ws_manager.broadcast("logs", "log", entry),
            asyncio.get_event_loop(),
        )

    log_capture.on_log(on_new_log)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket, "logs")
    except Exception:
        await ws_manager.disconnect(websocket, "logs")


# ── Helpers ───────────────────────────────────────────────────────────
def _deep_merge(base: dict, override: dict):
    for key, val in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(val, dict):
            _deep_merge(base[key], val)
        else:
            base[key] = val


def _apply_overrides(config, overrides: dict):
    for key, val in overrides.items():
        if hasattr(config, key):
            attr = getattr(config, key)
            if hasattr(attr, '__dataclass_fields__') and isinstance(val, dict):
                for k2, v2 in val.items():
                    if hasattr(attr, k2):
                        setattr(attr, k2, v2)
            else:
                setattr(config, key, val)
