'use client';

import { useEffect, useRef, useCallback } from 'react';
import { useTradingStore } from '@/store/tradingStore';
import { api } from '@/lib/api';

const MAX_RECONNECT_DELAY = 30000;
const BASE_RECONNECT_DELAY = 1000;

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<NodeJS.Timeout>();
  const attemptRef = useRef(0);
  const { setEngineStatus, setStats, appendCandles, addLog, setWsConnected, setTrades } =
    useTradingStore();

  const connect = useCallback(() => {
    const token = api.getToken();
    if (!token) return;

    if (wsRef.current?.readyState === WebSocket.OPEN ||
        wsRef.current?.readyState === WebSocket.CONNECTING) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = process.env.NEXT_PUBLIC_WS_URL || `${protocol}//${window.location.host}`;
    const url = `${host}/ws/live?token=${token}`;

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setWsConnected(true);
        attemptRef.current = 0;
        if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          switch (msg.type) {
            case 'init':
              if (msg.data.status) setEngineStatus(msg.data.status);
              if (msg.data.stats) setStats(msg.data.stats);
              if (msg.data.candles?.length) appendCandles(msg.data.candles);
              break;
            case 'engine_status':
              setEngineStatus(msg.data);
              break;
            case 'tick': {
              if (msg.data.candles?.length) appendCandles(msg.data.candles);
              const store = useTradingStore.getState();
              const prev = store.stats;
              setStats({
                daily_pnl: msg.data.pnl ?? prev?.daily_pnl ?? 0,
                total_pnl: msg.data.pnl ?? prev?.total_pnl ?? 0,
                win_rate: prev?.win_rate ?? 0,
                total_trades_today: msg.data.trades_today ?? prev?.total_trades_today ?? 0,
                winning_trades: prev?.winning_trades ?? 0,
                losing_trades: prev?.losing_trades ?? 0,
                capital_deployed: prev?.capital_deployed ?? 0,
                risk_usage_pct: prev?.risk_usage_pct ?? 0,
                max_drawdown: prev?.max_drawdown ?? 0,
                current_position: msg.data.active_trade,
              });
              break;
            }
            case 'log':
              addLog(msg.data);
              break;
          }
        } catch {
          // ignore
        }
      };

      ws.onclose = () => {
        setWsConnected(false);
        wsRef.current = null;
        scheduleReconnect();
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch {
      scheduleReconnect();
    }
  }, [setEngineStatus, setStats, appendCandles, addLog, setWsConnected, setTrades]);

  const scheduleReconnect = useCallback(() => {
    attemptRef.current++;
    const delay = Math.min(
      BASE_RECONNECT_DELAY * Math.pow(1.5, attemptRef.current - 1),
      MAX_RECONNECT_DELAY,
    );
    reconnectTimer.current = setTimeout(connect, delay);
  }, [connect]);

  useEffect(() => {
    connect();

    const heartbeat = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'ping' }));
      }
    }, 25000);

    return () => {
      clearInterval(heartbeat);
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { reconnect: connect };
}
