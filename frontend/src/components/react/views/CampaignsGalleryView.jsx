import { useEffect, useMemo, useState } from 'react';
import {
  RefreshCw,
  CheckCircle2,
  Loader2,
  Clock,
  Eye,
  AlertTriangle,
  XCircle,
  Sparkles,
  Layers,
  DollarSign,
  Copy,
  Check,
  ArrowUpRight,
  X,
  ClipboardList,
} from 'lucide-react';
import { Page } from '../Page.jsx';
import { Button } from '../ui/Button.jsx';
import { cn } from '@/lib/cn.js';
import { fetchRecentCampaigns, getCampaign } from '@/lib/api.js';

// Status → visual treatment. Tone classes use the theme-aware semantic tokens
// so they read correctly in both light and dark mode.
const STATUS_META = {
  published: { label: 'Published', icon: CheckCircle2, tone: 'success' },
  running: { label: 'Running', icon: Loader2, tone: 'brand', spin: true },
  queued: { label: 'Queued', icon: Clock, tone: 'warning' },
  awaiting_review: { label: 'Awaiting review', icon: Eye, tone: 'warning' },
  failed: { label: 'Failed', icon: AlertTriangle, tone: 'danger' },
  cancelled: { label: 'Cancelled', icon: XCircle, tone: 'muted' },
  draft: { label: 'Draft', icon: Clock, tone: 'muted' },
  archived: { label: 'Archived', icon: Layers, tone: 'muted' },
};

const TONE_CLASSES = {
  success: 'bg-success/12 text-success ring-success/20',
  brand: 'bg-brand/12 text-brand ring-brand/20',
  warning: 'bg-warning/12 text-warning ring-warning/20',
  danger: 'bg-danger/12 text-danger ring-danger/20',
  muted: 'bg-surface-2 text-muted ring-border',
};

const metaFor = (status) => STATUS_META[(status || '').toLowerCase()] || STATUS_META.draft;

const TERMINAL_STATUSES = new Set(['published', 'failed', 'cancelled', 'archived']);

function isInProgressStatus(status) {
  const normalized = String(status || '').toLowerCase();
  if (!normalized) return false;
  if (TERMINAL_STATUSES.has(normalized)) return false;
  return normalized !== 'draft';
}

function relativeTime(value) {
  if (!value) return '—';
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return '—';
  const diff = Date.now() - then;
  const min = Math.round(diff / 60000);
  if (min < 1) return 'just now';
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.round(hr / 24);
  if (day < 30) return `${day}d ago`;
  return new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

const shortId = (id = '') => (id.length > 12 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id);

function StatusPill({ status }) {
  const meta = metaFor(status);
  const Icon = meta.icon;
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset',
        TONE_CLASSES[meta.tone],
      )}
    >
      <Icon size={12} aria-hidden="true" className={meta.spin ? 'animate-spin' : ''} />
      {meta.label}
    </span>
  );
}

function StatCard({ icon: Icon, label, value, accent = 'text-brand' }) {
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-border bg-surface p-4 card-shadow">
      <span className={cn('grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-surface-2', accent)}>
        <Icon size={18} aria-hidden="true" />
      </span>
      <div className="min-w-0">
        <p className="truncate text-xs font-medium text-muted">{label}</p>
        <p className="text-xl font-semibold tracking-tight text-fg">{value}</p>
      </div>
    </div>
  );
}

function CopyId({ id }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        navigator.clipboard?.writeText(id).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1200);
        });
      }}
      title="Copy campaign ID"
      className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 font-mono text-xs text-muted transition-colors hover:bg-surface-2 hover:text-fg"
    >
      {shortId(id)}
      {copied ? (
        <Check size={12} aria-hidden="true" className="text-success" />
      ) : (
        <Copy size={12} aria-hidden="true" />
      )}
    </button>
  );
}

function CampaignCard({ campaign, onClick }) {
  const meta = metaFor(campaign.status);
  return (
    <article
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => e.key === 'Enter' && onClick?.()}
      className="group relative flex cursor-pointer flex-col overflow-hidden rounded-2xl border border-border bg-surface p-4 transition-all hover:-translate-y-0.5 hover:border-border-strong hover:card-shadow focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
    >
      {/* top accent that hints the status colour */}
      <span
        aria-hidden="true"
        className={cn('absolute inset-x-0 top-0 h-0.5 opacity-70', {
          'bg-success': meta.tone === 'success',
          'bg-brand': meta.tone === 'brand',
          'bg-warning': meta.tone === 'warning',
          'bg-danger': meta.tone === 'danger',
          'bg-border-strong': meta.tone === 'muted',
        })}
      />
      <header className="flex items-center justify-between gap-2">
        <StatusPill status={campaign.status} />
        <span className="text-xs text-faint">{relativeTime(campaign.created_at)}</span>
      </header>

      <div className="mt-3 flex items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[11px] font-medium uppercase tracking-wide text-faint">Campaign</p>
          <CopyId id={campaign.campaign_id} />
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 border-t border-border pt-3">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wide text-faint">Variants</p>
          <p className="mt-0.5 text-sm font-semibold text-fg">{campaign.variant_count ?? 0}</p>
        </div>
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wide text-faint">Cost</p>
          <p className="mt-0.5 text-sm font-semibold text-fg">
            ${Number(campaign.cost_usd || 0).toFixed(4)}
          </p>
        </div>
      </div>

      <div className="mt-3 flex items-center gap-1.5 text-[11px] text-faint">
        <span className="truncate font-mono">brand {shortId(campaign.brand_id)}</span>
      </div>
    </article>
  );
}

function CardSkeleton() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-4">
      <div className="flex items-center justify-between">
        <div className="shimmer relative h-6 w-24 overflow-hidden rounded-full bg-surface-2" />
        <div className="shimmer relative h-3 w-12 overflow-hidden rounded bg-surface-2" />
      </div>
      <div className="shimmer relative mt-4 h-4 w-32 overflow-hidden rounded bg-surface-2" />
      <div className="mt-4 grid grid-cols-2 gap-3 border-t border-border pt-3">
        <div className="shimmer relative h-8 overflow-hidden rounded bg-surface-2" />
        <div className="shimmer relative h-8 overflow-hidden rounded bg-surface-2" />
      </div>
    </div>
  );
}

function CampaignDetailModal({ campaignId, onClose }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    getCampaign(campaignId)
      .then((d) => { if (!cancelled) { setDetail(d); setLoading(false); } })
      .catch((e) => { if (!cancelled) { setError(e instanceof Error ? e.message : 'Failed to load'); setLoading(false); } });
    return () => { cancelled = true; };
  }, [campaignId]);

  const airtableRecords = detail?.airtable_review_records ?? [];
  const variants = detail?.variants ?? [];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="relative flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-3xl border border-border bg-surface card-shadow">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <div>
            <p className="text-[11px] font-medium uppercase tracking-wide text-faint">Campaign</p>
            <p className="font-mono text-sm font-semibold text-fg">{shortId(campaignId)}</p>
          </div>
          {detail && <StatusPill status={detail.status} />}
          <button
            type="button"
            onClick={onClose}
            className="grid h-8 w-8 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-fg"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 space-y-5 overflow-y-auto px-6 py-5">
          {loading && (
            <div className="flex items-center gap-2 text-sm text-muted">
              <Loader2 size={16} className="animate-spin" />
              Loading campaign details…
            </div>
          )}
          {error && <p className="text-sm text-danger">{error}</p>}
          {detail && (
            <>
              {/* Cost + tokens */}
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[
                  { label: 'Cost', value: `$${Number(detail.token_cost_usd || 0).toFixed(4)}` },
                  { label: 'Status', value: detail.status },
                  { label: 'Started', value: detail.started_at ? relativeTime(detail.started_at) : '—' },
                  { label: 'Completed', value: detail.completed_at ? relativeTime(detail.completed_at) : '—' },
                ].map(({ label, value }) => (
                  <div key={label} className="rounded-xl border border-border bg-surface-2 px-3 py-2.5">
                    <p className="text-[10px] font-medium uppercase tracking-wide text-faint">{label}</p>
                    <p className="mt-0.5 text-sm font-semibold text-fg">{value}</p>
                  </div>
                ))}
              </div>

              {/* Variants */}
              {variants.length > 0 && (
                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-faint">
                    Variants ({variants.length})
                  </h3>
                  <div className="space-y-2">
                    {variants.map((v) => (
                      <div key={v.task_id} className="rounded-xl border border-border bg-surface-2 px-3 py-2.5 text-xs">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-mono font-medium text-fg">{v.task_id}</span>
                          <span className="rounded-full bg-surface px-1.5 py-0.5 text-[10px] text-muted">{v.channel}</span>
                          <span className="rounded-full bg-surface px-1.5 py-0.5 text-[10px] text-muted">{v.locale}</span>
                          <span className="rounded-full bg-surface px-1.5 py-0.5 text-[10px] text-muted">{v.segment}</span>
                          {typeof v.composite_score === 'number' && (
                            <span className="ml-auto font-semibold text-brand">{v.composite_score.toFixed(2)}</span>
                          )}
                        </div>
                        {v.final_content && (
                          <p className="mt-1.5 line-clamp-3 text-muted">{v.final_content}</p>
                        )}
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* Human Review (Airtable) */}
              <section>
                <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-faint">
                  <ClipboardList size={12} /> Human Review
                </h3>
                {airtableRecords.length === 0 ? (
                  <p className="text-xs text-faint">
                    No human review records — this campaign was auto-approved or Airtable is not configured.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {airtableRecords.map((r, i) => (
                      <div key={r.airtable_record_id || i} className="rounded-xl border border-warning/30 bg-warning/5 px-3 py-2.5 text-xs">
                        <div className="flex flex-wrap gap-2">
                          {Object.entries(r)
                            .filter(([k]) => k !== 'airtable_record_id')
                            .slice(0, 8)
                            .map(([k, v]) => (
                              <span key={k} className="text-muted">
                                <span className="font-medium text-fg">{k}:</span> {String(v ?? '—')}
                              </span>
                            ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export function CampaignsGalleryView() {
  const [campaigns, setCampaigns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('all');
  const [selectedCampaignId, setSelectedCampaignId] = useState(null);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const payload = await fetchRecentCampaigns();
      setCampaigns(payload.campaigns || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load campaigns');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const stats = useMemo(() => {
    const total = campaigns.length;
    const published = campaigns.filter((c) => (c.status || '').toLowerCase() === 'published').length;
    const active = campaigns.filter((c) => isInProgressStatus(c.status)).length;
    const variants = campaigns.reduce((n, c) => n + (c.variant_count || 0), 0);
    const spend = campaigns.reduce((n, c) => n + Number(c.cost_usd || 0), 0);
    return { total, published, active, variants, spend };
  }, [campaigns]);

  const filters = useMemo(
    () => [
      { key: 'all', label: 'All', count: campaigns.length },
      { key: 'published', label: 'Published', count: stats.published },
      { key: 'active', label: 'In progress', count: stats.active },
      {
        key: 'failed',
        label: 'Failed',
        count: campaigns.filter((c) => ['failed', 'cancelled'].includes((c.status || '').toLowerCase()))
          .length,
      },
    ],
    [campaigns, stats],
  );

  const visible = useMemo(() => {
    return campaigns.filter((c) => {
      const status = (c.status || '').toLowerCase();
      const matchesFilter =
        filter === 'all' ||
        (filter === 'published' && status === 'published') ||
        (filter === 'active' && isInProgressStatus(status)) ||
        (filter === 'failed' && ['failed', 'cancelled'].includes(status));
      return matchesFilter;
    });
  }, [campaigns, filter]);

  let content = null;
  if (loading) {
    content = (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <CardSkeleton key={i} />
        ))}
      </div>
    );
  } else if (visible.length > 0) {
    content = (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {visible.map((c) => (
          <CampaignCard key={c.campaign_id} campaign={c} onClick={() => setSelectedCampaignId(c.campaign_id)} />
        ))}
      </div>
    );
  } else if (campaigns.length === 0) {
    content = (
      <EmptyState
        title="No campaigns yet"
        body="Kick off your first campaign from the workspace — it'll show up here with live status and results."
        cta
      />
    );
  } else {
    content = (
      <EmptyState
        title="Nothing matches your filters"
        body="Try a different status filter."
      />
    );
  }

  return (
    <>
    <Page
      wide
      eyebrow="Workspace"
      title="Campaign Gallery"
      description="Every campaign your team has run — track status, output, and spend at a glance."
      actions={
        <div className="flex items-center gap-2">
          <Button as="a" href="/app" variant="primary" size="md">
            <Sparkles size={15} aria-hidden="true" /> New campaign
          </Button>
          <Button variant="secondary" onClick={load} disabled={loading}>
            <RefreshCw size={15} aria-hidden="true" className={loading ? 'animate-spin' : ''} />
            {loading ? 'Refreshing…' : 'Refresh'}
          </Button>
        </div>
      }
    >
      {/* KPI row */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard icon={Layers} label="Total campaigns" value={stats.total} accent="text-brand" />
        <StatCard icon={CheckCircle2} label="Published" value={stats.published} accent="text-success" />
        <StatCard icon={Loader2} label="In progress" value={stats.active} accent="text-warning" />
        <StatCard
          icon={DollarSign}
          label="Total spend"
          value={`$${stats.spend.toFixed(2)}`}
          accent="text-fg"
        />
      </div>

      {/* Toolbar: filters */}
      <div className="mt-6">
        <div className="flex flex-wrap items-center gap-1.5">
          {filters.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key)}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium transition-colors',
                filter === f.key
                  ? 'bg-brand text-brand-fg'
                  : 'text-muted hover:bg-surface-2 hover:text-fg',
              )}
            >
              {f.label}
              <span
                className={cn(
                  'rounded-full px-1.5 text-xs',
                  filter === f.key ? 'bg-brand-fg/20 text-brand-fg' : 'bg-surface-2 text-faint',
                )}
              >
                {f.count}
              </span>
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="mt-4 flex items-center gap-2 rounded-xl border border-danger/30 bg-danger/5 px-3 py-2.5 text-sm text-danger">
          <AlertTriangle size={15} aria-hidden="true" /> {error}
        </div>
      )}

      {/* Content */}
      <div className="mt-5">{content}</div>
    </Page>

    {selectedCampaignId && (
      <CampaignDetailModal campaignId={selectedCampaignId} onClose={() => setSelectedCampaignId(null)} />
    )}
    </>
  );
}

function EmptyState({ title, body, cta = false }) {
  return (
    <div className="relative overflow-hidden rounded-3xl border border-dashed border-border-strong bg-surface/60 px-6 py-16 text-center">
      <div className="brand-glow pointer-events-none absolute inset-0 opacity-30" aria-hidden="true" />
      <div className="relative mx-auto max-w-sm">
        <span className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-brand-soft text-brand">
          <Layers size={26} aria-hidden="true" />
        </span>
        <h3 className="mt-4 text-lg font-semibold text-fg">{title}</h3>
        <p className="mt-1.5 text-sm text-muted">{body}</p>
        {cta && (
          <Button as="a" href="/app" variant="primary" size="md" className="mt-5">
            <Sparkles size={15} aria-hidden="true" /> Start a campaign
            <ArrowUpRight size={15} aria-hidden="true" />
          </Button>
        )}
      </div>
    </div>
  );
}
