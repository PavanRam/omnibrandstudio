import { Check, Loader2 } from 'lucide-react';
import { cn } from '@/lib/cn.js';

// Pipeline stages, in the order the LangGraph graph runs them.
const STAGES = [
  'Intake',
  'Content generation',
  'Personalization',
  'Translation',
  'Brand judges (×3)',
  'Score aggregation',
  'Review gate',
  'Publishing',
];

// The status endpoint is coarse (queued → running → terminal), so while the
// pipeline is "running" we advance a visual pointer through the stages on a
// timer to convey progress. This is an affordance, not exact backend telemetry.
const MS_PER_STAGE = 2600;

function activeStageIndex(status, elapsedMs) {
  if (status === 'queued' || status == null) return -1;
  return Math.min(Math.floor(elapsedMs / MS_PER_STAGE), STAGES.length - 1);
}

function SkeletonVariantCard() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-4">
      <div className="mb-3 flex gap-2">
        <div className="shimmer h-5 w-16 rounded-full bg-surface-2" />
        <div className="shimmer h-5 w-14 rounded-full bg-surface-2" />
      </div>
      <div className="space-y-2">
        <div className="shimmer h-3 w-full rounded bg-surface-2" />
        <div className="shimmer h-3 w-[92%] rounded bg-surface-2" />
        <div className="shimmer h-3 w-[78%] rounded bg-surface-2" />
      </div>
    </div>
  );
}

/**
 * Loading state shown while a campaign is queued/running: an animated pipeline
 * stepper plus skeleton variant cards.
 */
export function CampaignProgress({ status, elapsedMs = 0, taskCount = 4, campaignId }) {
  const active = activeStageIndex(status, elapsedMs);
  const queued = status === 'queued' || status == null;
  const skeletons = Math.max(1, Math.min(taskCount, 8));

  return (
    <div className="rounded-3xl border border-border bg-surface p-5 card-shadow sm:p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Loader2 size={18} aria-hidden="true" className="animate-spin text-brand" />
          <h2 className="text-base font-semibold text-fg">
            {queued ? 'Queued — waiting for a worker…' : 'Generating your campaign…'}
          </h2>
        </div>
        <span className="text-xs text-muted">
          {(elapsedMs / 1000).toFixed(0)}s · status:{' '}
          <span className="font-medium text-fg">{status || 'queued'}</span>
        </span>
      </div>

      {campaignId && (
        <p className="mb-4 font-mono text-[11px] text-faint">campaign {campaignId}</p>
      )}

      {/* Pipeline stepper */}
      <ol className="mb-6 grid gap-2 sm:grid-cols-2" aria-label="Pipeline progress">
        {STAGES.map((stage, i) => {
          const done = !queued && i < active;
          const running = !queued && i === active;
          return (
            <li
              key={stage}
              className={cn(
                'flex items-center gap-2.5 rounded-xl border px-3 py-2 text-sm transition-colors',
                running
                  ? 'border-brand/40 bg-brand-soft text-brand'
                  : done
                    ? 'border-transparent bg-surface-2 text-fg'
                    : 'border-border bg-surface text-faint',
              )}
            >
              <span
                className={cn(
                  'grid h-5 w-5 shrink-0 place-items-center rounded-full text-[10px] font-semibold',
                  done
                    ? 'bg-success/15 text-success'
                    : running
                      ? 'brand-gradient text-white'
                      : 'bg-surface-3 text-faint',
                )}
                aria-hidden="true"
              >
                {done ? (
                  <Check size={12} />
                ) : running ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : (
                  i + 1
                )}
              </span>
              <span className="truncate font-medium">{stage}</span>
            </li>
          );
        })}
      </ol>

      {/* Skeleton variant placeholders */}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: skeletons }).map((_, i) => (
          <SkeletonVariantCard key={i} />
        ))}
      </div>
    </div>
  );
}
