'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import { useTradingStore } from '@/store/tradingStore';
import { useWebSocket } from '@/hooks/useWebSocket';
import Sidebar from '@/components/Sidebar';
import StatsGrid from '@/components/dashboard/StatsGrid';
import ActiveTrades from '@/components/dashboard/ActiveTrades';
import ControlPanel from '@/components/control/ControlPanel';
import PriceChart from '@/components/charts/PriceChart';
import AnimatedNumber from '@/components/ui/AnimatedNumber';
import { clsx } from 'clsx';

export default function DashboardPage() {
  const router = useRouter();
  const { setEngineStatus, setStats, setCandles, setTrades, engineStatus, stats, wsConnected } = useTradingStore();

  useWebSocket();

  useEffect(() => {
    if (!api.getToken()) {
      router.push('/login');
      return;
    }

    const poll = async () => {
      try {
        const [status, st, candles, trades] = await Promise.all([
          api.getStatus(), api.getStats(), api.getCandles(), api.getTrades(),
        ]);
        setEngineStatus(status);
        setStats(st);
        if (candles?.length) setCandles(candles);
        if (trades?.length) setTrades(trades);
      } catch { /* 401 redirects */ }
    };

    poll();
    const interval = setInterval(poll, 5000);
    return () => clearInterval(interval);
  }, [router, setEngineStatus, setStats, setCandles, setTrades]);

  if (!api.getToken()) return null;

  const statusColor = {
    RUNNING: 'text-profit', STOPPED: 'text-slate-500', STARTING: 'text-warn',
    STOPPING: 'text-warn', ERROR: 'text-loss',
  }[engineStatus?.status || 'STOPPED'];

  const pnl = stats?.daily_pnl ?? 0;

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        {/* Top Bar */}
        <div className="sticky top-0 z-10 bg-surface-0/80 backdrop-blur-xl border-b border-surface-3/40">
          <div className="flex items-center justify-between px-6 py-3">
            <div className="flex items-center gap-6">
              <div>
                <h1 className="text-lg font-bold text-white">Dashboard</h1>
              </div>
              {/* Live PnL in top bar */}
              <div className={clsx('flex items-center gap-2 px-4 py-1.5 rounded-lg', pnl > 0 ? 'bg-profit/10' : pnl < 0 ? 'bg-loss/10' : 'bg-surface-2')}>
                <span className="text-[10px] text-slate-500 uppercase font-semibold">P&L</span>
                <AnimatedNumber
                  value={pnl}
                  format={(n) => `${n >= 0 ? '+' : ''}₹${Math.abs(n).toFixed(0)}`}
                  className={clsx('text-sm font-bold font-mono', pnl > 0 ? 'text-profit' : pnl < 0 ? 'text-loss' : 'text-slate-400')}
                />
              </div>
            </div>

            <div className="flex items-center gap-4">
              {/* Status */}
              <div className="flex items-center gap-2">
                <div className={clsx(
                  'w-2 h-2 rounded-full',
                  engineStatus?.status === 'RUNNING' && 'bg-profit status-running',
                  engineStatus?.status === 'STOPPED' && 'bg-slate-500',
                  (engineStatus?.status === 'STARTING' || engineStatus?.status === 'STOPPING') && 'bg-warn animate-pulse',
                  engineStatus?.status === 'ERROR' && 'bg-loss',
                )} />
                <span className={clsx('text-xs font-semibold', statusColor)}>
                  {engineStatus?.status || 'STOPPED'}
                </span>
                {engineStatus?.mode && engineStatus.status === 'RUNNING' && (
                  <span className={clsx('badge', engineStatus.mode === 'live' ? 'badge-red' : 'badge-blue')}>
                    {engineStatus.mode.toUpperCase()}
                  </span>
                )}
              </div>

              {/* WS indicator */}
              <div className="flex items-center gap-1.5">
                <div className={clsx('w-1.5 h-1.5 rounded-full', wsConnected ? 'bg-profit' : 'bg-slate-600')} />
                <span className="text-[10px] text-slate-500">{wsConnected ? 'Live' : 'Offline'}</span>
              </div>

              {/* Date */}
              <span className="text-xs text-slate-600 font-mono">
                {new Date().toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })}
              </span>
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="p-6 space-y-4">
          <StatsGrid />

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="lg:col-span-2">
              <PriceChart />
            </div>
            <div className="space-y-4">
              <ControlPanel />
              <ActiveTrades />
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
