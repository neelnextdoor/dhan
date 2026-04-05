'use client';

import { clsx } from 'clsx';

interface ToggleProps {
  enabled: boolean;
  onChange: (val: boolean) => void;
  label?: string;
  description?: string;
  disabled?: boolean;
  loading?: boolean;
  size?: 'sm' | 'md';
  activeColor?: 'green' | 'blue' | 'red';
}

export default function Toggle({
  enabled, onChange, label, description, disabled = false,
  loading = false, size = 'md', activeColor = 'blue',
}: ToggleProps) {
  const isDisabled = disabled || loading;

  const trackSize = size === 'sm' ? 'w-9 h-5' : 'w-11 h-6';
  const thumbSize = size === 'sm' ? 'w-3.5 h-3.5' : 'w-4.5 h-4.5';
  const thumbTranslate = size === 'sm'
    ? (enabled ? 'translate-x-[18px]' : 'translate-x-[3px]')
    : (enabled ? 'translate-x-[22px]' : 'translate-x-[3px]');

  const colors = {
    green: 'bg-profit shadow-profit/25',
    blue: 'bg-accent shadow-accent/25',
    red: 'bg-loss shadow-loss/25',
  };

  return (
    <div className={clsx('flex items-center justify-between gap-3', isDisabled && 'opacity-50')}>
      {(label || description) && (
        <div className="flex-1 min-w-0">
          {label && <div className="text-xs font-medium text-gray-300">{label}</div>}
          {description && <div className="text-[10px] text-gray-500 mt-0.5">{description}</div>}
        </div>
      )}
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        disabled={isDisabled}
        onClick={() => onChange(!enabled)}
        className={clsx(
          'relative inline-flex shrink-0 cursor-pointer rounded-full transition-all duration-200',
          trackSize,
          enabled ? `${colors[activeColor]} shadow-lg` : 'bg-surface-3',
          isDisabled && 'cursor-not-allowed',
        )}
      >
        <span
          className={clsx(
            'pointer-events-none inline-block rounded-full bg-white shadow-md transition-transform duration-200 mt-[3px]',
            thumbSize,
            thumbTranslate,
            loading && 'animate-pulse',
          )}
        />
      </button>
    </div>
  );
}
