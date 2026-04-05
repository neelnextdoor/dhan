'use client';

import { useEffect, useState, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import { useTradingStore } from '@/store/tradingStore';
import Sidebar from '@/components/Sidebar';
import Toggle from '@/components/ui/Toggle';
import { clsx } from 'clsx';
import type { LogEntry } from '@/types/trading';

export default function LogsPage() {
  const router = useRouter();
  const storeLogs = useTradingStore((s) => s.logs);
  const setStoreLogs = useTradingStore((s) => s.setLogs);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [levelFilter, setLevelFilter] = useState<string>('ALL');
  const [moduleFilter, setModuleFilter] = useState('');
  const [search, setSearch] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!api.getToken()) { router.push('/login'); return; }
    api.getLogs({ limit: 500 }).then((data) => { setStoreLogs(data); });
  }, [router, setStoreLogs]);

  useEffect(() => {
    let filtered = [...storeLogs];
    if (levelFilter !== 'ALL') filtered = filtered.filter((l) => l.level === levelFilter);
    if (moduleFilter) filtered = filtered.filter((l) => l.module.toLowerCase().includes(moduleFilter.toLowerCase()));
    if (search) filtered = filtered.filter((l) => l.message.toLowerCase().includes(search.toLowerCase()));
    setLogs(filtered);
  }, [storeLogs, levelFilter, moduleFilter, search]);

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  const handleClear = async () => { await api.clearLogs(); setStoreLogs([]); };

  const levelColors: Record<string, string> = {
    DEBUG: 'text-slate-500',
    INFO: 'text-accent',
    WARNING: 'text-warn',
    ERROR: 'text-loss',
    CRITICAL: 'text-loss font-bold',
  };

  const levelBg: Record<string, string> = {
    ERROR: 'bg-red-950/20',
    CRITICAL: 'bg-red-950/30',
    WARNING: 'bg-yellow-950/10',
  };

  const levels = ['ALL', 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'];

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 flex flex-col p-6 gap-4 overflow-hidden">
        <div className="flex items-center justify-between shrink-0">
          <div>
            <h1 className="text-lg font-bold text-white">System Logs</h1>
            <p className="text-sm text-slate-500">{logs.length} entries</p>
          </div>
          <div className="flex items-center gap-4">
            <Toggle
              enabled={autoScroll}
              onChange={setAutoScroll}
              label="Auto-scroll"
              size="sm"
              activeColor="blue"
            />
            <button onClick={handleClear} className="btn-ghost text-xs">Clear</button>
          </div>
        </div>

        {/* Filters */}
        <div className="flex gap-2 items-center shrink-0 flex-wrap">
          <div className="flex gap-1">
            {levels.map((level) => (
              <button
                key={level}
                onClick={() => setLevelFilter(level)}
                className={clsx('tab-pill', levelFilter === level ? 'tab-pill-active' : 'tab-pill-inactive')}
              >
                {level}
              </button>
            ))}
          </div>
          <input
            className="input w-40 text-xs"
            placeholder="Filter module..."
            value={moduleFilter}
            onChange={(e) => setModuleFilter(e.target.value)}
          />
          <input
            className="input flex-1 text-xs"
            placeholder="Search logs..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {/* Log viewer */}
        <div ref={scrollRef} className="flex-1 card overflow-y-auto font-mono text-[11px] leading-relaxed">
          <div className="p-3 space-y-px">
            {logs.map((log, i) => (
              <div
                key={i}
                className={clsx(
                  'flex gap-2 py-1 px-2 rounded hover:bg-surface-2/50 transition-colors',
                  levelBg[log.level],
                )}
              >
                <span className="text-slate-600 shrink-0 w-16">{log.timestamp?.slice(11, 19)}</span>
                <span className={clsx('shrink-0 w-16 font-semibold', levelColors[log.level] || 'text-slate-400')}>
                  {log.level}
                </span>
                <span className="text-slate-500 shrink-0 w-28 truncate">{log.module}</span>
                <span className={clsx(
                  'flex-1',
                  log.level === 'ERROR' || log.level === 'CRITICAL' ? 'text-loss' : 'text-slate-300'
                )}>
                  {log.message}
                </span>
              </div>
            ))}
            {logs.length === 0 && (
              <div className="text-center py-16 text-slate-700">No logs to display</div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
