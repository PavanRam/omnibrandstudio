import { useId, useMemo, useState } from 'react';
import { Sparkles, Loader2, Megaphone } from 'lucide-react';
import { cn } from '@/lib/cn.js';

// Well-known local dev brand seeded by scripts/seed_prompts.py.
const DEFAULT_BRAND_ID = '00000000-0000-0000-0000-000000000002';

const CHANNELS = [
  { value: 'email', label: 'Email' },
  { value: 'linkedin', label: 'LinkedIn' },
  { value: 'instagram', label: 'Instagram' },
  { value: 'facebook', label: 'Facebook' },
  { value: 'twitter', label: 'Twitter' },
  { value: 'whatsapp', label: 'WhatsApp' },
];

const LOCALES = [
  { value: 'en-US', label: 'English (US)' },
  { value: 'es-ES', label: 'Spanish (ES)' },
  { value: 'fr-FR', label: 'French (FR)' },
];

const SEGMENTS = [
  { value: 'enterprise', label: 'Enterprise' },
  { value: 'smb', label: 'SMB' },
  { value: 'consumer', label: 'Consumer' },
];

const inputClass =
  'w-full rounded-xl border border-border bg-surface px-3 py-2.5 text-sm text-fg ' +
  'placeholder:text-faint transition-colors hover:border-border-strong ' +
  'focus:border-brand focus:outline-none';

function Field({ label, htmlFor, hint, required, children }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-xs font-semibold text-fg">
        {label}
        {required && <span className="ml-0.5 text-danger">*</span>}
        {hint && <span className="ml-2 font-normal text-faint">{hint}</span>}
      </label>
      {children}
    </div>
  );
}

/** Toggle-chip multi-select rendered as accessible checkboxes. */
function ChipGroup({ legend, required, options, selected, onToggle }) {
  return (
    <fieldset className="flex flex-col gap-1.5">
      <legend className="text-xs font-semibold text-fg">
        {legend}
        {required && <span className="ml-0.5 text-danger">*</span>}
      </legend>
      <div className="flex flex-wrap gap-2">
        {options.map((opt) => {
          const active = selected.includes(opt.value);
          return (
            <label
              key={opt.value}
              className={cn(
                'cursor-pointer select-none rounded-full border px-3 py-1.5 text-xs font-medium transition-colors',
                active
                  ? 'border-transparent bg-brand-soft text-brand'
                  : 'border-border bg-surface text-muted hover:border-border-strong hover:text-fg',
              )}
            >
              <input
                type="checkbox"
                className="sr-only"
                checked={active}
                onChange={() => onToggle(opt.value)}
              />
              {opt.label}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

const splitLines = (text) =>
  text
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);

/**
 * Collects a campaign brief and hands back a payload matching the backend's
 * CreateCampaignRequest schema exactly.
 */
export function CampaignForm({ onSubmit, busy }) {
  const ids = {
    brand: useId(),
    objective: useId(),
    audience: useId(),
    messages: useId(),
    tone: useId(),
    budget: useId(),
  };

  const [brandId, setBrandId] = useState(DEFAULT_BRAND_ID);
  const [objective, setObjective] = useState('');
  const [targetAudience, setTargetAudience] = useState('');
  const [keyMessages, setKeyMessages] = useState('');
  const [toneOverride, setToneOverride] = useState('');
  const [channels, setChannels] = useState(['email', 'linkedin']);
  const [locales, setLocales] = useState(['en-US']);
  const [segments, setSegments] = useState(['enterprise']);
  const [tokenBudget, setTokenBudget] = useState(4000);

  const toggle = (setter, list) => (value) =>
    setter(list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);

  const taskCount = channels.length * locales.length * segments.length;

  const canSubmit = useMemo(
    () =>
      !busy &&
      brandId.trim().length > 0 &&
      objective.trim().length > 2 &&
      targetAudience.trim().length > 2 &&
      channels.length > 0 &&
      locales.length > 0 &&
      segments.length > 0 &&
      Number(tokenBudget) > 0,
    [busy, brandId, objective, targetAudience, channels, locales, segments, tokenBudget],
  );

  const submit = (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    onSubmit({
      brand_id: brandId.trim(),
      objective: objective.trim(),
      target_audience: targetAudience.trim(),
      key_messages: splitLines(keyMessages),
      tone_override: toneOverride.trim() || null,
      channels,
      locales,
      audience_segments: segments,
      token_budget: Number(tokenBudget),
      raw_text: '',
    });
  };

  return (
    <form
      onSubmit={submit}
      aria-label="Campaign brief"
      className="rounded-3xl border border-border bg-surface p-5 card-shadow sm:p-6"
    >
      <div className="mb-5 flex items-center gap-2">
        <span className="grid h-9 w-9 place-items-center rounded-xl brand-gradient text-white">
          <Megaphone size={18} aria-hidden="true" />
        </span>
        <div>
          <h2 className="text-base font-semibold text-fg">Campaign brief</h2>
          <p className="text-xs text-muted">
            Generates brand-compliant content across every selected channel, locale and segment.
          </p>
        </div>
      </div>

      <div className="grid gap-4">
        <Field label="Brand ID" htmlFor={ids.brand} required hint="UUID of the target brand">
          <input
            id={ids.brand}
            value={brandId}
            onChange={(e) => setBrandId(e.target.value)}
            className={cn(inputClass, 'font-mono text-xs')}
            placeholder="00000000-0000-0000-0000-000000000002"
          />
        </Field>

        <Field label="Objective" htmlFor={ids.objective} required>
          <input
            id={ids.objective}
            value={objective}
            onChange={(e) => setObjective(e.target.value)}
            className={inputClass}
            placeholder="Launch summer promo for hydration packs"
          />
        </Field>

        <Field label="Target audience" htmlFor={ids.audience} required>
          <input
            id={ids.audience}
            value={targetAudience}
            onChange={(e) => setTargetAudience(e.target.value)}
            className={inputClass}
            placeholder="Urban commuters aged 25–40"
          />
        </Field>

        <Field
          label="Key messages"
          htmlFor={ids.messages}
          hint="one per line, optional"
        >
          <textarea
            id={ids.messages}
            value={keyMessages}
            onChange={(e) => setKeyMessages(e.target.value)}
            rows={3}
            className={cn(inputClass, 'resize-none')}
            placeholder={'Lightweight\nLeak-proof\nAll-day comfort'}
          />
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Tone override" htmlFor={ids.tone} hint="optional">
            <input
              id={ids.tone}
              value={toneOverride}
              onChange={(e) => setToneOverride(e.target.value)}
              className={inputClass}
              placeholder="confident and helpful"
            />
          </Field>

          <Field label="Token budget" htmlFor={ids.budget} required>
            <input
              id={ids.budget}
              type="number"
              min={1}
              value={tokenBudget}
              onChange={(e) => setTokenBudget(e.target.value)}
              className={inputClass}
            />
          </Field>
        </div>

        <ChipGroup
          legend="Channels"
          required
          options={CHANNELS}
          selected={channels}
          onToggle={toggle(setChannels, channels)}
        />

        <div className="grid gap-4 sm:grid-cols-2">
          <ChipGroup
            legend="Locales"
            required
            options={LOCALES}
            selected={locales}
            onToggle={toggle(setLocales, locales)}
          />
          <ChipGroup
            legend="Audience segments"
            required
            options={SEGMENTS}
            selected={segments}
            onToggle={toggle(setSegments, segments)}
          />
        </div>
      </div>

      <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
        <p className="text-xs text-muted">
          {taskCount > 0 ? (
            <>
              Will generate{' '}
              <span className="font-semibold text-fg">{taskCount}</span> variant
              {taskCount === 1 ? '' : 's'}{' '}
              <span className="text-faint">(channels × locales × segments)</span>
            </>
          ) : (
            'Select at least one channel, locale and segment.'
          )}
        </p>

        <button
          type="submit"
          disabled={!canSubmit}
          className={cn(
            'inline-flex h-11 items-center gap-2 rounded-xl px-6 text-sm font-semibold',
            'brand-gradient text-white shadow-sm transition',
            'hover:brightness-110 active:brightness-95',
            'disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:brightness-100',
          )}
        >
          {busy ? (
            <>
              <Loader2 size={17} aria-hidden="true" className="animate-spin" />
              Processing…
            </>
          ) : (
            <>
              <Sparkles size={17} aria-hidden="true" />
              Generate campaign
            </>
          )}
        </button>
      </div>
    </form>
  );
}
