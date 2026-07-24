import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  MessageSquareText,
  Send,
  Radio,
  RefreshCw,
  Check,
  Bot,
  Sparkles,
  ListChecks,
  Activity,
  Plus,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { Page } from '../Page.jsx';
import { Button } from '../ui/Button.jsx';
import { Badge } from '../ui/Badge.jsx';
import { VariantCard } from '../VariantCard.jsx';
import { cn } from '@/lib/cn.js';
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

function briefValue(brief, key) {
  const v = brief?.[key];
  if (key === 'token_budget') return Number(v || 0) > 0 ? `${Number(v).toLocaleString()} tokens` : '';
  if (Array.isArray(v)) return v;
  return typeof v === 'string' ? v : '';
}

function BriefChecklist({ brief }) {
  const STEPS = [
    { key: 'objective', label: 'Objective' },
    { key: 'channels', label: 'Channels' },
    { key: 'locales', label: 'Locales' },
    { key: 'audience_segments', label: 'Audience segments' },
    { key: 'token_budget', label: 'Token budget' },
  ].map((s) => {
    const value = briefValue(brief, s.key);
    const ok = Array.isArray(value) ? value.length > 0 : Boolean(value);
    return { ...s, value, ok };
  });

  const done = STEPS.filter((s) => s.ok).length;
  const pct = Math.round((done / STEPS.length) * 100);
  const currentIndex = STEPS.findIndex((s) => !s.ok); // first incomplete = "up next"

  return (
    <div>
      <div className="mb-2 flex items-center justify-between text-xs">
        <span className="font-medium text-muted">
          {done} of {STEPS.length} complete
        </span>
        <span className="font-semibold text-fg">{pct}%</span>
      </div>
      <div className="mb-5 h-1.5 overflow-hidden rounded-full bg-surface-2">
        <div
          className={cn('h-full rounded-full transition-all duration-500', pct === 100 ? 'bg-success' : 'brand-gradient')}
          style={{ width: `${pct}%` }}
        />
      </div>

      <ol className="relative space-y-0">
        {STEPS.map((step, i) => {
          const isCurrent = i === currentIndex;
          const isLast = i === STEPS.length - 1;
          return (
            <li key={step.key} className="relative flex gap-3 pb-4 last:pb-0">
              {/* connector line */}
              {!isLast && (
                <span
                  aria-hidden="true"
                  className={cn(
                    'absolute left-[11px] top-6 h-[calc(100%-1rem)] w-px',
                    step.ok ? 'bg-success/40' : 'bg-border',
                  )}
                />
              )}
              {/* node */}
              <span
                className={cn(
                  'z-10 grid h-6 w-6 shrink-0 place-items-center rounded-full text-[11px] font-semibold ring-2 transition-colors',
                  step.ok
                    ? 'bg-success/15 text-success ring-success/30'
                    : isCurrent
                      ? 'bg-brand text-brand-fg ring-brand/30'
                      : 'bg-surface-2 text-faint ring-border',
                )}
              >
                {step.ok ? <Check size={13} aria-hidden="true" /> : i + 1}
              </span>
              {/* content */}
              <div className="min-w-0 flex-1 pt-0.5">
                <div className="flex items-center gap-2">
                  <p className={cn('text-sm font-medium', step.ok || isCurrent ? 'text-fg' : 'text-muted')}>
                    {step.label}
                  </p>
                  {isCurrent && !step.ok && (
                    <span className="rounded-full bg-brand-soft px-1.5 py-0.5 text-[10px] font-medium text-brand">
                      up next
                    </span>
                  )}
                </div>
                {step.ok ? (
                  Array.isArray(step.value) ? (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {step.value.map((v) => (
                        <span
                          key={String(v)}
                          className="rounded-md bg-surface-2 px-1.5 py-0.5 text-[11px] text-muted"
                        >
                          {String(v)}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-0.5 truncate text-xs text-muted">{step.value}</p>
                  )
                ) : (
                  <p className="mt-0.5 text-xs text-faint">
                    {isCurrent ? 'Answer in chat to complete' : 'Pending'}
                  </p>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
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
  isAssistantTyping = false,
  streamingMessage = '',
  suggestedPrompts,
  campaignId,
  campaignSummary,
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
  const stageBadges = [
    conversationStage && { label: conversationStage.replaceAll('_', ' '), key: 'stage' },
    primaryObjective && { label: primaryObjective.replaceAll('_', ' '), key: 'obj' },
    turnType && { label: turnType.replaceAll('_', ' '), key: 'turn' },
  ].filter(Boolean);

  const bottomRef = useRef(null);

  // Auto-scroll the thread to the newest message whenever one is sent or
  // received, so the user never has to scroll down manually.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages.length, pendingReviews.length, isAssistantTyping, streamingMessage]);

  return (
    <section className="flex h-[calc(100vh-13rem)] min-h-[32rem] flex-col overflow-hidden rounded-2xl border border-border bg-surface card-shadow">
      {/* Header */}
      <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg brand-gradient text-white">
            <Sparkles size={16} aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-fg">Campaign Studio</h2>
            <p className="truncate font-mono text-[11px] text-faint">
              {conversationId || 'No active conversation'}
            </p>
          </div>
        </div>
        {stageBadges.length > 0 && (
          <div className="hidden flex-wrap justify-end gap-1.5 sm:flex">
            {stageBadges.map((b) => (
              <Badge key={b.key} tone="neutral" className="capitalize">
                {b.label}
              </Badge>
            ))}
          </div>
        )}
      </header>

      {needsClarification ? (
        <div className="border-b border-warning/30 bg-warning/5 px-4 py-2 text-xs text-warning">
          Clarification needed{clarificationTarget ? `: ${clarificationTarget.replaceAll('_', ' ')}` : ''}
        </div>
      ) : null}

      {campaignId ? (
        <div className="border-b border-border bg-surface-2 px-4 py-2 text-xs text-muted">
          <span className="font-medium text-fg">Campaign cost</span>{' '}
          <span className="font-mono">{formatCostLabel(campaignSummary?.token_cost_usd) || '—'}</span>
          <span className="mx-1.5 text-faint">·</span>
          <span className="font-medium text-fg">Tokens</span>{' '}
          <span className="font-mono">{formatTokenUsageLabel(campaignSummary) || '—'}</span>
        </div>
      ) : null}

      {/* Messages */}
      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <span className="grid h-14 w-14 place-items-center rounded-2xl bg-brand-soft text-brand">
              <MessageSquareText size={26} aria-hidden="true" />
            </span>
            <p className="mt-4 text-sm font-medium text-fg">Start collecting your brief</p>
            <p className="mt-1 max-w-xs text-sm text-muted">
              Describe your campaign objective in plain language — the copilot will ask for anything it needs.
            </p>
          </div>
        ) : (
          messages.map((msg, idx) => {
            const isUser = msg.role === 'user';
            return (
              <div key={`${msg.role}-${idx}`} className={cn('flex gap-2.5', isUser && 'flex-row-reverse')}>
                <span
                  className={cn(
                    'grid h-8 w-8 shrink-0 place-items-center rounded-full text-xs font-semibold',
                    isUser ? 'bg-surface-2 text-muted' : 'brand-gradient text-white',
                  )}
                  aria-hidden="true"
                >
                  {isUser ? 'You' : <Bot size={16} />}
                </span>
                <div
                  className={cn(
                    'max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm',
                    isUser
                      ? 'rounded-tr-sm bg-brand text-brand-fg'
                      : 'rounded-tl-sm border border-border bg-surface-2 text-fg',
                  )}
                >
                  <p className="whitespace-pre-wrap leading-relaxed">{msg.content}</p>
                  {!isUser && Array.isArray(msg.variants) && msg.variants.length > 0 ? (
                    <div className="mt-3 grid gap-2.5">
                      {msg.variants.map((v, vIdx) => (
                        <VariantCard key={v.task_id || `${v.channel}-${v.locale}-${vIdx}`} variant={v} />
                      ))}
                    </div>
                  ) : null}
                  {!isUser && Array.isArray(msg.captured) && msg.captured.length > 0 ? (
                    <div className="mt-2.5 border-t border-border/60 pt-2">
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-faint">Captured</p>
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        {msg.captured.map((item) => (
                          <span
                            key={`${idx}-${item}`}
                            className="inline-flex items-center gap-1 rounded-full bg-success/12 px-2 py-0.5 text-[11px] font-medium text-success"
                          >
                            <Check size={10} aria-hidden="true" /> {item}
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  {!isUser && msg.campaignSummary ? (
                    <div className="mt-2 border-t border-border/60 pt-2 text-[11px] text-muted">
                      campaign cost:{' '}
                      <span className="font-mono text-fg">
                        {formatCostLabel(msg.campaignSummary.token_cost_usd) || '—'}
                      </span>
                      <span className="mx-1 text-faint">·</span>
                      tokens:{' '}
                      <span className="font-mono text-fg">{formatTokenUsageLabel(msg.campaignSummary) || '—'}</span>
                    </div>
                  ) : null}
                  {!isUser && Array.isArray(msg.changes) && msg.changes.length > 0 ? (
                    <div className="mt-2.5 border-t border-border/60 pt-2">
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-faint">Updated</p>
                      <div className="mt-1 space-y-1">
                        {msg.changes.map((change, changeIdx) => (
                          <p key={`${idx}-${change.field || 'field'}-${changeIdx}`} className="text-[11px] text-muted">
                            <span className="font-medium text-fg">
                              {String(change.field || '').replaceAll('_', ' ')}:
                            </span>{' '}
                            {formatChangeSummary(change)}
                          </p>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              </div>
            );
          })
        )}

        {streamingMessage ? (
          <div className="flex gap-2.5" aria-live="polite">
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full brand-gradient text-white" aria-hidden="true">
              <Bot size={16} />
            </span>
            <div className="max-w-[85%] rounded-2xl rounded-tl-sm border border-border bg-surface-2 px-3.5 py-2.5 text-sm text-fg">
              <p className="whitespace-pre-wrap leading-relaxed">{streamingMessage}</p>
            </div>
          </div>
        ) : isAssistantTyping ? (
          <div className="flex gap-2.5" aria-live="polite" aria-label="Assistant is typing">
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full brand-gradient text-white" aria-hidden="true">
              <Bot size={16} />
            </span>
            <div className="rounded-2xl rounded-tl-sm border border-border bg-surface-2 px-3.5 py-2.5">
              <span className="inline-flex items-center gap-1">
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted [animation-delay:0ms]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted [animation-delay:150ms]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted [animation-delay:300ms]" />
              </span>
            </div>
          </div>
        ) : null}

        {pendingReviews.length > 0 ? (
          <div className="space-y-2">
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
        <div ref={bottomRef} aria-hidden="true" />
      </div>

      {/* Composer */}
      <div className="border-t border-border bg-surface px-4 py-3">
        {suggestedPrompts.length > 0 && !campaignId ? (
          <div className="mb-2 flex flex-wrap gap-1.5">
            {suggestedPrompts.map((prompt) => (
              <button
                key={prompt}
                type="button"
                onClick={() => sendPrompt(prompt)}
                disabled={!canChat}
                className="rounded-full border border-border bg-surface px-2.5 py-1 text-xs text-muted transition-colors hover:border-brand hover:text-brand disabled:opacity-50"
              >
                {prompt}
              </button>
            ))}
          </div>
        ) : null}
        {campaignId ? (
          <div className="mb-2 flex flex-wrap gap-1.5">
            {[
              'What is the current campaign status?',
              'What happened in the last step?',
              'Show outputs from content_generator',
            ].map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => sendPrompt(q)}
                className="rounded-full border border-border bg-surface px-2.5 py-1 text-xs text-muted transition-colors hover:border-brand hover:text-brand"
              >
                {q}
              </button>
            ))}
          </div>
        ) : null}
        <div className="flex items-end gap-2 rounded-2xl border border-border bg-surface-2 p-1.5 focus-within:border-brand">
          <input
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') sendMessage();
            }}
            placeholder={chatPlaceholder}
            className="h-9 flex-1 bg-transparent px-2.5 text-sm text-fg placeholder:text-faint focus:outline-none"
          />
          <button
            type="button"
            onClick={sendMessage}
            disabled={!hasConversation || !message.trim()}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-xl brand-gradient text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:brightness-100"
            aria-label="Send message"
          >
            <Send size={16} aria-hidden="true" />
          </button>
        </div>
      </div>
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
    <section className="flex h-[calc(100vh-13rem)] min-h-[32rem] flex-col overflow-hidden rounded-2xl border border-border bg-surface card-shadow">
      <header className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold text-fg">Conversations</h2>
        <button
          type="button"
          onClick={loadRecentConversations}
          disabled={recentLoading}
          className="grid h-7 w-7 place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-fg"
          aria-label="Refresh conversations"
        >
          <RefreshCw size={14} aria-hidden="true" className={recentLoading ? 'animate-spin' : ''} />
        </button>
      </header>
      <div className="flex-1 space-y-1 overflow-y-auto p-2">
        {recentConversations.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center px-3 text-center">
            <MessageSquareText size={22} aria-hidden="true" className="text-faint" />
            <p className="mt-2 text-sm text-muted">No conversations yet</p>
          </div>
        ) : (
          recentConversations.map((session) => {
            const isActive = session.conversation_id === conversationId;
            const updated = session.updated_at ? relativeTime(session.updated_at) : '';
            return (
              <button
                key={session.conversation_id}
                type="button"
                onClick={() => selectConversation(session)}
                className={cn(
                  'w-full rounded-xl border px-3 py-2.5 text-left transition-colors',
                  isActive
                    ? 'border-brand/40 bg-brand-soft'
                    : 'border-transparent hover:border-border hover:bg-surface-2',
                )}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      'h-1.5 w-1.5 shrink-0 rounded-full',
                      (session.status || 'collecting') === 'collecting' ? 'bg-warning' : 'bg-success',
                    )}
                  />
                  <p className={cn('truncate font-mono text-xs', isActive ? 'text-brand' : 'text-fg')}>
                    {session.conversation_id.slice(0, 12)}…
                  </p>
                </div>
                <p className="mt-1 flex items-center gap-1.5 pl-3.5 text-[11px] text-faint">
                  <span className="capitalize">{session.status || 'collecting'}</span>
                  {updated && <span>· {updated}</span>}
                </p>
              </button>
            );
          })
        )}
      </div>
    </section>
  );
}

function relativeTime(value) {
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return '';
  const diff = Date.now() - then;
  const min = Math.round(diff / 60000);
  if (min < 1) return 'just now';
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.round(hr / 24)}d ago`;
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

  if (!hasCampaign) {
    return (
      <div className="flex h-full flex-col items-center justify-center px-4 py-10 text-center">
        <span className="grid h-12 w-12 place-items-center rounded-2xl bg-surface-2 text-faint">
          <Activity size={22} aria-hidden="true" />
        </span>
        <p className="mt-3 text-sm font-medium text-fg">No campaign running</p>
        <p className="mt-1 max-w-[15rem] text-sm text-muted">
          Complete the brief and say “run campaign” — pipeline events stream here live.
        </p>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-3 flex items-center justify-between gap-2">
        <span className="truncate font-mono text-[11px] text-faint">Campaign {campaignId.slice(0, 12)}…</span>
        <Badge tone={streamBadgeTone}>
          <Radio size={12} aria-hidden="true" className={sseConnected ? 'animate-pulse' : ''} />
          {sseConnected ? 'Live' : 'Idle'}
        </Badge>
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
    </div>
  );
}

function WorkspaceInspector({ brief, stream }) {
  const [tab, setTab] = useState('brief');
  return (
    <section className="flex h-[calc(100vh-13rem)] min-h-[32rem] flex-col overflow-hidden rounded-2xl border border-border bg-surface card-shadow">
      <div className="flex items-center gap-1 border-b border-border p-1.5">
        {[
          { key: 'brief', label: 'Brief', icon: ListChecks },
          { key: 'pipeline', label: 'Pipeline', icon: Activity },
        ].map((t) => {
          const Icon = t.icon;
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={cn(
                'inline-flex flex-1 items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-sm font-medium transition-colors',
                active ? 'bg-brand text-brand-fg' : 'text-muted hover:bg-surface-2 hover:text-fg',
              )}
            >
              <Icon size={15} aria-hidden="true" />
              {t.label}
            </button>
          );
        })}
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        {tab === 'brief' ? (
          <>
            <BriefChecklist brief={brief} />
            <div className="mt-4 flex items-start gap-2 rounded-xl border border-border bg-surface-2 p-3">
              <Sparkles size={15} aria-hidden="true" className="mt-0.5 shrink-0 text-brand" />
              <p className="text-xs text-muted">
                When every field is complete, send{' '}
                <span className="font-medium text-fg">“run campaign”</span> to enqueue execution.
              </p>
            </div>
          </>
        ) : (
          stream
        )}
      </div>
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

function formatCostLabel(value) {
  return typeof value === 'number' ? `$${value.toFixed(4)}` : '';
}

function formatTokenUsageLabel(summary) {
  if (!summary || typeof summary !== 'object') return '';
  const total = summary.total_tokens;
  if (typeof total === 'number' && total >= 0) {
    return total.toLocaleString();
  }
  const input = summary.input_tokens;
  const output = summary.output_tokens;
  if (typeof input === 'number' && typeof output === 'number') {
    return `${(input + output).toLocaleString()}`;
  }
  return '';
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
  const campaignSummary =
    payload?.campaign_summary && typeof payload.campaign_summary === 'object'
      ? payload.campaign_summary
      : null;

  return {
    updates,
    changes,
    suggestedPrompts,
    conversationStage:
      typeof payload?.conversation_stage === 'string' && payload.conversation_stage
        ? payload.conversation_stage
        : '',
    primaryObjective: typeof payload?.primary_objective === 'string' ? payload.primary_objective : '',
    turnType: typeof payload?.turn_type === 'string' ? payload.turn_type : '',
    needsClarification: Boolean(payload?.needs_clarification),
    clarificationTarget: typeof payload?.clarification_target === 'string' ? payload.clarification_target : '',
    campaignSummary,
  };
}

async function handleStartConversationAction({
  setStatus,
  setError,
  setConversationId,
  setCampaignId,
  setCampaignSummary,
  setMessages,
  setBrief,
  setConversationStage,
  setPrimaryObjective,
  setTurnType,
  setNeedsClarification,
  setClarificationTarget,
  setSuggestedPrompts,
  loadRecentConversations,
}) {
  setStatus('creating');
  setError('');
  try {
    const session = await createConversation(DEFAULT_BRAND_ID);
    setConversationId(session.id);
    setCampaignId('');
    setCampaignSummary(null);
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
  setCampaignSummary,
  setBrief,
  setMessages,
  setConversationStage,
  setPrimaryObjective,
  setTurnType,
  setNeedsClarification,
  setClarificationTarget,
  setSuggestedPrompts,
  setError,
  setStatus,
}) {
  setConversationId(session.conversation_id);
  setCampaignId(session.active_campaign_id || '');
  setCampaignSummary(null);
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
  setSuggestedPrompts([]);
  setError('');
  setStatus('ready');
}

function handleSendPromptAction({ prompt, canChat, send, setError, setMessages, setIsAssistantTyping }) {
  if (!canChat) return;
  const sent = send({ message: prompt });
  if (!sent) {
    setError('Socket is not connected yet');
    return;
  }
  setMessages((prev) => [...prev, { role: 'user', content: prompt }]);
  setIsAssistantTyping?.(true);
}

function handleSendMessageAction({
  message,
  hasConversation,
  wsConnected,
  send,
  setError,
  setMessages,
  setMessage,
  setIsAssistantTyping,
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
  setIsAssistantTyping?.(true);
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
  const [campaignSummary, setCampaignSummary] = useState(null);
  const [message, setMessage] = useState('');
  const [messages, setMessages] = useState([]);
  const [brief, setBrief] = useState({});
  const [conversationStage, setConversationStage] = useState('');
  const [primaryObjective, setPrimaryObjective] = useState('');
  const [turnType, setTurnType] = useState('');
  const [needsClarification, setNeedsClarification] = useState(false);
  const [clarificationTarget, setClarificationTarget] = useState('');
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
  const [isAssistantTyping, setIsAssistantTyping] = useState(false);
  const [streamingMessage, setStreamingMessage] = useState('');

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
      setIsAssistantTyping(false);
      return;
    }

    // Immediate acknowledgement frame — the backend received the turn and is
    // working on it. Keep the typing indicator visible; no other state changes.
    if (payload.type === 'ack') {
      setIsAssistantTyping(true);
      return;
    }

    // Streaming delta — append to the in-progress assistant bubble. The typing
    // indicator gives way to the streaming text on the first delta.
    if (payload.type === 'delta') {
      setIsAssistantTyping(false);
      setStreamingMessage((prev) => prev + (payload.delta || ''));
      return;
    }

    // The responder leaked/produced nothing mid-stream; replace what streamed
    // so far with the grounded fallback.
    if (payload.type === 'replace') {
      setStreamingMessage(payload.message || '');
      return;
    }

    const parsed = parseSocketPayload(payload);

    // The turn is complete (or a message arrived) — stop the typing indicator
    // and clear the streaming buffer (the final message is appended below).
    if (payload.type === 'turn_complete' || payload.message) {
      setIsAssistantTyping(false);
      setStreamingMessage('');
    }

    if (payload.message) {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: payload.message,
          captured: parsed.updates,
          changes: parsed.changes,
          campaignSummary: parsed.campaignSummary,
          variants: Array.isArray(payload.variants) && payload.variants.length ? payload.variants : null,
        },
      ]);
    }
    if (payload.brief) setBrief(payload.brief);
    if (payload.campaign_id) setCampaignId(payload.campaign_id);
    if (parsed.campaignSummary) setCampaignSummary(parsed.campaignSummary);
    setConversationStage(parsed.conversationStage || '');
    setPrimaryObjective(parsed.primaryObjective || '');
    setTurnType(parsed.turnType || '');
    setNeedsClarification(parsed.needsClarification);
    setClarificationTarget(parsed.clarificationTarget);
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

  // Live cost/token updates pushed over the campaign SSE stream. Each new event
  // appends to `events`, so this effect fires once per event; we read only the
  // newest element and add its delta into the running campaign summary. The WS
  // turn response provides the authoritative cumulative total for reconciliation.
  const lastCostEventRef = useRef(null);
  useEffect(() => {
    if (!events.length) return;
    const latest = events[events.length - 1];
    if (!latest || latest.phase !== 'cost_update') return;
    if (lastCostEventRef.current === latest) return;
    lastCostEventRef.current = latest;
    const {
      delta_cost_usd: dCost,
      delta_input_tokens: dIn,
      delta_output_tokens: dOut,
    } = latest.payload ?? {};
    if (dCost == null && dIn == null && dOut == null) return;
    setCampaignSummary((prev) => {
      const base = prev ?? {
        token_cost_usd: 0,
        input_tokens: 0,
        output_tokens: 0,
        total_tokens: 0,
      };
      const input = (base.input_tokens ?? 0) + (dIn ?? 0);
      const output = (base.output_tokens ?? 0) + (dOut ?? 0);
      return {
        ...base,
        token_cost_usd: (base.token_cost_usd ?? 0) + (dCost ?? 0),
        input_tokens: input,
        output_tokens: output,
        total_tokens: input + output,
      };
    });
  }, [events]);

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
      setCampaignId,
      setCampaignSummary,
      setMessages,
      setBrief,
      setConversationStage,
      setPrimaryObjective,
      setTurnType,
      setNeedsClarification,
      setClarificationTarget,
      setSuggestedPrompts,
      loadRecentConversations,
    });

  const selectConversation = (session) =>
    handleSelectConversationAction({
      session,
      setConversationId,
      setCampaignId,
      setCampaignSummary,
      setBrief,
      setMessages,
      setConversationStage,
      setPrimaryObjective,
      setTurnType,
      setNeedsClarification,
      setClarificationTarget,
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
      setIsAssistantTyping,
    });

  const sendPrompt = (prompt) =>
    handleSendPromptAction({
      prompt,
      canChat,
      send,
      setError,
      setMessages,
      setIsAssistantTyping,
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
      title="Campaign Studio"
      description="Chat to build a brief, then watch the pipeline run in real time."
      actions={
        <div className="flex items-center gap-2">
          <span
            className={cn(
              'hidden items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset sm:inline-flex',
              wsConnected ? 'bg-success/12 text-success ring-success/20' : 'bg-surface-2 text-muted ring-border',
            )}
            title={wsConnected ? 'Chat connected' : 'Chat disconnected'}
          >
            {wsConnected ? <Wifi size={12} aria-hidden="true" /> : <WifiOff size={12} aria-hidden="true" />}
            Chat
          </span>
          <Button variant="primary" onClick={startConversation} disabled={status === 'creating'}>
            <Plus size={16} aria-hidden="true" />
            {status === 'creating' ? 'Creating…' : 'New conversation'}
          </Button>
        </div>
      }
    >
      {error ? (
        <div className="mb-4 rounded-xl border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,240px)_minmax(0,1fr)_minmax(0,380px)]">
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
          isAssistantTyping={isAssistantTyping}
          streamingMessage={streamingMessage}
          suggestedPrompts={suggestedPrompts}
          campaignId={campaignId}
          campaignSummary={campaignSummary}
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

        <WorkspaceInspector
          brief={brief}
          stream={
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
          }
        />
      </div>
    </Page>
  );
}
