import { Sparkles } from 'lucide-react';
import { cn } from '@/lib/cn.js';
import { BRAND } from '@/lib/nav.js';
import { withBase } from '@/lib/paths.js';

/** Brand lockup: gradient mark + wordmark. `compact` hides the wordmark. */
export function Logo({ compact = false, className }) {
  return (
    <a
      href={withBase('/')}
      className={cn(
        'inline-flex items-center gap-2.5 rounded-xl',
        'focus-visible:outline-none',
        className,
      )}
      aria-label={`${BRAND.name} ${BRAND.suffix} — home`}
    >
      <span className="grid h-9 w-9 place-items-center rounded-xl brand-gradient text-white shadow-sm">
        <Sparkles size={18} aria-hidden="true" />
      </span>
      {!compact && (
        <span className="text-[15px] font-semibold tracking-tight text-fg">
          {BRAND.name}
          <span className="text-muted font-normal"> {BRAND.suffix}</span>
        </span>
      )}
    </a>
  );
}
