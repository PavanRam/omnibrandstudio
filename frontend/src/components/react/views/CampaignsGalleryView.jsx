import { useEffect, useMemo, useState } from 'react';
import { RefreshCw, CircleDot } from 'lucide-react';
import { Page, SectionHeading } from '../Page.jsx';
import { Button } from '../ui/Button.jsx';
import { fetchRecentCampaigns } from '@/lib/api.js';

const STATUS_TONE = {
  queued: 'warning',
  running: 'brand',
  awaiting_review: 'neutral',
  published: 'success',
  failed: 'danger',
  cancelled: 'danger',
};

export function CampaignsGalleryView() {
  const [campaigns, setCampaigns] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

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

  const successfulCampaigns = useMemo(() => {
    return campaigns.filter((campaign) => (campaign.status || '').toLowerCase() === 'published');
  }, [campaigns]);

  return (
    <Page
      wide
      eyebrow="Workspace"
      title="Successful Campaigns"
      description="Published campaign outcomes from recent execution history."
      actions={
        <Button variant="secondary" onClick={load} disabled={loading}>
          <RefreshCw size={15} aria-hidden="true" /> {loading ? 'Refreshing…' : 'Refresh'}
        </Button>
      }
    >
      {error ? (
        <div className="mb-4 rounded-xl border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </div>
      ) : null}

      {successfulCampaigns.length === 0 && !loading ? (
        <div className="rounded-2xl border border-dashed border-border-strong bg-surface/60 px-6 py-10 text-center text-sm text-muted">
          No published campaigns found yet.
        </div>
      ) : null}

      <div className="space-y-5">
        {successfulCampaigns.length > 0 ? (
          <section>
            <SectionHeading
              title="Published"
              description={`${successfulCampaigns.length} campaign${successfulCampaigns.length === 1 ? '' : 's'}`}
            />
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {successfulCampaigns.map((campaign) => (
                <article
                  key={campaign.campaign_id}
                  className="rounded-2xl border border-border bg-surface p-4 card-shadow"
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-sm font-medium text-fg">{campaign.campaign_id}</p>
                    <span
                      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs capitalize ${
                        STATUS_TONE.published === 'success'
                          ? 'bg-success/15 text-success'
                          : STATUS_TONE.published === 'danger'
                            ? 'bg-danger/15 text-danger'
                            : STATUS_TONE.published === 'warning'
                              ? 'bg-warning/15 text-warning'
                              : STATUS_TONE.published === 'brand'
                                ? 'bg-brand/15 text-brand'
                                : 'bg-surface-2 text-muted'
                      }`}
                    >
                      <CircleDot size={10} aria-hidden="true" />
                      published
                    </span>
                  </div>
                  <dl className="mt-3 space-y-1 text-sm text-muted">
                    <div className="flex justify-between gap-2">
                      <dt>Brand</dt>
                      <dd className="truncate text-fg">{campaign.brand_id}</dd>
                    </div>
                    <div className="flex justify-between gap-2">
                      <dt>Variants</dt>
                      <dd className="text-fg">{campaign.variant_count}</dd>
                    </div>
                    <div className="flex justify-between gap-2">
                      <dt>Cost (USD)</dt>
                      <dd className="text-fg">{Number(campaign.cost_usd || 0).toFixed(4)}</dd>
                    </div>
                  </dl>
                </article>
              ))}
            </div>
          </section>
        ) : null}
      </div>
    </Page>
  );
}
