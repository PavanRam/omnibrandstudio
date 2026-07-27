import { useEffect, useId, useRef, useState } from 'react';
import { Bell, CheckCheck, CircleCheck, Info, XCircle, Pencil } from 'lucide-react';
import {
  fetchNotifications,
  fetchUnreadNotificationCount,
  markAllNotificationsRead,
  markNotificationRead,
} from '@/lib/api.js';
import { useDismissable } from './hooks/useDismissable.js';
import { cn } from '@/lib/cn.js';
import { withBase } from '@/lib/paths.js';

const ICONS = {
  draft_ready: CircleCheck,
  review_task: Info,
  approved: CircleCheck,
  rejected: XCircle,
  edited: Pencil,
  campaign_published: CircleCheck,
  variants_rejected: XCircle,
};

const UNREAD_POLL_MS = 25_000;

function timeAgo(isoString) {
  const diffMs = Date.now() - new Date(isoString).getTime();
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function NotificationsMenu() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  const [unread, setUnread] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const ref = useRef(null);
  const panelRef = useRef(null);
  const panelId = useId();

  useDismissable(open, () => setOpen(false), ref);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const { count } = await fetchUnreadNotificationCount();
        if (!cancelled) setUnread(count);
      } catch {
        // Transient network/auth errors just leave the last-known count.
      }
    };
    poll();
    const interval = setInterval(poll, UNREAD_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    if (!open || loaded) return;
    let cancelled = false;
    (async () => {
      try {
        const { notifications } = await fetchNotifications();
        if (!cancelled) {
          setItems(notifications);
          setLoaded(true);
        }
      } catch {
        // Leave the panel empty on failure; next open retries since loaded stays false.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, loaded]);

  const markAllRead = async () => {
    setItems((prev) => prev.map((n) => ({ ...n, read: true })));
    setUnread(0);
    try {
      await markAllNotificationsRead();
    } catch {
      // Best-effort; next poll/open will reconcile the true state.
    }
  };

  const markOneRead = async (id) => {
    const wasUnread = items.find((n) => n.id === id)?.read === false;
    setItems((prev) => prev.map((n) => (n.id === id ? { ...n, read: true } : n)));
    if (wasUnread) setUnread((prev) => Math.max(0, prev - 1));
    try {
      await markNotificationRead(id);
    } catch {
      // Best-effort; next poll/open will reconcile the true state.
    }
  };

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
            {loaded && items.length === 0 && (
              <li className="px-4 py-6 text-center text-xs text-faint">
                No notifications yet.
              </li>
            )}
            {items.map((n) => {
              const Icon = ICONS[n.type] ?? Info;
              return (
                <li key={n.id}>
                  <button
                    type="button"
                    onClick={() => markOneRead(n.id)}
                    className="flex w-full gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-2"
                  >
                    <span
                      className={cn(
                        'mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg',
                        (n.type === 'draft_ready' || n.type === 'approved' || n.type === 'campaign_published') && 'bg-success/12 text-success',
                        (n.type === 'rejected' || n.type === 'variants_rejected') && 'bg-danger/12 text-danger',
                        (n.type === 'review_task' || n.type === 'edited') && 'bg-brand-soft text-brand',
                      )}
                    >
                      <Icon size={16} aria-hidden="true" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium text-fg">
                          {n.title}
                        </span>
                        {!n.read && (
                          <span
                            className="h-1.5 w-1.5 shrink-0 rounded-full bg-brand"
                            aria-label="unread"
                          />
                        )}
                      </span>
                      {n.body && (
                        <span className="mt-0.5 block text-xs leading-snug text-muted">
                          {n.body}
                        </span>
                      )}
                      <span className="mt-1 block text-[11px] text-faint">
                        {timeAgo(n.created_at)}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>

          <div className="border-t border-border px-4 py-2.5 text-center">
            <a
              href={withBase('/campaigns')}
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
