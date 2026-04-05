const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

class ApiClient {
  private token: string | null = null;

  constructor() {
    if (typeof window !== 'undefined') {
      this.token = localStorage.getItem('auth_token');
    }
  }

  setToken(token: string) {
    this.token = token;
    if (typeof window !== 'undefined') {
      localStorage.setItem('auth_token', token);
    }
  }

  clearToken() {
    this.token = null;
    if (typeof window !== 'undefined') {
      localStorage.removeItem('auth_token');
    }
  }

  getToken(): string | null {
    return this.token;
  }

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(options.headers as Record<string, string>),
    };

    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    }

    const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

    if (res.status === 401) {
      this.clearToken();
      if (typeof window !== 'undefined') {
        window.location.href = '/login';
      }
      throw new Error('Unauthorized');
    }

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    return res.json();
  }

  // Auth
  async login(username: string, password: string) {
    const data = await this.request<{ access_token: string }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
    this.setToken(data.access_token);
    return data;
  }

  // Engine
  getStatus() {
    return this.request<any>('/api/trading/status');
  }

  getStats() {
    return this.request<any>('/api/trading/stats');
  }

  startTrading(mode: string = 'paper') {
    return this.request<any>('/api/trading/start', {
      method: 'POST',
      body: JSON.stringify({ mode }),
    });
  }

  stopTrading() {
    return this.request<any>('/api/trading/stop', { method: 'POST' });
  }

  killTrading() {
    return this.request<any>('/api/trading/kill', { method: 'POST' });
  }

  // Trades
  getTrades(params?: Record<string, string>) {
    const qs = params ? '?' + new URLSearchParams(params).toString() : '';
    return this.request<any[]>(`/api/trades${qs}`);
  }

  getActiveTrade() {
    return this.request<any>('/api/trades/active');
  }

  // Config
  getConfig() {
    return this.request<any>('/api/config');
  }

  updateConfig(config: Record<string, any>) {
    return this.request<any>('/api/config', {
      method: 'PUT',
      body: JSON.stringify({ config }),
    });
  }

  resetConfig() {
    return this.request<any>('/api/config/reset', { method: 'POST' });
  }

  getPresets() {
    return this.request<any[]>('/api/config/presets');
  }

  savePreset(name: string, config: Record<string, any>) {
    return this.request<any>('/api/config/presets', {
      method: 'POST',
      body: JSON.stringify({ name, config }),
    });
  }

  loadPreset(name: string) {
    return this.request<any>(`/api/config/presets/${name}/load`, { method: 'POST' });
  }

  // Backtest
  runBacktest(params: { start_date: string; end_date: string; csv_path?: string }) {
    return this.request<any>('/api/backtest/run', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  }

  // Candles
  getCandles() {
    return this.request<any[]>('/api/candles');
  }

  // Logs
  getLogs(params?: { limit?: number; level?: string; module?: string }) {
    const qs = params ? '?' + new URLSearchParams(params as any).toString() : '';
    return this.request<any[]>(`/api/logs${qs}`);
  }

  clearLogs() {
    return this.request<any>('/api/logs', { method: 'DELETE' });
  }

  // Health
  getHealth() {
    return this.request<any>('/api/health');
  }
}

export const api = new ApiClient();
