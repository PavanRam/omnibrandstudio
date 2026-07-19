import { useMemo } from 'react';
import { sceneSvg } from '@/lib/art.js';
import { cn } from '@/lib/cn.js';

/**
 * Renders the deterministic local artwork for a seed as an inline SVG that
 * fills its container (object-cover behaviour via preserveAspectRatio="slice").
 * Decorative — the accessible name lives on the surrounding control.
 */
export function GenerativeArt({ seed, className }) {
  const html = useMemo(() => sceneSvg(seed, { responsive: true }), [seed]);
  return (
    <div
      aria-hidden="true"
      className={cn('block [&>svg]:block [&>svg]:h-full [&>svg]:w-full', className)}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
