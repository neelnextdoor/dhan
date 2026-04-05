'use client';

import { useTradingStore } from '@/store/tradingStore';
import { clsx } from 'clsx';
import AnimatedNumber from '@/components/ui/AnimatedNumber';

export default function StatsGrid() {
  const stats = useTradingStore((s) => s.stats);

  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
      {/* PnL — hero card */}
      <div className={clsx(
        'card p-4 md:col-span-1',
        (stats?.daily_pnl ?? 0) > 0 && 'glow-green border-emerald-500/20',
        (stats?.daily_pnl ?? 0) < 0 && 'glow-red border-red-500/20',
      )}>
        <AnimatedNumber
          value={stats?.daily_pnl ?? 0}
          format={formatCurrency}
          className={clsx('stat-value', pnlColor(stats?.daily_pnl ?? 0))}
        />
        <div className="stat-label">Day P&L</div>
      </div>

      {/* Win Rate */}
      <div className="card p-4">
        <div className="flex items-baseline gap-1.5">
          <AnimatedNumber
            value={stats?.win_rate ?? 0}
            format={(n) => `${n.toFixed(1)}%`}
            className={clsx('stat-value', (stats?.win_rate ?? 0) >= 50 ? 'text-profit' : 'text-loss')}
          />
        </div>
        <div className="stat-label">Win Rate</div>
        <div className="flex items-center gap-2 mt-1.5">
          <span className="text-[10px] text-profit font-mono">{stats?.winning_trades ?? 0}W</span>
          <span className="text-[10px] text-slate-600">/</span>
          <span className="text-[10px] text-loss font-mono">{stats?.losing_trades ?? 0}L</span>
        </div>
      </div>

      {/* Trades */}
      <div className="card p-4">
        <AnimatedNumber
          value={stats?.total_trades_today ?? 0}
          className="stat-value text-white"
        />
        <div className="stat-label">Trades Today</div>
      </div>

      {/* Capital */}
      <div className="card p-4">
        <AnimatedNumber
          value={stats?.capital_deployed ?? 0}
          format={formatCurrency}
          className="stat-value text-white"
        />
        <div className="stat-label">Capital</div>
      </div>

      {/* Risk */}
      <div className="card p-4">
        <AnimatedNumber
          value={stats?.risk_usage_pct ?? 0}
          format={(n) => `${n.toFixed(1)}%`}
          className={clsx(
            'stat-value',
            (stats?.risk_usage_pct ?? 0) > 80 ? 'text-loss' :
            (stats?.risk_usage_pct ?? 0) > 50 ? 'text-warn' : 'text-profit'
          )}
        />
        <div className="stat-label">Risk Usage</div>
        {/* Progress bar */}
        <div className="w-full h-1 bg-surface-3 rounded-full mt-2 overflow-hidden">
          <div
            className={clsx(
              'h-full rounded-full transition-all duration-500',
              (stats?.risk_usage_pct ?? 0) > 80 ? 'bg-loss' :
              (stats?.risk_usage_pct ?? 0) > 50 ? 'bg-warn' : 'bg-profit'
            )}
            style={{ width: `${Math.min(stats?.risk_usage_pct ?? 0, 100)}%` }}
          />
        </div>
      </div>
    </div>
  );
}

function formatCurrency(n: number): string {
  const abs = Math.abs(n);
  const formatted = abs >= 100000
    ? `${(abs / 100000).toFixed(2)}L`
    : abs >= 1000
    ? `${(abs / 1000).toFixed(1)}K`
    : abs.toFixed(0);
  return `${n < 0 ? '-' : n > 0 ? '+' : ''}₹${formatted}`;
}

function pnlColor(n: number): string {
  if (n > 0) return 'text-profit';
  if (n < 0) return 'text-loss';
  return 'text-slate-400';
}
