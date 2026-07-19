import { Moon, Sun } from 'lucide-react';
import { useTheme } from './hooks/useTheme.js';
import { cn } from '@/lib/cn.js';

/** Light/dark switch. Mount-gated to avoid a hydration flash. */
export function ThemeToggle({ className }) {
  const { theme, toggle, mounted } = useTheme();
  const isDark = theme === 'dark';

  return (
    <button
      type="button"
      onClick={toggle}
      role="switch"
      aria-checked={mounted ? isDark : undefined}
      aria-label={`Switch to ${isDark ? 'light' : 'dark'} mode`}
      title={`Switch to ${isDark ? 'light' : 'dark'} mode`}
      className={cn(
        'inline-flex h-10 w-10 items-center justify-center rounded-xl',
        'text-muted transition-colors hover:bg-surface-2 hover:text-fg',
        className,
      )}
    >
      {/* Keep both icons mounted; cross-fade based on theme to avoid layout shift. */}
      <span className="relative block h-[18px] w-[18px]">
        <Sun
          size={18}
          aria-hidden="true"
          className={cn(
            'absolute inset-0 transition-all duration-300',
            mounted && !isDark
              ? 'opacity-100 rotate-0 scale-100'
              : 'opacity-0 -rotate-90 scale-50',
          )}
        />
        <Moon
          size={18}
          aria-hidden="true"
          className={cn(
            'absolute inset-0 transition-all duration-300',
            mounted && isDark
              ? 'opacity-100 rotate-0 scale-100'
              : 'opacity-0 rotate-90 scale-50',
          )}
        />
      </span>
    </button>
  );
}
