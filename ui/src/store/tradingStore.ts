import { create } from 'zustand';
import type { EngineStatus, TradingStats, Trade, Candle, LogEntry } from '@/types/trading';

interface TradingState {
  // Auth
  isAuthenticated: boolean;
  setAuthenticated: (val: boolean) => void;

  // Engine
  engineStatus: EngineStatus | null;
  setEngineStatus: (s: EngineStatus) => void;

  // Stats
  stats: TradingStats | null;
  setStats: (s: TradingStats) => void;

  // Trades
  trades: Trade[];
  setTrades: (t: Trade[]) => void;

  // Candles
  candles: Candle[];
  setCandles: (c: Candle[]) => void;
  appendCandles: (c: Candle[]) => void;

  // Logs
  logs: LogEntry[];
  addLog: (l: LogEntry) => void;
  setLogs: (l: LogEntry[]) => void;

  // WS connected
  wsConnected: boolean;
  setWsConnected: (v: boolean) => void;
}

export const useTradingStore = create<TradingState>((set) => ({
  isAuthenticated: typeof window !== 'undefined' ? !!localStorage.getItem('auth_token') : false,
  setAuthenticated: (val) => set({ isAuthenticated: val }),

  engineStatus: null,
  setEngineStatus: (s) => set({ engineStatus: s }),

  stats: null,
  setStats: (s) => set({ stats: s }),

  trades: [],
  setTrades: (t) => set({ trades: t }),

  candles: [],
  setCandles: (c) => set({ candles: c }),
  appendCandles: (newCandles) =>
    set((state) => {
      const existing = new Map(state.candles.map((c) => [c.time, c]));
      newCandles.forEach((c) => existing.set(c.time, c));
      const all = Array.from(existing.values()).sort((a, b) => a.time.localeCompare(b.time));
      return { candles: all.slice(-500) };
    }),

  logs: [],
  addLog: (l) => set((state) => ({ logs: [...state.logs.slice(-999), l] })),
  setLogs: (l) => set({ logs: l }),

  wsConnected: false,
  setWsConnected: (v) => set({ wsConnected: v }),
}));
