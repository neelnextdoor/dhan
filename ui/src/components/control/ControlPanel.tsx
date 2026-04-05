'use client';

import { useState, useCallback } from 'react';
import { useTradingStore } from '@/store/tradingStore';
import { api } from '@/lib/api';
import { clsx } from 'clsx';
import ConfirmModal from '@/components/ui/ConfirmModal';
import Spinner from '@/components/ui/Spinner';

export default function ControlPanel() {
  const engineStatus = useTradingStore((s) => s.engineStatus);
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<'paper' | 'live'>('paper');
  const [showStopModal, setShowStopModal] = useState(false);
  const [showKillModal, setShowKillModal] = useState(false);

  const status = engineStatus?.status || 'STOPPED';
  const isRunning = status === 'RUNNING';
  const isStopped = status === 'STOPPED' || status === 'ERROR';
  const isTransition = status === 'STARTING' || status === 'STOPPING';

  const handleStart = useCallback(async () => {
    if (loading) return;
    setLoading('start');
    setError(null);
    try {
      await api.startTrading(mode);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(null);
    }
  }, [mode, loading]);

  const handleStop = useCallback(async () => {
    setLoading('stop');
    setError(null);
    setShowStopModal(false);
    try {
      await api.stopTrading();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(null);
    }
  }, []);

  const handleKill = useCallback(async () => {
    setLoading('kill');
    setError(null);
    setShowKillModal(false);
    try {
      await api.killTrading();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(null);
    }
  }, []);

  const formatUptime = (seconds: number) => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
  };

  return (
    <>
      <div className="card">
        <div className="card-header">
          <h3 className="text-sm font-semibold text-white">Trading Control</h3>
          <StatusPill status={status} />
        </div>

        <div className="card-body space-y-4">
          {/* Mode toggle */}
          {isStopped && (
            <div>
              <label className="label">Trading Mode</label>
              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={() => setMode('paper')}
                  className={clsx(
                    'relative py-2.5 px-3 rounded-lg text-sm font-semibold transition-all duration-200 border',
                    mode === 'paper'
                      ? 'bg-accent/10 text-accent border-accent/30 shadow-sm shadow-accent/10'
                      : 'bg-surface-2 text-slate-400 border-surface-3/60 hover:border-slate-500'
                  )}
                >
                  {mode === 'paper' && <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 bg-accent rounded-full" />}
                  Paper
                </button>
                <button
                  onClick={() => setMode('live')}
                  className={clsx(
                    'relative py-2.5 px-3 rounded-lg text-sm font-semibold transition-all duration-200 border',
                    mode === 'live'
                      ? 'bg-loss/10 text-loss border-loss/30 shadow-sm shadow-loss/10'
                      : 'bg-surface-2 text-slate-400 border-surface-3/60 hover:border-slate-500'
                  )}
                >
                  {mode === 'live' && <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 bg-loss rounded-full animate-pulse" />}
                  Live
                </button>
              </div>
            </div>
          )}

          {/* Main action */}
          {isStopped ? (
            <button
              onClick={handleStart}
              disabled={!!loading}
              className={clsx(
                'w-full py-3 rounded-lg text-sm font-bold transition-all duration-200 flex items-center justify-center gap-2',
                'bg-profit text-white hover:bg-green-600 shadow-md shadow-profit/25 hover:shadow-lg hover:shadow-profit/30',
                'disabled:opacity-40 disabled:cursor-not-allowed active:scale-[0.98]',
              )}
            >
              {loading === 'start' ? (
                <><Spinner size="sm" /> Starting...</>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                  </svg>
                  Start Trading
                </>
              )}
            </button>
          ) : (
            <button
              onClick={() => setShowStopModal(true)}
              disabled={!!loading || isTransition}
              className={clsx(
                'w-full py-3 rounded-lg text-sm font-bold transition-all duration-200 flex items-center justify-center gap-2',
                'bg-surface-2 text-slate-300 border border-surface-3 hover:bg-surface-3',
                'disabled:opacity-40 disabled:cursor-not-allowed active:scale-[0.98]',
              )}
            >
              {loading === 'stop' || isTransition ? (
                <><Spinner size="sm" /> {status === 'STARTING' ? 'Starting...' : 'Stopping...'}</>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M9 10a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z" />
                  </svg>
                  Stop Trading
                </>
              )}
            </button>
          )}

          {/* Kill switch */}
          <button
            onClick={() => setShowKillModal(true)}
            disabled={!!loading}
            className={clsx(
              'w-full py-2.5 rounded-lg text-xs font-bold tracking-widest uppercase transition-all duration-200',
              'bg-red-950/60 text-loss border border-loss/30 hover:bg-loss hover:text-white',
              'disabled:opacity-40 disabled:cursor-not-allowed',
            )}
          >
            {loading === 'kill' ? <Spinner size="sm" className="mx-auto" /> : 'EMERGENCY KILL'}
          </button>

          {/* Running info */}
          {engineStatus && (isRunning || isTransition) && (
            <div className="space-y-2 pt-3 border-t border-surface-3/60">
              <InfoRow label="Mode" value={engineStatus.mode?.toUpperCase()} valueClass={engineStatus.mode === 'live' ? 'text-loss font-bold' : 'text-accent'} />
              <InfoRow label="Symbol" value={engineStatus.symbol} />
              <InfoRow label="Strategy" value={engineStatus.strategy} />
              {isRunning && <InfoRow label="Uptime" value={formatUptime(engineStatus.uptime_seconds)} />}
              {engineStatus.last_tick && (
                <InfoRow label="Last Tick" value={new Date(engineStatus.last_tick).toLocaleTimeString()} />
              )}
            </div>
          )}

          {/* Error */}
          {(error || engineStatus?.error) && (
            <div className="text-xs text-loss bg-red-950/40 border border-loss/20 rounded-lg px-3 py-2.5 flex items-start gap-2">
              <svg className="w-3.5 h-3.5 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span>{error || engineStatus?.error}</span>
            </div>
          )}
        </div>
      </div>

      <ConfirmModal
        open={showStopModal}
        variant="warning"
        title="Stop Trading"
        description="This will gracefully stop the trading engine. Open positions will be managed according to your exit rules."
        confirmLabel="Stop Engine"
        loading={loading === 'stop'}
        onConfirm={handleStop}
        onCancel={() => setShowStopModal(false)}
      />

      <ConfirmModal
        open={showKillModal}
        variant="danger"
        title="Emergency Kill Switch"
        description="This will IMMEDIATELY halt all trading activity and activate the kill switch. Open positions may need manual management. Use only in emergencies."
        confirmLabel="KILL ALL TRADING"
        loading={loading === 'kill'}
        onConfirm={handleKill}
        onCancel={() => setShowKillModal(false)}
      />
    </>
  );
}

function StatusPill({ status }: { status: string }) {
  const config = {
    RUNNING: { bg: 'bg-profit/15', text: 'text-profit', dot: 'bg-profit', glow: true },
    STOPPED: { bg: 'bg-slate-500/15', text: 'text-slate-400', dot: 'bg-slate-500', glow: false },
    STARTING: { bg: 'bg-amber-500/15', text: 'text-amber-400', dot: 'bg-amber-400', glow: false },
    STOPPING: { bg: 'bg-amber-500/15', text: 'text-amber-400', dot: 'bg-amber-400', glow: false },
    ERROR: { bg: 'bg-loss/15', text: 'text-loss', dot: 'bg-loss', glow: false },
  }[status] || { bg: 'bg-slate-500/15', text: 'text-slate-400', dot: 'bg-slate-500', glow: false };

  return (
    <span className={clsx('inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold', config.bg, config.text)}>
      <span className={clsx(
        'w-1.5 h-1.5 rounded-full',
        config.dot,
        config.glow && 'status-running',
        (status === 'STARTING' || status === 'STOPPING') && 'animate-pulse',
      )} />
      {status}
    </span>
  );
}

function InfoRow({ label, value, valueClass }: { label: string; value: string; valueClass?: string }) {
  return (
    <div className="flex justify-between text-xs">
      <span className="text-slate-500">{label}</span>
      <span className={valueClass || 'text-slate-300'}>{value}</span>
    </div>
  );
}
