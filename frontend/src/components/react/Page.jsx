import { cn } from '@/lib/cn.js';

/** Consistent page container with an optional heading block. */
export function Page({ eyebrow, title, description, actions, wide = false, children }) {
  return (
    <div
      className={cn(
        'mx-auto w-full px-4 py-6 sm:px-6 lg:px-8 lg:py-8',
        wide ? 'max-w-[1600px]' : 'max-w-6xl',
      )}
    >
      {(title || actions) && (
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-0">
            {eyebrow && (
              <p className="text-xs font-semibold uppercase tracking-wider text-brand">
                {eyebrow}
              </p>
            )}
            {title && (
              <h1 className="mt-1 text-2xl font-semibold tracking-tight text-fg sm:text-3xl">
                {title}
              </h1>
            )}
            {description && (
              <p className="mt-2 max-w-2xl text-sm text-muted">{description}</p>
            )}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </div>
  );
}

/** Sub-section heading used within pages. */
export function SectionHeading({ title, description, action }) {
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 className="text-lg font-semibold text-fg">{title}</h2>
        {description && <p className="mt-0.5 text-sm text-muted">{description}</p>}
      </div>
      {action}
    </div>
  );
}
