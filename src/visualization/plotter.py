from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from src.core.config import AppConfig
from src.core.constants import OptionType
from src.core.logger import get_logger

logger = get_logger("plotter")


def _safe_import_matplotlib():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    return plt, mdates


class StrategyPlotter:
    """
    Generates publication-quality charts for backtesting results.

    Plots:
      1. Spot chart with MA + EMA overlay, entry/exit markers
      2. Option premium movement per trade
      3. Equity curve with drawdown shading
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.viz = config.visualization
        self._output_dir = Path(self.viz.output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def plot_all(
        self,
        spot_df: pd.DataFrame,
        trades: list,
        equity_curve: list[dict],
        ma_period: int = 20,
        ema_period: int = 50,
    ) -> list[str]:
        """Generate all charts. Returns list of saved file paths."""
        paths = []

        if self.viz.show_entry_exit:
            p = self.plot_spot_with_signals(spot_df, trades, ma_period, ema_period)
            if p:
                paths.append(p)

        if self.viz.show_equity_curve and equity_curve:
            p = self.plot_equity_curve(equity_curve)
            if p:
                paths.append(p)

        if self.viz.show_option_premium and trades:
            p = self.plot_trade_summary(trades)
            if p:
                paths.append(p)

        return paths

    def plot_spot_with_signals(
        self,
        df: pd.DataFrame,
        trades: list,
        ma_period: int = 20,
        ema_period: int = 50,
    ) -> str | None:
        try:
            plt, mdates = _safe_import_matplotlib()
        except ImportError:
            logger.warning("matplotlib not available — skipping plots")
            return None

        from src.indicators.ema import compute_ma_ema
        df = compute_ma_ema(df, ma_period, ema_period)

        fig, (ax1, ax2) = plt.subplots(
            2, 1,
            figsize=(self.viz.figsize_width, self.viz.figsize_height),
            gridspec_kw={"height_ratios": [3, 1]},
            sharex=True,
        )

        ax1.plot(df.index, df["close"], color="#555555", linewidth=0.8,
                 alpha=0.7, label="Close")
        if "ma" in df.columns:
            ax1.plot(df.index, df["ma"], color="#2196F3", linewidth=1.2,
                     label=f"MA({ma_period})")
        if "ema_of_ma" in df.columns:
            ax1.plot(df.index, df["ema_of_ma"], color="#FF9800", linewidth=1.2,
                     label=f"EMA({ema_period})")

        for t in trades:
            entry_time = t.entry_time
            exit_time = getattr(t, "exit_time", None)
            opt_type = getattr(t, "option_type", None)

            color = "#4CAF50" if opt_type == OptionType.CALL else "#F44336"
            marker = "^" if opt_type == OptionType.CALL else "v"
            label_prefix = "CE" if opt_type == OptionType.CALL else "PE"

            underlying_entry = getattr(t, "underlying_entry", 0) or getattr(t, "underlying_price_at_entry", 0)
            if underlying_entry and underlying_entry > 0:
                ax1.scatter(entry_time, underlying_entry, color=color,
                            marker=marker, s=100, zorder=5, edgecolors="black", linewidth=0.5)

            if exit_time:
                ax1.axvspan(entry_time, exit_time, alpha=0.05, color=color)

        ax1.set_ylabel("Spot Price")
        ax1.set_title(f"{self.config.symbol} — MA({ma_period})/EMA({ema_period}) Crossover Strategy",
                       fontsize=14, fontweight="bold")
        ax1.legend(loc="upper left", fontsize=9)
        ax1.grid(True, alpha=0.3)

        if "volume" in df.columns:
            colors = ["#4CAF50" if c >= o else "#F44336"
                      for c, o in zip(df["close"], df["open"])]
            ax2.bar(df.index, df["volume"], color=colors, alpha=0.6, width=0.002)
            ax2.set_ylabel("Volume")

        ax2.grid(True, alpha=0.3)
        fig.tight_layout()

        path = str(self._output_dir / "spot_signals.png")
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        logger.info("Saved spot chart -> %s", path)
        return path

    def plot_equity_curve(self, equity_curve: list[dict]) -> str | None:
        try:
            plt, mdates = _safe_import_matplotlib()
        except ImportError:
            return None

        eq_df = pd.DataFrame(equity_curve)
        if eq_df.empty or "equity" not in eq_df.columns:
            return None

        fig, (ax1, ax2) = plt.subplots(
            2, 1,
            figsize=(self.viz.figsize_width, self.viz.figsize_height // 2 + 2),
            gridspec_kw={"height_ratios": [3, 1]},
            sharex=True,
        )

        equity = eq_df["equity"].values
        timestamps = eq_df.get("timestamp", range(len(equity)))

        ax1.plot(timestamps, equity, color="#2196F3", linewidth=1.5, label="Equity")
        ax1.fill_between(timestamps, equity, equity[0], alpha=0.1, color="#2196F3")
        ax1.set_ylabel("Equity (₹)")
        ax1.set_title("Equity Curve", fontsize=14, fontweight="bold")
        ax1.legend(loc="upper left")
        ax1.grid(True, alpha=0.3)

        running_max = np.maximum.accumulate(equity)
        drawdown = (equity - running_max)
        ax2.fill_between(timestamps, drawdown, 0, color="#F44336", alpha=0.4)
        ax2.set_ylabel("Drawdown (₹)")
        ax2.grid(True, alpha=0.3)

        fig.tight_layout()
        path = str(self._output_dir / "equity_curve.png")
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        logger.info("Saved equity curve -> %s", path)
        return path

    def plot_trade_summary(self, trades: list) -> str | None:
        try:
            plt, _ = _safe_import_matplotlib()
        except ImportError:
            return None

        if not trades:
            return None

        fig, axes = plt.subplots(2, 2, figsize=(self.viz.figsize_width, self.viz.figsize_height))

        # 1. PnL distribution
        pnls = [getattr(t, "net_pnl", getattr(t, "pnl", 0)) for t in trades]
        colors = ["#4CAF50" if p > 0 else "#F44336" for p in pnls]
        axes[0, 0].bar(range(len(pnls)), pnls, color=colors, alpha=0.8)
        axes[0, 0].axhline(y=0, color="black", linewidth=0.5)
        axes[0, 0].set_title("PnL per Trade")
        axes[0, 0].set_ylabel("₹")

        # 2. Cumulative PnL
        cum_pnl = np.cumsum(pnls)
        axes[0, 1].plot(cum_pnl, color="#2196F3", linewidth=1.5)
        axes[0, 1].fill_between(range(len(cum_pnl)), cum_pnl, 0,
                                 where=[p >= 0 for p in cum_pnl],
                                 color="#4CAF50", alpha=0.2)
        axes[0, 1].fill_between(range(len(cum_pnl)), cum_pnl, 0,
                                 where=[p < 0 for p in cum_pnl],
                                 color="#F44336", alpha=0.2)
        axes[0, 1].set_title("Cumulative PnL")
        axes[0, 1].set_ylabel("₹")

        # 3. CE vs PE breakdown
        ce_pnl = sum(getattr(t, "net_pnl", getattr(t, "pnl", 0))
                      for t in trades if getattr(t, "option_type", None) == OptionType.CALL)
        pe_pnl = sum(getattr(t, "net_pnl", getattr(t, "pnl", 0))
                      for t in trades if getattr(t, "option_type", None) == OptionType.PUT)
        ce_count = sum(1 for t in trades if getattr(t, "option_type", None) == OptionType.CALL)
        pe_count = sum(1 for t in trades if getattr(t, "option_type", None) == OptionType.PUT)

        bar_colors = ["#4CAF50" if ce_pnl >= 0 else "#F44336",
                       "#4CAF50" if pe_pnl >= 0 else "#F44336"]
        axes[1, 0].bar(["CE", "PE"], [ce_pnl, pe_pnl], color=bar_colors, alpha=0.8)
        axes[1, 0].set_title(f"CE ({ce_count}) vs PE ({pe_count}) PnL")
        axes[1, 0].set_ylabel("₹")

        # 4. Win rate by type
        ce_wins = sum(1 for t in trades
                      if getattr(t, "option_type", None) == OptionType.CALL
                      and getattr(t, "net_pnl", getattr(t, "pnl", 0)) > 0)
        pe_wins = sum(1 for t in trades
                      if getattr(t, "option_type", None) == OptionType.PUT
                      and getattr(t, "net_pnl", getattr(t, "pnl", 0)) > 0)
        ce_wr = (ce_wins / ce_count * 100) if ce_count > 0 else 0
        pe_wr = (pe_wins / pe_count * 100) if pe_count > 0 else 0
        total_wr = (sum(1 for p in pnls if p > 0) / len(pnls) * 100) if pnls else 0

        axes[1, 1].bar(["CE", "PE", "Total"], [ce_wr, pe_wr, total_wr],
                        color=["#2196F3", "#FF9800", "#9C27B0"], alpha=0.8)
        axes[1, 1].set_title("Win Rate %")
        axes[1, 1].set_ylabel("%")
        axes[1, 1].set_ylim(0, 100)

        fig.suptitle(f"{self.config.symbol} — Trade Analysis", fontsize=14, fontweight="bold")
        fig.tight_layout()

        path = str(self._output_dir / "trade_summary.png")
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        logger.info("Saved trade summary -> %s", path)
        return path
