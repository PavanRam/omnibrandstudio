import { useEffect, useMemo, useRef, useState } from 'react';
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
  ChevronDown,
  ClipboardList,
  FileText,
  BarChart2,
  Users,
} from 'lucide-react';
import { Page } from '../Page.jsx';
import { Button } from '../ui/Button.jsx';
import { cn } from '@/lib/cn.js';
import { fetchRecentCampaigns, getCampaign } from '@/lib/api.js';

// ─── Status helpers ───────────────────────────────────────────────────────────

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

const DECISION_TONE = {
  approved: 'bg-success/12 text-success ring-success/20',
  rejected: 'bg-danger/12 text-danger ring-danger/20',
  pending: 'bg-warning/12 text-warning ring-warning/20',
};

const metaFor = (status) => STATUS_META[(status || '').toLowerCase()] || STATUS_META.draft;

function scoreTone(score) {
  if (score >= 0.75) return 'bg-success/12 text-success';
  if (score >= 0.5) return 'bg-warning/12 text-warning';
  return 'bg-danger/12 text-danger';
}

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

// ─── Small primitives ─────────────────────────────────────────────────────────

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

function DecisionBadge({ decision }) {
  const d = (decision || 'pending').toLowerCase();
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium capitalize ring-1 ring-inset',
        DECISION_TONE[d] ?? DECISION_TONE.pending,
      )}
    >
      {d}
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

// ─── Tab: Brief ───────────────────────────────────────────────────────────────

function BriefTab({ brief }) {
  if (!brief || Object.keys(brief).length === 0) {
    return <p className="text-xs text-faint">No brief data recorded for this campaign.</p>;
  }
  const entries = Object.entries(brief).filter(([, v]) => v !== null && v !== '' && v !== undefined);
  return (
    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {entries.map(([key, value]) => (
        <div key={key} className="rounded-xl border border-border bg-surface px-3 py-2.5">
          <p className="text-[10px] font-medium uppercase tracking-wide text-faint">
            {key.replaceAll('_', ' ')}
          </p>
          <p className="mt-0.5 text-sm text-fg">
            {Array.isArray(value) ? value.join(', ') : String(value)}
          </p>
        </div>
      ))}
    </div>
  );
}

// ─── Tab: Variants (grouped by channel) ──────────────────────────────────────

function VariantsTab({ variants }) {
  if (!variants || variants.length === 0) {
    return <p className="text-xs text-faint">No variants generated for this campaign yet.</p>;
  }

  const byChannel = variants.reduce((acc, v) => {
    const ch = v.channel || 'unknown';
    if (!acc[ch]) acc[ch] = [];
    acc[ch].push(v);
    return acc;
  }, {});

  return (
    <div className="space-y-4">
      {Object.entries(byChannel).map(([channel, channelVariants]) => (
        <div key={channel}>
          <h4 className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">
            <Users size={11} aria-hidden="true" />
            {channel}
            <span className="rounded-full bg-surface-2 px-1.5 text-[10px] text-faint">
              {channelVariants.length}
            </span>
          </h4>
          <div className="space-y-2">
            {channelVariants.map((v) => (
              <div
                key={v.task_id}
                className="rounded-xl border border-border bg-surface px-3 py-2.5 text-xs"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono font-medium text-fg">{shortId(v.task_id)}</span>
                  <span className="rounded-full bg-surface-2 px-1.5 py-0.5 text-[10px] text-muted">
                    {v.locale}
                  </span>
                  {v.segment && (
                    <span className="rounded-full bg-surface-2 px-1.5 py-0.5 text-[10px] text-muted">
                      {v.segment}
                    </span>
                  )}
                  {v.status && (
                    <span className="rounded-full bg-surface-2 px-1.5 py-0.5 text-[10px] text-muted">
                      {v.status}
                    </span>
                  )}
                  {typeof v.composite_score === 'number' && (
                    <span
                      className={cn(
                        'ml-auto rounded-full px-2 py-0.5 text-[11px] font-semibold',
                        scoreTone(v.composite_score),
                      )}
                    >
                      {v.composite_score.toFixed(2)}
                    </span>
                  )}
                </div>
                {v.final_content && (
                  <p className="mt-1.5 line-clamp-3 text-muted">{v.final_content}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Tab: Scores ──────────────────────────────────────────────────────────────

function ScoresTab({ variants }) {
  if (!variants || variants.length === 0) {
    return <p className="text-xs text-faint">No score data available yet.</p>;
  }
  const scored = variants.filter((v) => typeof v.composite_score === 'number');
  if (scored.length === 0) {
    return <p className="text-xs text-faint">Scoring has not completed for this campaign.</p>;
  }

  const avg = scored.reduce((n, v) => n + v.composite_score, 0) / scored.length;
  const high = Math.max(...scored.map((v) => v.composite_score));
  const low = Math.min(...scored.map((v) => v.composite_score));

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: 'Avg score', value: avg.toFixed(2) },
          { label: 'Best', value: high.toFixed(2) },
          { label: 'Lowest', value: low.toFixed(2) },
        ].map(({ label, value }) => (
          <div key={label} className="rounded-xl border border-border bg-surface px-3 py-2.5 text-center">
            <p className="text-[10px] font-medium uppercase tracking-wide text-faint">{label}</p>
            <p className="mt-0.5 text-base font-semibold text-brand">{value}</p>
          </div>
        ))}
      </div>

      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border bg-surface-2">
              <th className="px-3 py-2 text-left font-medium text-faint">Variant</th>
              <th className="px-3 py-2 text-left font-medium text-faint">Channel</th>
              <th className="px-3 py-2 text-left font-medium text-faint">Locale</th>
              <th className="px-3 py-2 text-left font-medium text-faint">Segment</th>
              <th className="px-3 py-2 text-right font-medium text-faint">Score</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {[...scored]
              .sort((a, b) => b.composite_score - a.composite_score)
              .map((v) => (
                <tr key={v.task_id} className="bg-surface hover:bg-surface-2">
                  <td className="px-3 py-2 font-mono text-faint">{shortId(v.task_id)}</td>
                  <td className="px-3 py-2 text-fg">{v.channel}</td>
                  <td className="px-3 py-2 text-fg">{v.locale}</td>
                  <td className="px-3 py-2 text-muted">{v.segment || '—'}</td>
                  <td className="px-3 py-2 text-right">
                    <span className={cn('rounded-full px-2 py-0.5 font-semibold', scoreTone(v.composite_score))}>
                      {v.composite_score.toFixed(2)}
                    </span>
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Tab: Human Review (Airtable) ─────────────────────────────────────────────

function HumanReviewTab({ records }) {
  if (!records || records.length === 0) {
    return (
      <p className="text-xs text-faint">
        No human review records — this campaign was auto-approved or Airtable is not configured.
      </p>
    );
  }
  return (
    <div className="space-y-2">
      {records.map((r, i) => {
        const decision = String(r['Decision'] || r['decision'] || 'pending');
        const reviewerNote = r['Reviewer Note'] || r['reviewer_note'] || '';
        const generatedContent = r['Generated Content'] || r['generated_content'] || '';
        const personalizedContent = r['Personalized Content'] || r['personalized_content'] || '';
        const translatedContent = r['Translated Content'] || r['translated_content'] || '';
        const variantId = r['variant_id'] || '';
        const generatedAt = r['Generated At'] || r['generated_at'] || '';
        const requesterEmail = r['Requester Email'] || r['requester_email'] || '';
        const status = r['status'] || r['Status'] || '';
        const content = personalizedContent || translatedContent || generatedContent;

        return (
          <div
            key={r.airtable_record_id || i}
            className="rounded-xl border border-border bg-surface px-4 py-3 text-xs"
          >
            <div className="flex flex-wrap items-center gap-2">
              <DecisionBadge decision={decision} />
              {status && (
                <span className="rounded-full bg-surface-2 px-1.5 py-0.5 text-[10px] text-muted">
                  {status}
                </span>
              )}
              {generatedAt && (
                <span className="text-faint">{relativeTime(generatedAt)}</span>
              )}
              {requesterEmail && (
                <span className="ml-auto font-mono text-faint">{requesterEmail}</span>
              )}
            </div>
            {content && (
              <p className="mt-2 line-clamp-2 text-muted">{content}</p>
            )}
            {reviewerNote && (
              <div className="mt-2 rounded-lg bg-warning/5 px-2.5 py-1.5 text-warning">
                <span className="font-medium">Note: </span>{reviewerNote}
              </div>
            )}
            {variantId && (
              <p className="mt-1.5 font-mono text-[10px] text-faint">variant {shortId(variantId)}</p>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Detail panel (lazy-loaded on first expand) ───────────────────────────────

const DETAIL_TABS = [
  { key: 'variants', label: 'Variants', icon: Users },
  { key: 'brief', label: 'Brief', icon: FileText },
  { key: 'scores', label: 'Scores', icon: BarChart2 },
  { key: 'review', label: 'Human Review', icon: ClipboardList },
];

function CampaignDetailPanel({ campaignId }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('variants');
  const fetched = useRef(false);

  useEffect(() => {
    if (fetched.current) return;
    fetched.current = true;
    setLoading(true);
    getCampaign(campaignId)
      .then((d) => { setDetail(d); setLoading(false); })
      .catch((e) => { setError(e instanceof Error ? e.message : 'Failed to load'); setLoading(false); });
  }, [campaignId]);

  if (loading) {
    return (
      <div className="space-y-2 px-5 pb-5 pt-4">
        <div className="shimmer relative h-8 w-64 overflow-hidden rounded-lg bg-surface-2" />
        <div className="shimmer relative h-20 overflow-hidden rounded-xl bg-surface-2" />
        <div className="shimmer relative h-16 overflow-hidden rounded-xl bg-surface-2" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center gap-2 px-5 pb-5 pt-4 text-sm text-danger">
        <AlertTriangle size={14} aria-hidden="true" /> {error}
      </div>
    );
  }

  if (!detail) return null;

  return (
    <div className="border-t border-border">
      {/* Meta row */}
      <div className="grid grid-cols-2 gap-2 bg-surface-2/40 px-5 pt-4 sm:grid-cols-4">
        {[
          { label: 'Cost', value: `$${Number(detail.token_cost_usd || 0).toFixed(4)}` },
          { label: 'Started', value: detail.started_at ? relativeTime(detail.started_at) : '—' },
          { label: 'Completed', value: detail.completed_at ? relativeTime(detail.completed_at) : '—' },
          { label: 'Brand', value: shortId(detail.brand_id) },
        ].map(({ label, value }) => (
          <div key={label} className="rounded-xl border border-border bg-surface px-3 py-2 mb-3">
            <p className="text-[10px] font-medium uppercase tracking-wide text-faint">{label}</p>
            <p className="mt-0.5 font-mono text-xs font-semibold text-fg">{value}</p>
          </div>
        ))}
      </div>

      {/* Tab bar */}
      <div className="flex gap-0.5 border-b border-border bg-surface-2/40 px-5">
        {DETAIL_TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={cn(
              'flex items-center gap-1.5 border-b-2 px-3 pb-2.5 pt-1.5 text-xs font-medium transition-colors',
              tab === key
                ? 'border-brand text-brand'
                : 'border-transparent text-muted hover:text-fg',
            )}
          >
            <Icon size={12} aria-hidden="true" />
            {label}
            {key === 'review' && (detail.airtable_review_records?.length ?? 0) > 0 && (
              <span className="rounded-full bg-warning/15 px-1 text-[10px] text-warning">
                {detail.airtable_review_records.length}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="bg-surface px-5 py-4">
        {tab === 'brief' && <BriefTab brief={detail.brief} />}
        {tab === 'variants' && <VariantsTab variants={detail.variants} />}
        {tab === 'scores' && <ScoresTab variants={detail.variants} />}
        {tab === 'review' && <HumanReviewTab records={detail.airtable_review_records} />}
      </div>
    </div>
  );
}

// ─── Accordion row ────────────────────────────────────────────────────────────

function RowSkeleton() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="shimmer relative h-6 w-24 overflow-hidden rounded-full bg-surface-2" />
          <div className="shimmer relative h-4 w-32 overflow-hidden rounded bg-surface-2" />
        </div>
        <div className="shimmer relative h-4 w-16 overflow-hidden rounded bg-surface-2" />
      </div>
    </div>
  );
}

function CampaignAccordionItem({ campaign }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-surface transition-shadow hover:card-shadow">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-3.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-inset"
        aria-expanded={open}
      >
        <StatusPill status={campaign.status} />

        <div className="min-w-0 flex-1">
          <CopyId id={campaign.campaign_id} />
        </div>

        <div className="hidden shrink-0 items-center gap-5 sm:flex">
          <div className="text-right">
            <p className="text-[10px] font-medium uppercase tracking-wide text-faint">Variants</p>
            <p className="text-sm font-semibold text-fg">{campaign.variant_count ?? 0}</p>
          </div>
          <div className="text-right">
            <p className="text-[10px] font-medium uppercase tracking-wide text-faint">Cost</p>
            <p className="text-sm font-semibold text-fg">
              ${Number(campaign.cost_usd || 0).toFixed(4)}
            </p>
          </div>
          <div className="w-16 text-right">
            <p className="text-[10px] font-medium uppercase tracking-wide text-faint">When</p>
            <p className="text-xs text-muted">{relativeTime(campaign.created_at)}</p>
          </div>
        </div>

        <ChevronDown
          size={16}
          aria-hidden="true"
          className={cn('shrink-0 text-muted transition-transform duration-200', open && 'rotate-180')}
        />
      </button>

      {open && <CampaignDetailPanel campaignId={campaign.campaign_id} />}
    </div>
  );
}

// ─── Empty state ──────────────────────────────────────────────────────────────

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

// ─── Main view ────────────────────────────────────────────────────────────────

export function CampaignsGalleryView() {
  const [campaigns, setCampaigns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('all');

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

  useEffect(() => { load(); }, []);

  const stats = useMemo(() => {
    const total = campaigns.length;
    const published = campaigns.filter((c) => (c.status || '').toLowerCase() === 'published').length;
    const active = campaigns.filter((c) => isInProgressStatus(c.status)).length;
    const spend = campaigns.reduce((n, c) => n + Number(c.cost_usd || 0), 0);
    return { total, published, active, spend };
  }, [campaigns]);

  const filters = useMemo(
    () => [
      { key: 'all', label: 'All', count: campaigns.length },
      { key: 'published', label: 'Published', count: stats.published },
      { key: 'active', label: 'In progress', count: stats.active },
      {
        key: 'failed',
        label: 'Failed',
        count: campaigns.filter((c) =>
          ['failed', 'cancelled'].includes((c.status || '').toLowerCase()),
        ).length,
      },
    ],
    [campaigns, stats],
  );

  const visible = useMemo(() => {
    return campaigns.filter((c) => {
      const status = (c.status || '').toLowerCase();
      return (
        filter === 'all' ||
        (filter === 'published' && status === 'published') ||
        (filter === 'active' && isInProgressStatus(status)) ||
        (filter === 'failed' && ['failed', 'cancelled'].includes(status))
      );
    });
  }, [campaigns, filter]);

  let content = null;
  if (loading) {
    content = (
      <div className="space-y-2">
        {Array.from({ length: 6 }).map((_, i) => <RowSkeleton key={i} />)}
      </div>
    );
  } else if (visible.length > 0) {
    content = (
      <div className="space-y-2">
        {visible.map((c) => (
          <CampaignAccordionItem key={c.campaign_id} campaign={c} />
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
    <Page
      wide
      eyebrow="Workspace"
      title="Campaign Gallery"
      description="Every campaign your team has run — expand a row to see the brief, variants, scores, and Airtable review."
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

      {/* Filter pills */}
      <div className="mt-6 flex flex-wrap items-center gap-1.5">
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

      {error && (
        <div className="mt-4 flex items-center gap-2 rounded-xl border border-danger/30 bg-danger/5 px-3 py-2.5 text-sm text-danger">
          <AlertTriangle size={15} aria-hidden="true" /> {error}
        </div>
      )}

      <div className="mt-5">{content}</div>
    </Page>
  );
}
