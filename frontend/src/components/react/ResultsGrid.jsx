import { useState } from 'react';
import { ImageCard } from './ImageCard.jsx';
import { ImageDetailModal } from './ImageDetailModal.jsx';
import { cn } from '@/lib/cn.js';

/**
 * Masonry-style responsive grid of generated images (CSS multi-column so tiles
 * of different aspect ratios pack naturally). Owns the shared detail lightbox.
 */
export function ResultsGrid({ items, onLike, onRemove, onUsePrompt, className }) {
  const [active, setActive] = useState(null);

  // Keep the open modal in sync with the latest item data (likes etc.).
  const activeItem = active ? items.find((i) => i.id === active.id) ?? active : null;

  return (
    <>
      <div
        className={cn(
          'columns-2 gap-3 sm:gap-4 md:columns-3 xl:columns-4 [&>*]:mb-3 sm:[&>*]:mb-4',
          className,
        )}
      >
        {items.map((item) => (
          <div key={item.id} className="break-inside-avoid animate-fade-up">
            <ImageCard
              item={item}
              onOpen={setActive}
              onLike={onLike}
              onRemove={onRemove}
            />
          </div>
        ))}
      </div>

      <ImageDetailModal
        item={activeItem}
        open={Boolean(active)}
        onClose={() => setActive(null)}
        onLike={onLike}
        onRemove={onRemove}
        onUsePrompt={onUsePrompt}
      />
    </>
  );
}
