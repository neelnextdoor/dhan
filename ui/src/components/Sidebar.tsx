'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useTradingStore } from '@/store/tradingStore';
import { clsx } from 'clsx';

const navItems = [
  { href: '/', label: 'Dashboard', icon: DashboardIcon },
  { href: '/config', label: 'Strategy', icon: ConfigIcon },
  { href: '/backtest', label: 'Backtest', icon: BacktestIcon },
  { href: '/trades', label: 'Trades', icon: TradesIcon },
  { href: '/logs', label: 'Logs', icon: LogsIcon },
];

export default function Sidebar() {
  const pathname = usePathname();
  const engineStatus = useTradingStore((s) => s.engineStatus);
  const wsConnected = useTradingStore((s) => s.wsConnected);

  const status = engineStatus?.status || 'STOPPED';
  const statusColor = {
    RUNNING: 'bg-profit', STOPPED: 'bg-slate-600', STARTING: 'bg-warn',
    STOPPING: 'bg-warn', ERROR: 'bg-loss',
  }[status] || 'bg-slate-600';

  return (
    <aside className="w-16 lg:w-56 bg-surface-1/80 backdrop-blur-sm border-r border-surface-3/40 flex flex-col h-screen shrink-0">
      {/* Logo */}
      <div className="p-3 lg:p-4 border-b border-surface-3/40">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 bg-gradient-to-br from-accent to-blue-600 rounded-lg flex items-center justify-center shrink-0 shadow-md shadow-accent/20">
            <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
            </svg>
          </div>
          <span className="hidden lg:block text-sm font-bold text-white tracking-tight">Dhan Terminal</span>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 py-3 px-2 space-y-0.5">
        {navItems.map(({ href, label, icon: Icon }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={clsx(
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all duration-200',
                active
                  ? 'bg-accent/10 text-accent font-semibold shadow-sm shadow-accent/5'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-surface-2/60'
              )}
            >
              <Icon className="w-[18px] h-[18px] shrink-0" />
              <span className="hidden lg:block">{label}</span>
              {active && <span className="hidden lg:block ml-auto w-1.5 h-1.5 bg-accent rounded-full" />}
            </Link>
          );
        })}
      </nav>

      {/* Footer status */}
      <div className="p-3 lg:p-4 border-t border-surface-3/40 space-y-2.5">
        <div className="flex items-center gap-2">
          <div className={clsx(
            'w-2 h-2 rounded-full',
            statusColor,
            status === 'RUNNING' && 'status-running',
            (status === 'STARTING' || status === 'STOPPING') && 'animate-pulse',
          )} />
          <span className="hidden lg:block text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
            {status}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <div className={clsx('w-2 h-2 rounded-full', wsConnected ? 'bg-profit' : 'bg-slate-700')} />
          <span className="hidden lg:block text-[11px] text-slate-500">
            {wsConnected ? 'Connected' : 'Disconnected'}
          </span>
        </div>
      </div>
    </aside>
  );
}

function DashboardIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
    </svg>
  );
}

function ConfigIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.573-1.066z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  );
}

function BacktestIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
    </svg>
  );
}

function TradesIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
    </svg>
  );
}

function LogsIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
    </svg>
  );
}
