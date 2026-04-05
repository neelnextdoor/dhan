'use client';

import { useTradingStore } from '@/store/tradingStore';
import { clsx } from 'clsx';

export default function ActiveTrades() {
  const stats = useTradingStore((s) => s.stats);
  const trades = useTradingStore((s) => s.trades);

  const activeTrade = stats?.current_position;
  const recentClosed = trades
    .filter((t) => t.status === 'CLOSED')
    .slice(-5)
    .reverse();

  return (
    <div className="card">
      <div className="card-header">
        <h3 className="text-sm font-semibold text-white">Active Position</h3>
        {activeTrade && <span className="badge-blue">OPEN</span>}
      </div>
      <div className="card-body">
        {activeTrade ? (
          <div className="space-y-3 animate-in">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-lg font-bold text-white">
                  {activeTrade.symbol}{' '}
                  <span className={activeTrade.option_type === 'CALL' ? 'text-profit' : 'text-loss'}>
                    {activeTrade.strike?.toFixed(0)}{activeTrade.option_type === 'CALL' ? 'CE' : 'PE'}
                  </span>
                </div>
                <div className="text-xs text-slate-500">Qty: {activeTrade.quantity}</div>
              </div>
              <div className="text-right">
                <div className="text-sm font-mono text-slate-300">
                  Entry: ₹{activeTrade.entry_price?.toFixed(2)}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="bg-surface-2/80 rounded-lg p-2.5 border border-surface-3/40">
                <div className="text-[10px] text-loss font-semibold uppercase tracking-wider">SL</div>
                <div className="text-sm font-mono text-slate-300 mt-0.5">
                  ₹{activeTrade.stop_loss?.toFixed(2)}
                </div>
              </div>
              <div className="bg-surface-2/80 rounded-lg p-2.5 border border-surface-3/40">
                <div className="text-[10px] text-profit font-semibold uppercase tracking-wider">Target</div>
                <div className="text-sm font-mono text-slate-300 mt-0.5">
                  ₹{activeTrade.target?.toFixed(2)}
                </div>
              </div>
              <div className="bg-surface-2/80 rounded-lg p-2.5 border border-surface-3/40">
                <div className="text-[10px] text-accent font-semibold uppercase tracking-wider">Trail</div>
                <div className="text-sm font-mono text-slate-300 mt-0.5">
                  ₹{activeTrade.trailing_sl?.toFixed(2)}
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="text-center py-8">
            <div className="text-slate-600 text-sm">No active position</div>
            <div className="text-[10px] text-slate-700 mt-1">Waiting for signal...</div>
          </div>
        )}

        {recentClosed.length > 0 && (
          <div className="mt-4 pt-4 border-t border-surface-3/60">
            <h4 className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">Recent Trades</h4>
            <div className="space-y-1.5">
              {recentClosed.map((t) => (
                <div key={t.trade_id} className="flex items-center justify-between text-xs py-1 hover:bg-surface-2/30 rounded px-1 transition-colors">
                  <div className="flex items-center gap-2">
                    <span className={clsx(
                      'w-1.5 h-1.5 rounded-full',
                      t.pnl > 0 ? 'bg-profit' : 'bg-loss'
                    )} />
                    <span className="text-slate-400">
                      {t.strike?.toFixed(0)}{t.option_type === 'CALL' ? 'CE' : 'PE'}
                    </span>
                  </div>
                  <span className="text-slate-600 text-[10px]">{t.exit_reason}</span>
                  <span className={clsx('font-mono font-semibold', t.pnl > 0 ? 'text-profit' : 'text-loss')}>
                    {t.pnl > 0 ? '+' : ''}₹{t.pnl.toFixed(0)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
