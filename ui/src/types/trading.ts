export interface EngineStatus {
  status: 'STOPPED' | 'STARTING' | 'RUNNING' | 'STOPPING' | 'ERROR';
  mode: string;
  uptime_seconds: number;
  last_tick: string | null;
  error: string | null;
  symbol: string;
  strategy: string;
}

export interface TradingStats {
  daily_pnl: number;
  total_pnl: number;
  win_rate: number;
  total_trades_today: number;
  winning_trades: number;
  losing_trades: number;
  capital_deployed: number;
  risk_usage_pct: number;
  max_drawdown: number;
  current_position: ActiveTrade | null;
}

export interface ActiveTrade {
  trade_id: string;
  symbol: string;
  option_type: string | null;
  strike: number;
  entry_price: number;
  quantity: number;
  stop_loss: number;
  target: number;
  trailing_sl: number;
  peak_price: number;
}

export interface Trade {
  trade_id: string;
  symbol: string;
  side: string;
  option_type: string | null;
  strike: number;
  entry_price: number;
  exit_price: number;
  quantity: number;
  stop_loss: number;
  target: number;
  entry_time: string;
  exit_time: string | null;
  exit_reason: string | null;
  pnl: number;
  status: string;
  underlying_price: number;
}

export interface Candle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface LogEntry {
  timestamp: string;
  level: string;
  module: string;
  message: string;
}

export interface BacktestSummary {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  total_pnl: number;
  net_pnl: number;
  avg_win: number;
  avg_loss: number;
  largest_win: number;
  largest_loss: number;
  profit_factor: number;
  expectancy: number;
  sharpe_ratio: number;
  max_drawdown: number;
  max_drawdown_pct: number;
  initial_capital: number;
  final_capital: number;
  return_pct: number;
  ce_trades: number;
  pe_trades: number;
  ce_pnl: number;
  pe_pnl: number;
  error?: string;
}

export interface BacktestResult {
  summary: BacktestSummary;
  trades: Trade[];
  equity_curve: { timestamp: string; equity: number; price: number }[];
}

export interface TradingConfig {
  symbol: string;
  timeframe: string;
  ema: {
    primary_period: number;
    short_period: number;
    long_period: number;
    trend_period: number;
    use_crossover_confirmation: boolean;
  };
  entry: {
    mode: string;
    confirm_candle_close: boolean;
    volume_confirmation: boolean;
    min_grade: string;
    cooldown_bars: number;
  };
  sideways_filter: {
    enabled: boolean;
    atr_threshold: number;
    method: string;
  };
  risk: {
    max_trades_per_day: number;
    max_loss_per_day: number;
    capital_per_trade: number;
    lot_size: number;
    risk_per_trade_pct: number;
  };
  trading_hours: {
    start: string;
    end: string;
    force_exit: string;
  };
  options: {
    premium_sl_pct: number;
    premium_target_pct: number;
    strike_selection: string;
  };
  exit: {
    trailing_sl: { enabled: boolean; activation_pct: number; trail_pct: number };
    time_based_exit: { enabled: boolean; exit_time: string };
    exit_on_opposite_signal: boolean;
  };
  [key: string]: any;
}

export interface WSMessage {
  type: string;
  data: any;
  timestamp: string;
}
