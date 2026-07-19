import { forwardRef } from 'react';
import { cn } from '@/lib/cn.js';

/**
 * Square icon-only button. `label` is REQUIRED and becomes the accessible name
 * (aria-label + title) since there is no visible text.
 */
export const IconButton = forwardRef(function IconButton(
  { label, size = 'md', active = false, className, children, ...props },
  ref,
) {
  const sizes = {
    sm: 'h-8 w-8 rounded-lg',
    md: 'h-10 w-10 rounded-xl',
  };
  return (
    <button
      ref={ref}
      type="button"
      aria-label={label}
      title={label}
      className={cn(
        'inline-flex items-center justify-center transition-colors duration-150',
        'text-muted hover:text-fg hover:bg-surface-2',
        active && 'bg-surface-2 text-fg',
        sizes[size],
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
});
