import { useEffect, useState } from 'react';
import { MessageSquareText } from 'lucide-react';
import { Modal } from './ui/Modal.jsx';
import { ChannelBadge, StatusPill, campaignTitle, shortId } from './CampaignCard.jsx';
import { fetchCampaign, getCurrentAuthClaims } from '@/lib/api.js';

// Purely informational — no edit/approve/send-for-review actions anywhere in
// here. Shown when the similarity flag fires so the creator can check
// whether they actually need a new campaign at all before running one.
export function SimilarCampaignModal({ campaignId, onClose, onLoadConversation }) {
  const [campaign, setCampaign] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const currentUserId = getCurrentAuthClaims()?.sub || null;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    fetchCampaign(campaignId)
      .then((detail) => {
        if (!cancelled) setCampaign(detail);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load campaign');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [campaignId]);

  const title = campaign ? campaignTitle(campaign) || `Campaign ${shortId(campaign.id)}` : 'Similar campaign';
  const isOwnCampaign = campaign && currentUserId && campaign.created_by === currentUserId;

  return (
    <Modal open onClose={onClose} title={title} description="Existing campaign — read only" size="lg">
      {loading ? (
        <div className="py-8 text-center text-sm text-muted">Loading…</div>
      ) : error ? (
        <div className="rounded-xl border border-danger/30 bg-danger/5 px-3 py-2.5 text-sm text-danger">
          {error}
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-surface-2 p-3">
            <div className="flex items-center gap-2">
              <StatusPill status={campaign.status} />
              <span className="font-mono text-xs text-muted">{shortId(campaign.id)}</span>
            </div>
            {isOwnCampaign ? (
              <button
                type="button"
                onClick={() => {
                  onLoadConversation(campaign.conversation_id);
                  onClose();
                }}
                disabled={!campaign.conversation_id}
                className="inline-flex items-center gap-1.5 rounded-lg border border-brand/40 bg-brand-soft/40 px-2.5 py-1.5 text-xs font-medium text-brand transition-colors hover:border-brand disabled:cursor-not-allowed disabled:opacity-50"
              >
                <MessageSquareText size={14} aria-hidden="true" />
                Load that conversation
              </button>
            ) : (
              <span className="text-xs text-muted">
                Created by <span className="font-medium text-fg">{campaign.creator_email || 'another user'}</span>
              </span>
            )}
          </div>

          {campaign.brief?.raw_text ? (
            <div className="rounded-xl border border-border bg-surface-2 p-3">
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-faint">
                Original prompt
              </p>
              <p className="whitespace-pre-wrap text-sm text-fg">{campaign.brief.raw_text}</p>
            </div>
          ) : null}

          <div className="space-y-2.5">
            {(campaign.variants || []).map((variant) => (
              <div key={variant.task_id} className="rounded-xl border border-border bg-surface-2 p-3 text-sm">
                <div className="flex items-start gap-3">
                  <ChannelBadge channel={variant.channel} />
                  <div className="min-w-0 flex-1">
                    <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                      <span className="font-medium capitalize text-fg">{variant.channel}</span>
                      <span>·</span>
                      <span>{variant.locale}</span>
                    </div>
                    <p className="whitespace-pre-wrap rounded-lg border border-border bg-surface px-2 py-2 text-xs text-fg">
                      {variant.final_content || '(no content captured)'}
                    </p>
                  </div>
                </div>
              </div>
            ))}
            {(campaign.variants || []).length === 0 ? (
              <p className="text-sm text-muted">No content generated yet.</p>
            ) : null}
          </div>
        </div>
      )}
    </Modal>
  );
}
