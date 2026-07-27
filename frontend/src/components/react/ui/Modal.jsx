import { useCallback, useEffect, useId, useRef } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { cn } from '@/lib/cn.js';
import { IconButton } from './IconButton.jsx';

const FOCUSABLE =
  'a[href],button:not([disabled]),textarea,input,select,[tabindex]:not([tabindex="-1"])';

/**
 * Accessible modal dialog:
 * - role="dialog" + aria-modal, labelled by its title
 * - focus moves in on open and is restored on close
 * - Tab is trapped inside; Escape and backdrop click close
 * - body scroll is locked while open
 */
export function Modal({ open, onClose, title, description, size = 'md', children }) {
  const panelRef = useRef(null);
  const restoreRef = useRef(null);
  const titleId = useId();
  const descId = useId();

  const handleKeyDown = useCallback(
    (e) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== 'Tab' || !panelRef.current) return;
      const nodes = panelRef.current.querySelectorAll(FOCUSABLE);
      if (nodes.length === 0) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    },
    [onClose],
  );

  useEffect(() => {
    if (!open) return undefined;
    restoreRef.current = document.activeElement;
    const { overflow } = document.body.style;
    document.body.style.overflow = 'hidden';
    // Move focus into the dialog.
    const raf = requestAnimationFrame(() => {
      const target =
        panelRef.current?.querySelector(FOCUSABLE) ?? panelRef.current;
      target?.focus();
    });
    return () => {
      cancelAnimationFrame(raf);
      document.body.style.overflow = overflow;
      if (restoreRef.current instanceof HTMLElement) restoreRef.current.focus();
    };
  }, [open]);

  if (!open || typeof document === 'undefined') return null;

  const sizes = {
    sm: 'max-w-sm',
    md: 'max-w-lg',
    lg: 'max-w-3xl',
    xl: 'max-w-5xl',
  };

  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-end sm:items-center justify-center p-0 sm:p-4"
      onKeyDown={handleKeyDown}
    >
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm animate-fade-up"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        aria-describedby={description ? descId : undefined}
        tabIndex={-1}
        className={cn(
          'relative w-full bg-surface border border-border shadow-2xl',
          'rounded-t-3xl sm:rounded-3xl outline-none animate-fade-up',
          'max-h-[92vh] overflow-y-auto',
          sizes[size],
        )}
      >
        {(title || onClose) && (
          <div 
            className="flex items-start justify-between gap-4 p-5 sm:p-6 pb-0"
            style={{ paddingBottom: '0px' }}
          >
            <div>
              {title && (
                <h2 id={titleId} className="text-lg font-semibold text-fg">
                  {title}
                </h2>
              )}
              {description && (
                <p id={descId} className="mt-1 text-sm text-muted">
                  {description}
                </p>
              )}
            </div>
            <IconButton label="Close dialog" onClick={onClose}>
              <X size={18} aria-hidden="true" />
            </IconButton>
          </div>
        )}
        <div 
          className={cn("p-5 sm:p-6", (title || onClose) && "pt-0 sm:pt-0")}
          style={(title || onClose) ? { paddingTop: '0px' } : undefined}
        >
          {children}
        </div>
      </div>
    </div>,
    document.body,
  );
}
