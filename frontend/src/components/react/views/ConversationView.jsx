import { useCallback, useEffect, useMemo, useState } from 'react';
import { MessageSquareText, Send, Radio, CircleDot, RefreshCw } from 'lucide-react';
import { Page, SectionHeading } from '../Page.jsx';
import { Button } from '../ui/Button.jsx';
import { Badge } from '../ui/Badge.jsx';
import { useWebSocket } from '../hooks/useWebSocket.js';
import { useSSE } from '../hooks/useSSE.js';
import {
  createConversation,
  fetchCampaignReplay,
  fetchRecentConversations,
  openCampaignEventStream,
  openConversationSocket,
  rerunCampaign,
} from '@/lib/api.js';

const RERUN_NODES = [
  'content_generator',
  'personalization_agent',
  'judge_claude',
  'judge_gpt4o',
  'judge_llama',
  'confidence_aggregator',
  'review_gate',
  'publishing_agent',
];

const DEFAULT_BRAND_ID =
  import.meta.env.PUBLIC_DEFAULT_BRAND_ID || '00000000-0000-0000-0000-000000000002';

function BriefChecklist({ brief }) {
  const checks = [
    { key: 'objective', ok: Boolean(brief?.objective) },
    { key: 'channels', ok: Array.isArray(brief?.channels) && brief.channels.length > 0 },
    { key: 'locales', ok: Array.isArray(brief?.locales) && brief.locales.length > 0 },
    {
      key: 'audience_segments',
      ok: Array.isArray(brief?.audience_segments) && brief.audience_segments.length > 0,
    },
    { key: 'token_budget', ok: Number(brief?.token_budget || 0) > 0 },
  ];
  return (
    <ul className="space-y-1.5 text-sm">
      {checks.map((check) => (
        <li key={check.key} className="flex items-center gap-2 text-muted">
          {check.ok ? (
            <CircleDot size={14} className="text-success" aria-hidden="true" />
          ) : (
            <CircleDot size={14} className="text-faint" aria-hidden="true" />
          )}
          <span>{check.key.replaceAll('_', ' ')}</span>
        </li>
      ))}
    </ul>
  );
}

function ReviewCard({ review, onDecide, busy }) {
  const [editing, setEditing] = useState(false);
  const [editedContent, setEditedContent] = useState(review.content || '');

  const score = typeof review.composite_score === 'number' ? review.composite_score.toFixed(2) : 'n/a';

  return (
    <div className="rounded-xl border border-warning/40 bg-warning/5 p-3 text-sm">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <Badge tone="warning">Needs review</Badge>
        <span className="text-xs text-muted">{review.task_id}</span>
        <span className="text-xs text-faint">score {score}</span>
      </div>
      {review.routing_reason ? (
        <p className="mb-2 text-xs text-muted">{review.routing_reason}</p>
      ) : null}
      <p className="mb-2 whitespace-pre-wrap rounded-lg border border-border bg-surface px-2 py-2 text-xs text-fg">
        {review.content || '(no content captured)'}
      </p>
      {editing ? (
        <div className="mb-2 space-y-2">
          <textarea
            value={editedContent}
            onChange={(e) => setEditedContent(e.target.value)}
            className="h-24 w-full rounded-lg border border-border bg-surface-2 px-2 py-2 text-xs text-fg"
          />
          <div className="flex gap-2">
            <Button
              variant="primary"
              size="sm"
              disabled={busy || !editedContent.trim()}
              onClick={() => onDecide(review.review_request_id, 'edited', { editedContent })}
            >
              Submit edit
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setEditing(false)} disabled={busy}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button
            variant="primary"
            size="sm"
            disabled={busy}
            onClick={() => onDecide(review.review_request_id, 'approved')}
          >
            Approve
          </Button>
          <Button
            variant="danger"
            size="sm"
            disabled={busy}
            onClick={() => onDecide(review.review_request_id, 'rejected')}
          >
            Reject
          </Button>
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => setEditing(true)}>
            Edit
          </Button>
        </div>
      )}
    </div>
  );
}

function BriefFieldStates({ fieldStates }) {
  if (!Array.isArray(fieldStates) || fieldStates.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2">
      {fieldStates.map((state) => (
        <div key={state.field} className="rounded-lg border border-border bg-surface-2 px-2.5 py-2 text-xs">
          <p className="font-medium text-fg">{String(state.field || '').replaceAll('_', ' ')}</p>
          <p className="mt-0.5 text-muted">status: {String(state.status || 'unknown').replaceAll('_', ' ')}</p>
          {typeof state.confidence === 'number' ? (
            <p className="text-faint">confidence: {(state.confidence * 100).toFixed(0)}%</p>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function ChatThreadPanel({
  conversationId,
  conversationStage,
  primaryObjective,
  turnType,
  needsClarification,
  clarificationTarget,
  messages,
  suggestedPrompts,
  campaignId,
  canChat,
  sendPrompt,
  message,
  setMessage,
  sendMessage,
  chatPlaceholder,
  hasConversation,
  pendingReviews = [],
  onDecideReview,
  reviewDecisionBusyId = '',
}) {
  return (
    <section className="rounded-2xl border border-border bg-surface p-4 card-shadow">
      <SectionHeading
        title="Chat thread"
        description={conversationId ? `Conversation ${conversationId}` : 'No active conversation'}
      />
      {conversationStage ? (
        <div className="mb-2">
          <Badge tone="neutral">Stage: {conversationStage.replaceAll('_', ' ')}</Badge>
        </div>
      ) : null}
      {(primaryObjective || turnType) ? (
        <div className="mb-2 flex flex-wrap gap-2">
          {primaryObjective ? (
            <Badge tone="neutral">Objective: {primaryObjective.replaceAll('_', ' ')}</Badge>
          ) : null}
          {turnType ? <Badge tone="neutral">Turn: {turnType.replaceAll('_', ' ')}</Badge> : null}
        </div>
      ) : null}
      {needsClarification ? (
        <div className="mb-2 rounded-xl border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
          Clarification needed{clarificationTarget ? `: ${clarificationTarget.replaceAll('_', ' ')}` : ''}
        </div>
      ) : null}
      <div className="h-[22rem] space-y-3 overflow-y-auto rounded-xl border border-border bg-surface-2 p-3">
        {messages.length === 0 ? (
          <p className="text-sm text-muted">Start a conversation to begin brief collection.</p>
        ) : (
          messages.map((msg, idx) => (
            <div
              key={`${msg.role}-${idx}`}
              className={`max-w-[92%] rounded-xl px-3 py-2 text-sm ${
                msg.role === 'user'
                  ? 'ml-auto bg-brand/15 text-fg'
                  : 'bg-surface text-fg border border-border'
              }`}
            >
              {msg.content}
              {msg.role === 'assistant' && Array.isArray(msg.captured) && msg.captured.length > 0 ? (
                <div className="mt-2 border-t border-border/70 pt-2">
                  <p className="text-[11px] uppercase tracking-wide text-faint">Captured this turn</p>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {msg.captured.map((item) => (
                      <span
                        key={`${idx}-${item}`}
                        className="rounded-full border border-border bg-surface-2 px-2 py-0.5 text-[11px] text-muted"
                      >
                        {item}
                      </span>
                    ))}
                  </div>
                </div>
              ) : null}
              {msg.role === 'assistant' && Array.isArray(msg.changes) && msg.changes.length > 0 ? (
                <div className="mt-2 border-t border-border/70 pt-2">
                  <p className="text-[11px] uppercase tracking-wide text-faint">Updated this turn</p>
                  <div className="mt-1 space-y-1">
                    {msg.changes.map((change, changeIdx) => (
                      <p key={`${idx}-${change.field || 'field'}-${changeIdx}`} className="text-[11px] text-muted">
                        <span className="font-medium text-fg">{String(change.field || '').replaceAll('_', ' ')}:</span>{' '}
                        {formatChangeSummary(change)}
                      </p>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          ))
        )}
      </div>
      {pendingReviews.length > 0 ? (
        <div className="mt-3 space-y-2">
          {pendingReviews.map((review) => (
            <ReviewCard
              key={review.review_request_id}
              review={review}
              onDecide={onDecideReview}
              busy={reviewDecisionBusyId === review.review_request_id}
            />
          ))}
        </div>
      ) : null}
      {suggestedPrompts.length > 0 && !campaignId ? (
        <div className="mt-2 flex flex-wrap gap-2">
          {suggestedPrompts.map((prompt) => (
            <Button
              key={prompt}
              variant="ghost"
              size="sm"
              onClick={() => sendPrompt(prompt)}
              disabled={!canChat}
            >
              {prompt}
            </Button>
          ))}
        </div>
      ) : null}
      <div className="mt-3 flex gap-2">
        <input
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') sendMessage();
          }}
          placeholder={chatPlaceholder}
          className="h-10 flex-1 rounded-xl border border-border bg-surface-2 px-3 text-sm text-fg"
        />
        <Button variant="secondary" onClick={sendMessage} disabled={!hasConversation}>
          <Send size={15} aria-hidden="true" /> Send
        </Button>
      </div>
      {campaignId ? (
        <div className="mt-2 flex flex-wrap gap-2">
          <Button variant="ghost" size="sm" onClick={() => sendPrompt('What is the current campaign status?')}>
            What is the current campaign status?
          </Button>
          <Button variant="ghost" size="sm" onClick={() => sendPrompt('What happened in the last step?')}>
            What happened in the last step?
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => sendPrompt('Show outputs from content_generator')}
          >
            Show outputs from content_generator
          </Button>
        </div>
      ) : null}
    </section>
  );
}

function RecentConversationsPanel({
  recentConversations,
  recentLoading,
  loadRecentConversations,
  selectConversation,
  conversationId,
}) {
  return (
    <section className="rounded-2xl border border-border bg-surface p-4 card-shadow">
      <SectionHeading
        title="Recent conversations"
        action={
          <Button variant="ghost" size="sm" onClick={loadRecentConversations} disabled={recentLoading}>
            <RefreshCw size={12} aria-hidden="true" /> {recentLoading ? 'Loading…' : 'Refresh'}
          </Button>
        }
      />
      <div className="h-[22rem] space-y-2 overflow-y-auto rounded-xl border border-border bg-surface-2 p-2.5">
        {recentConversations.length === 0 ? (
          <p className="text-sm text-muted">No recent conversations.</p>
        ) : (
          recentConversations.map((session) => {
            const isActive = session.conversation_id === conversationId;
            const updated = session.updated_at ? new Date(session.updated_at).toLocaleString() : 'unknown';
            return (
              <button
                key={session.conversation_id}
                type="button"
                onClick={() => selectConversation(session)}
                className={`w-full rounded-lg border px-2.5 py-2 text-left text-xs transition ${
                  isActive
                    ? 'border-brand bg-brand/10 text-fg'
                    : 'border-border bg-surface text-muted hover:border-border-strong hover:text-fg'
                }`}
              >
                <p className="truncate font-medium">{session.conversation_id}</p>
                <p className="mt-0.5 text-[11px]">{session.status || 'collecting'} · {updated}</p>
              </button>
            );
          })
        )}
      </div>
    </section>
  );
}

function CampaignStreamPanel({
  streamBadgeTone,
  sseConnected,
  campaignId,
  rerunNode,
  setRerunNode,
  rerunReason,
  setRerunReason,
  rerunSubmitting,
  runRerun,
  rerunStatus,
  replayLoading,
  replayLoadingOlder,
  replayHasMore,
  replayCursorValid,
  loadOlderReplay,
  statusSummary,
  events,
}) {
  const hasCampaign = Boolean(campaignId);

  return (
    <section className="rounded-2xl border border-border bg-surface p-4 card-shadow">
      <SectionHeading
        title="Campaign stream"
        action={
          <Badge tone={streamBadgeTone}>
            <Radio size={12} aria-hidden="true" /> {sseConnected ? 'live' : 'idle'}
          </Badge>
        }
      />
      <div className="mb-3 text-xs text-faint">
        {hasCampaign ? `Campaign ${campaignId}` : 'No campaign yet'}
      </div>
      <ReplayStatusBanner
        hasCampaign={hasCampaign}
        replayLoading={replayLoading}
        replayCursorValid={replayCursorValid}
        statusSummary={statusSummary}
      />
      <ReplayLoadOlderButton
        hasCampaign={hasCampaign}
        replayHasMore={replayHasMore}
        replayLoading={replayLoading}
        replayLoadingOlder={replayLoadingOlder}
        loadOlderReplay={loadOlderReplay}
      />
      {hasCampaign ? (
        <div className="mb-3 space-y-2 rounded-xl border border-border bg-surface-2 p-2.5">
          <p className="text-[11px] uppercase tracking-wide text-faint">Selective rerun</p>
          <div className="grid gap-2 sm:grid-cols-2">
            <select
              value={rerunNode}
              onChange={(e) => setRerunNode(e.target.value)}
              disabled={rerunSubmitting}
              className="h-9 rounded-lg border border-border bg-surface px-2 text-xs text-fg"
            >
              {RERUN_NODES.map((node) => (
                <option key={node} value={node}>
                  {node}
                </option>
              ))}
            </select>
            <input
              value={rerunReason}
              onChange={(e) => setRerunReason(e.target.value)}
              disabled={rerunSubmitting}
              placeholder="Reason (optional)"
              className="h-9 rounded-lg border border-border bg-surface px-2 text-xs text-fg"
            />
          </div>
          <div className="flex items-center justify-between gap-2">
            <Button variant="secondary" onClick={runRerun} disabled={rerunSubmitting}>
              {rerunSubmitting ? 'Submitting…' : 'Trigger rerun'}
            </Button>
            {rerunStatus ? <span className="text-xs text-muted">{rerunStatus}</span> : null}
          </div>
        </div>
      ) : null}
      <CampaignEventsList events={events} />
    </section>
  );
}

function ReplayStatusBanner({ hasCampaign, replayLoading, replayCursorValid, statusSummary }) {
  if (!hasCampaign) return null;

  return (
    <div className="mb-3 rounded-xl border border-border bg-surface-2 px-2.5 py-2 text-xs text-muted">
      {replayLoading ? 'Loading replay…' : statusSummary}
      {!replayCursorValid ? (
        <p className="mt-1 text-warning">Replay cursor expired; reset to latest window.</p>
      ) : null}
    </div>
  );
}

function ReplayLoadOlderButton({
  hasCampaign,
  replayHasMore,
  replayLoading,
  replayLoadingOlder,
  loadOlderReplay,
}) {
  if (!hasCampaign || !replayHasMore) return null;

  return (
    <div className="mb-3">
      <Button variant="ghost" size="sm" onClick={loadOlderReplay} disabled={replayLoading || replayLoadingOlder}>
        {replayLoadingOlder ? 'Loading older…' : 'Load older replay'}
      </Button>
    </div>
  );
}

function CampaignEventsList({ events }) {
  return (
    <div className="h-[22rem] space-y-2 overflow-y-auto rounded-xl border border-border bg-surface-2 p-3">
      {events.length === 0 ? (
        <p className="text-sm text-muted">Events appear here after campaign start.</p>
      ) : (
        events.map((event) => <CampaignEventCard key={event.event_id || `${event.timestamp || 'na'}-${event.agent || 'event'}-${event.phase || 'update'}`} event={event} />)
      )}
    </div>
  );
}

function CampaignEventCard({ event }) {
  const [expanded, setExpanded] = useState(false);
  const source = event.source || 'live';
  const summary = event.summary || `${event.agent || 'event'} updated ${event.phase || 'state'}`;
  const payload = event.payload || {};
  const hasDetails = hasAgentDetails(event.agent || 'event', payload);

  return (
    <div className="rounded-lg border border-border bg-surface px-2.5 py-2 text-xs">
      <div className="flex items-start justify-between gap-2">
        <p className="font-medium text-fg">{event.agent || 'event'} · {event.phase || 'update'} <span className="text-faint">[{source}]</span></p>
        {hasDetails ? (
          <Button variant="ghost" size="sm" onClick={() => setExpanded((value) => !value)}>
            {expanded ? 'Hide details' : 'Show details'}
          </Button>
        ) : null}
      </div>
      <p className="mt-1 text-muted">{summary}</p>
      {expanded ? <AgentEventDetails agent={event.agent || 'event'} payload={payload} /> : null}
      {payload?.errors?.length ? (
        <p className="mt-1 text-danger">{payload.errors[0]}</p>
      ) : null}
    </div>
  );
}

function AgentEventDetails({ agent, payload }) {
  const details = buildAgentDetails(agent, payload);
  const variantSamples = extractVariantSamples(payload);
  if (details.length === 0 && variantSamples.length === 0) return null;

  return (
    <div className="mt-2 space-y-1">
      {details.map((detail) => (
        <p key={`${detail.label}-${detail.value}`} className="text-faint">
          {detail.label}: <span className="text-muted">{detail.value}</span>
        </p>
      ))}
      {variantSamples.length > 0 ? (
        <div className="mt-2 space-y-2 rounded-md border border-border bg-surface-2 p-2">
          <p className="text-faint">variant details</p>
          {variantSamples.map((variant, idx) => (
            <VariantSampleRow key={`${variant.task_id || 'variant'}-${idx}`} variant={variant} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function VariantSampleRow({ variant }) {
  const title = [
    variant.task_id || 'task',
    variant.channel,
    variant.locale,
    variant.segment,
  ].filter(Boolean).join(' · ');

  return (
    <div className="rounded border border-border px-2 py-1">
      <p className="text-muted">{title || 'variant'}</p>
      {variant.status ? <p className="text-faint">status: {variant.status}</p> : null}
      <VariantPreview label="generated" text={variant.generated_preview} />
      <VariantPreview label="personalized" text={variant.personalized_preview} />
      <VariantPreview label="translated" text={variant.translated_preview} />
      <VariantPreview label="final" text={variant.final_preview} />
      {variant.failure_reason ? <p className="text-danger">failure: {variant.failure_reason}</p> : null}
    </div>
  );
}

function VariantPreview({ label, text }) {
  if (!text) return null;
  return (
    <p className="text-faint">
      {label}: <span className="text-muted">{text}</span>
    </p>
  );
}

function extractVariantSamples(payload) {
  if (Array.isArray(payload.variant_samples) && payload.variant_samples.length > 0) {
    return payload.variant_samples;
  }
  if (Array.isArray(payload.variants) && payload.variants.length > 0) {
    return payload.variants.slice(0, 3);
  }
  return [];
}

function hasAgentDetails(agent, payload) {
  return buildAgentDetails(agent, payload).length > 0 || extractVariantSamples(payload).length > 0;
}

function buildAgentDetails(agent, payload) {
  const byAgent = {
    intake_agent: intakeDetails,
    content_generator: contentGeneratorDetails,
    personalization_agent: personalizationDetails,
    translation_agent: translationDetails,
    judge_claude: judgeDetails,
    judge_gpt4o: judgeDetails,
    judge_llama: judgeDetails,
    confidence_aggregator: confidenceDetails,
    review_gate: reviewGateDetails,
    publishing_agent: publishingDetails,
    publication_agent: publishingDetails,
  };
  const builder = byAgent[agent] || genericDetails;
  return builder(payload);
}

function intakeDetails(payload) {
  return compactDetails([
    ['brief valid', boolText(payload.brief_valid)],
    ['budget ok', boolText(payload.budget_ok)],
    ['task count', numberText(payload.task_count)],
    ['variant count', numberText(payload.variant_count)],
  ]);
}

function contentGeneratorDetails(payload) {
  const details = compactDetails([
    ['task', payload.task_id],
    ['channel', payload.channel],
    ['locale', payload.locale],
    ['segment', payload.segment],
    ['status', payload.status],
    ['variant count', numberText(payload.variant_count)],
    ['failed count', numberText(payload.failed_count)],
  ]);

  if (typeof payload.preview === 'string' && payload.preview.trim()) {
    details.push({ label: 'preview', value: payload.preview.trim() });
  }
  if (Array.isArray(payload.variants) && payload.variants.length > 0) {
    details.push({ label: 'variants delta', value: String(payload.variants.length) });
  }
  return details;
}

function personalizationDetails(payload) {
  return compactDetails([
    ['personalized', numberText(payload.personalized)],
    ['variant count', numberText(payload.variant_count)],
  ]);
}

function translationDetails(payload) {
  return compactDetails([
    ['translated', numberText(payload.translated)],
    ['variant count', numberText(payload.variant_count)],
  ]);
}

function judgeDetails(payload) {
  const details = compactDetails([
    ['brand scores', arrayCountText(payload.brand_scores)],
    ['variant count', numberText(payload.variant_count)],
  ]);
  const first = Array.isArray(payload.brand_scores) ? payload.brand_scores[0] : null;
  if (first && typeof first === 'object') {
    if (first.task_id) details.push({ label: 'first scored task', value: String(first.task_id) });
    if (first.weighted_mean !== undefined && first.weighted_mean !== null) {
      details.push({ label: 'first weighted mean', value: String(first.weighted_mean) });
    }
  }
  return details;
}

function confidenceDetails(payload) {
  return compactDetails([
    ['aggregated scores', arrayCountText(payload.aggregated_scores)],
    ['review requests', arrayCountText(payload.review_requests)],
    ['human review requested', boolText(payload.human_review_requested)],
    ['variant count', numberText(payload.variant_count)],
  ]);
}

function reviewGateDetails(payload) {
  return compactDetails([
    ['phase', payload.current_phase],
    ['human review requested', boolText(payload.human_review_requested)],
    ['publishing paused', boolText(payload.publishing_paused)],
    ['variant count', numberText(payload.variant_count)],
  ]);
}

function publishingDetails(payload) {
  return compactDetails([
    ['publication receipts', arrayCountText(payload.publication_receipts)],
    ['variant count', numberText(payload.variant_count)],
    ['failed tasks', arrayCountText(payload.failed_task_ids)],
  ]);
}

function genericDetails(payload) {
  return compactDetails([
    ['variant count', numberText(payload.variant_count)],
    ['human review requested', boolText(payload.human_review_requested)],
    ['errors', arrayCountText(payload.errors)],
  ]);
}

function compactDetails(entries) {
  return entries
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .map(([label, value]) => ({ label, value: String(value) }));
}

function boolText(value) {
  if (typeof value !== 'boolean') return null;
  return value ? 'yes' : 'no';
}

function numberText(value) {
  return typeof value === 'number' ? String(value) : null;
}

function arrayCountText(value) {
  return Array.isArray(value) ? String(value.length) : null;
}

function formatChangeValue(value) {
  if (Array.isArray(value)) {
    return value.length ? value.join(', ') : 'none';
  }
  if (value === null || value === undefined) {
    return 'none';
  }
  const text = String(value).trim();
  return text || 'none';
}

function formatChangeSummary(change) {
  const before = formatChangeValue(change?.before);
  const after = formatChangeValue(change?.after);
  if (change?.change_type === 'added') {
    return `set to ${after}`;
  }
  if (change?.change_type === 'removed') {
    return `cleared (was ${before})`;
  }
  return `${before} -> ${after}`;
}

function parseSocketPayload(payload) {
  const updates = Array.isArray(payload?.brief_updates)
    ? payload.brief_updates.filter((value) => typeof value === 'string')
    : [];
  const changes = Array.isArray(payload?.brief_changes)
    ? payload.brief_changes.filter((value) => value && typeof value === 'object')
    : [];
  const suggestedPrompts = Array.isArray(payload?.suggested_prompts)
    ? payload.suggested_prompts.filter((value) => typeof value === 'string').slice(0, 3)
    : [];
  const briefFieldStates = Array.isArray(payload?.brief_field_states)
    ? payload.brief_field_states.filter((value) => value && typeof value === 'object')
    : [];

  return {
    updates,
    changes,
    suggestedPrompts,
    briefFieldStates,
    conversationStage:
      typeof payload?.conversation_stage === 'string' && payload.conversation_stage
        ? payload.conversation_stage
        : '',
    primaryObjective: typeof payload?.primary_objective === 'string' ? payload.primary_objective : '',
    turnType: typeof payload?.turn_type === 'string' ? payload.turn_type : '',
    needsClarification: Boolean(payload?.needs_clarification),
    clarificationTarget: typeof payload?.clarification_target === 'string' ? payload.clarification_target : '',
  };
}

async function handleStartConversationAction({
  setStatus,
  setError,
  setConversationId,
  setMessages,
  setBrief,
  setConversationStage,
  setPrimaryObjective,
  setTurnType,
  setNeedsClarification,
  setClarificationTarget,
  setBriefFieldStates,
  setSuggestedPrompts,
  loadRecentConversations,
}) {
  setStatus('creating');
  setError('');
  try {
    const session = await createConversation(DEFAULT_BRAND_ID);
    setConversationId(session.id);
    setMessages([
      {
        role: 'assistant',
        content:
          'Conversation started. Tell me your campaign goal and I will collect the required brief fields.',
      },
    ]);
    setBrief(session.partial_brief || {});
    setConversationStage('greeting');
    setPrimaryObjective('build_rapport');
    setTurnType('greeting');
    setNeedsClarification(false);
    setClarificationTarget('');
    setBriefFieldStates([]);
    setSuggestedPrompts([
      'Our objective is to drive qualified demo requests',
      'Use LinkedIn, email, and landing page',
      'Target enterprise IT leaders and security buyers',
    ]);
    setStatus('ready');
    await loadRecentConversations();
  } catch (err) {
    setStatus('error');
    setError(err instanceof Error ? err.message : 'Failed to create conversation');
  }
}

function handleSelectConversationAction({
  session,
  setConversationId,
  setCampaignId,
  setBrief,
  setMessages,
  setConversationStage,
  setPrimaryObjective,
  setTurnType,
  setNeedsClarification,
  setClarificationTarget,
  setBriefFieldStates,
  setSuggestedPrompts,
  setError,
  setStatus,
}) {
  setConversationId(session.conversation_id);
  setCampaignId(session.active_campaign_id || '');
  setBrief(session.partial_brief || {});
  setMessages([
    {
      role: 'assistant',
      content: `Resumed conversation ${session.conversation_id}. Continue the brief or run campaign when ready.`,
    },
  ]);
  setConversationStage('campaign_discovery');
  setPrimaryObjective('');
  setTurnType('');
  setNeedsClarification(false);
  setClarificationTarget('');
  setBriefFieldStates([]);
  setSuggestedPrompts([]);
  setError('');
  setStatus('ready');
}

function handleSendPromptAction({ prompt, canChat, send, setError, setMessages }) {
  if (!canChat) return;
  const sent = send({ message: prompt });
  if (!sent) {
    setError('Socket is not connected yet');
    return;
  }
  setMessages((prev) => [...prev, { role: 'user', content: prompt }]);
}

function handleSendMessageAction({
  message,
  hasConversation,
  wsConnected,
  send,
  setError,
  setMessages,
  setMessage,
}) {
  const trimmed = message.trim();
  if (!trimmed) return;
  if (!hasConversation) {
    setError('Select or create a conversation first');
    return;
  }
  if (!wsConnected) {
    setError('Chat is reconnecting. Please try again in a moment.');
    return;
  }
  const sent = send({ message: trimmed });
  if (!sent) {
    setError('Chat socket is not connected yet');
    return;
  }
  setMessages((prev) => [...prev, { role: 'user', content: trimmed }]);
  setMessage('');
}

async function handleRunRerunAction({
  campaignId,
  rerunNode,
  rerunReason,
  setRerunSubmitting,
  setRerunStatus,
  setError,
  setReplayEvents,
  setReplayHasMore,
  setReplayCursor,
  setReplayCursorValid,
}) {
  if (!campaignId) return;
  setRerunSubmitting(true);
  setRerunStatus('Submitting rerun…');
  setError('');
  try {
    const payload = await rerunCampaign(campaignId, rerunNode, rerunReason.trim() || null);
    const revision = payload?.revision_number ?? payload?.revision_id ?? 'created';
    const status = payload?.status ? `, status: ${payload.status}` : '';
    setRerunStatus(`Rerun accepted (${revision}${status})`);

    const replayPayload = await fetchCampaignReplay(campaignId, 60, null);
    setReplayEvents(Array.isArray(replayPayload?.events) ? replayPayload.events : []);
    setReplayHasMore(Boolean(replayPayload?.has_more));
    setReplayCursor(replayPayload?.next_before_event_id || null);
    setReplayCursorValid(replayPayload?.cursor_found !== false);
  } catch (err) {
    setRerunStatus('');
    setError(err instanceof Error ? err.message : 'Failed to submit rerun');
  } finally {
    setRerunSubmitting(false);
  }
}

export function ConversationView() {
  const [conversationId, setConversationId] = useState('');
  const [campaignId, setCampaignId] = useState('');
  const [message, setMessage] = useState('');
  const [messages, setMessages] = useState([]);
  const [brief, setBrief] = useState({});
  const [conversationStage, setConversationStage] = useState('');
  const [primaryObjective, setPrimaryObjective] = useState('');
  const [turnType, setTurnType] = useState('');
  const [needsClarification, setNeedsClarification] = useState(false);
  const [clarificationTarget, setClarificationTarget] = useState('');
  const [briefFieldStates, setBriefFieldStates] = useState([]);
  const [suggestedPrompts, setSuggestedPrompts] = useState([]);
  const [status, setStatus] = useState('idle');
  const [error, setError] = useState('');
  const [rerunNode, setRerunNode] = useState('content_generator');
  const [rerunReason, setRerunReason] = useState('');
  const [rerunStatus, setRerunStatus] = useState('');
  const [rerunSubmitting, setRerunSubmitting] = useState(false);
  const [recentConversations, setRecentConversations] = useState([]);
  const [recentLoading, setRecentLoading] = useState(false);
  const [replayEvents, setReplayEvents] = useState([]);
  const [replayLoading, setReplayLoading] = useState(false);
  const [replayLoadingOlder, setReplayLoadingOlder] = useState(false);
  const [replayHasMore, setReplayHasMore] = useState(false);
  const [replayCursor, setReplayCursor] = useState(null);
  const [replayCursorValid, setReplayCursorValid] = useState(true);
  const [pendingReviews, setPendingReviews] = useState([]);
  const [reviewDecisionBusyId, setReviewDecisionBusyId] = useState('');

  const loadRecentConversations = useCallback(async () => {
    setRecentLoading(true);
    try {
      const payload = await fetchRecentConversations();
      setRecentConversations(payload.conversations || []);
    } catch {
      setRecentConversations([]);
    } finally {
      setRecentLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRecentConversations();
  }, [loadRecentConversations]);

  useEffect(() => {
    if (conversationId || recentConversations.length === 0) return;
    selectConversation(recentConversations[0]);
  }, [conversationId, recentConversations]);

  const createSocket = useCallback(() => openConversationSocket(conversationId), [conversationId]);

  const handleSocketMessage = useCallback((payload) => {
    if (payload.error) {
      setError(payload.error);
      return;
    }

    const parsed = parseSocketPayload(payload);

    if (payload.message) {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: payload.message,
          captured: parsed.updates,
          changes: parsed.changes,
        },
      ]);
    }
    if (payload.brief) setBrief(payload.brief);
    if (payload.campaign_id) setCampaignId(payload.campaign_id);
    setConversationStage(parsed.conversationStage || '');
    setPrimaryObjective(parsed.primaryObjective || '');
    setTurnType(parsed.turnType || '');
    setNeedsClarification(parsed.needsClarification);
    setClarificationTarget(parsed.clarificationTarget);
    setBriefFieldStates(parsed.briefFieldStates);
    setSuggestedPrompts(parsed.suggestedPrompts);
    if (Array.isArray(payload.pending_reviews)) {
      setPendingReviews(payload.pending_reviews);
    }
  }, []);

  const { connected: wsConnected, send } = useWebSocket(createSocket, {
    enabled: Boolean(conversationId),
    onMessage: handleSocketMessage,
  });

  const createCampaignStream = useCallback(
    () => openCampaignEventStream(campaignId),
    [campaignId],
  );

  const { events, connected: sseConnected } = useSSE(
    createCampaignStream,
    Boolean(campaignId),
  );

  useEffect(() => {
    let cancelled = false;

    async function loadReplay() {
      if (!campaignId) {
        setReplayEvents([]);
        setReplayLoading(false);
        setReplayHasMore(false);
        setReplayCursor(null);
        setReplayCursorValid(true);
        return;
      }

      setReplayLoading(true);
      try {
        const payload = await fetchCampaignReplay(campaignId, 60, null);
        if (!cancelled) {
          setReplayEvents(Array.isArray(payload?.events) ? payload.events : []);
          setReplayHasMore(Boolean(payload?.has_more));
          setReplayCursor(payload?.next_before_event_id || null);
          setReplayCursorValid(payload?.cursor_found !== false);
        }
      } catch {
        if (!cancelled) {
          setReplayEvents([]);
          setReplayHasMore(false);
          setReplayCursor(null);
          setReplayCursorValid(true);
        }
      } finally {
        if (!cancelled) {
          setReplayLoading(false);
        }
      }
    }

    loadReplay();
    return () => {
      cancelled = true;
    };
  }, [campaignId]);

  const loadOlderReplay = useCallback(async () => {
    if (!campaignId || !replayCursor || replayLoading || replayLoadingOlder) {
      return;
    }

    setReplayLoadingOlder(true);
    try {
      const payload = await fetchCampaignReplay(campaignId, 40, replayCursor);

      if (payload?.cursor_found === false) {
        // Cursor was stale; reset to latest window so pagination can continue safely.
        const resetPayload = await fetchCampaignReplay(campaignId, 60, null);
        setReplayEvents(Array.isArray(resetPayload?.events) ? resetPayload.events : []);
        setReplayHasMore(Boolean(resetPayload?.has_more));
        setReplayCursor(resetPayload?.next_before_event_id || null);
        setReplayCursorValid(false);
        return;
      }

      const olderEvents = Array.isArray(payload?.events) ? payload.events : [];
      setReplayEvents((prev) => [...olderEvents, ...prev]);
      setReplayHasMore(Boolean(payload?.has_more));
      setReplayCursor(payload?.next_before_event_id || null);
      setReplayCursorValid(true);
    } catch {
      setReplayCursorValid(false);
    } finally {
      setReplayLoadingOlder(false);
    }
  }, [campaignId, replayCursor, replayLoading, replayLoadingOlder]);

  const mergedEvents = useMemo(() => {
    const combined = [...replayEvents, ...events];
    const deduped = [];
    const seen = new Set();

    for (const event of combined) {
      const fallback = [
        event.timestamp || 'na',
        event.agent || 'event',
        event.phase || 'update',
        JSON.stringify(event.payload || {}),
      ].join('|');
      const key = event.event_id || fallback;
      if (seen.has(key)) continue;
      seen.add(key);
      deduped.push(event);
    }

    return deduped.slice(-80);
  }, [replayEvents, events]);

  const statusSummary = useMemo(() => {
    if (!campaignId) return 'No campaign selected.';
    if (!mergedEvents.length) return 'No replay/live events yet.';
    const latest = mergedEvents.at(-1);
    const variantCount = latest?.payload?.variant_count;
    const review = latest?.payload?.human_review_requested;
    let reviewText = '';
    if (typeof review === 'boolean') {
      reviewText = review ? ', review requested' : ', review not requested';
    }
    const variantsText = typeof variantCount === 'number' ? `, variants ${variantCount}` : '';
    return `Latest: ${latest.agent || 'event'} · ${latest.phase || 'update'}${variantsText}${reviewText}.`;
  }, [campaignId, mergedEvents]);

  const hasConversation = Boolean(conversationId);
  const canChat = hasConversation && wsConnected;
  let chatPlaceholder = 'Describe your campaign...';
  if (!hasConversation) {
    chatPlaceholder = 'Select or create a conversation first';
  } else if (!wsConnected) {
    chatPlaceholder = 'Reconnecting chat socket...';
  }

  const startConversation = () =>
    handleStartConversationAction({
      setStatus,
      setError,
      setConversationId,
      setMessages,
      setBrief,
      setConversationStage,
      setPrimaryObjective,
      setTurnType,
      setNeedsClarification,
      setClarificationTarget,
      setBriefFieldStates,
      setSuggestedPrompts,
      loadRecentConversations,
    });

  const selectConversation = (session) =>
    handleSelectConversationAction({
      session,
      setConversationId,
      setCampaignId,
      setBrief,
      setMessages,
      setConversationStage,
      setPrimaryObjective,
      setTurnType,
      setNeedsClarification,
      setClarificationTarget,
      setBriefFieldStates,
      setSuggestedPrompts,
      setError,
      setStatus,
    });

  const sendMessage = () =>
    handleSendMessageAction({
      message,
      hasConversation,
      wsConnected,
      send,
      setError,
      setMessages,
      setMessage,
    });

  const sendPrompt = (prompt) =>
    handleSendPromptAction({
      prompt,
      canChat,
      send,
      setError,
      setMessages,
    });

  const decideReviewAction = (reviewRequestId, decision, { editedContent = null } = {}) => {
    if (!wsConnected) {
      setError('Chat is reconnecting. Please try again in a moment.');
      return;
    }
    setReviewDecisionBusyId(reviewRequestId);
    const sent = send({
      review_request_id: reviewRequestId,
      decision,
      edited_content: editedContent,
    });
    if (!sent) {
      setError('Chat socket is not connected yet');
      setReviewDecisionBusyId('');
      return;
    }
    setPendingReviews((prev) => prev.filter((r) => r.review_request_id !== reviewRequestId));
    setReviewDecisionBusyId('');
  };

  const streamBadgeTone = useMemo(() => (sseConnected ? 'success' : 'neutral'), [sseConnected]);

  const runRerun = () =>
    handleRunRerunAction({
      campaignId,
      rerunNode,
      rerunReason,
      setRerunSubmitting,
      setRerunStatus,
      setError,
      setReplayEvents,
      setReplayHasMore,
      setReplayCursor,
      setReplayCursorValid,
    });

  return (
    <Page
      wide
      eyebrow="Workspace"
      title="Conversation Orchestrator"
      description="Collect campaign brief inputs over chat, then monitor pipeline progress in real time."
      actions={
        <Button variant="primary" onClick={startConversation} disabled={status === 'creating'}>
          <MessageSquareText size={16} aria-hidden="true" />
          {status === 'creating' ? 'Creating…' : 'New conversation'}
        </Button>
      }
    >
      {error ? (
        <div className="mb-4 rounded-xl border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[0.85fr_1.25fr_0.9fr_1fr]">
        <RecentConversationsPanel
          recentConversations={recentConversations}
          recentLoading={recentLoading}
          loadRecentConversations={loadRecentConversations}
          selectConversation={selectConversation}
          conversationId={conversationId}
        />

        <ChatThreadPanel
          conversationId={conversationId}
          conversationStage={conversationStage}
          primaryObjective={primaryObjective}
          turnType={turnType}
          needsClarification={needsClarification}
          clarificationTarget={clarificationTarget}
          messages={messages}
          suggestedPrompts={suggestedPrompts}
          campaignId={campaignId}
          canChat={canChat}
          sendPrompt={sendPrompt}
          message={message}
          setMessage={setMessage}
          sendMessage={sendMessage}
          chatPlaceholder={chatPlaceholder}
          hasConversation={hasConversation}
          pendingReviews={pendingReviews}
          onDecideReview={decideReviewAction}
          reviewDecisionBusyId={reviewDecisionBusyId}
        />

        <section className="rounded-2xl border border-border bg-surface p-4 card-shadow">
          <SectionHeading title="Brief completeness" />
          {briefFieldStates.length > 0 ? (
            <BriefFieldStates fieldStates={briefFieldStates} />
          ) : (
            <BriefChecklist brief={brief} />
          )}
          <div className="mt-4 rounded-xl border border-border bg-surface-2 p-3">
            <p className="text-xs uppercase tracking-wide text-faint">Tip</p>
            <p className="mt-1 text-sm text-muted">
              Once all fields are complete, send “run campaign” to enqueue execution.
            </p>
          </div>
        </section>

        <CampaignStreamPanel
          streamBadgeTone={streamBadgeTone}
          sseConnected={sseConnected}
          campaignId={campaignId}
          rerunNode={rerunNode}
          setRerunNode={setRerunNode}
          rerunReason={rerunReason}
          setRerunReason={setRerunReason}
          rerunSubmitting={rerunSubmitting}
          runRerun={runRerun}
          rerunStatus={rerunStatus}
          replayLoading={replayLoading}
          replayLoadingOlder={replayLoadingOlder}
          replayHasMore={replayHasMore}
          replayCursorValid={replayCursorValid}
          loadOlderReplay={loadOlderReplay}
          statusSummary={statusSummary}
          events={mergedEvents}
        />
      </div>
    </Page>
  );
}
