'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import Sidebar from '@/components/Sidebar';
import AnimatedNumber from '@/components/ui/AnimatedNumber';
import { clsx } from 'clsx';
import type { Trade } from '@/types/trading';

export default function TradesPage() {
  const router = useRouter();
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'all' | 'win' | 'loss'>('all');
  const [statusFilter, setStatusFilter] = useState<'all' | 'OPEN' | 'CLOSED'>('all');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    if (!api.getToken()) { router.push('/login'); return; }

    const load = async () => {
      try {
        const params: Record<string, string> = { limit: '500' };
        if (filter !== 'all') params.result = filter;
        if (statusFilter !== 'all') params.status = statusFilter;
        const data = await api.getTrades(params);
        setTrades(data);
      } catch { /* handled */ } finally { setLoading(false); }
    };

    load();
    const interval = setInterval(load, 10000);
    return () => clearInterval(interval);
  }, [router, filter, statusFilter]);

  const totalPnl = trades.reduce((sum, t) => sum + (t.pnl || 0), 0);
  const wins = trades.filter((t) => t.pnl > 0).length;
  const losses = trades.filter((t) => t.pnl <= 0 && t.status === 'CLOSED').length;

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto p-6 space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-bold text-white">Trade History</h1>
            <p className="text-sm text-slate-500">{trades.length} trades</p>
          </div>
          <div className="flex items-center gap-4">
            <div className={clsx('flex items-center gap-2 px-3 py-1.5 rounded-lg', totalPnl >= 0 ? 'bg-profit/10' : 'bg-loss/10')}>
              <span className="text-[10px] text-slate-500 uppercase font-semibold">Total</span>
              <AnimatedNumber
                value={totalPnl}
                format={(n) => `${n >= 0 ? '+' : ''}₹${Math.abs(n).toFixed(0)}`}
                className={clsx('text-sm font-bold font-mono', totalPnl >= 0 ? 'text-profit' : 'text-loss')}
              />
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className="text-profit font-semibold">{wins}W</span>
              <span className="text-slate-600">/</span>
              <span className="text-loss font-semibold">{losses}L</span>
            </div>
          </div>
        </div>

        {/* Filters */}
        <div className="flex gap-2 flex-wrap">
          {(['all', 'win', 'loss'] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={clsx('tab-pill capitalize', filter === f ? 'tab-pill-active' : 'tab-pill-inactive')}
            >
              {f}
            </button>
          ))}
          <div className="flex-1" />
          {(['all', 'OPEN', 'CLOSED'] as const).map((f) => (
            <button
              key={f}
              onClick={() => setStatusFilter(f)}
              className={clsx('tab-pill', statusFilter === f ? 'tab-pill-active' : 'tab-pill-inactive')}
            >
              {f === 'all' ? 'All Status' : f}
            </button>
          ))}
        </div>

        {/* Table */}
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-surface-3/60 text-slate-500">
                  <th className="px-4 py-3 text-left">Trade</th>
                  <th className="px-4 py-3 text-left">Type</th>
                  <th className="px-4 py-3 text-right">Entry</th>
                  <th className="px-4 py-3 text-right">Exit</th>
                  <th className="px-4 py-3 text-right">P&L</th>
                  <th className="px-4 py-3 text-left">Reason</th>
                  <th className="px-4 py-3 text-left">Status</th>
                  <th className="px-4 py-3 text-left">Time</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => (
                  <>
                    <tr
                      key={t.trade_id}
                      onClick={() => setExpandedId(expandedId === t.trade_id ? null : t.trade_id)}
                      className={clsx(
                        'border-b border-surface-3/30 cursor-pointer transition-colors',
                        expandedId === t.trade_id ? 'bg-accent/5' : 'hover:bg-surface-2/50',
                      )}
                    >
                      <td className="px-4 py-3 font-mono text-slate-400">{t.trade_id}</td>
                      <td className="px-4 py-3">
                        <span className={clsx('badge', t.option_type === 'CALL' ? 'badge-green' : 'badge-red')}>
                          {t.strike?.toFixed(0)} {t.option_type === 'CALL' ? 'CE' : 'PE'}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-slate-300">₹{t.entry_price?.toFixed(2)}</td>
                      <td className="px-4 py-3 text-right font-mono text-slate-300">
                        {t.exit_price ? `₹${t.exit_price.toFixed(2)}` : '—'}
                      </td>
                      <td className={clsx(
                        'px-4 py-3 text-right font-mono font-semibold',
                        t.status === 'OPEN' ? 'text-slate-400' : t.pnl >= 0 ? 'text-profit' : 'text-loss'
                      )}>
                        {t.status === 'OPEN' ? '—' : `${t.pnl >= 0 ? '+' : ''}₹${t.pnl.toFixed(0)}`}
                      </td>
                      <td className="px-4 py-3 text-slate-400">{t.exit_reason || '—'}</td>
                      <td className="px-4 py-3">
                        <span className={clsx('badge', t.status === 'OPEN' ? 'badge-blue' : 'badge-green')}>{t.status}</span>
                      </td>
                      <td className="px-4 py-3 text-slate-500 font-mono text-[10px]">{formatTime(t.entry_time)}</td>
                    </tr>
                    {expandedId === t.trade_id && (
                      <tr key={`${t.trade_id}-detail`}>
                        <td colSpan={8} className="px-4 py-4 bg-surface-2/30">
                          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs animate-in">
                            <DetailItem label="Symbol" value={t.symbol || '—'} />
                            <DetailItem label="Underlying" value={t.underlying_price ? `₹${t.underlying_price.toFixed(2)}` : '—'} />
                            <DetailItem label="Stop Loss" value={`₹${t.stop_loss?.toFixed(2)}`} />
                            <DetailItem label="Target" value={`₹${t.target?.toFixed(2)}`} />
                            <DetailItem label="Quantity" value={String(t.quantity)} />
                            <DetailItem label="Entry Time" value={t.entry_time?.slice(0, 19)} />
                            <DetailItem label="Exit Time" value={t.exit_time?.slice(0, 19) || '—'} />
                            <DetailItem label="Duration" value={t.entry_time && t.exit_time ? computeDuration(t.entry_time, t.exit_time) : '—'} />
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>

          {trades.length === 0 && !loading && (
            <div className="text-center py-16 text-slate-600 text-sm">No trades found</div>
          )}
        </div>
      </main>
    </div>
  );
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-slate-500 mb-0.5">{label}</div>
      <div className="text-slate-300 font-mono">{value}</div>
    </div>
  );
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString('en-IN', {
      day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
    });
  } catch { return iso?.slice(0, 16) || ''; }
}

function computeDuration(start: string, end: string): string {
  try {
    const ms = new Date(end).getTime() - new Date(start).getTime();
    const mins = Math.floor(ms / 60000);
    if (mins < 60) return `${mins}m`;
    const hours = Math.floor(mins / 60);
    return `${hours}h ${mins % 60}m`;
  } catch { return '—'; }
}
