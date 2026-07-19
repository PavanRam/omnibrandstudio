import { aspectStyle } from './ImageCard.jsx';

/** Placeholder tiles shown while a batch is generating. */
export function SkeletonGrid({ count = 4, aspect = '1:1' }) {
  return (
    <div className="columns-2 gap-3 sm:gap-4 md:columns-3 xl:columns-4 [&>*]:mb-3 sm:[&>*]:mb-4">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="break-inside-avoid">
          <div
            className="shimmer relative overflow-hidden rounded-2xl border border-border bg-surface-2"
            style={aspectStyle(aspect)}
            aria-hidden="true"
          />
        </div>
      ))}
    </div>
  );
}
