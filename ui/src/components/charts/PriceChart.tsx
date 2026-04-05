'use client';

import { useEffect, useRef, useMemo } from 'react';
import { useTradingStore } from '@/store/tradingStore';

export default function PriceChart() {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const candleSeriesRef = useRef<any>(null);
  const emaRefs = useRef<{ [key: string]: any }>({});
  const candles = useTradingStore((s) => s.candles);

  const chartData = useMemo(() => {
    const deduped = new Map<string, { time: any; open: number; high: number; low: number; close: number }>();
    for (const c of candles) {
      const key = c.time.slice(0, 10);
      const prev = deduped.get(key);
      if (prev) {
        prev.high = Math.max(prev.high, c.high);
        prev.low = Math.min(prev.low, c.low);
        prev.close = c.close;
      } else {
        deduped.set(key, { time: key as any, open: c.open, high: c.high, low: c.low, close: c.close });
      }
    }
    return Array.from(deduped.values()).sort((a, b) => (a.time as string).localeCompare(b.time as string));
  }, [candles]);

  useEffect(() => {
    if (!containerRef.current) return;

    let chart: any;

    const init = async () => {
      const { createChart, ColorType, CrosshairMode } = await import('lightweight-charts');

      if (chartRef.current) chartRef.current.remove();

      chart = createChart(containerRef.current!, {
        layout: { background: { type: ColorType.Solid, color: '#0f172a' }, textColor: '#64748b' },
        grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
        crosshair: { mode: CrosshairMode.Normal },
        rightPriceScale: { borderColor: '#1e293b' },
        timeScale: { borderColor: '#1e293b', timeVisible: true },
        width: containerRef.current!.clientWidth,
        height: containerRef.current!.clientHeight,
      });

      const candleSeries = chart.addCandlestickSeries({
        upColor: '#22c55e', downColor: '#ef4444',
        borderDownColor: '#ef4444', borderUpColor: '#22c55e',
        wickDownColor: '#ef444480', wickUpColor: '#22c55e80',
      });

      chartRef.current = chart;
      candleSeriesRef.current = candleSeries;

      const emaColors = ['#f59e0b', '#3b82f6', '#8b5cf6'];
      [7, 21, 50].forEach((period, i) => {
        const series = chart.addLineSeries({
          color: emaColors[i], lineWidth: 1, title: `EMA ${period}`,
        });
        emaRefs.current[period] = series;
      });

      const handleResize = () => {
        if (containerRef.current && chart) {
          chart.applyOptions({
            width: containerRef.current.clientWidth,
            height: containerRef.current.clientHeight,
          });
        }
      };
      window.addEventListener('resize', handleResize);
      return () => window.removeEventListener('resize', handleResize);
    };

    init();
    return () => {
      if (chartRef.current) { chartRef.current.remove(); chartRef.current = null; }
    };
  }, []);

  useEffect(() => {
    if (!candleSeriesRef.current || chartData.length === 0) return;

    try {
      candleSeriesRef.current.setData(chartData);

      [7, 21, 50].forEach((period) => {
        if (emaRefs.current[period] && candles.length > period) {
          const emaData = computeEMA(candles.map((c) => c.close), period);
          const dedupMap = new Map<string, number>();
          emaData.forEach((val, i) => {
            if (val !== null) dedupMap.set(candles[i].time.slice(0, 10), val);
          });
          const lineData = Array.from(dedupMap.entries())
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([time, value]) => ({ time: time as any, value }));
          emaRefs.current[period].setData(lineData);
        }
      });
    } catch { /* chart may not be ready */ }
  }, [chartData, candles]);

  return (
    <div className="card overflow-hidden">
      <div className="card-header">
        <h3 className="text-sm font-semibold text-white">Price Chart</h3>
        <div className="flex items-center gap-3 text-[10px]">
          <span className="flex items-center gap-1">
            <span className="w-3 h-0.5 bg-[#f59e0b] rounded" /> EMA 7
          </span>
          <span className="flex items-center gap-1">
            <span className="w-3 h-0.5 bg-[#3b82f6] rounded" /> EMA 21
          </span>
          <span className="flex items-center gap-1">
            <span className="w-3 h-0.5 bg-[#8b5cf6] rounded" /> EMA 50
          </span>
        </div>
      </div>
      <div ref={containerRef} className="h-[420px] w-full" />
    </div>
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
