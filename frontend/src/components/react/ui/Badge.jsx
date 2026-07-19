import { cn } from '@/lib/cn.js';

const TONES = {
  neutral: 'bg-surface-2 text-muted border-border',
  brand: 'bg-brand-soft text-brand border-transparent',
  success: 'bg-success/12 text-success border-transparent',
  warning: 'bg-warning/12 text-warning border-transparent',
  danger: 'bg-danger/12 text-danger border-transparent',
};

export function Badge({ tone = 'neutral', className, children }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5',
        'text-[11px] font-medium leading-none tracking-wide',
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
