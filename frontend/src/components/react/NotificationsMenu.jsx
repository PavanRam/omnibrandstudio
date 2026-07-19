import { useId, useRef, useState } from 'react';
import { Bell, CheckCheck, CircleCheck, Heart, Info } from 'lucide-react';
import { NOTIFICATIONS } from '@/data/notifications.js';
import { useDismissable } from './hooks/useDismissable.js';
import { cn } from '@/lib/cn.js';
import { withBase } from '@/lib/paths.js';

const ICONS = {
  success: CircleCheck,
  info: Info,
  like: Heart,
};

export function NotificationsMenu() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState(NOTIFICATIONS);
  const ref = useRef(null);
  const panelRef = useRef(null);
  const panelId = useId();

  useDismissable(open, () => setOpen(false), ref);

  const unread = items.filter((n) => n.unread).length;
  const markAllRead = () =>
    setItems((prev) => prev.map((n) => ({ ...n, unread: false })));

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-label={`Notifications${unread ? `, ${unread} unread` : ''}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'relative inline-flex h-10 w-10 items-center justify-center rounded-xl',
          'text-muted transition-colors hover:bg-surface-2 hover:text-fg',
          open && 'bg-surface-2 text-fg',
        )}
      >
        <Bell size={18} aria-hidden="true" />
        {unread > 0 && (
          <span
            className="absolute right-1.5 top-1.5 grid h-4 min-w-4 place-items-center rounded-full bg-danger px-1 text-[10px] font-semibold leading-none text-white"
            aria-hidden="true"
          >
            {unread}
          </span>
        )}
      </button>

      {open && (
        <div
          ref={panelRef}
          id={panelId}
          role="dialog"
          aria-label="Notifications"
          className="absolute right-0 z-50 mt-2 w-[min(92vw,22rem)] origin-top-right rounded-2xl border border-border bg-surface shadow-xl card-shadow animate-fade-up"
        >
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <h3 className="text-sm font-semibold text-fg">Notifications</h3>
            <button
              type="button"
              onClick={markAllRead}
              disabled={unread === 0}
              className="inline-flex items-center gap-1.5 text-xs font-medium text-brand hover:underline disabled:text-faint disabled:no-underline"
            >
              <CheckCheck size={14} aria-hidden="true" /> Mark all read
            </button>
          </div>

          <ul className="max-h-[19rem] overflow-y-auto py-1">
            {items.map((n) => {
              const Icon = ICONS[n.type] ?? Info;
              return (
                <li key={n.id}>
                  <button
                    type="button"
                    onClick={() =>
                      setItems((prev) =>
                        prev.map((x) =>
                          x.id === n.id ? { ...x, unread: false } : x,
                        ),
                      )
                    }
                    className="flex w-full gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-2"
                  >
                    <span
                      className={cn(
                        'mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg',
                        n.type === 'success' && 'bg-success/12 text-success',
                        n.type === 'like' && 'bg-danger/12 text-danger',
                        n.type === 'info' && 'bg-brand-soft text-brand',
                      )}
                    >
                      <Icon size={16} aria-hidden="true" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium text-fg">
                          {n.title}
                        </span>
                        {n.unread && (
                          <span
                            className="h-1.5 w-1.5 shrink-0 rounded-full bg-brand"
                            aria-label="unread"
                          />
                        )}
                      </span>
                      <span className="mt-0.5 block text-xs leading-snug text-muted">
                        {n.body}
                      </span>
                      <span className="mt-1 block text-[11px] text-faint">
                        {n.time}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>

          <div className="border-t border-border px-4 py-2.5 text-center">
            <a
              href={withBase('/gallery')}
              className="text-xs font-medium text-brand hover:underline"
            >
              View all activity
            </a>
          </div>
        </div>
      )}
    </div>
  );
}
