import { Heart, Download, Trash2, Maximize2 } from 'lucide-react';
import { artDataUrl } from '@/lib/art.js';
import { GenerativeArt } from './GenerativeArt.jsx';
import { cn } from '@/lib/cn.js';

export function aspectStyle(aspect) {
  const [w, h] = String(aspect || '1:1').split(':').map(Number);
  return { aspectRatio: `${w || 1} / ${h || 1}` };
}

/**
 * A single generated image tile. The artwork itself is a button that opens the
 * detail view; like/download/delete are sibling controls layered on top (never
 * nested inside the open button, so the markup stays valid & accessible).
 */
export function ImageCard({ item, onOpen, onLike, onRemove, showActions = true }) {
  const seed = item.seed ?? item.id;
  const downloadUrl = artDataUrl(seed, { w: 1024, h: 1024 });

  return (
    <figure
      className="group relative overflow-hidden rounded-2xl border border-border bg-surface-2 card-shadow"
      style={aspectStyle(item.aspect)}
    >
      {/* Open-detail button fills the tile */}
      <button
        type="button"
        onClick={() => onOpen?.(item)}
        className="absolute inset-0 h-full w-full cursor-zoom-in focus-visible:outline-none"
      >
        <span className="sr-only">Open image: {item.prompt}</span>
        <GenerativeArt
          seed={seed}
          className="h-full w-full transition-transform duration-500 group-hover:scale-[1.04]"
        />
      </button>

      {/* Bottom gradient + prompt (revealed on hover/focus-within) */}
      <figcaption className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/75 to-transparent p-3 pt-8 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
        <p className="line-clamp-2 text-xs font-medium text-white/95">{item.prompt}</p>
        <p className="mt-1 text-[11px] text-white/70">
          {item.model} · {item.aspect}
        </p>
      </figcaption>

      {/* Actions */}
      {showActions && (
        <div className="absolute right-2 top-2 flex gap-1.5 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
          {onLike && (
            <button
              type="button"
              onClick={() => onLike(item.id)}
              aria-pressed={item.liked}
              aria-label={item.liked ? 'Remove from favourites' : 'Add to favourites'}
              className="grid h-8 w-8 place-items-center rounded-lg bg-black/45 text-white backdrop-blur-sm transition hover:bg-black/65"
            >
              <Heart
                size={15}
                aria-hidden="true"
                className={cn(item.liked && 'fill-current text-rose-400')}
              />
            </button>
          )}
          <a
            href={downloadUrl}
            download={`omnibrand-${item.id}.svg`}
            aria-label="Download image"
            className="grid h-8 w-8 place-items-center rounded-lg bg-black/45 text-white backdrop-blur-sm transition hover:bg-black/65"
            onClick={(e) => e.stopPropagation()}
          >
            <Download size={15} aria-hidden="true" />
          </a>
          {onRemove && (
            <button
              type="button"
              onClick={() => onRemove(item.id)}
              aria-label="Delete image"
              className="grid h-8 w-8 place-items-center rounded-lg bg-black/45 text-white backdrop-blur-sm transition hover:bg-danger/80"
            >
              <Trash2 size={15} aria-hidden="true" />
            </button>
          )}
        </div>
      )}

      {/* Corner hint */}
      <span
        className="pointer-events-none absolute left-2 top-2 grid h-7 w-7 place-items-center rounded-lg bg-black/40 text-white opacity-0 backdrop-blur-sm transition-opacity group-hover:opacity-100"
        aria-hidden="true"
      >
        <Maximize2 size={13} />
      </span>
    </figure>
  );
}
