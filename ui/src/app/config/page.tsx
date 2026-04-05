'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import Sidebar from '@/components/Sidebar';
import Toggle from '@/components/ui/Toggle';
import Spinner from '@/components/ui/Spinner';
import { clsx } from 'clsx';

interface ConfigState {
  [key: string]: any;
}

export default function ConfigPage() {
  const router = useRouter();
  const [config, setConfig] = useState<ConfigState | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [presetName, setPresetName] = useState('');
  const [activeTab, setActiveTab] = useState('strategy');

  useEffect(() => {
    if (!api.getToken()) { router.push('/login'); return; }
    api.getConfig().then(setConfig).finally(() => setLoading(false));
  }, [router]);

  const handleSave = async () => {
    if (!config) return;
    setSaving(true);
    try {
      await api.updateConfig(config);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e: any) {
      alert(e.message);
    } finally {
      setSaving(false);
    }
  };

  const handleSavePreset = async () => {
    if (!config || !presetName.trim()) return;
    await api.savePreset(presetName.trim(), config);
    setPresetName('');
    alert(`Preset "${presetName}" saved`);
  };

  const handleReset = async () => {
    if (!confirm('Reset config to defaults?')) return;
    const res = await api.resetConfig();
    alert(res.message);
    const fresh = await api.getConfig();
    setConfig(fresh);
  };

  const update = (section: string, key: string, value: any) => {
    setConfig((prev) => {
      if (!prev) return prev;
      if (section === '_root') return { ...prev, [key]: value };
      return { ...prev, [section]: { ...prev[section], [key]: value } };
    });
  };

  const updateNested = (section: string, sub: string, key: string, value: any) => {
    setConfig((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        [section]: {
          ...prev[section],
          [sub]: { ...prev[section]?.[sub], [key]: value },
        },
      };
    });
  };

  const tabs = [
    { id: 'strategy', label: 'Strategy' },
    { id: 'risk', label: 'Risk' },
    { id: 'trading', label: 'Trading' },
    { id: 'exit', label: 'Exit Rules' },
    { id: 'options', label: 'Options' },
  ];

  if (loading) return <LoadingShell />;

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-bold text-white">Strategy Configuration</h1>
            <p className="text-sm text-slate-500">Customize your trading parameters</p>
          </div>
          <div className="flex items-center gap-3">
            {saved && <span className="text-xs text-profit font-semibold animate-in">Saved!</span>}
            <button onClick={handleReset} className="btn-ghost text-xs">Reset</button>
            <button onClick={handleSave} disabled={saving} className="btn-primary text-xs flex items-center gap-2">
              {saving && <Spinner size="sm" />}
              {saving ? 'Saving...' : 'Save Config'}
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 bg-surface-1 border border-surface-3/60 rounded-xl p-1">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={clsx('tab-pill', activeTab === tab.id ? 'tab-pill-active' : 'tab-pill-inactive')}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {config && (
          <div className="card card-body space-y-6">
            {activeTab === 'strategy' && (
              <>
                <Section title="General">
                  <Field label="Symbol" value={config.symbol} onChange={(v) => update('_root', 'symbol', v)} />
                  <SelectField label="Timeframe" value={config.timeframe} options={['1m', '5m', '15m', '30m', '1h']} onChange={(v) => update('_root', 'timeframe', v)} />
                </Section>

                <Section title="EMA Periods">
                  <NumField label="Primary (Fast)" value={config.ema?.primary_period} onChange={(v) => update('ema', 'primary_period', v)} />
                  <NumField label="Short" value={config.ema?.short_period} onChange={(v) => update('ema', 'short_period', v)} />
                  <NumField label="Long" value={config.ema?.long_period} onChange={(v) => update('ema', 'long_period', v)} />
                  <NumField label="Trend" value={config.ema?.trend_period} onChange={(v) => update('ema', 'trend_period', v)} />
                  <div className="md:col-span-2 lg:col-span-3">
                    <Toggle
                      label="Crossover Confirmation"
                      description="Require EMA crossover before entry"
                      enabled={!!config.ema?.use_crossover_confirmation}
                      onChange={(v) => update('ema', 'use_crossover_confirmation', v)}
                      activeColor="blue"
                    />
                  </div>
                </Section>

                <Section title="Entry Rules">
                  <SelectField label="Entry Mode" value={config.entry?.mode} options={['breakout', 'pullback', 'both']} onChange={(v) => update('entry', 'mode', v)} />
                  <SelectField label="Min Grade" value={config.entry?.min_grade} options={['A+', 'A', 'B', 'C']} onChange={(v) => update('entry', 'min_grade', v)} />
                  <NumField label="Cooldown Bars" value={config.entry?.cooldown_bars} onChange={(v) => update('entry', 'cooldown_bars', v)} />
                  <div className="md:col-span-2 lg:col-span-3 space-y-3">
                    <Toggle label="Confirm Candle Close" enabled={!!config.entry?.confirm_candle_close} onChange={(v) => update('entry', 'confirm_candle_close', v)} activeColor="blue" />
                    <Toggle label="Volume Confirmation" enabled={!!config.entry?.volume_confirmation} onChange={(v) => update('entry', 'volume_confirmation', v)} activeColor="blue" />
                  </div>
                </Section>

                <Section title="Sideways Filter">
                  <div className="md:col-span-2 lg:col-span-3">
                    <Toggle label="Enabled" description="Skip trades in sideways markets" enabled={!!config.sideways_filter?.enabled} onChange={(v) => update('sideways_filter', 'enabled', v)} activeColor="blue" />
                  </div>
                  <SelectField label="Method" value={config.sideways_filter?.method} options={['atr', 'candle_range', 'combined']} onChange={(v) => update('sideways_filter', 'method', v)} />
                  <NumField label="ATR Threshold" value={config.sideways_filter?.atr_threshold} step={0.01} onChange={(v) => update('sideways_filter', 'atr_threshold', v)} />
                </Section>
              </>
            )}

            {activeTab === 'risk' && (
              <Section title="Risk Management">
                <NumField label="Risk Per Trade (%)" value={config.risk?.risk_per_trade_pct} step={0.5} onChange={(v) => update('risk', 'risk_per_trade_pct', v)} />
                <NumField label="Max Trades/Day" value={config.risk?.max_trades_per_day} onChange={(v) => update('risk', 'max_trades_per_day', v)} />
                <NumField label="Max Daily Loss (₹)" value={config.risk?.max_loss_per_day} onChange={(v) => update('risk', 'max_loss_per_day', v)} />
                <NumField label="Capital Per Trade (₹)" value={config.risk?.capital_per_trade} onChange={(v) => update('risk', 'capital_per_trade', v)} />
                <NumField label="Max Consecutive Losses" value={config.risk?.max_consecutive_losses} onChange={(v) => update('risk', 'max_consecutive_losses', v)} />
              </Section>
            )}

            {activeTab === 'trading' && (
              <>
                <Section title="Symbol & Lots">
                  <Field label="Symbol" value={config.symbol} onChange={(v) => update('_root', 'symbol', v)} />
                  <NumField label="Lot Size" value={config.risk?.lot_size} onChange={(v) => update('risk', 'lot_size', v)} />
                </Section>

                <Section title="Trading Hours (IST)">
                  <Field label="Start" value={config.trading_hours?.start} onChange={(v) => update('trading_hours', 'start', v)} />
                  <Field label="End" value={config.trading_hours?.end} onChange={(v) => update('trading_hours', 'end', v)} />
                  <Field label="Force Exit" value={config.trading_hours?.force_exit} onChange={(v) => update('trading_hours', 'force_exit', v)} />
                </Section>

                <Section title="Multi-Timeframe">
                  <div className="md:col-span-2 lg:col-span-3">
                    <Toggle label="Enabled" enabled={!!config.multi_timeframe?.enabled} onChange={(v) => update('multi_timeframe', 'enabled', v)} activeColor="blue" />
                  </div>
                  <NumField label="Higher TF (minutes)" value={config.multi_timeframe?.higher_tf_minutes} onChange={(v) => update('multi_timeframe', 'higher_tf_minutes', v)} />
                  <div className="md:col-span-2">
                    <Toggle label="Require HTF Alignment" enabled={!!config.multi_timeframe?.require_htf_alignment} onChange={(v) => update('multi_timeframe', 'require_htf_alignment', v)} activeColor="blue" />
                  </div>
                </Section>
              </>
            )}

            {activeTab === 'exit' && (
              <>
                <Section title="Stop Loss">
                  <SelectField label="Type" value={config.exit?.stop_loss?.type} options={['fixed_points', 'fixed_pct', 'swing', 'ema_breach']} onChange={(v) => updateNested('exit', 'stop_loss', 'type', v)} />
                  <NumField label="Value" value={config.exit?.stop_loss?.value} onChange={(v) => updateNested('exit', 'stop_loss', 'value', v)} />
                </Section>

                <Section title="Target">
                  <SelectField label="Type" value={config.exit?.target?.type} options={['risk_reward', 'fixed_points', 'fixed_pct']} onChange={(v) => updateNested('exit', 'target', 'type', v)} />
                  <NumField label="Risk:Reward Ratio" value={config.exit?.target?.risk_reward_ratio} step={0.1} onChange={(v) => updateNested('exit', 'target', 'risk_reward_ratio', v)} />
                </Section>

                <Section title="Trailing Stop Loss">
                  <div className="md:col-span-2 lg:col-span-3">
                    <Toggle label="Enabled" enabled={!!config.exit?.trailing_sl?.enabled} onChange={(v) => updateNested('exit', 'trailing_sl', 'enabled', v)} activeColor="green" />
                  </div>
                  <NumField label="Activation (%)" value={config.exit?.trailing_sl?.activation_pct} onChange={(v) => updateNested('exit', 'trailing_sl', 'activation_pct', v)} />
                  <NumField label="Trail (%)" value={config.exit?.trailing_sl?.trail_pct} onChange={(v) => updateNested('exit', 'trailing_sl', 'trail_pct', v)} />
                </Section>

                <Section title="Other Exit Rules">
                  <div className="md:col-span-2 lg:col-span-3 space-y-3">
                    <Toggle label="Exit on Opposite Signal" enabled={!!config.exit?.exit_on_opposite_signal} onChange={(v) => update('exit', 'exit_on_opposite_signal', v)} activeColor="blue" />
                    <Toggle label="Time-Based Exit" enabled={!!config.exit?.time_based_exit?.enabled} onChange={(v) => updateNested('exit', 'time_based_exit', 'enabled', v)} activeColor="blue" />
                  </div>
                  <Field label="Exit Time" value={config.exit?.time_based_exit?.exit_time} onChange={(v) => updateNested('exit', 'time_based_exit', 'exit_time', v)} />
                </Section>
              </>
            )}

            {activeTab === 'options' && (
              <Section title="Options Configuration">
                <SelectField label="Strike Selection" value={config.options?.strike_selection} options={['atm', 'itm_1', 'itm_2', 'otm_1', 'otm_2']} onChange={(v) => update('options', 'strike_selection', v)} />
                <NumField label="Strike Interval" value={config.options?.strike_interval} onChange={(v) => update('options', 'strike_interval', v)} />
                <NumField label="Premium SL (%)" value={config.options?.premium_sl_pct} onChange={(v) => update('options', 'premium_sl_pct', v)} />
                <NumField label="Premium Target (%)" value={config.options?.premium_target_pct} onChange={(v) => update('options', 'premium_target_pct', v)} />
                <div className="md:col-span-2 lg:col-span-3 space-y-3">
                  <Toggle label="Premium-Based SL" enabled={!!config.options?.use_premium_based_sl} onChange={(v) => update('options', 'use_premium_based_sl', v)} activeColor="blue" />
                  <Toggle label="Avoid Last Hour Entry" enabled={!!config.options?.avoid_last_hour_entry} onChange={(v) => update('options', 'avoid_last_hour_entry', v)} activeColor="blue" />
                </div>
                <NumField label="Min Premium (₹)" value={config.options?.min_premium} onChange={(v) => update('options', 'min_premium', v)} />
                <NumField label="Max Premium (₹)" value={config.options?.max_premium} onChange={(v) => update('options', 'max_premium', v)} />
              </Section>
            )}

            {/* Preset Save */}
            <div className="pt-4 border-t border-surface-3/60 flex items-center gap-3">
              <input
                className="input flex-1"
                placeholder="Preset name..."
                value={presetName}
                onChange={(e) => setPresetName(e.target.value)}
              />
              <button onClick={handleSavePreset} className="btn-ghost text-xs" disabled={!presetName.trim()}>
                Save Preset
              </button>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-sm font-semibold text-white mb-4">{title}</h3>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">{children}</div>
    </div>
  );
}

function Field({ label, value, onChange }: { label: string; value: any; onChange: (v: string) => void }) {
  return (
    <div>
      <label className="label">{label}</label>
      <input className="input" value={value ?? ''} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

function NumField({ label, value, step, onChange }: { label: string; value: any; step?: number; onChange: (v: number) => void }) {
  return (
    <div>
      <label className="label">{label}</label>
      <input
        type="number"
        className="input font-mono"
        value={value ?? 0}
        step={step ?? 1}
        onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
      />
    </div>
  );
}

function SelectField({ label, value, options, onChange }: { label: string; value: any; options: string[]; onChange: (v: string) => void }) {
  return (
    <div>
      <label className="label">{label}</label>
      <select className="input" value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
        {options.map((opt) => (
          <option key={opt} value={opt}>{opt}</option>
        ))}
      </select>
    </div>
  );
}

function LoadingShell() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 flex items-center justify-center">
        <div className="flex items-center gap-3 text-slate-500">
          <Spinner />
          <span>Loading configuration...</span>
        </div>
      </main>
    </div>
  );
}
