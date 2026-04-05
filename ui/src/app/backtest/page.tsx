'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import Sidebar from '@/components/Sidebar';
import Spinner from '@/components/ui/Spinner';
import { clsx } from 'clsx';
import type { BacktestResult } from '@/types/trading';

export default function BacktestPage() {
  const router = useRouter();
  const [startDate, setStartDate] = useState('2025-01-01');
  const [endDate, setEndDate] = useState('2025-12-31');
  const [csvPath, setCsvPath] = useState('');
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<'chart' | 'summary' | 'trades'>('chart');
  const [selectedTrade, setSelectedTrade] = useState<any | null>(null);

  // Replay state
  const [replayMode, setReplayMode] = useState(false);
  const [replayIndex, setReplayIndex] = useState(0);
  const [replaySpeed, setReplaySpeed] = useState(1);
  const [replayPlaying, setReplayPlaying] = useState(false);
  const replayTimerRef = useRef<NodeJS.Timeout>();

  const candleChartRef = useRef<HTMLDivElement>(null);
  const equityChartRef = useRef<HTMLDivElement>(null);
  const drawdownChartRef = useRef<HTMLDivElement>(null);
  const chartInstanceRef = useRef<any>(null);
  const candleSeriesRef = useRef<any>(null);
  const emaSeriesRefs = useRef<any>({});

  useEffect(() => {
    if (!api.getToken()) router.push('/login');
  }, [router]);

  const runBacktest = async () => {
    setRunning(true);
    setError(null);
    setResult(null);
    setSelectedTrade(null);
    setReplayMode(false);
    setReplayPlaying(false);
    try {
      const res = await api.runBacktest({
        start_date: startDate,
        end_date: endDate,
        csv_path: csvPath || undefined,
      });
      setResult(res);
      setActiveView('chart');
    } catch (e: any) {
      setError(e.message);
    } finally {
      setRunning(false);
    }
  };

  // === Main candle chart with markers ===
  useEffect(() => {
    if (!result?.equity_curve?.length || activeView !== 'chart' || !candleChartRef.current) return;

    let chart: any;
    const init = async () => {
      const { createChart, ColorType, CrosshairMode } = await import('lightweight-charts');

      chart = createChart(candleChartRef.current!, {
        layout: { background: { type: ColorType.Solid, color: '#0f172a' }, textColor: '#64748b' },
        grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
        crosshair: { mode: CrosshairMode.Normal },
        rightPriceScale: { borderColor: '#1e293b' },
        timeScale: { borderColor: '#1e293b', timeVisible: false },
        width: candleChartRef.current!.clientWidth,
        height: 420,
      });
      chartInstanceRef.current = chart;

      const candleSeries = chart.addCandlestickSeries({
        upColor: '#22c55e', downColor: '#ef4444',
        borderDownColor: '#ef4444', borderUpColor: '#22c55e',
        wickDownColor: '#ef444480', wickUpColor: '#22c55e80',
      });
      candleSeriesRef.current = candleSeries;

      // Build OHLC from equity curve price data
      const priceMap = new Map<string, { o: number; h: number; l: number; c: number }>();
      for (const e of result!.equity_curve) {
        const day = e.timestamp.slice(0, 10);
        const prev = priceMap.get(day);
        if (prev) {
          prev.h = Math.max(prev.h, e.price);
          prev.l = Math.min(prev.l, e.price);
          prev.c = e.price;
        } else {
          priceMap.set(day, { o: e.price, h: e.price, l: e.price, c: e.price });
        }
      }

      const candleData = Array.from(priceMap.entries())
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([time, v]) => ({ time: time as any, open: v.o, high: v.h, low: v.l, close: v.c }));

      const visibleData = replayMode ? candleData.slice(0, replayIndex + 1) : candleData;
      candleSeries.setData(visibleData);

      // EMA overlays
      const closePrices = visibleData.map(c => c.close);
      const emaColors: Record<number, string> = { 7: '#f59e0b', 21: '#3b82f6', 50: '#8b5cf6' };
      for (const period of [7, 21, 50]) {
        const series = chart.addLineSeries({ color: emaColors[period], lineWidth: 1, title: `EMA ${period}` });
        if (closePrices.length > period) {
          const emaVals = computeEMA(closePrices, period);
          const lineData = emaVals
            .map((val, i) => val !== null ? { time: visibleData[i].time, value: val } : null)
            .filter(Boolean);
          series.setData(lineData);
        }
        emaSeriesRefs.current[period] = series;
      }

      // Trade markers
      const markers: any[] = [];
      const trades = result!.trades || [];
      const visibleTrades = replayMode
        ? trades.filter(t => t.entry_time?.slice(0, 10) <= (visibleData[visibleData.length - 1]?.time || ''))
        : trades;

      for (const t of visibleTrades) {
        const entryDay = t.entry_time?.slice(0, 10);
        const exitDay = t.exit_time?.slice(0, 10);
        const isLong = t.option_type === 'CE';

        if (entryDay) {
          markers.push({
            time: entryDay,
            position: isLong ? 'belowBar' : 'aboveBar',
            color: isLong ? '#22c55e' : '#ef4444',
            shape: isLong ? 'arrowUp' : 'arrowDown',
            text: `${isLong ? 'BUY CE' : 'BUY PE'} ${t.strike?.toFixed?.(0) || ''} @₹${t.entry_price?.toFixed?.(1) || ''}`,
          });
        }

        if (exitDay && t.exit_reason) {
          const isTarget = t.exit_reason === 'TARGET';
          markers.push({
            time: exitDay,
            position: isLong ? 'aboveBar' : 'belowBar',
            color: isTarget ? '#22c55e' : '#ef4444',
            shape: 'circle',
            text: `${t.exit_reason} ${t.pnl >= 0 ? '+' : ''}₹${t.pnl?.toFixed?.(0) || ''}`,
          });
        }
      }

      markers.sort((a, b) => (a.time as string).localeCompare(b.time as string));
      candleSeries.setMarkers(markers);
      chart.timeScale().fitContent();

      const handleResize = () => {
        if (candleChartRef.current && chart) {
          chart.applyOptions({ width: candleChartRef.current.clientWidth });
        }
      };
      window.addEventListener('resize', handleResize);
      return () => window.removeEventListener('resize', handleResize);
    };

    init();
    return () => { chart?.remove(); chartInstanceRef.current = null; };
  }, [result, activeView, replayMode, replayIndex]);

  // === Equity curve chart ===
  useEffect(() => {
    if (!result?.equity_curve?.length || activeView !== 'chart' || !equityChartRef.current) return;

    let chart: any;
    const init = async () => {
      const { createChart, ColorType } = await import('lightweight-charts');
      chart = createChart(equityChartRef.current!, {
        layout: { background: { type: ColorType.Solid, color: '#0f172a' }, textColor: '#64748b' },
        grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
        rightPriceScale: { borderColor: '#1e293b' },
        timeScale: { borderColor: '#1e293b', visible: false },
        width: equityChartRef.current!.clientWidth,
        height: 150,
      });

      const deduped = new Map<string, number>();
      const visibleCurve = replayMode
        ? result!.equity_curve.slice(0, Math.floor(result!.equity_curve.length * (replayIndex + 1) / getMaxReplayIndex()))
        : result!.equity_curve;
      for (const e of visibleCurve) {
        deduped.set(e.timestamp.slice(0, 10), e.equity);
      }
      const data = Array.from(deduped.entries())
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([time, value]) => ({ time: time as any, value }));

      const initial = result!.summary.initial_capital || data[0]?.value || 0;
      const area = chart.addAreaSeries({
        lineColor: data[data.length - 1]?.value >= initial ? '#22c55e' : '#ef4444',
        topColor: data[data.length - 1]?.value >= initial ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.15)',
        bottomColor: 'transparent',
        lineWidth: 2,
      });
      area.setData(data);
      chart.timeScale().fitContent();
    };

    init();
    return () => chart?.remove();
  }, [result, activeView, replayMode, replayIndex]);

  // === Drawdown chart ===
  useEffect(() => {
    if (!result?.equity_curve?.length || activeView !== 'chart' || !drawdownChartRef.current) return;

    let chart: any;
    const init = async () => {
      const { createChart, ColorType } = await import('lightweight-charts');
      chart = createChart(drawdownChartRef.current!, {
        layout: { background: { type: ColorType.Solid, color: '#0f172a' }, textColor: '#64748b' },
        grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
        rightPriceScale: { borderColor: '#1e293b' },
        timeScale: { borderColor: '#1e293b', visible: false },
        width: drawdownChartRef.current!.clientWidth,
        height: 120,
      });

      const deduped = new Map<string, number>();
      for (const e of result!.equity_curve) {
        deduped.set(e.timestamp.slice(0, 10), e.equity);
      }
      const equities = Array.from(deduped.entries()).sort(([a], [b]) => a.localeCompare(b));

      let peak = 0;
      const ddData = equities.map(([time, eq]) => {
        peak = Math.max(peak, eq);
        const dd = peak > 0 ? ((eq - peak) / peak) * 100 : 0;
        return { time: time as any, value: dd };
      });

      const area = chart.addAreaSeries({
        lineColor: '#ef4444',
        topColor: 'transparent',
        bottomColor: 'rgba(239,68,68,0.15)',
        lineWidth: 1,
      });
      area.setData(ddData);
      chart.timeScale().fitContent();
    };

    init();
    return () => chart?.remove();
  }, [result, activeView]);

  // === Replay controls ===
  const getMaxReplayIndex = useCallback(() => {
    if (!result?.equity_curve?.length) return 0;
    const priceMap = new Map<string, boolean>();
    for (const e of result.equity_curve) priceMap.set(e.timestamp.slice(0, 10), true);
    return priceMap.size - 1;
  }, [result]);

  useEffect(() => {
    if (!replayPlaying || !replayMode) return;
    const maxIdx = getMaxReplayIndex();
    const delay = Math.max(50, 500 / replaySpeed);
    replayTimerRef.current = setInterval(() => {
      setReplayIndex(prev => {
        if (prev >= maxIdx) { setReplayPlaying(false); return maxIdx; }
        return prev + 1;
      });
    }, delay);
    return () => { if (replayTimerRef.current) clearInterval(replayTimerRef.current); };
  }, [replayPlaying, replayMode, replaySpeed, getMaxReplayIndex]);

  const handleReplayToggle = () => {
    if (!replayMode) {
      setReplayMode(true);
      setReplayIndex(0);
      setReplayPlaying(true);
    } else {
      setReplayPlaying(!replayPlaying);
    }
  };

  const handleReplayStop = () => {
    setReplayMode(false);
    setReplayPlaying(false);
    setReplayIndex(0);
  };

  const s = result?.summary;

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto p-6 space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-bold text-white">Backtesting</h1>
            <p className="text-sm text-slate-500">Test strategy on historical data</p>
          </div>
        </div>

        {/* Controls */}
        <div className="card card-body">
          <div className="grid grid-cols-1 md:grid-cols-5 gap-4 items-end">
            <div>
              <label className="label">Start Date</label>
              <input type="date" className="input" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
            </div>
            <div>
              <label className="label">End Date</label>
              <input type="date" className="input" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
            </div>
            <div>
              <label className="label">CSV Path (optional)</label>
              <input className="input" placeholder="data/nifty.csv" value={csvPath} onChange={(e) => setCsvPath(e.target.value)} />
            </div>
            <button onClick={runBacktest} disabled={running} className="btn-primary h-[42px] flex items-center justify-center gap-2">
              {running ? <><Spinner size="sm" /> Running...</> : 'Run Backtest'}
            </button>
            {result && (
              <button onClick={handleReplayToggle} className="btn-ghost h-[42px] flex items-center justify-center gap-2">
                {replayPlaying ? (
                  <><PauseIcon /> Pause</>
                ) : replayMode ? (
                  <><PlayIcon /> Resume</>
                ) : (
                  <><PlayIcon /> Replay</>
                )}
              </button>
            )}
          </div>
          {error && <div className="mt-3 text-sm text-loss bg-red-950/40 border border-loss/20 rounded-lg px-3 py-2.5">{error}</div>}

          {/* Replay bar */}
          {replayMode && (
            <div className="flex items-center gap-4 mt-4 pt-4 border-t border-surface-3/60">
              <button onClick={handleReplayToggle} className="btn-ghost py-1.5 px-3">
                {replayPlaying ? <PauseIcon /> : <PlayIcon />}
              </button>
              <button onClick={handleReplayStop} className="btn-ghost py-1.5 px-3 text-xs">Stop</button>
              <input
                type="range" min={0} max={getMaxReplayIndex()} value={replayIndex}
                onChange={(e) => { setReplayIndex(Number(e.target.value)); setReplayPlaying(false); }}
                className="flex-1 accent-accent h-1"
              />
              <div className="flex items-center gap-1">
                {[1, 2, 5, 10].map(sp => (
                  <button
                    key={sp}
                    onClick={() => setReplaySpeed(sp)}
                    className={clsx('px-2 py-1 rounded text-[10px] font-bold', replaySpeed === sp ? 'bg-accent text-white' : 'bg-surface-2 text-slate-400')}
                  >
                    {sp}x
                  </button>
                ))}
              </div>
              <span className="text-xs text-slate-500 font-mono">{replayIndex}/{getMaxReplayIndex()}</span>
            </div>
          )}
        </div>

        {/* Results */}
        {s && !s.error && (
          <>
            {/* Tabs */}
            <div className="flex gap-1 bg-surface-1 border border-surface-3/60 rounded-xl p-1">
              {([
                { id: 'chart', label: 'Chart & Trades' },
                { id: 'summary', label: 'Summary' },
                { id: 'trades', label: 'Trade List' },
              ] as const).map(tab => (
                <button
                  key={tab.id}
                  onClick={() => setActiveView(tab.id)}
                  className={clsx('tab-pill', activeView === tab.id ? 'tab-pill-active' : 'tab-pill-inactive')}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {activeView === 'chart' && (
              <div className="space-y-3">
                {/* Main chart */}
                <div className="card overflow-hidden">
                  <div className="card-header">
                    <h3 className="text-sm font-semibold text-white">Price Chart + Trade Markers</h3>
                    <div className="flex items-center gap-3 text-[10px]">
                      <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-[#f59e0b] rounded" /> EMA 7</span>
                      <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-[#3b82f6] rounded" /> EMA 21</span>
                      <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-[#8b5cf6] rounded" /> EMA 50</span>
                      <span className="text-slate-600">|</span>
                      <span className="flex items-center gap-1"><span className="text-profit">▲</span> Long</span>
                      <span className="flex items-center gap-1"><span className="text-loss">▼</span> Short</span>
                    </div>
                  </div>
                  <div ref={candleChartRef} className="h-[420px]" />
                </div>

                {/* Equity + Drawdown side by side */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div className="card overflow-hidden">
                    <div className="card-header">
                      <h3 className="text-xs font-semibold text-white">Equity Curve</h3>
                      <span className={clsx('text-xs font-bold font-mono', (s.net_pnl ?? 0) >= 0 ? 'text-profit' : 'text-loss')}>
                        {(s.net_pnl ?? 0) >= 0 ? '+' : ''}₹{s.net_pnl?.toLocaleString()}
                      </span>
                    </div>
                    <div ref={equityChartRef} className="h-[150px]" />
                  </div>
                  <div className="card overflow-hidden">
                    <div className="card-header">
                      <h3 className="text-xs font-semibold text-white">Drawdown</h3>
                      <span className="text-xs font-bold font-mono text-loss">-{s.max_drawdown_pct?.toFixed(1)}%</span>
                    </div>
                    <div ref={drawdownChartRef} className="h-[150px]" />
                  </div>
                </div>
              </div>
            )}

            {activeView === 'summary' && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <MetricCard label="Total Trades" value={s.total_trades} />
                <MetricCard label="Win Rate" value={`${s.win_rate}%`} color={s.win_rate >= 50 ? 'text-profit' : 'text-loss'} />
                <MetricCard label="Net P&L" value={`₹${s.net_pnl?.toLocaleString()}`} color={s.net_pnl >= 0 ? 'text-profit' : 'text-loss'} />
                <MetricCard label="Return" value={`${s.return_pct}%`} color={s.return_pct >= 0 ? 'text-profit' : 'text-loss'} />
                <MetricCard label="Profit Factor" value={s.profit_factor?.toFixed(2)} color={s.profit_factor >= 1 ? 'text-profit' : 'text-loss'} />
                <MetricCard label="Sharpe Ratio" value={s.sharpe_ratio?.toFixed(2)} />
                <MetricCard label="Max Drawdown" value={`₹${s.max_drawdown?.toLocaleString()}`} color="text-loss" />
                <MetricCard label="Max DD %" value={`${s.max_drawdown_pct}%`} color="text-loss" />
                <MetricCard label="Avg Win" value={`₹${s.avg_win?.toLocaleString()}`} color="text-profit" />
                <MetricCard label="Avg Loss" value={`₹${Math.abs(s.avg_loss)?.toLocaleString()}`} color="text-loss" />
                <MetricCard label="Largest Win" value={`₹${s.largest_win?.toLocaleString()}`} color="text-profit" />
                <MetricCard label="Largest Loss" value={`₹${Math.abs(s.largest_loss)?.toLocaleString()}`} color="text-loss" />
                <MetricCard label="CE Trades" value={`${s.ce_trades} (₹${s.ce_pnl?.toLocaleString()})`} />
                <MetricCard label="PE Trades" value={`${s.pe_trades} (₹${s.pe_pnl?.toLocaleString()})`} />
                <MetricCard label="Initial Capital" value={`₹${s.initial_capital?.toLocaleString()}`} />
                <MetricCard label="Final Capital" value={`₹${s.final_capital?.toLocaleString()}`} color={s.final_capital >= s.initial_capital ? 'text-profit' : 'text-loss'} />
              </div>
            )}

            {activeView === 'trades' && (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div className="lg:col-span-2 card overflow-hidden">
                  <div className="card-header">
                    <h3 className="text-sm font-semibold text-white">Trade List ({result?.trades?.length})</h3>
                  </div>
                  <div className="overflow-x-auto max-h-[600px]">
                    <table className="w-full text-xs">
                      <thead className="sticky top-0 bg-surface-1">
                        <tr className="border-b border-surface-3/60 text-slate-500">
                          <th className="px-3 py-2.5 text-left">#</th>
                          <th className="px-3 py-2.5 text-left">Type</th>
                          <th className="px-3 py-2.5 text-right">Entry</th>
                          <th className="px-3 py-2.5 text-right">Exit</th>
                          <th className="px-3 py-2.5 text-right">P&L</th>
                          <th className="px-3 py-2.5 text-left">Reason</th>
                          <th className="px-3 py-2.5 text-left">Grade</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result?.trades?.map((t: any) => (
                          <tr
                            key={t.trade_id}
                            onClick={() => setSelectedTrade(t)}
                            className={clsx(
                              'border-b border-surface-3/30 cursor-pointer transition-colors',
                              selectedTrade?.trade_id === t.trade_id ? 'bg-accent/10' : 'hover:bg-surface-2',
                            )}
                          >
                            <td className="px-3 py-2 text-slate-500">{t.trade_id}</td>
                            <td className="px-3 py-2">
                              <span className={t.option_type === 'CE' ? 'text-profit' : 'text-loss'}>
                                {t.strike?.toFixed(0)} {t.option_type}
                              </span>
                            </td>
                            <td className="px-3 py-2 text-right font-mono text-slate-300">₹{t.entry_price?.toFixed(2)}</td>
                            <td className="px-3 py-2 text-right font-mono text-slate-300">₹{t.exit_price?.toFixed(2)}</td>
                            <td className={clsx('px-3 py-2 text-right font-mono font-semibold', t.pnl >= 0 ? 'text-profit' : 'text-loss')}>
                              {t.pnl >= 0 ? '+' : ''}₹{t.pnl?.toFixed(0)}
                            </td>
                            <td className="px-3 py-2 text-slate-400">{t.exit_reason}</td>
                            <td className="px-3 py-2">
                              <span className={clsx('badge', t.grade === 'A+' || t.grade === 'A' ? 'badge-green' : 'badge-yellow')}>
                                {t.grade}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Trade detail panel */}
                <div className="card">
                  <div className="card-header">
                    <h3 className="text-sm font-semibold text-white">Trade Details</h3>
                  </div>
                  <div className="card-body">
                    {selectedTrade ? (
                      <div className="space-y-3 animate-in">
                        <div className="text-center pb-3 border-b border-surface-3/60">
                          <span className={clsx('text-xl font-bold', selectedTrade.pnl >= 0 ? 'text-profit' : 'text-loss')}>
                            {selectedTrade.pnl >= 0 ? '+' : ''}₹{selectedTrade.pnl?.toFixed(0)}
                          </span>
                          <div className="text-xs text-slate-500 mt-1">
                            {selectedTrade.strike?.toFixed(0)} {selectedTrade.option_type}
                          </div>
                        </div>
                        <DetailRow label="Entry Price" value={`₹${selectedTrade.entry_price?.toFixed(2)}`} />
                        <DetailRow label="Exit Price" value={`₹${selectedTrade.exit_price?.toFixed(2)}`} />
                        <DetailRow label="Stop Loss" value={`₹${selectedTrade.stop_loss?.toFixed(2)}`} />
                        <DetailRow label="Target" value={`₹${selectedTrade.target?.toFixed(2)}`} />
                        <DetailRow label="Entry Time" value={selectedTrade.entry_time?.slice(0, 16)} />
                        <DetailRow label="Exit Time" value={selectedTrade.exit_time?.slice(0, 16)} />
                        <DetailRow label="Exit Reason" value={selectedTrade.exit_reason} highlight />
                        <DetailRow label="Entry Reason" value={selectedTrade.reason || '—'} />
                        <DetailRow label="Grade" value={selectedTrade.grade} />
                        <DetailRow label="Confidence" value={`${(selectedTrade.confidence * 100).toFixed(0)}%`} />
                        {/* RR achieved */}
                        {selectedTrade.entry_price && selectedTrade.stop_loss && (
                          <DetailRow
                            label="R:R Achieved"
                            value={(() => {
                              const risk = Math.abs(selectedTrade.entry_price - selectedTrade.stop_loss);
                              return risk > 0 ? `${(selectedTrade.pnl / (risk * selectedTrade.quantity || 1)).toFixed(2)}R` : '—';
                            })()}
                            highlight
                          />
                        )}
                      </div>
                    ) : (
                      <div className="text-center py-8 text-slate-600 text-sm">Click a trade to view details</div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}

function MetricCard({ label, value, color }: { label: string; value: any; color?: string }) {
  return (
    <div className="card p-4">
      <div className={clsx('text-lg font-bold font-mono', color || 'text-white')}>{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

function DetailRow({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex justify-between text-xs">
      <span className="text-slate-500">{label}</span>
      <span className={highlight ? 'text-accent font-semibold' : 'text-slate-300 font-mono'}>{value}</span>
    </div>
  );
}

function PlayIcon() {
  return (
    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}

function PauseIcon() {
  return (
    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
      <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" />
    </svg>
  );
}

function computeEMA(prices: number[], period: number): (number | null)[] {
  const result: (number | null)[] = [];
  const k = 2 / (period + 1);
  let ema: number | null = null;
  for (let i = 0; i < prices.length; i++) {
    if (i < period - 1) { result.push(null); }
    else if (ema === null) {
      ema = prices.slice(0, period).reduce((a, b) => a + b, 0) / period;
      result.push(ema);
    } else {
      ema = prices[i] * k + ema * (1 - k);
      result.push(ema);
    }
  }
  return result;
}
