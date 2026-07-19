import { useId, useState } from 'react';
import { Sparkles, Loader2, Lightbulb } from 'lucide-react';
import { cn } from '@/lib/cn.js';
import { PROMPT_IDEAS } from '@/data/showcase.js';

const MODELS = ['OmniImage 3', 'OmniImage 3 Turbo'];
const STYLES = ['None', 'Photo', 'Cinematic', 'Anime', '3D Render', 'Watercolor', 'Neon'];
const ASPECTS = [
  { value: '1:1', label: 'Square' },
  { value: '4:3', label: 'Landscape' },
  { value: '3:4', label: 'Portrait' },
  { value: '16:9', label: 'Wide' },
];
const COUNTS = [1, 2, 3, 4];

function Field({ label, children }) {
  return (
    <label className="flex flex-col gap-1.5 text-xs font-medium text-muted">
      {label}
      {children}
    </label>
  );
}

const selectClass =
  'h-9 rounded-lg border border-border bg-surface px-2.5 text-sm font-medium text-fg ' +
  'transition-colors hover:border-border-strong focus:border-brand';

/**
 * Firefly-style prompt composer. Prompt text is controlled by the parent (so
 * "use this prompt" flows work); generation settings live here and are handed
 * back on submit.
 */
export function PromptComposer({ value, onChange, onGenerate, generating }) {
  const promptId = useId();
  const [model, setModel] = useState(MODELS[0]);
  const [style, setStyle] = useState(STYLES[0]);
  const [aspect, setAspect] = useState(ASPECTS[0].value);
  const [count, setCount] = useState(4);

  const canSubmit = value.trim().length > 2 && !generating;

  const submit = (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    onGenerate(value.trim(), { model, style, aspect, count });
  };

  const onKeyDown = (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') submit(e);
  };

  return (
    <form onSubmit={submit} aria-label="Image prompt">
      <div
        className={cn(
          'rounded-3xl border border-border bg-surface p-2 card-shadow',
          'focus-within:border-brand/60 transition-colors',
        )}
      >
        <label htmlFor={promptId} className="sr-only">
          Describe the image you want to generate
        </label>
        <textarea
          id={promptId}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          rows={3}
          placeholder="Describe anything… e.g. “a serene Japanese garden in the rain, cinematic lighting, ultra detailed”"
          className="w-full resize-none bg-transparent px-3 py-2.5 text-[15px] leading-relaxed text-fg placeholder:text-faint focus:outline-none"
        />

        <div className="flex flex-wrap items-end gap-2 border-t border-border px-2 pb-1 pt-3">
          {/* Aspect ratio segmented control */}
          <fieldset className="flex flex-col gap-1.5">
            <legend className="text-xs font-medium text-muted">Aspect</legend>
            <div className="inline-flex rounded-lg border border-border bg-surface-2 p-0.5" role="radiogroup" aria-label="Aspect ratio">
              {ASPECTS.map((a) => (
                <button
                  key={a.value}
                  type="button"
                  role="radio"
                  aria-checked={aspect === a.value}
                  onClick={() => setAspect(a.value)}
                  title={a.label}
                  className={cn(
                    'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                    aspect === a.value
                      ? 'bg-surface text-fg shadow-sm'
                      : 'text-muted hover:text-fg',
                  )}
                >
                  {a.value}
                </button>
              ))}
            </div>
          </fieldset>

          <Field label="Model">
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className={selectClass}
            >
              {MODELS.map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          </Field>

          <Field label="Style">
            <select
              value={style}
              onChange={(e) => setStyle(e.target.value)}
              className={selectClass}
            >
              {STYLES.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </Field>

          <Field label="Images">
            <select
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
              className={selectClass}
            >
              {COUNTS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </Field>

          <button
            type="submit"
            disabled={!canSubmit}
            className={cn(
              'ml-auto inline-flex h-11 items-center gap-2 rounded-xl px-5 text-sm font-semibold',
              'brand-gradient text-white shadow-sm transition',
              'hover:brightness-110 active:brightness-95',
              'disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:brightness-100',
            )}
          >
            {generating ? (
              <>
                <Loader2 size={17} aria-hidden="true" className="animate-spin" />
                Generating…
              </>
            ) : (
              <>
                <Sparkles size={17} aria-hidden="true" />
                Generate
              </>
            )}
          </button>
        </div>
      </div>

      {/* Prompt ideas — shown when the field is empty */}
      {value.trim().length === 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-faint">
            <Lightbulb size={13} aria-hidden="true" /> Try
          </span>
          {PROMPT_IDEAS.slice(0, 4).map((idea) => (
            <button
              key={idea}
              type="button"
              onClick={() => onChange(idea)}
              className="max-w-[15rem] truncate rounded-full border border-border bg-surface px-3 py-1 text-xs text-muted transition-colors hover:border-border-strong hover:text-fg"
            >
              {idea}
            </button>
          ))}
        </div>
      )}
    </form>
  );
}
