import { useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  RotateCcw,
  Megaphone,
} from 'lucide-react';
import { Page, SectionHeading } from '../Page.jsx';
import { CampaignForm } from '../CampaignForm.jsx';
import { CampaignProgress } from '../CampaignProgress.jsx';
import { VariantCard } from '../VariantCard.jsx';
import { Badge } from '../ui/Badge.jsx';
import { Button } from '../ui/Button.jsx';
import { useCampaign } from '../hooks/useCampaign.js';
import { API_BASE_URL } from '@/lib/api.js';
import { cn } from '@/lib/cn.js';

const STATUS_TONE = {
  published: 'success',
  awaiting_review: 'warning',
  failed: 'danger',
  cancelled: 'danger',
  running: 'brand',
  queued: 'neutral',
};

const STATUS_COPY = {
  published: 'Published — all variants approved and sent to their channels.',
  awaiting_review: 'Awaiting human review — the pipeline paused at the review gate.',
  failed: 'The pipeline failed. Check the worker logs (docker compose logs -f worker).',
  cancelled: 'The campaign was cancelled.',
};

export function CampaignView() {
  const { phase, campaignId, status, campaign, campaignStatus, error, elapsedMs, submit, reset } =
    useCampaign();

  // Remember the submitted payload so we can size the loading skeletons.
  const [lastPayload, setLastPayload] = useState(null);
  const expectedVariants = lastPayload
    ? lastPayload.channels.length *
      lastPayload.locales.length *
      lastPayload.audience_segments.length
    : 4;

  const handleSubmit = (payload) => {
    setLastPayload(payload);
    submit(payload);
  };

  const variants = campaign?.variants ?? [];
  const busy = phase === 'submitting' || phase === 'polling';

  const costLabel = useMemo(() => {
    const cost = campaign?.token_cost_usd ?? campaignStatus?.token_cost_usd;
    return typeof cost === 'number' ? `$${cost.toFixed(4)}` : null;
  }, [campaign, campaignStatus]);

  return (
    <Page
      eyebrow="OmniBrand pipeline"
      title="Campaign Studio"
      description="Turn a single brief into brand-compliant content for every channel and locale — generated, judged and scored by the agentic pipeline."
      actions={
        <Badge tone="neutral" className="font-mono">
          API · {API_BASE_URL.replace(/^https?:\/\//, '')}
        </Badge>
      }
      wide
    >
      <div className="grid gap-6 lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)] lg:items-start">
        {/* Brief form */}
        <div className="lg:sticky lg:top-6">
          <CampaignForm onSubmit={handleSubmit} busy={busy} />
        </div>

        {/* Results column */}
        <div className="min-w-0">
          {campaignId ? (
            <div className="mb-3 flex flex-wrap items-center gap-2 rounded-xl border border-border bg-surface-2 px-3 py-2 text-xs text-muted">
              <span className="font-medium text-fg">Campaign total cost</span>
              <Badge tone="neutral" className="font-mono">
                {costLabel || 'calculating...'}
              </Badge>
              <span>Campaign {campaignId.slice(0, 12)}...</span>
            </div>
          ) : null}

          {phase === 'idle' && (
            <div className="grid min-h-[320px] place-items-center rounded-3xl border border-dashed border-border bg-surface-2/40 p-8 text-center">
              <div className="max-w-sm">
                <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-brand-soft text-brand">
                  <Megaphone size={22} aria-hidden="true" />
                </span>
                <h2 className="mt-4 text-lg font-semibold text-fg">
                  Your generated content will appear here
                </h2>
                <p className="mt-1.5 text-sm text-muted">
                  Fill in the brief and hit <span className="font-medium">Generate campaign</span>.
                  You'll see live pipeline progress, then a card per variant with its brand score.
                </p>
              </div>
            </div>
          )}

          {busy && (
            <CampaignProgress
              status={status}
              elapsedMs={elapsedMs}
              taskCount={expectedVariants}
              campaignId={campaignId}
            />
          )}

          {phase === 'error' && (
            <div className="rounded-3xl border border-danger/30 bg-danger/5 p-6">
              <div className="flex items-start gap-3">
                <AlertTriangle size={20} aria-hidden="true" className="mt-0.5 shrink-0 text-danger" />
                <div className="min-w-0">
                  <h2 className="text-base font-semibold text-fg">Something went wrong</h2>
                  <p className="mt-1 break-words text-sm text-muted">{error}</p>
                  {campaignId && (
                    <p className="mt-2 font-mono text-[11px] text-faint">campaign {campaignId}</p>
                  )}
                  <Button variant="secondary" size="sm" className="mt-4" onClick={reset}>
                    <RotateCcw size={14} aria-hidden="true" /> Try again
                  </Button>
                </div>
              </div>
            </div>
          )}

          {phase === 'done' && (
            <div>
              {/* Result summary */}
              <div
                className={cn(
                  'mb-5 rounded-2xl border p-4',
                  status === 'failed' || status === 'cancelled'
                    ? 'border-danger/30 bg-danger/5'
                    : status === 'published'
                      ? 'border-success/30 bg-success/5'
                      : 'border-warning/30 bg-warning/5',
                )}
              >
                <div className="flex flex-wrap items-center gap-3">
                  {status === 'published' ? (
                    <CheckCircle2 size={20} aria-hidden="true" className="text-success" />
                  ) : status === 'failed' || status === 'cancelled' ? (
                    <AlertTriangle size={20} aria-hidden="true" className="text-danger" />
                  ) : (
                    <Clock size={20} aria-hidden="true" className="text-warning" />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold text-fg">Status</span>
                      <Badge tone={STATUS_TONE[status] || 'neutral'}>{status}</Badge>
                      {costLabel && (
                        <span className="text-xs text-muted">· cost {costLabel}</span>
                      )}
                    </div>
                    <p className="mt-1 text-sm text-muted">
                      {STATUS_COPY[status] || 'Campaign processing complete.'}
                    </p>
                  </div>
                  <Button variant="secondary" size="sm" onClick={reset}>
                    <RotateCcw size={14} aria-hidden="true" /> New campaign
                  </Button>
                </div>
              </div>

              {/* Variants */}
              {variants.length > 0 ? (
                <>
                  <SectionHeading
                    title="Generated variants"
                    description={`${variants.length} variant${variants.length === 1 ? '' : 's'} across your channels, locales and segments.`}
                  />
                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                    {variants.map((v, i) => (
                      <VariantCard key={v.task_id || i} variant={v} />
                    ))}
                  </div>
                </>
              ) : (
                <div className="rounded-2xl border border-dashed border-border bg-surface-2/40 p-6 text-center text-sm text-muted">
                  No variants were returned. If the status is <b>failed</b>, the worker likely
                  needs a valid <code className="font-mono">ANTHROPIC_API_KEY</code> in the backend
                  <code className="font-mono"> .env</code>.
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </Page>
  );
}
