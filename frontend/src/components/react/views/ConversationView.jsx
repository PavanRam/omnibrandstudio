import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  MessageSquareText,
  Send,
  Radio,
  CircleDot,
  RefreshCw,
  Check,
  Bot,
  Sparkles,
  ListChecks,
  Activity,
  Plus,
  Eye,
  AlertTriangle,
  Pencil,
  Archive,
  ClipboardList,
  FileEdit,
  UserCog,
  Languages,
  Gavel,
  Scale,
  BadgeCheck,
  Filter,
  BarChart3,
  RotateCcw,
  PlayCircle,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { Page, SectionHeading } from '../Page.jsx';
import { Button } from '../ui/Button.jsx';
import { Badge } from '../ui/Badge.jsx';
import { ReviewCard } from '../ReviewCard.jsx';
import { CampaignDetailModal, campaignTitle, ChannelIcon } from '../CampaignCard.jsx';
import { SimilarCampaignModal } from '../SimilarCampaignModal.jsx';
import { SampleBriefModal } from '../SampleBriefModal.jsx';
import { cn } from '@/lib/cn.js';
import { useWebSocket } from '../hooks/useWebSocket.js';
import { useSSE } from '../hooks/useSSE.js';
import { useAuth } from '../hooks/useAuth.js';
import {
  archiveConversation,
  createConversation,
  fetchCampaign,
  fetchCampaignReplay,
  fetchCampaignStats,
  fetchConversationMessages,
  fetchRecentConversations,
  fetchSegmentOptions,

  fetchBrandEntitlements,
  listBrands,
  openCampaignEventStream,
  openConversationSocket,
  rerunCampaign,
  runCampaignAnyway,
  setBriefField,
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

// Format brief field values for display. token_budget removed from user-facing
// collection (2026-07-29) — backend auto-defaults it, so it never needs a value here.
function briefValue(brief, key) {
  const v = brief?.[key];
  if (Array.isArray(v)) return v;
  return typeof v === 'string' ? v : '';
}

// Brief collection steps — fields user must fill before campaign submission.
// token_budget removed (2026-07-29): no longer asked from users; backend auto-defaults
// it and tracks actual consumption end-to-end.
const BRIEF_STEP_DEFS = [
  { key: 'objective', label: 'Objective' },
  { key: 'channels', label: 'Channels' },
  { key: 'locales', label: 'Locales' },
  { key: 'audience_segments', label: 'Audience segments' },
];

// Shared by the read-only sidebar checklist and the inline chat picker so
// both agree on which field is "up next" — a single source of truth for
// "what's the first incomplete slot."
function computeBriefSteps(brief) {
  return BRIEF_STEP_DEFS.map((s) => {
    const value = briefValue(brief, s.key);
    const ok = Array.isArray(value) ? value.length > 0 : Boolean(value);
    return { ...s, value, ok };
  });
}

// Fields that get a structured picker inline in chat (item 23/23a).
// Objective stays free-text — it was never in scope for a picker.
// token_budget is auto-set, hidden from user (2026-07-29): tracking consumption end-to-end.
const PICKER_STEP_KEYS = new Set(['channels', 'locales', 'audience_segments']);

// Structured brief-input pickers (next_tasks.md item 23, 2026-07-27) — a
// pill/dropdown/tier selection patches the brief directly via
// setBriefField(), bypassing understanding_engine/brief_collector's LLM
// extraction entirely. This is the design choice that actually closes the
// locale/channel/segment free-text extraction bug class this session kept
// hitting, not just a UI layer on top of the same fragile parsing.

function ChannelPillsPicker({ conversationId, brandId, currentValue, onSelected }) {
  const [options, setOptions] = useState([]);
  const [selected, setSelected] = useState(() => new Set(currentValue || []));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!brandId) return;
    let cancelled = false;
    fetchBrandEntitlements(brandId)
      .then((res) => {
        if (!cancelled) setOptions(res.channels || []);
      })
      .catch(() => {
        if (!cancelled) setError('Could not load supported channels');
      });
    return () => { cancelled = true; };
  }, [brandId]);

  const toggle = (channel) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(channel)) next.delete(channel);
      else next.add(channel);
      return next;
    });
  };

  const submit = async () => {
    if (selected.size === 0) return;
    setSubmitting(true);
    setError('');
    try {
      const res = await setBriefField(conversationId, 'channels', Array.from(selected));
      onSelected(res, `Channels: ${Array.from(selected).join(', ')}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to set channels');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mt-2 space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {options.map((channel) => (
          <button
            key={channel}
            type="button"
            onClick={() => toggle(channel)}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium capitalize transition-colors',
              selected.has(channel)
                ? 'border-brand bg-brand text-brand-fg'
                : 'border-border bg-surface text-muted hover:border-border-strong hover:text-fg',
            )}
          >
            <ChannelIcon channel={channel} size={13} />
            {channel}
          </button>
        ))}
      </div>
      <Button variant="primary" size="sm" onClick={submit} disabled={selected.size === 0 || submitting}>
        {submitting ? 'Saving…' : `Use ${selected.size || ''} channel${selected.size === 1 ? '' : 's'}`}
      </Button>
      {error ? <p className="text-[11px] text-danger">{error}</p> : null}
    </div>
  );
}

function LocalePillsPicker({ conversationId, brandId, currentValue, onSelected }) {
  const [options, setOptions] = useState([]);
  const [selected, setSelected] = useState(() => new Set(currentValue || []));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!brandId) return;
    let cancelled = false;
    fetchBrandEntitlements(brandId)
      .then((res) => {
        // entitlements returns locale codes like 'en-US', 'fr-FR'.
        // Wrap in {code, label} shape the pill list expects.
        if (!cancelled) {
          const codes = res.locales || [];
          setOptions(codes.map((c) => ({ code: c, label: c })));
        }
      })
      .catch(() => {
        if (!cancelled) setError('Could not load supported locales');
      });
    return () => { cancelled = true; };
  }, [brandId]);

  const toggle = (code) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const submit = async () => {
    if (selected.size === 0) return;
    setSubmitting(true);
    setError('');
    try {
      const res = await setBriefField(conversationId, 'locales', Array.from(selected));
      const labels = options.filter((o) => selected.has(o.code)).map((o) => o.label);
      onSelected(res, `Locales: ${labels.join(', ') || Array.from(selected).join(', ')}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to set locales');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mt-2 space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {options.map((loc) => (
          <button
            key={loc.code}
            type="button"
            onClick={() => toggle(loc.code)}
            className={cn(
              'rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
              selected.has(loc.code)
                ? 'border-brand bg-brand text-brand-fg'
                : 'border-border bg-surface text-muted hover:border-border-strong hover:text-fg',
            )}
          >
            {loc.label}
          </button>
        ))}
      </div>
      <Button variant="primary" size="sm" onClick={submit} disabled={selected.size === 0 || submitting}>
        {submitting ? 'Saving…' : `Use ${selected.size || ''} locale${selected.size === 1 ? '' : 's'}`}
      </Button>
      {error ? <p className="text-[11px] text-danger">{error}</p> : null}
    </div>
  );
}

function SegmentDropdownPicker({ conversationId, brandId, currentValue, onSelected }) {
  const [options, setOptions] = useState([]);
  const [selected, setSelected] = useState(() => new Set(currentValue || []));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetchSegmentOptions(brandId)
      .then((res) => {
        if (!cancelled) setOptions(res.options || []);
      })
      .catch(() => {
        if (!cancelled) setError('Could not load segment options');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [brandId]);

  const toggle = (option) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(option)) next.delete(option);
      else next.add(option);
      return next;
    });
  };

  const submit = async () => {
    if (selected.size === 0) return;
    setSubmitting(true);
    setError('');
    try {
      const res = await setBriefField(conversationId, 'audience_segments', Array.from(selected));
      onSelected(res, `Audience segments: ${Array.from(selected).join(', ')}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to set audience segments');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) return <p className="mt-2 text-xs text-faint">Loading segment options…</p>;

  return (
    <div className="mt-2 space-y-2">
      {options.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {options.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => toggle(option)}
              className={cn(
                'rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
                selected.has(option)
                  ? 'border-brand bg-brand text-brand-fg'
                  : 'border-border bg-surface text-muted hover:border-border-strong hover:text-fg',
              )}
            >
              {option}
            </button>
          ))}
        </div>
      ) : (
        <p className="text-xs text-faint">No seeded segment data for this brand — answer in chat instead.</p>
      )}
      {options.length > 0 && (
        <Button variant="primary" size="sm" onClick={submit} disabled={selected.size === 0 || submitting}>
          {submitting ? 'Saving…' : `Use ${selected.size || ''} segment${selected.size === 1 ? '' : 's'}`}
        </Button>
      )}
      {error ? <p className="text-[11px] text-danger">{error}</p> : null}
    </div>
  );
}

// BudgetTierPicker removed (2026-07-29): token_budget is no longer collected from
// users — it's auto-set to a safe default and actual consumption is tracked
// end-to-end via telemetry. The inline budget-tier chooser and its estimateBudget
// call are no longer needed.

// Read-only progress summary — the "up next" step's picker now lives inline
// in the chat transcript (ChatThreadPanel), not here. Kept this component
// display-only per the 2026-07-27 UX decision: pickers belong right under
// the assistant's question, sidebar is just status.
function BriefChecklist({ brief, brandName = '' }) {
  const briefSteps = computeBriefSteps(brief);

  // Brand is always step 1 and is always complete (user selected it before
  // the conversation was created — it can never be changed afterward).
  const STEPS = [
    { key: '__brand__', label: 'Brand', value: brandName || 'Selected', ok: true, isBrand: true },
    ...briefSteps,
  ];

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

// Builds an inline "Campaign Plan" view from the same SSE event stream
// CampaignStreamPanel already consumes — no new backend state needed, per
// the 2026-07-26 design: intake_agent's event carries the full task list,
// and downstream agents (content_generator, translation_agent,
// confidence_aggregator) already publish per-task_id detail. This function
// just derives row status from events already flowing; the backend agents
// themselves decide when a task needs human attention (any failure status,
// a critical judge violation, or a non-auto_approve routing decision), not
// this function.
// Full pipeline-stage tracker (2026-07-27, replaces the old variant-grid
// CampaignPlanPanel — see next_tasks.md item 33). One row per AGENT STAGE,
// not per variant, since that's the actual unit of pipeline execution and
// what a creator asking "what's happening / what failed" wants to see:
// Intake -> Content Generation -> Personalization -> Translation ->
// Judge Gate -> Confidence Aggregation -> Reflexion. Every description/chip
// below is computed from the REAL event payload for that phase — never a
// fixed label shown regardless of what actually happened.
const RUN_STAGES = [
  { key: 'intake', agent: 'intake_agent', label: 'Intake' },
  { key: 'content_generator', agent: 'content_generator', label: 'Content Generation' },
  { key: 'personalization_agent', agent: 'personalization_agent', label: 'Personalization' },
  { key: 'translation_agent', agent: 'translation_agent', label: 'Translation' },
  { key: 'judge_gate', agent: 'judge_gate', label: 'Judge Gate' },
  { key: 'confidence_aggregator', agent: 'confidence_aggregator', label: 'Confidence Aggregation' },
  { key: 'reflexion', agent: 'reflexion', label: 'Reflexion' },
];

// judge_gate_complete only tells us the panel SIZE (judge_mode), not literal
// model names — but judge_gate_router (judge_planner.py) deterministically
// maps mode -> this exact node list, so it's safe to mirror here rather than
// add a redundant backend field just to say the same thing twice.
const JUDGE_MODEL_NAMES = {
  full: ['judge_claude', 'judge_gpt4o', 'judge_llama'],
  lite: ['judge_claude'],
  skip: [],
};

function _freshStages() {
  return new Map(
    RUN_STAGES.map((s) => [s.key, { ...s, status: 'pending', description: '', chips: [], failed: false, failReason: '' }]),
  );
}

function deriveCampaignRun(events, campaignStatus) {
  const stageMap = _freshStages();
  let iteration = 1;
  let variantCount = 0;
  let aggregatorFlagged = false;
  let aggregatorFlagReason = '';

  for (const event of events) {
    const phase = event.phase;
    const payload = event.payload || {};

    if (phase === 'intake_complete') {
      const s = stageMap.get('intake');
      s.status = 'done';
      variantCount = payload.task_count ?? variantCount;
      const invalid = payload.brief_valid === false || payload.budget_ok === false;
      s.description = invalid
        ? 'Brief invalid or over budget — nothing generated'
        : `brief parsed, ${variantCount} deliverable${variantCount === 1 ? '' : 's'} planned`;
      if (invalid) {
        s.failed = true;
        s.failReason = s.description;
      }
    } else if (phase === 'variant_generated' && payload.channel) {
      const s = stageMap.get('content_generator');
      if (s.status === 'pending') s.status = 'in_progress';
      if (!s.chips.includes(payload.channel)) s.chips.push(payload.channel);
    } else if (phase === 'content_generated') {
      const s = stageMap.get('content_generator');
      s.status = 'done';
      s.description = `${payload.variant_count ?? 0} variant${payload.variant_count === 1 ? '' : 's'} drafted`;
      if (payload.failed_count > 0) {
        s.failed = true;
        s.failReason = `${payload.failed_count} channel(s) failed to generate`;
      }
    } else if (phase === 'personalization_complete') {
      const s = stageMap.get('personalization_agent');
      s.status = 'done';
      s.description = `${payload.personalized ?? 0} variant${payload.personalized === 1 ? '' : 's'} personalized`;
    } else if (phase === 'translation_complete') {
      const s = stageMap.get('translation_agent');
      s.status = 'done';
      const tasks = payload.tasks || [];
      s.chips = [...new Set(tasks.map((t) => t.locale).filter(Boolean))];
      s.description = `${payload.translated ?? 0} locale variant${payload.translated === 1 ? '' : 's'} generated`;
      const failedTasks = tasks.filter((t) =>
        ['failed', 'unsupported', 'blocked'].some((frag) => String(t.status || '').includes(frag)),
      );
      if (failedTasks.length > 0) {
        s.failed = true;
        s.failReason = `Translation failed for ${failedTasks.length} variant${failedTasks.length === 1 ? '' : 's'}`;
      }
    } else if (phase === 'judge_gate_complete') {
      const s = stageMap.get('judge_gate');
      s.status = 'done';
      s.description = `multi-model review panel (${payload.judge_mode || 'full'})`;
      s.chips = JUDGE_MODEL_NAMES[payload.judge_mode] || JUDGE_MODEL_NAMES.full;
    } else if (phase === 'aggregation_complete') {
      const s = stageMap.get('confidence_aggregator');
      s.status = 'done';
      s.description = `scores combined across judges (${payload.aggregated_count ?? 0})`;
      const tasks = payload.tasks || [];
      const rejected = tasks.filter((t) => t.any_critical_violation || t.routing_decision === 'auto_reject');
      if (rejected.length > 0) {
        aggregatorFlagged = true;
        aggregatorFlagReason = rejected[0].any_critical_violation
          ? 'Critical brand-compliance violation flagged by judges'
          : `Judges rejected ${rejected.length} variant${rejected.length === 1 ? '' : 's'}`;
      }
    } else if (phase === 'reflexion_complete') {
      const s = stageMap.get('reflexion');
      s.status = 'done';
      const tasks = payload.tasks || [];
      if (payload.retried > 0) {
        iteration = 2;
        s.description = `re-running judge panel, ${payload.retried} variant${payload.retried === 1 ? '' : 's'} revised`;
        s.chips = tasks.map((t) => t.task_id);
      } else {
        s.description = 'no retries needed';
      }
    }
  }

  // Reflexion gets exactly one retry round (reflexion.py, hard-capped) —
  // if judges are STILL rejecting after that, or the campaign's own status
  // says 'failed' for a reason not otherwise caught above (e.g. the all-
  // or-nothing worker check — next_tasks.md item 1, 2026-07-27), surface it
  // as the failure point rather than showing a falsely-clean aggregator row.
  const aggStage = stageMap.get('confidence_aggregator');
  const reflexionRan = stageMap.get('reflexion').status === 'done';
  if (aggregatorFlagged && (reflexionRan || campaignStatus === 'failed')) {
    aggStage.failed = true;
    aggStage.failReason = aggregatorFlagReason;
  }

  const stages = RUN_STAGES.map((s) => stageMap.get(s.key));
  const failedStage = stages.find((s) => s.failed);

  if (failedStage) {
    // Processing stops visually right at the failure point — nothing after
    // it should look "in progress" even if the backend graph kept running
    // internally (per-task isolation means later nodes often still execute;
    // the user-facing narrative is "this is where it broke").
    const failIdx = stages.indexOf(failedStage);
    stages.forEach((s, i) => {
      if (i > failIdx) s.status = 'pending';
    });
  } else {
    const firstPending = stages.find((s) => s.status === 'pending');
    if (firstPending) {
      if (campaignStatus === 'failed') {
        // Campaign terminated in failure but no explicit failure event was
        // captured for this stage (e.g. personalization died mid-run without
        // emitting a phase event). Mark the apparent stuck stage as the
        // failure point — show a red triangle, not a pulsing "in progress"
        // indicator, which would falsely imply the pipeline is still running.
        firstPending.failed = true;
        firstPending.failReason = 'Campaign failed — pipeline interrupted at this stage';
      } else {
        firstPending.status = 'in_progress';
      }
    }
  }

  return { stages, iteration, variantCount, failedStage };
}

function RunStageDot({ status, failed }) {
  if (failed) {
    return (
      <span className="grid size-6 shrink-0 place-items-center rounded-full bg-danger text-white">
        <AlertTriangle size={13} strokeWidth={2.5} aria-hidden="true" />
      </span>
    );
  }
  if (status === 'done') {
    return (
      <span className="grid size-6 shrink-0 place-items-center rounded-full bg-success text-white">
        <Check size={13} strokeWidth={3} aria-hidden="true" />
      </span>
    );
  }
  if (status === 'in_progress') {
    return (
      <span className="grid size-6 shrink-0 place-items-center rounded-full">
        <span className="size-3.5 animate-pulse rounded-full border-2 border-brand" />
      </span>
    );
  }
  return <span className="size-6 shrink-0 rounded-full bg-surface-2 ring-1 ring-inset ring-border" />;
}

function CampaignRunPanel({ campaignId, events, campaignStatus }) {
  if (!campaignId) return null;
  const { stages, iteration, variantCount, failedStage } = deriveCampaignRun(events, campaignStatus);
  if (!stages.some((s) => s.status !== 'pending')) return null; // nothing has run yet

  return (
    <div className="mb-3 rounded-xl border border-border bg-surface-2 p-4">
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm font-semibold text-fg">Campaign Run</p>
        <p className="text-xs text-faint">
          Iteration {iteration} · {variantCount} variant{variantCount === 1 ? '' : 's'}
        </p>
      </div>
      <ul className="relative">
        {stages.map((stage, index) => {
          const isLast = index === stages.length - 1;
          return (
            <li key={stage.key} className="relative flex gap-3 pb-6 last:pb-0">
              {!isLast && (
                <span
                  aria-hidden="true"
                  className={cn(
                    'absolute left-3 top-6 -ml-px h-[calc(100%-1.5rem)] w-0.5 transition-colors duration-500',
                    stage.status === 'done' ? 'bg-success/60' : 'bg-border',
                  )}
                />
              )}
              <RunStageDot status={stage.status} failed={stage.failed} />
              <div className="min-w-0 flex-1 pt-0.5">
                <p className={cn('text-sm font-semibold', stage.status === 'pending' ? 'text-muted' : 'text-fg')}>
                  {stage.label}
                </p>
                <p className={cn('text-xs', stage.failed ? 'text-danger' : 'text-muted')}>
                  {stage.agent}
                  {stage.description ? ` — ${stage.failed ? stage.failReason : stage.description}` : ''}
                </p>
                {stage.chips.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {stage.key === 'content_generator'
                      ? stage.chips.map((channel) => <ChannelIcon key={channel} channel={channel} size={14} />)
                      : stage.chips.map((chip) => (
                          <span
                            key={chip}
                            className="rounded-full bg-surface px-2 py-0.5 text-[11px] font-medium text-muted ring-1 ring-inset ring-border"
                          >
                            {chip}
                          </span>
                        ))}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {failedStage && (
        <div className="mt-3 rounded-lg border border-danger/30 bg-danger/5 px-3 py-2.5 text-xs text-danger">
          <span className="font-semibold">Campaign failed at {failedStage.label}.</span>{' '}
          {failedStage.failReason} Processing stopped — this campaign will not produce a
          usable draft.
        </div>
      )}
    </div>
  );
}

// Real pipeline stages pushed from _process_turn (conversations.py) over the
// already-open per-conversation websocket — not timer-driven guesses, so
// this always reflects the step actually running server-side.
const STATUS_STAGE_LABELS = {
  understanding: 'Reading your message…',
  checking_brief: 'Checking the brief…',
  checking_similar: 'Checking for similar campaigns…',
  drafting_reply: 'Drafting a reply…',
};

function StatusIndicator({ stage }) {
  const label = STATUS_STAGE_LABELS[stage] || 'Working on it…';
  return (
    <div className="flex items-center gap-2 text-xs text-muted">
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full brand-gradient text-white">
        <Bot size={16} aria-hidden="true" className="animate-pulse" />
      </span>
      <span className="flex items-center gap-1.5 rounded-2xl rounded-tl-sm border border-border bg-surface-2 px-3.5 py-2.5">
        <span className="flex gap-0.5">
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand [animation-delay:-0.3s]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand [animation-delay:-0.15s]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand" />
        </span>
        {label}
      </span>
    </div>
  );
}

// Fake streaming: the full reply already arrived over the websocket, this
// just reveals it fast (many chars/tick, short interval) so it *reads* as a
// continuous stream rather than popping in — deliberately quick, not a
// slow word-by-word typewriter.
function StreamedText({ text, active }) {
  const [shown, setShown] = useState(active ? '' : text);

  useEffect(() => {
    if (!active) {
      setShown(text);
      return;
    }
    setShown('');
    let i = 0;
    const chunk = Math.max(2, Math.ceil(text.length / 60));
    const timer = window.setInterval(() => {
      i += chunk;
      setShown(text.slice(0, i));
      if (i >= text.length) window.clearInterval(timer);
    }, 12);
    return () => window.clearInterval(timer);
  }, [text, active]);

  return <>{shown}</>;
}

function ChatThreadPanel({
  conversationId,
  brief,
  brandId,
  onBriefUpdated,
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
  draftCampaign,
  onOpenDraftReview,
  similarCampaign,
  onVerifySimilar,
  onModifyPrompt,
  onProceedAnyway,
  proceedingAnyway,
  awaitingConfirmation,
  onProceed,
  proceedingConfirm,
  waitingForReply,
  statusStage,
  campaignEvents,
  campaignStatus,
  onOpenSampleBrief,
  forcedPickerStep = '',
}) {
  const stageBadges = [
    conversationStage && { label: conversationStage.replaceAll('_', ' '), key: 'stage' },
    primaryObjective && { label: primaryObjective.replaceAll('_', ' '), key: 'obj' },
    turnType && { label: turnType.replaceAll('_', ' '), key: 'turn' },
  ].filter(Boolean);
  const headerTitle = conversationTitle({ partial_brief: brief }) === 'New conversation'
    ? 'Campaign copilot'
    : conversationTitle({ partial_brief: brief });

  // Which structured field (if any) the copilot's last question is waiting
  // on — same "first incomplete slot" logic the sidebar checklist uses, so
  // the inline picker always matches what the assistant just asked about.
  // No campaign running yet, brief not already complete, not mid-reply.
  // `forcedPickerStep` (set when the last turn rejected free-text input for
  // a picker-only field) takes priority — otherwise a user who has already
  // typed a segment name would just see the checklist stay "Pending" with no
  // picker until every earlier step also happened to be filled.
  const briefSteps = computeBriefSteps(brief);
  const forcedStep = forcedPickerStep && briefSteps.find((s) => s.key === forcedPickerStep);
  const currentBriefStep = (forcedStep && !forcedStep.ok ? forcedStep : null) || briefSteps.find((s) => !s.ok);
  const showInlinePicker =
    Boolean(conversationId) &&
    !campaignId &&
    !awaitingConfirmation &&
    !waitingForReply &&
    currentBriefStep &&
    PICKER_STEP_KEYS.has(currentBriefStep.key) &&
    messages.length > 0 &&
    messages[messages.length - 1]?.role !== 'user';

  const messagesEndRef = useRef(null);
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ block: 'end' });
  }, [messages, waitingForReply, showInlinePicker]);

  return (
    <section className="flex h-[calc(100vh-13rem)] min-h-[32rem] flex-col overflow-hidden rounded-2xl border border-border bg-surface card-shadow">
      {/* Header removed — campaign metadata moved to page-level header */}

      {needsClarification ? (
        <div className="border-b border-warning/30 bg-warning/5 px-4 py-2 text-xs text-warning">
          Clarification needed{clarificationTarget ? `: ${clarificationTarget.replaceAll('_', ' ')}` : ''}
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
                  <p className="whitespace-pre-wrap leading-relaxed">
                    {!isUser && msg.stream ? (
                      <StreamedText text={msg.content} active={idx === messages.length - 1} />
                    ) : (
                      msg.content
                    )}
                  </p>
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

        {showInlinePicker ? (
          <div className="ml-[42px] max-w-[85%] rounded-2xl rounded-tl-sm border border-border bg-surface-2 px-3.5 py-3">
            {currentBriefStep.key === 'channels' ? (
              <ChannelPillsPicker
                conversationId={conversationId}
                brandId={brandId}
                currentValue={brief?.channels}
                onSelected={onBriefUpdated}
              />
            ) : currentBriefStep.key === 'locales' ? (
              <LocalePillsPicker
                conversationId={conversationId}
                brandId={brandId}
                currentValue={brief?.locales}
                onSelected={onBriefUpdated}
              />
            ) : currentBriefStep.key === 'audience_segments' ? (
              <SegmentDropdownPicker
                conversationId={conversationId}
                brandId={brandId}
                currentValue={brief?.audience_segments}
                onSelected={onBriefUpdated}
              />
            ) : null}
            {/* token_budget picker removed (2026-07-29): auto-set, no longer collected from users */}
          </div>
        ) : null}

        {waitingForReply ? <StatusIndicator stage={statusStage} /> : null}

        <CampaignRunPanel campaignId={campaignId} events={campaignEvents || []} campaignStatus={campaignStatus} />

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

        {draftCampaign ? (
          (() => {
            const variants = draftCampaign.variants || [];
            const uniqueChannels = [...new Set(variants.map((v) => v.channel).filter(Boolean))];
            const uniqueLocales = [...new Set(variants.map((v) => v.locale).filter(Boolean))];
            return (
              <article
                role="button"
                tabIndex={0}
                onClick={() => onOpenDraftReview(draftCampaign.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onOpenDraftReview(draftCampaign.id);
                  }
                }}
                className="flex cursor-pointer items-center justify-between gap-3 rounded-xl border border-brand/40 bg-brand-soft/40 px-3 py-2.5 text-left transition-colors hover:border-brand focus:outline-none focus-visible:ring-2 focus-visible:ring-brand"
              >
                <div className="min-w-0">
                  <div className="mb-1 flex flex-wrap items-center gap-2">
                    <Badge tone="brand">Content Draft Ready</Badge>
                    {uniqueChannels.length > 0 ? (
                      <span className="flex items-center gap-1.5 text-xs text-muted">
                        Variants:
                        <span className="flex items-center gap-1 text-brand">
                          {uniqueChannels.map((ch) => (
                            <button
                              key={ch}
                              type="button"
                              title={`Preview ${ch}`}
                              onClick={(e) => {
                                e.stopPropagation();
                                const task = variants.find((v) => v.channel === ch);
                                onOpenDraftReview(draftCampaign.id, task?.task_id);
                              }}
                              className="rounded-full p-0.5 hover:bg-brand/15"
                            >
                              <ChannelIcon channel={ch} size={14} />
                            </button>
                          ))}
                        </span>
                      </span>
                    ) : null}
                    {uniqueLocales.map((loc) => (
                      <span
                        key={loc}
                        className="rounded-full bg-surface-2 px-2 py-0.5 text-[10px] font-medium text-muted"
                      >
                        {loc}
                      </span>
                    ))}
                  </div>
                  <p className="truncate text-sm text-fg">
                    {campaignTitle(draftCampaign) || 'Click to review the generated content'}
                  </p>
                </div>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={(e) => {
                    e.stopPropagation();
                    onOpenDraftReview(draftCampaign.id);
                  }}
                >
                  <Eye size={14} aria-hidden="true" className="mr-1.5" />
                  Preview
                </Button>
              </article>
            );
          })()
        ) : null}

        {awaitingConfirmation && !similarCampaign ? (
          <div className="flex items-center justify-between gap-2 rounded-xl border border-brand/40 bg-brand-soft/40 px-3 py-2.5">
            <p className="text-sm text-fg">Brief looks complete — ready to run this campaign?</p>
            <Button variant="primary" size="sm" onClick={onProceed} disabled={proceedingConfirm}>
              {proceedingConfirm ? 'Starting…' : 'Proceed'}
            </Button>
          </div>
        ) : null}

        {similarCampaign ? (
          <div className="rounded-xl border border-warning/40 bg-warning/5 px-3 py-2.5">
            <div className="mb-1.5 flex items-center gap-2">
              <AlertTriangle size={16} aria-hidden="true" className="shrink-0 text-warning" />
              <Badge tone="warning">Similar campaign found</Badge>
            </div>
            <p className="mb-1 text-sm text-fg">
              {similarCampaign.objective
                ? `${similarCampaign.objective}${
                    similarCampaign.target_audience ? ` in ${similarCampaign.target_audience}` : ''
                  }`
                : 'An existing campaign looks a lot like this one.'}
            </p>
            {similarCampaign.channels?.length > 0 ? (
              <div className="mb-2 flex items-center gap-1.5 text-xs text-muted">
                Variants:
                <span className="flex items-center gap-1 text-brand">
                  {similarCampaign.channels.map((ch) => (
                    <ChannelIcon key={ch} channel={ch} size={14} />
                  ))}
                </span>
              </div>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" size="sm" onClick={onVerifySimilar}>
                <Eye size={14} aria-hidden="true" className="mr-1.5" />
                Verify
              </Button>
              <Button variant="ghost" size="sm" onClick={onModifyPrompt}>
                <Pencil size={14} aria-hidden="true" className="mr-1.5" />
                Modify prompt
              </Button>
              <Button variant="primary" size="sm" onClick={onProceedAnyway} disabled={proceedingAnyway}>
                {proceedingAnyway ? 'Starting…' : 'Proceed anyway'}
              </Button>
            </div>
          </div>
        ) : null}

        <div ref={messagesEndRef} />
      </div>

      {/* Composer */}
      <div className="border-t border-border bg-surface px-4 py-3">
        {draftCampaign ? (
          <p className="mb-2 text-xs text-muted">
            Content has been generated for this campaign — preview it above, edit individual channels, or discard
            and regenerate from the preview popup. Chat is paused until then.
          </p>
        ) : null}
        {similarCampaign ? (
          <p className="mb-2 text-xs text-muted">
            A similar campaign was found — verify it or proceed anyway above. Chat is paused until then.
          </p>
        ) : null}
        {suggestedPrompts.length > 0 && !campaignId && !draftCampaign && !similarCampaign ? (
          <div className="mb-2 flex flex-wrap gap-1.5">
            <button
              type="button"
              onClick={onOpenSampleBrief}
              className="rounded-full border border-border bg-surface px-2.5 py-1 text-xs text-muted transition-colors hover:border-brand hover:text-brand disabled:opacity-50"
            >
               View Sample Brief
            </button>
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
        {campaignId && !draftCampaign && !similarCampaign ? (
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
                disabled={!canChat || waitingForReply}
                className="rounded-full border border-border bg-surface px-2.5 py-1 text-xs text-muted transition-colors hover:border-brand hover:text-brand disabled:opacity-50 disabled:cursor-not-allowed"
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
            placeholder={
              draftCampaign || similarCampaign ? 'Chat is paused — see the card above' : chatPlaceholder
            }
            disabled={Boolean(draftCampaign || similarCampaign || waitingForReply)}
            className="h-9 flex-1 bg-transparent px-2.5 text-sm text-fg placeholder:text-faint focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
          />
          <button
            type="button"
            onClick={sendMessage}
            disabled={
              !hasConversation || !message.trim() || Boolean(draftCampaign || similarCampaign || waitingForReply)
            }
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
  const [archivingId, setArchivingId] = useState('');

  const handleArchiveOne = async (e, id) => {
    e.stopPropagation();
    setArchivingId(id);
    try {
      await archiveConversation(id);
      await loadRecentConversations();
    } catch {
      // Best-effort — the row just stays visible if this fails; user can retry.
    } finally {
      setArchivingId('');
    }
  };

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
          recentConversations
            // Filter out incomplete conversations: those still in 'collecting' status
            // with no campaign attached and default titles
            .filter((session) => {
              const displayStatus = session.campaign_status || session.status || 'collecting';
              const title = conversationTitle(session);
              // Hide empty conversations in collecting phase (no campaign created yet)
              const isEmptyCollecting = displayStatus === 'collecting' && !session.campaign_id;
              return !isEmptyCollecting;
            })
            .map((session) => {
            const isActive = session.conversation_id === conversationId;
            const updated = session.updated_at ? relativeTime(session.updated_at) : '';
            const title = conversationTitle(session);
            // Prefer the attached campaign's live status over the
            // conversation's own status field, which is never rewritten once
            // a campaign attaches and would otherwise show "processing"
            // forever regardless of what actually happened to the campaign.
            const displayStatus = session.campaign_status || session.status || 'collecting';
            const statusInfo = conversationStatusInfo(session);
            // Archiving is only offered for conversations that are done being
            // useful: hard-failed campaigns, or ones stuck in brief collection
            // that were never finished — not for anything still active/live.
            const canArchive = displayStatus === 'failed' || displayStatus === 'collecting';
            return (
              <div
                key={session.conversation_id}
                role="button"
                tabIndex={0}
                onClick={() => selectConversation(session)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    selectConversation(session);
                  }
                }}
                className={cn(
                  'group relative w-full cursor-pointer rounded-xl border px-3 py-2.5 text-left transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand',
                  isActive
                    ? 'border-brand/40 bg-brand-soft'
                    : 'border-transparent hover:border-border hover:bg-surface-2',
                )}
              >
                {canArchive && (
                  <button
                    type="button"
                    onClick={(e) => handleArchiveOne(e, session.conversation_id)}
                    disabled={archivingId === session.conversation_id}
                    title="Archive this conversation"
                    className="absolute right-2 top-2 hidden size-6 items-center justify-center rounded-lg text-faint transition-colors hover:bg-surface hover:text-fg group-hover:flex disabled:opacity-60"
                  >
                    <Archive size={12} aria-hidden="true" />
                  </button>
                )}
                <div className={cn(canArchive && 'pr-6')}>
                  <p
                    title={title}
                    className={cn('truncate text-sm font-medium', isActive ? 'text-brand' : 'text-fg')}
                  >
                    {title}
                  </p>
                  <div className="mt-1.5 flex items-center gap-2">
                    <div className="group relative flex items-center cursor-help">
                      <span
                        className={cn(
                          'h-2 w-2 rounded-full shrink-0',
                          statusInfo.tone === 'success' && 'bg-success',
                          statusInfo.tone === 'warning' && 'bg-warning',
                          statusInfo.tone === 'danger' && 'bg-danger',
                          statusInfo.tone === 'brand' && 'bg-brand',
                          statusInfo.tone === 'neutral' && 'bg-muted',
                        )}
                      />
                      <div className="pointer-events-none invisible absolute bottom-full left-1/2 -translate-x-1/2 z-20 mb-1.5 w-max rounded-md border border-border bg-surface px-2 py-1 text-[11px] font-medium text-fg opacity-0 shadow-md transition-opacity group-hover:visible group-hover:opacity-100">
                        {statusInfo.label}
                      </div>
                    </div>
                    {updated && <span className="text-[11px] text-faint">{updated}</span>}
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}

function HomeGreetingPanel({
  user,
  brands = [],
  brandsLoading = false,
  selectedBrandId = '',
  onSelectBrand = () => {},
  onStartConversation,
}) {
  const [stats, setStats] = useState({ total: 0, draft: 0, pending: 0, published: 0, failed: 0 });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let active = true;
    async function loadStats() {
      setLoading(true);
      try {
        const data = await fetchCampaignStats();
        if (active) {
          setStats(data);
        }
      } catch (err) {
        console.error('Failed to load campaign stats:', err);
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }
    loadStats();
    return () => {
      active = false;
    };
  }, []);

  const getGreeting = () => {
    const hour = new Date().getHours();
    if (hour >= 5 && hour < 12) return 'Good morning';
    if (hour >= 12 && hour < 17) return 'Good afternoon';
    return 'Good evening';
  };

  const firstName = user?.name ? user.name.split(' ')[0] : 'User';

  const pillsData = [
    {
      key: 'total',
      label: 'Total campaigns',
      count: stats.total,
      icon: ListChecks,
      color: 'var(--grad-4)',
    },
    {
      key: 'draft',
      label: 'Draft',
      count: stats.draft,
      icon: Pencil,
      color: 'var(--grad-3)',
    },
    {
      key: 'pending',
      label: 'Pending approval',
      count: stats.pending,
      icon: AlertTriangle,
      color: 'var(--grad-1)',
    },
    {
      key: 'published',
      label: 'Published',
      count: stats.published,
      icon: Check,
      color: 'var(--success)',
    },
    {
      key: 'failed',
      label: 'Failed',
      count: stats.failed,
      icon: AlertTriangle,
      color: 'var(--grad-2)',
    },
  ];

  return (
    <section className="flex flex-col items-center justify-center h-[calc(100vh-8rem)] min-h-[42rem] overflow-hidden rounded-2xl border border-border bg-surface p-8 card-shadow relative">
      {/* Soft decorative background glow */}
      <div className="absolute inset-0 pointer-events-none opacity-40 brand-glow rounded-2xl" />

      {/* Main greeting content */}
      <div className="relative z-10 flex flex-col items-center justify-center text-center px-4 max-w-3xl mx-auto w-full mb-8">
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-brand-soft text-brand border border-brand/10 mb-6 animate-fade-up">
          <Sparkles size={13} aria-hidden="true" />
          Welcome to OmniBrand Studio
        </span>
        
        <h1 className="text-4xl font-bold tracking-tight text-fg sm:text-5xl font-display mb-4 animate-fade-up">
          ✨ {getGreeting()}, {firstName}
        </h1>
        
        <p className="text-base text-muted max-w-md mb-6 leading-relaxed animate-fade-up" style={{ animationDelay: '0.1s' }}>
          Create and launch high-performing, brand-compliant campaigns across multiple channels and locales.
        </p>

        {/* Brand pills selection before starting */}
        {brands.length > 1 && (
          <div className="mb-8 w-full max-w-lg animate-fade-up" style={{ animationDelay: '0.15s' }}>
            <p className="mb-2.5 text-xs font-semibold uppercase tracking-wider text-muted">Select Active Brand</p>
            <div className="flex flex-wrap justify-center gap-2">
              {brands.map((b) => {
                const active = selectedBrandId === b.id;
                return (
                  <button
                    key={b.id}
                    type="button"
                    onClick={() => onSelectBrand(b.id)}
                    className={cn(
                      "rounded-full px-4 py-2 text-xs font-semibold transition-all duration-200 border cursor-pointer",
                      active
                        ? "bg-brand border-brand text-brand-fg shadow-md shadow-brand/20 scale-[1.03]"
                        : "bg-surface-2 border-border text-muted hover:border-brand/40 hover:text-fg"
                    )}
                  >
                    {b.name}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        <button
          type="button"
          onClick={onStartConversation}
          className="group cursor-pointer inline-flex items-center justify-center gap-2 rounded-2xl brand-gradient hover:opacity-95 text-white px-8 py-4 text-base font-semibold shadow-lg hover:shadow-xl transition-all duration-200 hover:-translate-y-0.5 active:translate-y-0 animate-fade-up"
          style={{ animationDelay: '0.2s' }}
        >
          <Plus size={20} aria-hidden="true" className="transition-transform group-hover:rotate-90" />
          Start new conversation
        </button>
      </div>

      {/* Stats Dashboard */}
      <div className="w-full max-w-5xl mx-auto px-4 relative z-10 border-t border-border/60 pt-8 animate-fade-up" style={{ animationDelay: '0.3s' }}>
        <h2 className="text-xs font-semibold uppercase tracking-wider text-faint mb-4 text-center">
          Campaign Overview
        </h2>
        
        <div className="flex items-center justify-center gap-3 overflow-x-auto no-scrollbar py-1 w-full">
          {pillsData.map((pill) => {
            const Icon = pill.icon;
            return (
              <div
                key={pill.key}
                style={{
                  borderColor: pill.color,
                  color: pill.color,
                  backgroundColor: `color-mix(in oklab, ${pill.color} 10%, transparent)`,
                }}
                className="flex items-center gap-2.5 rounded-full border px-4 py-2.5 text-xs font-semibold shadow-sm transition-transform hover:scale-[1.02] shrink-0"
              >
                <Icon size={14} style={{ color: pill.color }} className="shrink-0" aria-hidden="true" />
                <span className="text-sm font-bold">{loading ? '...' : pill.count}</span>
                <span className="opacity-90">{pill.label}</span>
              </div>
            );
          })}
        </div>
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

// A short, human-readable label for the sidebar — "{objective} in {audience}"
// reads like a real campaign subject line once both are captured. Falls back
// gracefully as fields fill in one at a time during brief collection, and —
// if the conversation was abandoned before any brief field was captured —
// to a snippet of the user's first message rather than a permanent, useless
// "New conversation" (see next_tasks.md item 11).
function conversationTitle(session) {
  const brief = session.partial_brief || {};
  const objective = (brief.objective || '').trim();
  const audience = (brief.target_audience || '').trim() || (brief.audience_segments || []).join(', ');

  if (objective) {
    const title = audience ? `${objective} in ${audience}` : objective;
    return title.length > 100 ? `${title.slice(0, 100)}…` : title;
  }
  const firstMessage = (session.first_message || '').trim();
  if (firstMessage) {
    return firstMessage.length > 100 ? `${firstMessage.slice(0, 100)}…` : firstMessage;
  }
  return 'New conversation';
}

// Distinguishes near-identical titles (several conversations often start with
// the same objective wording) with the channels/locales captured so far —
// see next_tasks.md item 12.
// Sidebar status pill (2026-07-27) — collapses the raw status value plus a
// "has anything actually been entered yet" check into one user-facing label,
// since the backend only ever tracks a single "collecting" status for both
// a just-opened blank conversation and one that's partway through the brief.
// "New" = literally nothing captured yet (brief is empty); "Waiting for
// input" = the objective (or something) was given but required slots are
// still missing — per the user's own definition of the two states.
function conversationStatusInfo(session) {
  const status = session.campaign_status || session.status || 'collecting';
  if (status === 'collecting') {
    const brief = session.partial_brief || {};
    const hasAnyContent =
      Boolean((brief.objective || '').trim()) ||
      Boolean((brief.target_audience || '').trim()) ||
      (brief.channels || []).length > 0 ||
      (brief.locales || []).length > 0 ||
      (brief.audience_segments || []).length > 0 ||
      Boolean(brief.token_budget);
    return hasAnyContent
      ? { label: 'Waiting for input', tone: 'warning' }
      : { label: 'New', tone: 'neutral' };
  }
  return STATUS_INFO[status] || { label: status.replaceAll('_', ' '), tone: 'neutral' };
}

const STATUS_INFO = {
  awaiting_confirmation: { label: 'Pending approval', tone: 'warning' },
  processing: { label: 'In progress', tone: 'brand' },
  queued: { label: 'In progress', tone: 'brand' },
  running: { label: 'In progress', tone: 'brand' },
  draft: { label: 'Draft', tone: 'neutral' },
  awaiting_review: { label: 'Needs review', tone: 'warning' },
  published: { label: 'Published', tone: 'success' },
  failed: { label: 'Failed', tone: 'danger' },
  cancelled: { label: 'Cancelled', tone: 'neutral' },
};

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
  campaignStatus,
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
      <CampaignEventsList events={events} campaignStatus={campaignStatus} />
    </div>
  );
}

// "Run summary" — Brief tab content once a campaign exists (2026-07-27
// revamp; the step-by-step BriefChecklist/BriefFieldStates below still
// covers the PRE-campaign brief-collection phase, when there's nothing to
// summarize yet). Every value here is real, derived from the actual
// campaign detail response (brief, variants incl. translation_checks +
// judge_scores, cost_by_agent) — never a placeholder.
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

// Donut via conic-gradient — no chart library needed for a single small
// fixed-palette per-stage token breakdown.
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

// Native `title` only reliably hovers where the browser thinks there's
// text, not necessarily the full 2-line clamped block (confirmed: hover
// only triggered near the truncation ellipsis, not the whole paragraph).
// This wraps the trigger in a `group` block so `group-hover` fires across
// the ENTIRE bounding box, not just wherever the browser's title heuristic
// picks.
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

// SVG arcs (not CSS conic-gradient) deliberately — a conic-gradient is one
// flat background image with no per-segment DOM nodes, so it can never have
// per-segment hover. Each <circle> here is its own element with its own
// native <title> tooltip (stage / tokens / %), same reliable browser-native
// hover mechanism as the prompt-summary tooltip below.
function TokenDonut({ segments, total }) {
  const [hovered, setHovered] = useState(null);
  if (total <= 0) return null;
  const radius = 60;
  const strokeWidth = 24;
  const circumference = 2 * Math.PI * radius;
  let offsetAcc = 0;

  return (
    <div className="relative size-40 shrink-0">
      <svg viewBox="0 0 160 160" className="size-40 -rotate-90">
        {segments.map(({ key, tokens }) => {
          const pct = tokens / total;
          const dash = pct * circumference;
          const strokeDashoffset = -offsetAcc;
          offsetAcc += dash;
          return (
            <circle
              key={key}
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
          );
        })}
      </svg>
      <div className="pointer-events-none absolute inset-0 grid place-items-center">
        <div className="text-center">
          <p className="text-2xl font-bold text-fg">{total.toLocaleString()}</p>
          <p className="text-xs text-muted">tokens</p>
        </div>
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

function RunSummaryPanel({ campaign, iteration }) {
  if (!campaign) return null;
  const summary = deriveRunSummary(campaign);

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-2">
        <p className="text-base font-bold text-fg">Run summary</p>
        <p className="text-xs text-faint">iteration {iteration || 1}</p>
      </div>

      {summary.promptSummary ? (
        <HoverTooltip content={summary.promptSummary}>
          <p className="line-clamp-2 cursor-default text-sm text-muted">{summary.promptSummary}</p>
        </HoverTooltip>
      ) : null}
      {summary.objectiveLine ? <p className="text-sm font-semibold text-fg">{summary.objectiveLine}</p> : null}

      {summary.channels.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {summary.channels.map((ch) => (
            <span
              key={ch}
              className="inline-flex items-center gap-1.5 rounded-full bg-brand-soft px-2.5 py-1 text-xs font-medium text-brand"
            >
              <ChannelIcon channel={ch} size={13} />
              {ch}
            </span>
          ))}
        </div>
      ) : null}
      {summary.segmentChips.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {summary.segmentChips.map((chip) => (
            <span
              key={chip}
              className="rounded-full bg-surface-2 px-2.5 py-1 text-xs font-medium text-muted ring-1 ring-inset ring-border"
            >
              {chip}
            </span>
          ))}
        </div>
      ) : null}

      {(summary.translationRows.length > 0 || summary.judgeRows.length > 0) && (
        <div className="grid grid-cols-1 gap-4 border-t border-border pt-4 sm:grid-cols-2">
          {summary.translationRows.length > 0 && (
            <div>
              <p className="mb-2 text-sm font-semibold text-muted">Translation</p>
              <div className="space-y-2">
                {summary.translationRows.map((row) => (
                  <div key={row.locale} className="rounded-lg border border-border bg-surface-2 p-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="flex items-center gap-1.5 text-sm font-semibold text-fg">
                        <span className={cn('size-2 rounded-full', _dotClass(row.tone))} />
                        {row.locale}
                      </span>
                      <span className="text-sm font-semibold text-fg">{row.score?.toFixed(2)}</span>
                    </div>
                    <p className="mt-1 text-xs text-muted">{row.reason}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
          {summary.judgeRows.length > 0 && (
            <div>
              <p className="mb-2 text-sm font-semibold text-muted">Judge gate</p>
              <div className="space-y-2">
                {summary.judgeRows.map((row) => (
                  <div key={row.judgeModel} className="rounded-lg border border-border bg-surface-2 p-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="flex items-center gap-1.5 text-sm font-semibold text-fg">
                        <span className={cn('size-2 rounded-full', _dotClass(row.tone))} />
                        {row.judgeModel}
                      </span>
                      <span className="text-sm font-semibold text-fg">{row.pct}%</span>
                    </div>
                    <p className="mt-1 text-xs text-muted">{row.reasoning}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {summary.totalTokens > 0 && (
        <div className="border-t border-border pt-4">
          <p className="mb-3 text-sm font-semibold text-muted">Tokens consumed by stage</p>
          <TokenDonut segments={summary.tokenSegments} total={summary.totalTokens} />
        </div>
      )}
    </div>
  );
}

function WorkspaceInspector({
  brief,
  briefFieldStates,
  stream,
  campaign,
  campaignId,
  iteration,
  brandName = '',
}) {
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
          campaign ? (
            <RunSummaryPanel campaign={campaign} iteration={iteration} />
          ) : campaignId ? (
            // Campaign exists but its detail hasn't loaded yet — show a
            // loading state instead of the pre-campaign checklist, which
            // would otherwise flash briefly before RunSummaryPanel takes
            // over once campaignDetail finishes fetching (2026-07-27).
            <div className="flex items-center gap-2 text-sm text-muted">
              <RefreshCw size={14} aria-hidden="true" className="animate-spin" />
              Loading run summary…
            </div>
          ) : (
            <>
              {briefFieldStates.length > 0 ? (
                <BriefFieldStates fieldStates={briefFieldStates} />
              ) : (
                <BriefChecklist brief={brief} brandName={brandName} />
              )}
              <div className="mt-4 flex items-start gap-2 rounded-xl border border-border bg-surface-2 p-3">
                <Sparkles size={15} aria-hidden="true" className="mt-0.5 shrink-0 text-brand" />
                <p className="text-xs text-muted">
                  When every field is complete, send{' '}
                  <span className="font-medium text-fg">“run campaign”</span> to enqueue execution.
                </p>
              </div>
            </>
          )
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

// One icon per pipeline agent (2026-07-27) — same "icon instead of raw
// name" treatment ChannelIcon already gives channels. `__start__`/unknown
// agents fall back to PlayCircle.
const AGENT_ICON = {
  __start__: PlayCircle,
  intake_agent: ClipboardList,
  content_generator: FileEdit,
  personalization_agent: UserCog,
  translation_agent: Languages,
  judge_gate: Filter,
  judge_claude: Scale,
  judge_gpt4o: BadgeCheck,
  judge_llama: Gavel,
  confidence_aggregator: BarChart3,
  reflexion: RotateCcw,
  review_gate: Eye,
  publishing_agent: Send,
};

// Small hover tooltip for a dot/icon — floats above, same pattern item 37a
// already uses for the sidebar's status dots (native `title` was found
// unreliable in Chrome in an earlier session, see item 34c).
function DotTooltip({ label, children }) {
  return (
    <div className="group relative flex cursor-help items-center">
      {children}
      <div className="pointer-events-none invisible absolute bottom-full left-1/2 z-20 mb-1.5 w-max -translate-x-1/2 rounded-md border border-border bg-surface px-2 py-1 text-[11px] font-medium text-fg opacity-0 shadow-md transition-opacity group-hover:visible group-hover:opacity-100">
        {label}
      </div>
    </div>
  );
}

function AgentIcon({ agent, size = 13 }) {
  const Icon = AGENT_ICON[agent] || PlayCircle;
  return (
    <DotTooltip label={agent}>
      <Icon size={size} aria-hidden="true" />
    </DotTooltip>
  );
}

// Readable status per event, instead of the raw phase string — same 4
// labels the user asked for: Errored / Failed / Running / Completed.
// `isLatest`/`campaignStatus` are only needed to detect "still running."
function agentEventStatus({ payload, isLatest, campaignStatus }) {
  if (payload?.errors?.length) {
    return { label: 'Errored', tone: 'danger' };
  }

  // Same failure signals deriveCampaignRun() already checks per stage —
  // reused here so a single event card and the Campaign Run timeline never
  // disagree about whether a given stage's outcome was a failure.
  const tasks = payload?.tasks || [];
  const failedTranslation = tasks.some((t) =>
    ['failed', 'unsupported', 'blocked'].some((frag) => String(t.status || '').includes(frag)),
  );
  const judgeRejected = tasks.some((t) => t.any_critical_violation || t.routing_decision === 'auto_reject');
  if (payload?.failed_count > 0 || failedTranslation || judgeRejected) {
    return { label: 'Failed', tone: 'danger' };
  }

  if (isLatest && ['running', 'queued'].includes(campaignStatus)) {
    return { label: 'Running', tone: 'brand' };
  }

  return { label: 'Completed', tone: 'success' };
}

function CampaignEventsList({ events, campaignStatus }) {
  return (
    <div className="h-[22rem] space-y-2 overflow-y-auto rounded-xl border border-border bg-surface-2 p-3">
      {events.length === 0 ? (
        <p className="text-sm text-muted">Events appear here after campaign start.</p>
      ) : (
        events.map((event, idx) => (
          <CampaignEventCard
            key={event.event_id || `${event.timestamp || 'na'}-${event.agent || 'event'}-${event.phase || 'update'}`}
            event={event}
            isLatest={idx === events.length - 1}
            campaignStatus={campaignStatus}
          />
        ))
      )}
    </div>
  );
}

function CampaignEventCard({ event, isLatest, campaignStatus }) {
  const [expanded, setExpanded] = useState(false);
  const source = event.source || 'live';
  const agent = event.agent || 'event';
  const summary = event.summary || `${agent} updated ${event.phase || 'state'}`;
  const payload = event.payload || {};
  const hasDetails = hasAgentDetails(agent, payload);
  const status = agentEventStatus({ payload, isLatest, campaignStatus });
  const ChevronIcon = expanded ? ChevronUp : ChevronDown;

  return (
    <div className="rounded-lg border border-border bg-surface px-2.5 py-2 text-xs">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-muted">
          <AgentIcon agent={agent} />
          <span className="text-faint">[{source}]</span>
        </div>
        <div className="flex items-center gap-2">
          <DotTooltip label={status.label}>
            <span
              className={cn(
                'h-2 w-2 shrink-0 rounded-full',
                status.tone === 'success' && 'bg-success',
                status.tone === 'danger' && 'bg-danger',
                status.tone === 'brand' && 'bg-brand',
              )}
            />
          </DotTooltip>
          {hasDetails ? (
            <button
              type="button"
              onClick={() => setExpanded((value) => !value)}
              aria-label={expanded ? 'Hide details' : 'Show details'}
              className="grid h-5 w-5 place-items-center rounded text-faint transition-colors hover:bg-surface-2 hover:text-fg"
            >
              <ChevronIcon size={14} aria-hidden="true" />
            </button>
          ) : null}
        </div>
      </div>
      <p className="mt-1 text-muted">{summary}</p>
      {expanded ? <AgentEventDetails agent={agent} payload={payload} /> : null}
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
  const rejectedFields = Array.isArray(payload?.rejected_fields)
    ? payload.rejected_fields.filter((value) => typeof value === 'string')
    : [];

  return {
    updates,
    changes,
    suggestedPrompts,
    briefFieldStates,
    rejectedFields,
    conversationStage:
      typeof payload?.conversation_stage === 'string' && payload.conversation_stage
        ? payload.conversation_stage
        : '',
    primaryObjective: typeof payload?.primary_objective === 'string' ? payload.primary_objective : '',
    turnType: typeof payload?.turn_type === 'string' ? payload.turn_type : '',
    needsClarification: Boolean(payload?.needs_clarification),
    clarificationTarget: typeof payload?.clarification_target === 'string' ? payload.clarification_target : '',
    awaitingConfirmation: Boolean(payload?.awaiting_confirmation),
  };
}

async function handleStartConversationAction({
  brandId,
  setBrandId,
  setStatus,
  setError,
  setConversationId,
  setCampaignId,
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
    const session = await createConversation(brandId);
    setBrandId(session.brand_id || brandId);
    setConversationId(session.id);
    setCampaignId('');
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

async function handleSelectConversationAction({
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
  setSimilarCampaign,
  setAwaitingConfirmation,
  setBrandId,
}) {
  setConversationId(session.conversation_id);
  setCampaignId(session.active_campaign_id || '');
  setBrief(session.partial_brief || {});
  setBrandId(session.brand_id || '');
  // Restore the Proceed-button gate on reload/conversation-switch — session.status
  // already carries this (it's what drives the sidebar's "Awaiting Review" badge),
  // it just wasn't being read into chat state here (2026-07-27 persistence bug).
  setAwaitingConfirmation(session.status === 'awaiting_confirmation');
  setMessages([{ role: 'assistant', content: 'Loading conversation history…' }]);
  setConversationStage('campaign_discovery');
  setPrimaryObjective('');
  setTurnType('');
  setNeedsClarification(false);
  setClarificationTarget('');
  setBriefFieldStates([]);
  setSuggestedPrompts([]);
  setError('');
  setStatus('ready');

  try {
    const payload = await fetchConversationMessages(session.conversation_id);
    const history = payload.messages || [];
    setMessages(
      history.length > 0
        ? history.map((m) => ({
            role: m.role,
            content: m.content,
            captured: Array.isArray(m.captured) ? m.captured : [],
            changes: Array.isArray(m.changes) ? m.changes : [],
          }))
        : [
            {
              role: 'assistant',
              content: 'Conversation resumed — no earlier messages. Continue the brief or run campaign when ready.',
            },
          ],
    );
    // Restores a similar-campaign flag that a page reload or conversation
    // switch would otherwise silently drop — see the endpoint's docstring.
    setSimilarCampaign(payload.similar_campaign || null);
  } catch {
    // Non-fatal: chat still works, just without visible history for this turn.
    setMessages([
      {
        role: 'assistant',
        content: `Resumed conversation ${session.conversation_id}. Couldn't load earlier messages — continue the brief or run campaign when ready.`,
      },
    ]);
  }
}

function handleSendPromptAction({ prompt, canChat, send, setError, setMessages, setWaitingForReply, setStatusStage }) {
  if (!canChat) return;
  const sent = send({ message: prompt });
  if (!sent) {
    setError('Socket is not connected yet');
    return;
  }
  setMessages((prev) => [...prev, { role: 'user', content: prompt }]);
  setStatusStage('');
  setWaitingForReply(true);
}

function handleSendMessageAction({
  message,
  hasConversation,
  wsConnected,
  send,
  setError,
  setMessages,
  setMessage,
  setWaitingForReply,
  setStatusStage,
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
  setStatusStage('');
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
  const { user } = useAuth();
  // Multi-brand support (2026-07-27): a conversation is always tied to one
  // brand. `brandId` tracks whichever brand the ACTIVE conversation belongs
  // to (set on create/select), separate from `brands` (every brand the
  // logged-in user can see, for the "which brand is this for?" gate below).
  const [brands, setBrands] = useState([]);
  // Only needed for org-wide users (no explicit brand_ids in JWT) to discover
  // all available brands. Single-brand users use their JWT brand_ids directly.
  const [brandsLoading, setBrandsLoading] = useState(false);
  const [selectedGreetingBrandId, setSelectedGreetingBrandId] = useState('');
  const [brandId, setBrandId] = useState('');
  const [pendingBrandChoice, setPendingBrandChoice] = useState(false);
  const [brandChoiceError, setBrandChoiceError] = useState('');

  // Load brand list for display purposes (pill labels). We only set
  // brandsLoading=true when the user is org-wide (no explicit brand_ids in
  // their JWT) because those users need the list to pick a brand. Users with
  // explicit brand_ids can start immediately using those ids directly.
  useEffect(() => {
    let cancelled = false;
    const jwtBrandIds = user?.brand_ids || [];
    const needsApiForBrandChoice = jwtBrandIds.length !== 1;
    if (needsApiForBrandChoice) setBrandsLoading(true);
    const load = async () => {
      try {
        const res = await listBrands();
        if (!cancelled) {
          const list = res.brands || [];
          setBrands(list);
          // Auto-select when there's only one brand in the returned list
          if (list.length === 1) {
            setSelectedGreetingBrandId(list[0].id);
          }
        }
      } catch (err) {
        console.error('Failed to load brands:', err);
      } finally {
        if (!cancelled) setBrandsLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [user]);

  const [conversationId, setConversationId] = useState('');
  const [campaignId, setCampaignId] = useState('');
  const [draftCampaign, setDraftCampaign] = useState(null);
  const [draftPollTrigger, setDraftPollTrigger] = useState(0);
  const [campaignStatus, setCampaignStatus] = useState('');
  const [campaignDetail, setCampaignDetail] = useState(null);
  const [reviewModalCampaignId, setReviewModalCampaignId] = useState(null);
  const [reviewModalInitialTaskId, setReviewModalInitialTaskId] = useState('');
  const openDraftReview = (id, taskId = '') => {
    setReviewModalInitialTaskId(taskId || '');
    setReviewModalCampaignId(id);
  };
  const [similarCampaign, setSimilarCampaign] = useState(null);
  const [similarCampaignModalOpen, setSimilarCampaignModalOpen] = useState(false);
  const [proceedingAnyway, setProceedingAnyway] = useState(false);
  const [proceedingConfirm, setProceedingConfirm] = useState(false);
  const [waitingForReply, setWaitingForReply] = useState(false);
  const [statusStage, setStatusStage] = useState('');
  const [message, setMessage] = useState('');
  const [messages, setMessages] = useState([]);
  const [brief, setBrief] = useState({});
  // A field the latest turn rejected free-text input for (see rejected_fields
  // in the turn response) — forces that field's inline picker into view even
  // if an earlier brief step is still incomplete, so the picker appears right
  // where the user's rejected mention was, not just when its turn comes up.
  const [forcedPickerStep, setForcedPickerStep] = useState('');
  const [conversationStage, setConversationStage] = useState('');
  const [primaryObjective, setPrimaryObjective] = useState('');
  const [turnType, setTurnType] = useState('');
  const [needsClarification, setNeedsClarification] = useState(false);
  const [awaitingConfirmation, setAwaitingConfirmation] = useState(false);
  const [clarificationTarget, setClarificationTarget] = useState('');
  const [briefFieldStates, setBriefFieldStates] = useState([]);
  const [suggestedPrompts, setSuggestedPrompts] = useState([]);
  const [sampleBriefModalOpen, setSampleBriefModalOpen] = useState(false);
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



  // A similar-campaign flag is scoped to the conversation that produced it —
  // clear it (and any open popup) whenever the active conversation changes,
  // so switching away doesn't leave a stale flag/lock behind.
  useEffect(() => {
    setSimilarCampaign(null);
    setSimilarCampaignModalOpen(false);
    setWaitingForReply(false);
  }, [conversationId]);

  // Polls the campaign this conversation is running so a content card can
  // appear in the chat on its own, without the user having to leave and
  // check the Gallery. Stops once the campaign lands anywhere past 'draft'
  // (or fails) — there's nothing more to show here at that point.
  useEffect(() => {
    setDraftCampaign(null);
    setCampaignStatus('');
    setCampaignDetail(null);
    if (!campaignId) return undefined;

    let cancelled = false;
    let timer;

    const poll = async () => {
      try {
        const detail = await fetchCampaign(campaignId);
        if (cancelled) return;
        setCampaignStatus(detail.status || '');
        setCampaignDetail(detail);
        if (detail.status === 'draft') {
          setDraftCampaign(detail);
          return;
        }
        if (['running', 'queued'].includes(detail.status)) {
          timer = setTimeout(poll, 3000);
        }
        // awaiting_review / published / failed / cancelled: nothing to show
        // here anymore — awaiting_review already has its own card via
        // pendingReviews, and the rest are terminal.
      } catch {
        timer = setTimeout(poll, 5000);
      }
    };

    timer = setTimeout(poll, 3000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [campaignId, draftPollTrigger]);

  const createSocket = useCallback(() => openConversationSocket(conversationId), [conversationId]);

  const handleSocketMessage = useCallback((payload) => {
    if (payload.type === 'status') {
      // Real pipeline stage pushed from _process_turn as it actually runs —
      // not a timer guess, so this always matches the work in flight.
      setStatusStage(payload.stage || '');
      return;
    }

    // Stop the status indicator and append the reply FIRST, before any
    // further parsing — a bare payload.message is always shown even if
    // something below throws, instead of the whole turn silently vanishing
    // with the status indicator just stuck/cleared and no visible reply.
    setWaitingForReply(false);
    setStatusStage('');
    setProceedingConfirm(false);
    if (payload.error) {
      setError(payload.error);
      return;
    }
    if (payload.message) {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: payload.message,
          captured: [],
          changes: [],
          stream: true,
        },
      ]);
    }

    try {
      const parsed = parseSocketPayload(payload);
      if (payload.message) {
        setMessages((prev) => {
          const next = [...prev];
          const lastIdx = next.length - 1;
          if (next[lastIdx]?.role === 'assistant' && next[lastIdx]?.content === payload.message) {
            next[lastIdx] = { ...next[lastIdx], captured: parsed.updates, changes: parsed.changes };
          }
          return next;
        });
      }
      if (payload.brief) setBrief(payload.brief);
      if (payload.campaign_id) setCampaignId(payload.campaign_id);
      setSimilarCampaign(payload.similar_campaign || null);
      setForcedPickerStep(
        parsed.rejectedFields.find((field) => PICKER_STEP_KEYS.has(field)) || '',
      );
      setConversationStage(parsed.conversationStage || '');
      setPrimaryObjective(parsed.primaryObjective || '');
      setTurnType(parsed.turnType || '');
      setNeedsClarification(parsed.needsClarification);
      setClarificationTarget(parsed.clarificationTarget);
      // Only meaningful while nothing's enqueued yet — once campaign_id
      // shows up the confirm gate has already been passed (or bypassed via
      // "Proceed anyway"), so hide the button rather than leave it stale.
      setAwaitingConfirmation(parsed.awaitingConfirmation && !payload.campaign_id);
      setBriefFieldStates(parsed.briefFieldStates);
      setSuggestedPrompts(parsed.suggestedPrompts);
      if (Array.isArray(payload.pending_reviews)) {
        setPendingReviews(payload.pending_reviews);
      }
      // A review decision made in-app (Approve/Reject in the chat's review
      // card) returns the campaign's up-to-date status right here in the
      // websocket reply — previously never read, so the Run Summary panel
      // etc. only ever caught up once the (separate, and by this point
      // already-stopped) polling loop happened to re-check. Purely
      // additive: doesn't touch how the decision itself is recorded, just
      // lets the UI notice sooner for this one path. A decision made in
      // Airtable instead is caught by the SSE-driven refresh below, since
      // it never goes through this websocket at all.
      if (typeof payload.campaign_status === 'string' && payload.campaign_status) {
        setCampaignStatus(payload.campaign_status);
      }
    } catch (exc) {
      // The reply itself is already rendered (above) — a failure parsing
      // secondary fields (brief diff chips, suggested prompts, etc.) must
      // never make the whole turn look like it silently disappeared.
      console.error('handleSocketMessage: failed to parse secondary fields', exc);
    }
  }, []);

  const { connected: wsConnected, send } = useWebSocket(createSocket, {
    enabled: Boolean(conversationId),
    onMessage: handleSocketMessage,
  });

  // The "reconnecting" banner is only meaningful while the socket is down —
  // clear it once the socket comes back so it doesn't linger indefinitely.
  useEffect(() => {
    if (!wsConnected) return;
    setError((prev) => (prev === 'Chat is reconnecting. Please try again in a moment.' ? '' : prev));
  }, [wsConnected]);

  const createCampaignStream = useCallback(
    () => openCampaignEventStream(campaignId),
    [campaignId],
  );

  const { events, connected: sseConnected } = useSSE(
    createCampaignStream,
    Boolean(campaignId),
  );

  // Refresh campaignStatus/campaignDetail whenever the live SSE stream shows
  // a review decision was actually applied — additive, doesn't touch how
  // decisions are recorded or synced. This is the one hook that covers BOTH
  // approval paths uniformly: an Airtable-driven decision resumes the same
  // graph and emits the same review_complete/publishing_complete events an
  // in-app decision does, even though it never goes through the chat
  // websocket at all. The existing polling loop (elsewhere in this file)
  // already stops once status reaches 'awaiting_review', on the assumption
  // "nothing to show here anymore" — which is exactly the state a decision
  // gets made FROM, so nothing was left to notice it happened.
  useEffect(() => {
    if (!campaignId || events.length === 0) return;
    const latestPhase = events[events.length - 1]?.phase;
    if (latestPhase !== 'review_complete' && latestPhase !== 'publishing_complete') return;

    let cancelled = false;
    fetchCampaign(campaignId)
      .then((detail) => {
        if (cancelled) return;
        setCampaignStatus(detail.status || '');
        setCampaignDetail(detail);
      })
      .catch(() => {
        /* best-effort refresh — the existing polling loop remains a fallback */
      });
    return () => {
      cancelled = true;
    };
  }, [campaignId, events]);

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

  const createConversationForBrand = (chosenBrandId) =>
    handleStartConversationAction({
      brandId: chosenBrandId,
      setBrandId,
      setStatus,
      setError,
      setConversationId,
      setCampaignId,
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

  // Multi-brand gate (2026-07-27): a user with exactly one brand never sees
  // a prompt at all (auto-picked); a user with more than one is asked which
  // brand this campaign is for BEFORE the conversation is created — the
  // brand can't be changed afterward, since it's threaded into RAG
  // retrieval, judge context, and channel/locale entitlement from the very
  // first intake step.
  const myBrandIds = user?.brand_ids || [];
  const candidateBrands = myBrandIds.length
    ? brands.filter((b) => myBrandIds.includes(b.id))
    : brands; // org-wide user (no explicit brand_ids) — every brand in the org

  const startConversation = () => {
    setBrandChoiceError('');

    // Case 1: user has exactly 1 brand in their JWT — use it immediately,
    // no need to wait for the listBrands API response.
    if (myBrandIds.length === 1) {
      return createConversationForBrand(myBrandIds[0]);
    }

    // Case 2: user has multiple brands in their JWT or is org-wide (0 brand_ids).
    // We need the listBrands response to know which brands to show / pick from.
    if (brandsLoading) {
      setBrandChoiceError('Loading your assigned brands… please try again in a moment.');
      return undefined;
    }

    // candidateBrands = brands filtered by JWT brand_ids (or all org brands if org-wide)
    if (candidateBrands.length === 1) {
      return createConversationForBrand(candidateBrands[0].id);
    }
    if (candidateBrands.length > 1) {
      if (selectedGreetingBrandId) {
        return createConversationForBrand(selectedGreetingBrandId);
      }
      setBrandChoiceError('Please select a brand from the options above before starting.');
      return undefined;
    }
    setBrandChoiceError('No brand is assigned to your account yet — contact an admin.');
    return undefined;
  };

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
      setSimilarCampaign,
      setAwaitingConfirmation,
      setBrandId,
    });

  // Used by the read-only similar-campaign popup's "Load that conversation"
  // button. Reuses the same conversation object shape as the sidebar list —
  // pulled from the already-loaded recent list when possible; falls back to
  // a minimal session so selection still works if it's fallen out of that
  // window (a real fetch of the full session isn't available client-side).
  const loadConversationById = (targetConversationId) => {
    const known = recentConversations.find((s) => s.conversation_id === targetConversationId);
    selectConversation(
      known || { conversation_id: targetConversationId, active_campaign_id: '', partial_brief: {} },
    );
  };

  // Dispatch events to sidebar to keep it in sync
  useEffect(() => {
    window.dispatchEvent(new CustomEvent('obs:conversations-changed', {
      detail: { recentConversations, conversationId }
    }));
  }, [recentConversations, conversationId]);

  // Listen to select-conversation events from sidebar
  useEffect(() => {
    const handleSelect = (e) => {
      selectConversation(e.detail);
    };
    window.addEventListener('obs:select-conversation', handleSelect);
    return () => {
      window.removeEventListener('obs:select-conversation', handleSelect);
    };
  }, [selectConversation]);

  // Listen to archive-conversation events from sidebar
  useEffect(() => {
    const handleArchive = async (e) => {
      const id = e.detail;
      await loadRecentConversations();
      if (conversationId === id) {
        setConversationId('');
      }
    };
    window.addEventListener('obs:archive-conversation', handleArchive);
    return () => {
      window.removeEventListener('obs:archive-conversation', handleArchive);
    };
  }, [conversationId, loadRecentConversations]);

  // Broadcast SSE live/idle status to TopNav for the Chat status indicator
  useEffect(() => {
    window.dispatchEvent(new CustomEvent('obs:sse-status', { detail: { connected: sseConnected } }));
  }, [sseConnected]);

  // Allow the TopNav Create button to reset to the greeting / new conversation
  useEffect(() => {
    const handler = () => startConversation();
    window.addEventListener('obs:start-new-conversation', handler);
    return () => window.removeEventListener('obs:start-new-conversation', handler);
  }, []);

  // Handle URL query parameter on mount
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const cid = params.get('conversation_id');
    if (cid && recentConversations.length > 0) {
      loadConversationById(cid);
      // Clear URL parameter
      window.history.replaceState({}, '', window.location.pathname);
    }
  }, [recentConversations]);

  // Structured brief-input pickers (locale pills / segment dropdown / budget
  // tiers) call setBriefField() directly via REST, bypassing the chat
  // websocket turn entirely — this reconciles that response back into the
  // same local state the websocket path would otherwise have set, including
  // showing the server's own ack message in the transcript (it's persisted
  // server-side into conversation_messages, but the live `messages` array
  // here needs the same append the websocket path gets for free).
  const handleBriefUpdated = (res, label) => {
    if (!res) return;
    setBrief(res.brief);
    // Picker updates bypass the chat websocket turn, so the field-status
    // panel needs this response's own brief_field_states — otherwise it
    // kept showing stale "missing" until the next chat message came in
    // and recomputed it server-side (2026-07-30 fix).
    if (Array.isArray(res.brief_field_states)) {
      setBriefFieldStates(res.brief_field_states);
    }
    setMessages((prev) => {
      const next = [...prev];
      // Collapse the picker selection into a normal user-style bubble
      // (2026-07-27 UX decision) so the transcript reads as a real
      // conversation instead of leaving the picker widget behind.
      if (label) next.push({ role: 'user', content: label });
      if (res.message) next.push({ role: 'assistant', content: res.message });
      return next;
    });
    setAwaitingConfirmation(Boolean(res.awaiting_confirmation));
  };

  const handleProceedConfirm = () => {
    if (!wsConnected) {
      setError('Chat is reconnecting. Please try again in a moment.');
      return;
    }
    setProceedingConfirm(true);
    // Sends the exact same "yes" a typed reply would — goes through the
    // normal chat-confirm turn (_is_affirmative in conversations.py), not a
    // separate bypass endpoint, so this is just a click standing in for
    // typing the word, not a different code path.
    const sent = send({ message: 'yes' });
    if (!sent) {
      setError('Chat socket is not connected yet');
      setProceedingConfirm(false);
      return;
    }
    setMessages((prev) => [...prev, { role: 'user', content: 'Yes' }]);
    setAwaitingConfirmation(false);
    setWaitingForReply(true);
    setStatusStage('');
  };

  const handleProceedAnyway = async () => {
    if (!conversationId) return;
    setProceedingAnyway(true);
    setError('');
    try {
      const result = await runCampaignAnyway(conversationId);
      setSimilarCampaign(null);
      if (result.campaign_id) {
        setCampaignId(result.campaign_id);
        setDraftPollTrigger((n) => n + 1);
        // "Proceed anyway" bypasses the normal chat-confirm turn entirely,
        // which previously meant the campaign started with zero visible
        // acknowledgment in the thread — same message the chat-confirm
        // path posts, so both ways of starting a campaign look consistent.
        if (result.message) {
          setMessages((prev) => [...prev, { role: 'assistant', content: result.message }]);
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to proceed');
    } finally {
      setProceedingAnyway(false);
    }
  };

  const sendMessage = () =>
    handleSendMessageAction({
      message,
      hasConversation,
      wsConnected,
      send,
      setError,
      setMessages,
      setMessage,
      setWaitingForReply,
      setStatusStage,
    });

  const sendPrompt = (prompt) =>
    handleSendPromptAction({
      prompt,
      canChat,
      send,
      setError,
      setMessages,
      setWaitingForReply,
      setStatusStage,
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

  // Derive active session metadata for the page header
  const activeSession = conversationId
    ? (recentConversations.find((s) => s.conversation_id === conversationId) || null)
    : null;
  const activeConvoTitle = conversationId
    ? conversationTitle({ partial_brief: brief })
    : '';
  // Which brand this conversation belongs to, shown in the title (multi-
  // brand support, 2026-07-27) — resolved from the fetched brands list;
  // falls back to activeSession.brand_id if the dedicated brandId state
  // hasn't caught up yet (e.g. right after a page reload).
  const activeBrandName = conversationId
    ? brands.find((b) => b.id === (brandId || activeSession?.brand_id))?.name
    : '';
  const activeStatusInfo = activeSession ? conversationStatusInfo(activeSession) : null;
  const BADGE_TONE_COLORS = {
    success: 'bg-success/12 text-success ring-success/20',
    warning: 'bg-warning/12 text-warning ring-warning/20',
    danger: 'bg-danger/12 text-danger ring-danger/20',
    brand: 'bg-brand/10 text-brand ring-brand/20',
    neutral: 'bg-surface-2 text-muted ring-border',
  };

  function fmtDate(iso) {
    if (!iso) return null;
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return null;
    return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
  }

  const createdAt = fmtDate(activeSession?.created_at);
  const updatedAt = fmtDate(activeSession?.updated_at);
  const approvedBy = campaignDetail?.approved_by || null;

  return (
    <Page
      wide
      eyebrow={conversationId ? 'Campaign' : ''}
      title={activeConvoTitle || ''}
      description={
        conversationId
          ? <span className="font-mono text-xs text-faint select-all">{conversationId}</span>
          : ''
      }
      actions={
        conversationId && activeStatusInfo ? (
          <div className="flex flex-wrap items-center gap-3 text-xs text-muted">
            {/* Status badge */}
            <span
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-medium ring-1 ring-inset capitalize',
                BADGE_TONE_COLORS[activeStatusInfo.tone] || BADGE_TONE_COLORS.neutral,
              )}
            >
              {activeStatusInfo.label}
            </span>
            {/* Brand chip — shown right after status */}
            {activeBrandName && (
              <span className="inline-flex items-center gap-1 rounded-full bg-brand/10 px-2.5 py-1 font-medium text-brand ring-1 ring-inset ring-brand/20">
                {activeBrandName}
              </span>
            )}
            {/* Created date */}
            {createdAt && (
              <span className="flex items-center gap-1">
                <span className="text-faint">Created</span> {createdAt}
              </span>
            )}
            {/* Modified date */}
            {updatedAt && (
              <span className="flex items-center gap-1">
                <span className="text-faint">Modified</span> {updatedAt}
              </span>
            )}
            {/* Approved by */}
            {approvedBy && (
              <span className="flex items-center gap-1">
                <span className="text-faint">Approved by</span> {approvedBy}
              </span>
            )}
          </div>
        ) : null
      }
    >
      {error ? (
        <div className="mb-4 rounded-xl border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </div>
      ) : null}

      {brandChoiceError ? (
        <div className="mb-4 rounded-xl border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          {brandChoiceError}
        </div>
      ) : null}



      <div className={cn("grid gap-4", conversationId ? "lg:grid-cols-[minmax(0,1fr)_minmax(0,380px)]" : "")}>
        {conversationId ? (
          <>
            <ChatThreadPanel
              conversationId={conversationId}
              brief={brief}
              brandId={brandId}
              onBriefUpdated={handleBriefUpdated}
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
              draftCampaign={draftCampaign}
              onOpenDraftReview={openDraftReview}
              similarCampaign={similarCampaign}
              onVerifySimilar={() => setSimilarCampaignModalOpen(true)}
              onModifyPrompt={() => setSimilarCampaign(null)}
              onProceedAnyway={handleProceedAnyway}
              awaitingConfirmation={awaitingConfirmation}
              onProceed={handleProceedConfirm}
              proceedingConfirm={proceedingConfirm}
              proceedingAnyway={proceedingAnyway}
              waitingForReply={waitingForReply}
              statusStage={statusStage}
              campaignEvents={mergedEvents}
              campaignStatus={campaignStatus}
              onOpenSampleBrief={() => setSampleBriefModalOpen(true)}
              forcedPickerStep={forcedPickerStep}
            />

            {reviewModalCampaignId ? (
              <CampaignDetailModal
                campaignId={reviewModalCampaignId}
                initialTaskId={reviewModalInitialTaskId}
                onClose={() => {
                  setReviewModalCampaignId(null);
                  setReviewModalInitialTaskId('');
                }}
                onChanged={() => setDraftPollTrigger((n) => n + 1)}
              />
            ) : null}

            {similarCampaignModalOpen && similarCampaign ? (
              <SimilarCampaignModal
                campaignId={similarCampaign.campaign_id}
                onClose={() => setSimilarCampaignModalOpen(false)}
                onLoadConversation={loadConversationById}
              />
            ) : null}

            <SampleBriefModal
              open={sampleBriefModalOpen}
              onClose={() => setSampleBriefModalOpen(false)}
            />

            <WorkspaceInspector
              brief={brief}
              briefFieldStates={briefFieldStates}
              brandName={activeBrandName}
              campaign={campaignDetail}
              campaignId={campaignId}
              iteration={deriveCampaignRun(events || [], campaignStatus).iteration}
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
                  campaignStatus={campaignStatus}
                />
              }
            />
          </>
        ) : (
          <HomeGreetingPanel
            user={user}
            brands={candidateBrands}
            brandsLoading={brandsLoading}
            selectedBrandId={selectedGreetingBrandId}
            onSelectBrand={setSelectedGreetingBrandId}
            onStartConversation={startConversation}
          />
        )}
      </div>
    </Page>
  );
}
