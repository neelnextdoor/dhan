from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from tabulate import tabulate

from src.backtest.engine import BacktestTrade
from src.core.logger import get_logger
from src.utils.helpers import format_currency, format_pct

logger = get_logger("backtest_report")


class BacktestReport:
    def __init__(
        self,
        trades: list[BacktestTrade],
        equity_curve: list[dict],
        initial_capital: float,
        commission: float,
    ):
        self.trades = trades
        self.equity_curve = equity_curve
        self.initial_capital = initial_capital
        self.commission = commission

    def summary(self) -> dict:
        if not self.trades:
            return {"error": "No trades to analyze"}

        pnls = [t.pnl for t in self.trades]
        total_pnl = sum(pnls)
        total_commission = len(self.trades) * self.commission * 2
        net_pnl = total_pnl - total_commission

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        win_rate = len(wins) / len(pnls) * 100 if pnls else 0

        avg_win = np.mean(wins) if wins else 0
        avg_loss = np.mean(losses) if losses else 0
        profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf")
        expectancy = np.mean(pnls) if pnls else 0

        equity = [e["equity"] for e in self.equity_curve] if self.equity_curve else [self.initial_capital]
        max_dd, max_dd_pct = self._max_drawdown(equity)

        sharpe = self._sharpe_ratio(pnls)

        from src.core.constants import OptionType
        ce_trades = [t for t in self.trades if getattr(t, "option_type", None) == OptionType.CALL]
        pe_trades = [t for t in self.trades if getattr(t, "option_type", None) == OptionType.PUT]
        ce_pnl = sum(t.pnl for t in ce_trades)
        pe_pnl = sum(t.pnl for t in pe_trades)

        return {
            "total_trades": len(self.trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round(win_rate, 2),
            "total_pnl": round(total_pnl, 2),
            "total_commission": round(total_commission, 2),
            "net_pnl": round(net_pnl, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "largest_win": round(max(pnls), 2) if pnls else 0,
            "largest_loss": round(min(pnls), 2) if pnls else 0,
            "profit_factor": round(profit_factor, 2),
            "expectancy": round(expectancy, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown": round(max_dd, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "ce_trades": len(ce_trades),
            "pe_trades": len(pe_trades),
            "ce_pnl": round(ce_pnl, 2),
            "pe_pnl": round(pe_pnl, 2),
            "initial_capital": self.initial_capital,
            "final_capital": round(self.initial_capital + net_pnl, 2),
            "return_pct": round((net_pnl / self.initial_capital) * 100, 2),
        }

    def print_summary(self) -> None:
        s = self.summary()
        if "error" in s:
            print(f"\n  {s['error']}\n")
            return

        print("\n" + "=" * 60)
        print("  BACKTEST RESULTS")
        print("=" * 60)

        rows = [
            ["Total Trades", s["total_trades"]],
            ["Win / Loss", f"{s['winning_trades']} / {s['losing_trades']}"],
            ["Win Rate", format_pct(s["win_rate"])],
            ["", ""],
            ["Gross PnL", format_currency(s["total_pnl"])],
            ["Commission", format_currency(-s["total_commission"])],
            ["Net PnL", format_currency(s["net_pnl"])],
            ["Return", format_pct(s["return_pct"])],
            ["", ""],
            ["Avg Win", format_currency(s["avg_win"])],
            ["Avg Loss", format_currency(s["avg_loss"])],
            ["Largest Win", format_currency(s["largest_win"])],
            ["Largest Loss", format_currency(s["largest_loss"])],
            ["Profit Factor", f"{s['profit_factor']:.2f}"],
            ["Expectancy", format_currency(s["expectancy"])],
            ["", ""],
            ["Sharpe Ratio", f"{s['sharpe_ratio']:.2f}"],
            ["Max Drawdown", format_currency(s["max_drawdown"])],
            ["Max DD %", format_pct(s["max_drawdown_pct"])],
            ["", ""],
            ["Buy CE Trades", f"{s['ce_trades']}  ({format_currency(s['ce_pnl'])})"],
            ["Buy PE Trades", f"{s['pe_trades']}  ({format_currency(s['pe_pnl'])})"],
            ["", ""],
            ["Initial Capital", format_currency(s["initial_capital"])],
            ["Final Capital", format_currency(s["final_capital"])],
        ]

        print(tabulate(rows, tablefmt="simple", colalign=("right", "left")))
        print("=" * 60 + "\n")

    def print_trade_log(self, limit: int = 50) -> None:
        if not self.trades:
            print("  No trades.\n")
            return

        headers = ["#", "Type", "Strike", "Entry", "Exit", "SL", "TP", "PnL", "Reason", "Time"]
        rows = []
        for t in self.trades[:limit]:
            from src.core.constants import OptionType
            ot = "CE" if getattr(t, "option_type", None) == OptionType.CALL else "PE"
            strike = getattr(t, "strike", 0)
            rows.append([
                t.trade_id,
                ot,
                f"{strike:.0f}",
                f"{t.entry_price:.2f}",
                f"{t.exit_price:.2f}",
                f"{t.stop_loss:.2f}",
                f"{t.target:.2f}",
                format_currency(t.pnl),
                t.exit_reason.value if t.exit_reason else "",
                t.entry_time.strftime("%Y-%m-%d %H:%M") if hasattr(t.entry_time, "strftime") else str(t.entry_time)[:16],
            ])

        print("\n  TRADE LOG (last %d)" % min(limit, len(self.trades)))
        print(tabulate(rows, headers=headers, tablefmt="simple"))
        if len(self.trades) > limit:
            print(f"  ... and {len(self.trades) - limit} more trades")
        print()

    def export_trades_csv(self, path: str = "backtest_results/trades.csv") -> str:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        if self.trades:
            fieldnames = list(self.trades[0].to_dict().keys())
        else:
            fieldnames = [
                "trade_id", "side", "option_type", "strike",
                "entry_price", "entry_time", "exit_price", "exit_time",
                "quantity", "stop_loss", "target", "underlying_entry",
                "exit_reason", "pnl", "costs", "net_pnl", "reason",
                "grade", "confidence",
            ]
        with open(out, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for t in self.trades:
                writer.writerow(t.to_dict())
        logger.info("Trade log exported to %s", out)
        return str(out)

    def export_equity_csv(self, path: str = "backtest_results/equity.csv") -> str:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame(self.equity_curve)
        df.to_csv(out, index=False)
        logger.info("Equity curve exported to %s", out)
        return str(out)

    @staticmethod
    def _max_drawdown(equity: list[float]) -> tuple[float, float]:
        if not equity:
            return 0.0, 0.0
        peak = equity[0]
        max_dd = 0.0
        max_dd_pct = 0.0
        for val in equity:
            if val > peak:
                peak = val
            dd = peak - val
            dd_pct = (dd / peak * 100) if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
                max_dd_pct = dd_pct
        return max_dd, max_dd_pct

    @staticmethod
    def _sharpe_ratio(pnls: list[float], risk_free_rate: float = 0.06, periods: int = 252) -> float:
        if len(pnls) < 2:
            return 0.0
        returns = np.array(pnls)
        mean_return = np.mean(returns)
        std_return = np.std(returns, ddof=1)
        if std_return == 0:
            return 0.0
        daily_rf = risk_free_rate / periods
        sharpe = (mean_return - daily_rf) / std_return
        return sharpe * np.sqrt(periods)
