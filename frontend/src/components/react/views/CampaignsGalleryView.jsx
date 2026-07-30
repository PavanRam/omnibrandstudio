import { useEffect, useMemo, useState } from 'react';
import { RefreshCw, CheckCircle2, Loader2, AlertTriangle, Sparkles, Layers, DollarSign, Search, ArrowUpRight, Archive } from 'lucide-react';
import { Page } from '../Page.jsx';
import { Button } from '../ui/Button.jsx';
import { CampaignCard, CardSkeleton, CampaignDetailModal, campaignTitle } from '../CampaignCard.jsx';
import { cn } from '@/lib/cn.js';
import { fetchRecentCampaigns, getCurrentAuthClaims } from '@/lib/api.js';

const IN_PROGRESS = new Set(['queued', 'running', 'awaiting_review']);

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

export function CampaignsGalleryView() {
  const [campaigns, setCampaigns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [activeCampaignId, setActiveCampaignId] = useState(null);
  const [showArchived, setShowArchived] = useState(false);
  const isAdmin = (getCurrentAuthClaims()?.roles || []).includes('admin');

  // Read URL search parameter on mount (2026-07-27)
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      const searchQ = params.get('search') || '';
      if (searchQ) {
        setQuery(searchQ);
      }
    }
  }, []);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const payload = await fetchRecentCampaigns({ includeArchived: isAdmin && showArchived });
      setCampaigns(payload.campaigns || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load campaigns');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showArchived]);

  const stats = useMemo(() => {
    const total = campaigns.length;
    const published = campaigns.filter((c) => (c.status || '').toLowerCase() === 'published').length;
    const active = campaigns.filter((c) => IN_PROGRESS.has((c.status || '').toLowerCase())).length;
    const variants = campaigns.reduce((n, c) => n + (c.variant_count || 0), 0);
    const spend = campaigns.reduce((n, c) => n + Number(c.cost_usd || 0), 0);
    return { total, published, active, variants, spend };
  }, [campaigns]);

  const filters = useMemo(
    () => [
      { key: 'all',       label: 'All',        count: campaigns.length,       activeClass: 'bg-brand/15 text-brand',           badgeClass: 'bg-brand/20 text-brand' },
      { key: 'published', label: 'Published',   count: stats.published,        activeClass: 'bg-success/15 text-success',        badgeClass: 'bg-success/20 text-success' },
      { key: 'active',    label: 'In progress', count: stats.active,           activeClass: 'bg-warning/15 text-warning',        badgeClass: 'bg-warning/20 text-warning' },
      { key: 'failed',    label: 'Failed',
        count: campaigns.filter((c) => ['failed', 'cancelled'].includes((c.status || '').toLowerCase())).length,
        activeClass: 'bg-danger/15 text-danger', badgeClass: 'bg-danger/20 text-danger' },
    ],
    [campaigns, stats],
  );

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return campaigns.filter((c) => {
      const status = (c.status || '').toLowerCase();
      const titleText = campaignTitle(c) || '';
      const matchesFilter =
        filter === 'all' ||
        (filter === 'published' && status === 'published') ||
        (filter === 'active' && IN_PROGRESS.has(status)) ||
        (filter === 'failed' && ['failed', 'cancelled'].includes(status));
      const matchesQuery =
        !q ||
        c.campaign_id?.toLowerCase().includes(q) ||
        c.brand_id?.toLowerCase().includes(q) ||
        titleText.toLowerCase().includes(q) ||
        status.includes(q);
      return matchesFilter && matchesQuery;
    });
  }, [campaigns, filter, query]);

  return (
    <Page
      wide
      eyebrow="Studio"
      title="Campaigns"
      description="Every campaign your team has run — track status, output, and spend at a glance."
      actions={
        <div className="flex items-center gap-2">
          <Button as="a" href="/studio" variant="primary" size="md">
            <Sparkles size={15} aria-hidden="true" /> New campaign
          </Button>
          {isAdmin && (
            <Button
              variant={showArchived ? 'primary' : 'secondary'}
              onClick={() => setShowArchived((v) => !v)}
            >
              <Archive size={15} aria-hidden="true" />
              {showArchived ? 'Showing archived' : 'Show archived'}
            </Button>
          )}
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

      {/* Toolbar: filters + search */}
      <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-1.5">
          {filters.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key)}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium transition-colors',
                filter === f.key
                  ? f.activeClass
                  : 'text-muted hover:bg-surface-2 hover:text-fg',
              )}
            >
              {f.label}
              <span
                className={cn(
                  'rounded-full px-1.5 text-xs',
                  filter === f.key ? f.badgeClass : 'bg-surface-2 text-faint',
                )}
              >
                {f.count}
              </span>
            </button>
          ))}
        </div>

        <div className="relative w-full sm:w-64">
          <Search
            size={15}
            aria-hidden="true"
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint"
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by ID, brand, status…"
            className="h-9 w-full rounded-xl border border-border bg-surface pl-9 pr-3 text-sm text-fg transition-colors hover:border-border-strong focus:border-brand focus:outline-none"
          />
        </div>
      </div>

      {error && (
        <div className="mt-4 flex items-center gap-2 rounded-xl border border-danger/30 bg-danger/5 px-3 py-2.5 text-sm text-danger">
          <AlertTriangle size={15} aria-hidden="true" /> {error}
        </div>
      )}

      {/* Content */}
      <div className="mt-5">
        {loading ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 8 }).map((_, i) => (
              <CardSkeleton key={i} />
            ))}
          </div>
        ) : visible.length > 0 ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {visible.map((c) => (
              <CampaignCard key={c.campaign_id} campaign={c} onOpen={setActiveCampaignId} onArchived={load} />
            ))}
          </div>
        ) : campaigns.length === 0 ? (
          <EmptyState
            title="No campaigns yet"
            body="Kick off your first campaign from the workspace — it'll show up here with live status and results."
            cta
          />
        ) : (
          <EmptyState
            title="Nothing matches your filters"
            body="Try a different status filter or clear your search."
          />
        )}
      </div>

      {activeCampaignId ? (
        <CampaignDetailModal
          campaignId={activeCampaignId}
          onClose={() => setActiveCampaignId(null)}
          onChanged={load}
        />
      ) : null}
    </Page>
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
          <Button as="a" href="/studio" variant="primary" size="md" className="mt-5">
            <Sparkles size={15} aria-hidden="true" /> Start a campaign
            <ArrowUpRight size={15} aria-hidden="true" />
          </Button>
        )}
      </div>
    </div>
  );
}
