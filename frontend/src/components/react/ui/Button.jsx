import { cn } from '@/lib/cn.js';
import { withBase } from '@/lib/paths.js';

const VARIANTS = {
  // Solid, theme-aware brand fill (the token flips per light/dark mode).
  primary:
    'bg-brand text-brand-fg shadow-sm hover:brightness-110 active:brightness-95 border border-transparent',
  secondary:
    'bg-surface-2 text-fg border border-border hover:bg-surface-3',
  outline:
    'bg-transparent text-fg border border-border-strong hover:bg-surface-2',
  ghost: 'bg-transparent text-muted hover:text-fg hover:bg-surface-2 border border-transparent',
  danger:
    'bg-transparent text-danger border border-danger/40 hover:bg-danger/10',
};

const SIZES = {
  sm: 'h-8 px-3 text-sm gap-1.5 rounded-lg',
  md: 'h-10 px-4 text-sm gap-2 rounded-xl',
  lg: 'h-12 px-6 text-base gap-2.5 rounded-xl',
  icon: 'h-10 w-10 rounded-xl justify-center',
};

/**
 * Polymorphic button. Renders an <a> when `href` is provided, otherwise a
 * <button>. Internal (root-relative) hrefs are automatically prefixed with the
 * deploy base path so links work under a GitHub Pages sub-path.
 * Focus-visible ring comes from the global stylesheet.
 */
export function Button({
  as,
  href,
  variant = 'secondary',
  size = 'md',
  className,
  children,
  ...props
}) {
  const Tag = as ?? (href ? 'a' : 'button');
  const resolvedHref = href && href.startsWith('/') ? withBase(href) : href;
  const classes = cn(
    'inline-flex items-center justify-center font-medium select-none',
    'transition-colors duration-150 disabled:opacity-50 disabled:pointer-events-none',
    'whitespace-nowrap',
    VARIANTS[variant],
    SIZES[size],
    className,
  );

  if (Tag === 'button' && props.type === undefined) {
    props.type = 'button';
  }

  return (
    <Tag href={resolvedHref} className={classes} {...props}>
      {children}
    </Tag>
  );
}
