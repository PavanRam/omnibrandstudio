import { useEffect, useState } from 'react';
import {
  CheckCircle2,
  Loader2,
  Clock,
  Eye,
  AlertTriangle,
  XCircle,
  Layers,
  Copy,
  Check,
  Briefcase,
  Users,
  Camera,
  MessageCircle,
  Mail,
  MessageSquare,
  Send,
  Megaphone,
  Pencil,
  RotateCcw,
  Archive,
} from 'lucide-react';
import { Button } from './ui/Button.jsx';
import { Modal } from './ui/Modal.jsx';
import { ReviewCard } from './ReviewCard.jsx';
import { cn } from '@/lib/cn.js';
import {
  fetchCampaign,
  sendCampaignToReview,
  fetchPendingReviews,
  decideReview,
  rerunCampaign,
  archiveCampaign,
  getCurrentAuthClaims,
} from '@/lib/api.js';

// Frontend approximation of the backend's real permission check
// (services/campaign/archive_service.py) — the backend is authoritative
// (403s if this is wrong), this just decides whether to show the button.
// Admins can archive anything; regular users only failed/stuck campaigns,
// never awaiting_review or published. Uses created_at as a stand-in for
// started_at (not present on the Gallery list payload) — close enough for
// a UI-visibility decision.
const ARCHIVE_STUCK_RUNNING_MS = 60 * 60 * 1000; // 1h
const ARCHIVE_STUCK_DRAFT_MS = 24 * 60 * 60 * 1000; // 24h

export function canArchiveCampaign(campaign, roles = []) {
  const status = (campaign?.status || '').toLowerCase();
  if (status === 'archived') return false;
  if (roles.includes('admin')) return true;
  if (status === 'failed') return true;
  const ageMs = campaign?.created_at ? Date.now() - new Date(campaign.created_at).getTime() : 0;
  if ((status === 'queued' || status === 'running') && ageMs > ARCHIVE_STUCK_RUNNING_MS) return true;
  if (status === 'draft' && ageMs > ARCHIVE_STUCK_DRAFT_MS) return true;
  return false;
}

// Per-channel icon + brand-ish accent colour so a row of variants reads at a
// glance which platform each one is for. Not literal platform logos (lucide
// dropped brand marks) — a distinct glyph + colour badge per channel instead.
const CHANNEL_BADGES = {
  linkedin: { icon: Briefcase, bg: '#0A66C2', fg: '#fff' },
  twitter: { icon: 'X', bg: '#000', fg: '#fff' },
  x: { icon: 'X', bg: '#000', fg: '#fff' },
  facebook: { icon: Users, bg: '#1877F2', fg: '#fff' },
  instagram: { icon: Camera, bg: 'linear-gradient(135deg,#f58529,#dd2a7b,#8134af,#515bd4)', fg: '#fff' },
  whatsapp: { icon: MessageCircle, bg: '#25D366', fg: '#fff' },
  email: { icon: Mail, bg: '#475569', fg: '#fff' },
  sms: { icon: MessageSquare, bg: '#0EA5A0', fg: '#fff' },
  rcs: { icon: Send, bg: '#6366F1', fg: '#fff' },
};

export function ChannelBadge({ channel, size = 32 }) {
  const key = (channel || '').toLowerCase();
  const badge = CHANNEL_BADGES[key] || { icon: Megaphone, bg: 'var(--color-surface-2)', fg: 'var(--color-muted)' };
  const Icon = badge.icon;
  return (
    <span
      aria-hidden="true"
      className="flex shrink-0 items-center justify-center rounded-full font-semibold"
      style={{ width: size, height: size, background: badge.bg, color: badge.fg, fontSize: size * 0.45 }}
    >
      {Icon === 'X' ? 'X' : <Icon size={size * 0.55} strokeWidth={2.25} />}
    </span>
  );
}

// Minimal, monochrome (currentColor) version for compact spaces — a row of
// these next to each other reads as "channels used" without the visual
// weight of ChannelBadge's colour-coded circles.
export function ChannelIcon({ channel, size = 14 }) {
  const key = (channel || '').toLowerCase();
  const badge = CHANNEL_BADGES[key] || { icon: Megaphone };
  const Icon = badge.icon;
  return (
    <span
      aria-hidden="true"
      title={channel}
      className="inline-flex shrink-0 items-center justify-center"
      style={{ width: size, height: size, fontSize: size * 0.85, lineHeight: 1 }}
    >
      {Icon === 'X' ? 'X' : <Icon size={size} strokeWidth={2} />}
    </span>
  );
}

// Beautified per-channel content rendering, used in place of one flat
// whitespace-pre-wrap block. Email gets its Subject line pulled out and
// styled distinctly from the body; SMS/WhatsApp render inside a chat-bubble
// shape (matches how the content will actually appear to a recipient);
// everything else keeps the plain paragraph treatment.
function VariantContent({ channel, content }) {
  const text = content || '(no content captured)';
  const key = (channel || '').toLowerCase();

  if (key === 'email') {
    const match = text.match(/^\s*subject\s*:\s*(.+?)\s*\n+([\s\S]*)$/i);
    if (match) {
      const [, subject, body] = match;
      return (
        <div className="overflow-hidden rounded-lg border border-border bg-surface">
          <div className="border-b border-border bg-surface-2 px-2.5 py-1.5">
            <span className="text-[10px] font-medium uppercase tracking-wide text-faint">Subject</span>
            <p className="truncate text-xs font-semibold text-fg">{subject}</p>
          </div>
          <p className="whitespace-pre-wrap px-2.5 py-2 text-xs text-fg">{body.trim() || '(no body captured)'}</p>
        </div>
      );
    }
  }

  if (key === 'sms' || key === 'whatsapp' || key === 'rcs') {
    return (
      <div className="flex justify-start">
        <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-tl-sm border border-border bg-surface px-3 py-2 text-xs text-fg shadow-sm">
          {text}
        </p>
      </div>
    );
  }

  return (
    <p className="whitespace-pre-wrap rounded-lg border border-border bg-surface px-2 py-2 text-xs text-fg">
      {text}
    </p>
  );
}

// Roles that can act as a "campaign manager" — preview a draft and send it
// to review. Deliberately the same roles that can create campaigns; the
// backend is the real gate (creator OR admin/editor), this is just which
// button we show.
export const MANAGER_ROLES = new Set(['admin', 'editor']);
// Roles that can approve/reject content once it's awaiting review.
export const REVIEWER_ROLES = new Set(['admin', 'editor', 'reviewer']);

// Status → visual treatment. Tone classes use the theme-aware semantic tokens
// so they read correctly in both light and dark mode.
export const STATUS_META = {
  published: { label: 'Published', icon: CheckCircle2, tone: 'success' },
  running: { label: 'Running', icon: Loader2, tone: 'brand', spin: true },
  queued: { label: 'Queued', icon: Clock, tone: 'warning' },
  draft: { label: 'Draft', icon: Clock, tone: 'muted' },
  awaiting_review: { label: 'Awaiting review', icon: Eye, tone: 'warning' },
  failed: { label: 'Failed', icon: AlertTriangle, tone: 'danger' },
  cancelled: { label: 'Cancelled', icon: XCircle, tone: 'muted' },
  archived: { label: 'Archived', icon: Layers, tone: 'muted' },
};

const TONE_CLASSES = {
  success: 'bg-success/12 text-success ring-success/20',
  brand: 'bg-brand/12 text-brand ring-brand/20',
  warning: 'bg-warning/12 text-warning ring-warning/20',
  danger: 'bg-danger/12 text-danger ring-danger/20',
  muted: 'bg-surface-2 text-muted ring-border',
};

export const metaFor = (status) => STATUS_META[(status || '').toLowerCase()] || STATUS_META.draft;

// Variant-level (not campaign-level) failure statuses — mirrors
// backend/worker/main.py::_VARIANT_FAILURE_STATUSES. A campaign can still be
// 'draft' overall while individual variants carry one of these, since the
// worker now persists whatever survived rather than discarding the batch
// (see next_tasks.md item 1).
const VARIANT_FAILURE_STATUSES = new Set([
  'failed',
  'translation_failed',
  'translation_unsupported_locale',
  'translation_blocked_no_source',
]);

export function relativeTime(value) {
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

export const shortId = (id = '') => (id.length > 12 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id);

// "{objective} in {audience}" — same pattern as the conversation sidebar
// title. Accepts either the flat shape from /me/recent-campaigns
// (campaign.objective) or the nested shape from GET /campaigns/{id}
// (campaign.brief.objective), so callers don't need to normalize first.
export function campaignTitle(campaign) {
  const objective = (campaign?.objective || campaign?.brief?.objective || '').trim();
  const audience = (campaign?.target_audience || campaign?.brief?.target_audience || '').trim();
  if (!objective) return null;
  const title = audience ? `${objective} in ${audience}` : objective;
  return title.length > 100 ? `${title.slice(0, 100)}…` : title;
}

export function StatusPill({ status }) {
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

export function CampaignCard({ campaign, onOpen, onArchived }) {
  const meta = metaFor(campaign.status);
  const title = campaignTitle(campaign);
  const [archiving, setArchiving] = useState(false);
  const roles = getCurrentAuthClaims()?.roles || [];
  const showArchive = canArchiveCampaign(campaign, roles);

  const handleArchive = async (e) => {
    e.stopPropagation();
    setArchiving(true);
    try {
      await archiveCampaign(campaign.campaign_id);
      onArchived?.();
    } catch {
      // Best-effort — the card just stays visible if this fails; user can retry.
    } finally {
      setArchiving(false);
    }
  };

  return (
    <article
      role="button"
      tabIndex={0}
      onClick={() => onOpen(campaign.campaign_id)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onOpen(campaign.campaign_id);
        }
      }}
      className="group relative flex cursor-pointer flex-col overflow-hidden rounded-2xl border border-border bg-surface p-4 text-left transition-all hover:-translate-y-0.5 hover:border-border-strong hover:card-shadow focus:outline-none focus-visible:ring-2 focus-visible:ring-brand"
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
      {showArchive && (
        <button
          type="button"
          onClick={handleArchive}
          disabled={archiving}
          title="Archive this campaign"
          className="absolute right-2 top-3 hidden size-7 items-center justify-center rounded-lg bg-surface text-faint shadow-sm transition-colors hover:bg-surface-2 hover:text-fg group-hover:flex disabled:opacity-60"
        >
          <Archive size={14} aria-hidden="true" />
        </button>
      )}
      <header className="flex items-center justify-between gap-2">
        <StatusPill status={campaign.status} />
        <span className="text-xs text-faint">{relativeTime(campaign.created_at)}</span>
      </header>

      <div className="mt-3 min-w-0">
        {title ? (
          <>
            <p className="truncate text-sm font-medium text-fg">{title}</p>
            <div className="mt-1">
              <CopyId id={campaign.campaign_id} />
            </div>
          </>
        ) : (
          <>
            <p className="text-[11px] font-medium uppercase tracking-wide text-faint">Campaign</p>
            <CopyId id={campaign.campaign_id} />
          </>
        )}
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

export function CardSkeleton() {
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

export function CampaignDetailModal({ campaignId, onClose, onChanged, initialTaskId = '' }) {
  const [campaign, setCampaign] = useState(null);
  const [reviews, setReviews] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [sending, setSending] = useState(false);
  const [decisionBusyId, setDecisionBusyId] = useState('');
  const [approvedTaskIds, setApprovedTaskIds] = useState(() => new Set());
  const [editingTaskId, setEditingTaskId] = useState('');
  const [variantFeedback, setVariantFeedback] = useState('');
  const [variantSubmitting, setVariantSubmitting] = useState(false);
  const [discardEditing, setDiscardEditing] = useState(false);
  const [discardFeedback, setDiscardFeedback] = useState('');
  const [discardSubmitting, setDiscardSubmitting] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const [highlightedTaskId, setHighlightedTaskId] = useState('');
  const variantRefs = useState(() => new Map())[0];

  const jumpToVariant = (taskId) => {
    const node = variantRefs.get(taskId);
    if (node) node.scrollIntoView({ behavior: 'smooth', block: 'center' });
    setHighlightedTaskId(taskId);
    window.setTimeout(() => setHighlightedTaskId((cur) => (cur === taskId ? '' : cur)), 1600);
  };

  const roles = getCurrentAuthClaims()?.roles || [];
  const canManage = roles.some((r) => MANAGER_ROLES.has(r));
  const canReview = roles.some((r) => REVIEWER_ROLES.has(r));

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const detail = await fetchCampaign(campaignId);
      setCampaign(detail);
      if (detail.status === 'awaiting_review') {
        const payload = await fetchPendingReviews({ status: 'pending', limit: 50 });
        setReviews((payload.reviews || []).filter((r) => r.campaign_id === campaignId));
      } else {
        setReviews([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load campaign');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campaignId]);

  useEffect(() => {
    if (!loading && initialTaskId && campaign?.variants?.some((v) => v.task_id === initialTaskId)) {
      const timer = window.setTimeout(() => jumpToVariant(initialTaskId), 150);
      return () => window.clearTimeout(timer);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, initialTaskId, campaign]);

  const handleSendToReview = async () => {
    setSending(true);
    setError('');
    try {
      await sendCampaignToReview(campaignId);
      await load();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send for review');
    } finally {
      setSending(false);
    }
  };

  const handleArchive = async () => {
    setArchiving(true);
    setError('');
    try {
      await archiveCampaign(campaignId);
      onChanged();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to archive this campaign');
    } finally {
      setArchiving(false);
    }
  };

  const toggleApproved = (taskId) => {
    setApprovedTaskIds((prev) => {
      const next = new Set(prev);
      if (next.has(taskId)) next.delete(taskId);
      else next.add(taskId);
      return next;
    });
  };

  const handleStartEdit = (taskId) => {
    setEditingTaskId(taskId);
    setVariantFeedback('');
    setApprovedTaskIds((prev) => {
      if (!prev.has(taskId)) return prev;
      const next = new Set(prev);
      next.delete(taskId);
      return next;
    });
  };

  const handleSubmitVariantEdit = async (taskId) => {
    setVariantSubmitting(true);
    setError('');
    try {
      await rerunCampaign(campaignId, 'content_generator', variantFeedback.trim() || null, taskId);
      setEditingTaskId('');
      setVariantFeedback('');
      await load();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to regenerate this channel');
    } finally {
      setVariantSubmitting(false);
    }
  };

  const handleDiscardAndRegenerate = async () => {
    setDiscardSubmitting(true);
    setError('');
    try {
      await rerunCampaign(campaignId, 'content_generator', discardFeedback.trim() || null, null);
      setDiscardEditing(false);
      setDiscardFeedback('');
      setApprovedTaskIds(new Set());
      setEditingTaskId('');
      await load();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to discard and regenerate');
    } finally {
      setDiscardSubmitting(false);
    }
  };

  const handleDecide = async (reviewRequestId, decision) => {
    setDecisionBusyId(reviewRequestId);
    setError('');
    try {
      await decideReview(reviewRequestId, decision);
      await load();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to record decision');
    } finally {
      setDecisionBusyId('');
    }
  };

  const status = campaign?.status;
  const title = campaign ? campaignTitle(campaign) || `Campaign ${shortId(campaign.campaign_id || campaign.id)}` : 'Campaign';
  const summary = campaign ? deriveRunSummary(campaign) : null;

  return (
    <Modal
      open
      onClose={onClose}
      title={title}
      size="lg"
    >
      {loading ? (
        <div className="py-8 text-center text-sm text-muted">Loading…</div>
      ) : error && !campaign ? (
        <div className="rounded-xl border border-danger/30 bg-danger/5 px-3 py-2.5 text-sm text-danger">
          {error}
        </div>
      ) : (
        <div className="mt-0 space-y-3">
          {error ? (
            <div className="rounded-xl border border-danger/30 bg-danger/5 px-3 py-2.5 text-sm text-danger">
              {error}
            </div>
          ) : null}

          {campaign && (
            <>
              <div className="flex items-center justify-between pb-1">
                <h3 className="text-sm font-bold text-muted uppercase tracking-wider">Run summary</h3>
                <div className="flex items-center gap-3">
                  <StatusPill status={status} />
                  <span className="text-xs text-faint">iteration {campaign.iteration || 1}</span>
                  {canArchiveCampaign(campaign, roles) && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={handleArchive}
                      disabled={archiving}
                      title="Archive campaign"
                      className="hover:text-danger hover:bg-danger/10 px-1.5 py-1.5"
                    >
                      <Archive size={15} aria-hidden="true" />
                    </Button>
                  )}
                </div>
              </div>

              {/* Two-column summary section */}
              {summary && (
                <div className="flex flex-col sm:flex-row gap-4 border-b border-border pb-3 justify-between items-start">
                  {/* Left Column: Description, Objective, and Badges (Takes up remaining space) */}
                  <div className="grow flex-1 space-y-2 min-w-0 pr-2">
                    {summary.promptSummary && (
                      <HoverTooltip content={summary.promptSummary}>
                        <p className="line-clamp-2 cursor-default text-sm text-muted leading-relaxed">
                          {summary.promptSummary}
                        </p>
                      </HoverTooltip>
                    )}
                    
                    {summary.objectiveLine && (
                      <p className="text-base font-bold text-fg leading-tight">
                        {summary.objectiveLine}
                      </p>
                    )}
                    
                    {/* Pills/chips row */}
                    <div className="flex flex-wrap gap-1.5 items-center">
                      {/* Channel pills */}
                      {campaign.brief?.channels && campaign.brief.channels.map((ch) => (
                        <span
                          key={ch}
                          className="inline-flex items-center gap-1.5 rounded-full bg-brand-soft px-2.5 py-1 text-xs font-medium text-brand"
                        >
                          <ChannelIcon channel={ch} size={12} />
                          {ch}
                        </span>
                      ))}

                      {/* Target audience and Locale chips */}
                      {[
                        ...(campaign.brief?.audience_segments || []),
                        ...(campaign.brief?.locales || [])
                      ].map((chip) => (
                        <span
                          key={chip}
                          className="rounded-full bg-surface-2 px-2.5 py-1 text-xs font-medium text-muted ring-1 ring-inset ring-border"
                        >
                          {chip}
                        </span>
                      ))}
                    </div>
                  </div>

                  {/* Right Column: Tokens consumed chart (Fixed width) */}
                  {summary.totalTokens > 0 && (
                    <div className="w-[120px] shrink-0 flex items-center justify-center pt-2 sm:pt-0">
                      <TokenDonut segments={summary.tokenSegments} total={summary.totalTokens} />
                    </div>
                  )}
                </div>
              )}
            </>
          )}

          {status === 'draft' ? (
            <div className="rounded-xl border border-brand/30 bg-brand-soft/40 px-3 py-2.5 text-sm text-fg">
              This content hasn't been sent to a reviewer yet — only you can see it right now.
              {canManage ? " Look it over, then send it for review when you're ready." : ' Ask an admin or editor to send it for review.'}
            </div>
          ) : null}

          {status === 'awaiting_review' && !canReview ? (
            <div className="rounded-xl border border-warning/30 bg-warning/5 px-3 py-2.5 text-sm text-fg">
              This is waiting on a reviewer. Only reviewer/editor/admin accounts can approve or reject it.
            </div>
          ) : null}

          {status === 'awaiting_review' && canReview ? (
            reviews.length > 0 ? (
              <div className="space-y-3">
                {reviews.map((review) => (
                  <ReviewCard
                    key={review.review_request_id}
                    review={review}
                    onDecide={handleDecide}
                    busy={decisionBusyId === review.review_request_id}
                  />
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted">
                No individual variants were flagged for review — this campaign is between stages.
              </p>
            )
          ) : null}

          {status !== 'awaiting_review' && (campaign?.variants || []).length > 1 ? (
            <div className="flex flex-wrap gap-1.5">
              {(campaign?.variants || []).map((variant) => {
                const isFailed = VARIANT_FAILURE_STATUSES.has(variant.status);
                return (
                  <button
                    key={variant.task_id}
                    type="button"
                    onClick={() => jumpToVariant(variant.task_id)}
                    className={cn(
                      'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
                      isFailed
                        ? 'border-danger/30 bg-danger/5 text-danger hover:bg-danger/10'
                        : 'border-border bg-surface text-muted hover:border-border-strong hover:text-fg',
                    )}
                  >
                    <ChannelIcon channel={variant.channel} size={12} />
                    <span className="capitalize">{variant.channel}</span>
                    <span className="text-faint">·</span>
                    <span>{variant.locale}</span>
                  </button>
                );
              })}
            </div>
          ) : null}

          {status !== 'awaiting_review' ? (
            <div className="space-y-2.5">
              {(campaign?.variants || []).map((variant) => {
                const canEditVariant = status === 'draft' && canManage;
                const isApproved = approvedTaskIds.has(variant.task_id);
                const isEditing = editingTaskId === variant.task_id;
                const isFailedVariant = VARIANT_FAILURE_STATUSES.has(variant.status);
                return (
                  <div
                    key={variant.task_id}
                    ref={(node) => {
                      if (node) variantRefs.set(variant.task_id, node);
                      else variantRefs.delete(variant.task_id);
                    }}
                    className={cn(
                      'rounded-xl border p-3 text-sm transition-shadow',
                      isFailedVariant ? 'border-danger/30 bg-danger/5' : 'border-border bg-surface-2',
                      highlightedTaskId === variant.task_id ? 'ring-2 ring-brand ring-offset-2 ring-offset-surface' : '',
                    )}
                  >
                    <div className="flex items-start gap-3">
                      <ChannelBadge channel={variant.channel} />
                      <div className="min-w-0 flex-1">
                        <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                          <span className="font-medium capitalize text-fg">{variant.channel}</span>
                          <span>·</span>
                          <span>{variant.locale}</span>
                          {typeof variant.composite_score === 'number' ? (
                            <>
                              <span>·</span>
                              <span>score {variant.composite_score.toFixed(2)}</span>
                            </>
                          ) : null}
                          {isFailedVariant ? (
                            <span className="inline-flex items-center gap-1 rounded-full bg-danger/12 px-2 py-0.5 font-medium text-danger">
                               <AlertTriangle size={11} aria-hidden="true" />
                              {variant.status === 'translation_failed' ? 'Translation failed' : 'Failed'}
                            </span>
                          ) : null}
                        </div>
                        <VariantContent channel={variant.channel} content={variant.final_content} />
                        {isFailedVariant ? (
                          <p className="mt-1.5 text-[11px] text-danger">
                            This channel didn't make it through the pipeline — the content above (if any) is from an
                            earlier step, not the final version. Regenerate this channel before sending for review.
                          </p>
                        ) : null}
                      </div>
                      {canEditVariant ? (
                        <div className="flex shrink-0 items-center gap-1">
                          <button
                            type="button"
                            title={isApproved ? 'Marked as looking good' : 'Looks good'}
                            onClick={() => toggleApproved(variant.task_id)}
                            disabled={isEditing}
                            className={cn(
                              'flex size-8 items-center justify-center rounded-lg transition-colors',
                              isApproved
                                ? 'bg-success/15 text-success'
                                : 'text-muted hover:bg-success/10 hover:text-success',
                            )}
                          >
                            <CheckCircle2 size={18} aria-hidden="true" />
                          </button>
                          <button
                            type="button"
                            title="Regenerate just this channel"
                            onClick={() => (isEditing ? setEditingTaskId('') : handleStartEdit(variant.task_id))}
                            className={cn(
                              'flex size-8 items-center justify-center rounded-lg transition-colors',
                              isEditing
                                ? 'bg-warning/15 text-warning'
                                : 'text-muted hover:bg-warning/10 hover:text-warning',
                            )}
                          >
                            <Pencil size={16} aria-hidden="true" />
                          </button>
                        </div>
                      ) : null}
                    </div>

                    {isEditing ? (
                      <div className="mt-3 space-y-2 border-t border-border pt-3">
                        <textarea
                          autoFocus
                          rows={2}
                          value={variantFeedback}
                          onChange={(e) => setVariantFeedback(e.target.value)}
                          placeholder={`What should change about the ${variant.channel} content?`}
                          className="w-full resize-none rounded-lg border border-border bg-surface px-2.5 py-2 text-xs text-fg placeholder:text-faint focus:outline-none focus:ring-2 focus:ring-brand"
                        />
                        <div className="flex justify-end gap-2">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setEditingTaskId('')}
                            disabled={variantSubmitting}
                          >
                            Cancel
                          </Button>
                          <Button
                            variant="primary"
                            size="sm"
                            onClick={() => handleSubmitVariantEdit(variant.task_id)}
                            disabled={variantSubmitting}
                          >
                            {variantSubmitting ? 'Regenerating…' : 'Regenerate'}
                          </Button>
                        </div>
                      </div>
                    ) : null}
                  </div>
                );
              })}
              {(campaign?.variants || []).length === 0 ? (
                <p className="text-sm text-muted">No content generated yet.</p>
              ) : null}
            </div>
          ) : null}

          {status === 'draft' && canManage && discardEditing ? (
            <div className="space-y-2 rounded-xl border border-danger/30 bg-danger/5 p-3">
              <p className="text-xs font-medium text-danger">
                This discards every channel's current content (including any per-channel edits above)
                and regenerates the whole campaign from scratch.
              </p>
              <textarea
                autoFocus
                rows={2}
                value={discardFeedback}
                onChange={(e) => setDiscardFeedback(e.target.value)}
                placeholder="Optional: what should change across the whole campaign?"
                className="w-full resize-none rounded-lg border border-border bg-surface px-2.5 py-2 text-xs text-fg placeholder:text-faint focus:outline-none focus:ring-2 focus:ring-danger"
              />
              <div className="flex justify-end gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setDiscardEditing(false)}
                  disabled={discardSubmitting}
                >
                  Cancel
                </Button>
                <Button variant="danger" size="sm" onClick={handleDiscardAndRegenerate} disabled={discardSubmitting}>
                  {discardSubmitting ? 'Regenerating…' : 'Discard & regenerate'}
                </Button>
              </div>
            </div>
          ) : null}

          {status === 'draft' && canManage && !discardEditing ? (
            <div className="flex items-center justify-between gap-2 border-t border-border pt-4">
              <Button variant="ghost" size="sm" onClick={() => setDiscardEditing(true)}>
                <RotateCcw size={14} aria-hidden="true" className="mr-1.5" />
                Discard all &amp; regenerate
              </Button>
              <Button variant="primary" onClick={handleSendToReview} disabled={sending}>
                {sending ? 'Sending…' : 'Send for review'}
              </Button>
            </div>
          ) : null}
        </div>
      )}
    </Modal>
  );
}

// STAGE_DONUT_COLORS, TRANSLATION_CHECK_REASONS, _translationReasonText, _dotClass, deriveRunSummary, TokenDonut
const STAGE_DONUT_COLORS = {
  intake_agent: '#3b82f6',
  content_generator: '#f97316',
  personalization_agent: '#22c55e',
  translation_agent: '#eab308',
  judge_claude: '#8b5cf6',
  judge_gpt4o: '#8b5cf6',
  judge_llama: '#8b5cf6',
  judge_gate: '#8b5cf6',
  confidence_aggregator: '#8b5cf6',
  reflexion: '#ec4899',
};

const TRANSLATION_CHECK_REASONS = {
  bleu: 'BLEU score below threshold, meaning wording diverged from the reference',
  semantic_similarity: 'Semantic similarity below threshold, meaning meaning drifted',
  back_translation_cosine: 'Back-translation cosine below threshold, meaning drifted',
};

function _translationReasonText(checks) {
  if (!Array.isArray(checks) || checks.length === 0) return '';
  const failed = checks.find((c) => c && c.passed === false);
  if (!failed) return 'Faithful to source, passes all thresholds';
  return TRANSLATION_CHECK_REASONS[failed.name] || `${failed.name} check failed`;
}

function _dotClass(tone) {
  if (tone === 'good') return 'bg-success';
  if (tone === 'warn') return 'bg-warning';
  return 'bg-danger';
}

function deriveRunSummary(campaign) {
  const brief = campaign?.brief || {};
  const variants = campaign?.variants || [];
  const costByAgent = campaign?.cost_by_agent || {};

  const translationByLocale = new Map();
  for (const v of variants) {
    const base = String(v.locale || '').split('-')[0].toLowerCase();
    if (base === 'en' || v.back_translation_score == null) continue;
    const existing = translationByLocale.get(v.locale);
    if (!existing || v.back_translation_score < existing.back_translation_score) {
      translationByLocale.set(v.locale, v);
    }
  }
  const translationRows = Array.from(translationByLocale.entries()).map(([locale, v]) => ({
    locale,
    score: v.back_translation_score,
    tone: v.status === 'translation_failed' ? 'bad' : v.back_translation_score >= 0.85 ? 'good' : 'warn',
    reason: v.failure_reason || _translationReasonText(v.translation_checks),
  }));

  const judgeByModel = new Map();
  for (const v of variants) {
    for (const js of v.judge_scores || []) {
      const existing = judgeByModel.get(js.judge_model);
      if (!existing || js.composite_score < existing.composite_score) {
        judgeByModel.set(js.judge_model, js);
      }
    }
  }
  const judgeRows = Array.from(judgeByModel.entries()).map(([judgeModel, js]) => ({
    judgeModel,
    pct: Math.round(js.composite_score * 10),
    tone: js.composite_score >= 8 ? 'good' : js.composite_score >= 6 ? 'warn' : 'bad',
    reasoning: js.reasoning || (js.critical_violations || [])[0] || '',
  }));

  const tokenSegments = Object.entries(costByAgent).map(([agent, calls]) => ({
    key: agent,
    tokens: calls.reduce((sum, c) => sum + (c.input_tokens || 0) + (c.output_tokens || 0), 0),
  })).filter((s) => s.tokens > 0);
  const totalTokens = tokenSegments.reduce((sum, s) => sum + s.tokens, 0);

  return {
    promptSummary: brief.raw_text || brief.objective || '',
    objectiveLine: campaignTitle(campaign) || brief.objective || '',
    channels: brief.channels || [],
    segmentChips: [...(brief.audience_segments || []), ...(brief.locales || [])],
    translationRows,
    judgeRows,
    tokenSegments,
    totalTokens,
  };
}

function HoverTooltip({ content, children }) {
  if (!content) return children;
  return (
    <div className="group relative">
      {children}
      <div className="pointer-events-none invisible absolute left-0 top-full z-20 mt-1 w-80 max-w-[90vw] rounded-lg border border-border bg-surface p-2.5 text-xs text-fg opacity-0 shadow-lg transition-opacity group-hover:visible group-hover:opacity-100">
        {content}
      </div>
    </div>
  );
}

function TokenDonut({ segments, total }) {
  const [hovered, setHovered] = useState(null);
  if (total <= 0) return null;
  const radius = 60;
  const strokeWidth = 22;
  const circumference = 2 * Math.PI * radius;
  let offsetAcc = 0;

  return (
    <div className="relative shrink-0" style={{ width: '112px', height: '112px' }}>
      <svg viewBox="0 0 160 160" className="-rotate-90" style={{ width: '112px', height: '112px' }}>
        {/* Outer/inner border backing circle */}
        <circle cx={80} cy={80} r={radius} fill="none" stroke="#0b0f19" strokeWidth={strokeWidth + 3} />
        {segments.map(({ key, tokens }) => {
          const pct = tokens / total;
          const dash = pct * circumference;
          const strokeDashoffset = -offsetAcc;
          offsetAcc += dash;
          return (
            <g key={key}>
              {/* Dark separator/outline circle */}
              <circle
                cx={80}
                cy={80}
                r={radius}
                fill="none"
                stroke="#0b0f19"
                strokeWidth={strokeWidth + 2}
                strokeDasharray={`${dash} ${circumference - dash}`}
                strokeDashoffset={strokeDashoffset}
              />
              {/* Colored segment circle */}
              <circle
                cx={80}
                cy={80}
                r={radius}
                fill="none"
                stroke={STAGE_DONUT_COLORS[key] || '#64748b'}
                strokeWidth={strokeWidth}
                strokeDasharray={`${dash} ${circumference - dash}`}
                strokeDashoffset={strokeDashoffset}
                onMouseEnter={() => setHovered({ key, tokens, pct })}
                onMouseLeave={() => setHovered((cur) => (cur?.key === key ? null : cur))}
                className={cn(
                  'cursor-pointer transition-opacity',
                  hovered && hovered.key !== key ? 'opacity-40' : 'opacity-100',
                )}
              />
            </g>
          );
        })}
      </svg>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
        <p className="text-lg font-extrabold text-fg tracking-tight leading-none">{total.toLocaleString()}</p>
        <p className="text-[10px] text-muted font-medium mt-0.5 leading-none">tokens</p>
      </div>
      {hovered ? (
        <div className="pointer-events-none absolute left-1/2 top-full z-20 mt-2 w-max max-w-xs -translate-x-1/2 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-xs shadow-lg">
          <p className="font-semibold text-fg">{hovered.key}</p>
          <p className="text-muted">
            {hovered.tokens.toLocaleString()} tokens · {Math.round(hovered.pct * 100)}%
          </p>
        </div>
      ) : null}
    </div>
  );
}
