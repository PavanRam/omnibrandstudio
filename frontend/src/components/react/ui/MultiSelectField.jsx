import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { ChevronDown, X, Check, Plus } from 'lucide-react';
import { cn } from '@/lib/cn.js';
import { useDismissable } from '../hooks/useDismissable.js';

/**
 * Creatable multi-select combobox (token / tags input).
 *
 * - Pick from preset `options`, and/or type a custom value and press Enter/comma
 *   to add it (`allowCustom`).
 * - Selected values render as removable chips inside the control ("in the text box").
 * - Fully keyboard-accessible: ↑/↓ to move, Enter to add/toggle, Backspace to
 *   remove the last chip, Escape to close. Click-outside closes the menu.
 *
 * `value` is an array of strings; `onChange(nextArray)` is called on every change.
 */
export function MultiSelectField({
  id,
  label,
  hint,
  required = false,
  options = [],
  value = [],
  onChange,
  placeholder = 'Select or type…',
  allowCustom = true,
  emptyText = 'No matches',
}) {
  const reactId = useId();
  const fieldId = id || reactId;
  const listboxId = `${fieldId}-listbox`;

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);

  const containerRef = useRef(null);
  const inputRef = useRef(null);
  const listRef = useRef(null);

  useDismissable(open, () => setOpen(false), containerRef);

  const has = (v) => value.some((x) => x.toLowerCase() === v.toLowerCase());

  // Options not yet selected, filtered by the current query.
  const available = useMemo(
    () => options.filter((o) => !has(o)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [options, value],
  );
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? available.filter((o) => o.toLowerCase().includes(q)) : available;
  }, [available, query]);

  const trimmed = query.trim();
  const canCreate =
    allowCustom &&
    trimmed.length > 0 &&
    !options.some((o) => o.toLowerCase() === trimmed.toLowerCase()) &&
    !has(trimmed);

  // Combined, navigable rows: an optional "create" row first, then options.
  const rows = useMemo(() => {
    const r = [];
    if (canCreate) r.push({ type: 'create', value: trimmed });
    filtered.forEach((o) => r.push({ type: 'option', value: o }));
    return r;
  }, [canCreate, trimmed, filtered]);

  // Keep the highlighted row in range as the list changes.
  useEffect(() => {
    setActiveIndex((i) => Math.min(Math.max(i, 0), Math.max(rows.length - 1, 0)));
  }, [rows.length]);

  const addValue = (raw) => {
    const t = String(raw).trim();
    if (!t) return;
    const canonical = options.find((o) => o.toLowerCase() === t.toLowerCase()) || t;
    if (!has(canonical)) onChange([...value, canonical]);
    setQuery('');
    setActiveIndex(0);
    inputRef.current?.focus();
  };

  const removeValue = (v) => {
    onChange(value.filter((x) => x !== v));
    inputRef.current?.focus();
  };

  const commitActiveRow = () => {
    const row = rows[activeIndex];
    if (row) {
      addValue(row.value);
    } else if (canCreate) {
      addValue(trimmed);
    }
  };

  const onKeyDown = (e) => {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        if (!open) setOpen(true);
        setActiveIndex((i) => Math.min(i + 1, rows.length - 1));
        break;
      case 'ArrowUp':
        e.preventDefault();
        setActiveIndex((i) => Math.max(i - 1, 0));
        break;
      case 'Enter':
        // Never let Enter submit the parent form from this control.
        e.preventDefault();
        if (open && rows.length) commitActiveRow();
        else if (canCreate) addValue(trimmed);
        break;
      case ',':
        if (trimmed) {
          e.preventDefault();
          addValue(trimmed);
        }
        break;
      case 'Backspace':
        if (query === '' && value.length) {
          e.preventDefault();
          removeValue(value[value.length - 1]);
        }
        break;
      case 'Escape':
        if (open) {
          e.preventDefault();
          setOpen(false);
        }
        break;
      default:
        break;
    }
  };

  return (
    <div className="flex flex-col gap-1.5">
      {label && (
        <label htmlFor={fieldId} className="text-xs font-semibold text-fg">
          {label}
          {required && <span className="ml-0.5 text-danger">*</span>}
          {hint && <span className="ml-2 font-normal text-faint">{hint}</span>}
        </label>
      )}

      <div ref={containerRef} className="relative">
        {/* Control */}
        <div
          className={cn(
            'flex min-h-[2.75rem] w-full flex-wrap items-center gap-1.5 rounded-xl border bg-surface px-2 py-1.5',
            'cursor-text transition-colors',
            open ? 'border-brand' : 'border-border hover:border-border-strong',
          )}
          onMouseDown={(e) => {
            // Clicks on the blank control area focus the input; ignore chip buttons.
            if (e.target === e.currentTarget) {
              e.preventDefault();
              inputRef.current?.focus();
              setOpen(true);
            }
          }}
        >
          {value.map((v) => (
            <span
              key={v}
              className="inline-flex max-w-full items-center gap-1 rounded-lg bg-brand-soft py-0.5 pl-2 pr-1 text-xs font-medium text-brand"
            >
              <span className="truncate">{v}</span>
              <button
                type="button"
                onClick={() => removeValue(v)}
                aria-label={`Remove ${v}`}
                className="grid h-4 w-4 shrink-0 place-items-center rounded hover:bg-brand/20"
              >
                <X size={12} aria-hidden="true" />
              </button>
            </span>
          ))}

          <input
            ref={inputRef}
            id={fieldId}
            role="combobox"
            aria-expanded={open}
            aria-controls={listboxId}
            aria-autocomplete="list"
            autoComplete="off"
            value={query}
            placeholder={value.length === 0 ? placeholder : ''}
            onChange={(e) => {
              setQuery(e.target.value);
              if (!open) setOpen(true);
            }}
            onFocus={() => setOpen(true)}
            onKeyDown={onKeyDown}
            className="min-w-[6rem] flex-1 bg-transparent px-1 py-0.5 text-sm text-fg placeholder:text-faint focus:outline-none"
          />

          <button
            type="button"
            tabIndex={-1}
            aria-label={open ? 'Close options' : 'Open options'}
            onClick={() => {
              setOpen((o) => !o);
              inputRef.current?.focus();
            }}
            className="grid h-6 w-6 shrink-0 place-items-center rounded-md text-muted hover:text-fg"
          >
            <ChevronDown
              size={16}
              aria-hidden="true"
              className={cn('transition-transform', open && 'rotate-180')}
            />
          </button>
        </div>

        {/* Dropdown */}
        {open && (
          <ul
            ref={listRef}
            id={listboxId}
            role="listbox"
            aria-multiselectable="true"
            className="absolute left-0 right-0 z-20 mt-1 max-h-60 overflow-auto rounded-xl border border-border bg-surface p-1 card-shadow"
          >
            {rows.length === 0 && (
              <li className="px-3 py-2 text-sm text-faint">
                {value.length && available.length === 0 && !trimmed
                  ? 'All options selected'
                  : emptyText}
              </li>
            )}

            {rows.map((row, i) => {
              const active = i === activeIndex;
              if (row.type === 'create') {
                return (
                  <li key="__create__" role="option" aria-selected={false}>
                    <button
                      type="button"
                      onMouseEnter={() => setActiveIndex(i)}
                      onClick={() => addValue(row.value)}
                      className={cn(
                        'flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm',
                        active ? 'bg-brand-soft text-brand' : 'text-fg hover:bg-surface-2',
                      )}
                    >
                      <Plus size={14} aria-hidden="true" className="shrink-0" />
                      <span className="truncate">
                        Add “<span className="font-medium">{row.value}</span>”
                      </span>
                    </button>
                  </li>
                );
              }
              return (
                <li key={row.value} role="option" aria-selected={false}>
                  <button
                    type="button"
                    onMouseEnter={() => setActiveIndex(i)}
                    onClick={() => addValue(row.value)}
                    className={cn(
                      'flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-sm',
                      active ? 'bg-surface-2 text-fg' : 'text-fg hover:bg-surface-2',
                    )}
                  >
                    <span className="truncate">{row.value}</span>
                    <Plus size={14} aria-hidden="true" className="shrink-0 text-faint" />
                  </button>
                </li>
              );
            })}

            {value.length > 0 && (
              <li className="mt-1 border-t border-border px-3 pb-1 pt-2">
                <div className="mb-1 flex items-center justify-between">
                  <span className="text-[11px] font-medium uppercase tracking-wide text-faint">
                    Selected ({value.length})
                  </span>
                  <button
                    type="button"
                    onClick={() => onChange([])}
                    className="text-[11px] font-medium text-muted hover:text-fg"
                  >
                    Clear all
                  </button>
                </div>
                <div className="flex flex-wrap gap-1">
                  {value.map((v) => (
                    <button
                      key={v}
                      type="button"
                      onClick={() => removeValue(v)}
                      className="inline-flex items-center gap-1 rounded-md bg-brand-soft px-2 py-0.5 text-xs text-brand hover:bg-brand/20"
                    >
                      <Check size={11} aria-hidden="true" /> {v}
                    </button>
                  ))}
                </div>
              </li>
            )}
          </ul>
        )}
      </div>
    </div>
  );
}
