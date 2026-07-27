import { useState, useEffect } from "react";
import { Heart, Archive } from "lucide-react";
import { PRIMARY_NAV, SECONDARY_NAV } from "@/lib/nav.js";
import { cn } from "@/lib/cn.js";
import { withBase } from "@/lib/paths.js";
import { CreditsModal } from "./CreditsModal.jsx";
import { fetchRecentConversations, archiveConversation } from "@/lib/api.js";

const STATUS_DOT_CLASS = {
  success: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-danger',
  brand: 'bg-brand',
  neutral: 'bg-muted',
};

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

function ConversationsSection({ collapsed, currentRoute }) {
  const [conversations, setConversations] = useState([]);
  const [activeId, setActiveId] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let active = true;
    async function load() {
      setLoading(true);
      try {
        const payload = await fetchRecentConversations();
        if (active) {
          setConversations(payload.conversations || []);
        }
      } catch (err) {
        console.error('Failed to load recent conversations in sidebar:', err);
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }
    load();

    const handleChanged = (e) => {
      if (active) {
        setConversations(e.detail.recentConversations || []);
        setActiveId(e.detail.conversationId || '');
      }
    };
    window.addEventListener('obs:conversations-changed', handleChanged);

    const handleArchiveEvent = async () => {
      try {
        const payload = await fetchRecentConversations();
        if (active) {
          setConversations(payload.conversations || []);
        }
      } catch {}
    };
    window.addEventListener('obs:archive-conversation', handleArchiveEvent);

    return () => {
      active = false;
      window.removeEventListener('obs:conversations-changed', handleChanged);
      window.removeEventListener('obs:archive-conversation', handleArchiveEvent);
    };
  }, []);

  const handleSelect = (session) => {
    const id = session.conversation_id;
    setActiveId(id);
    if (currentRoute === 'studio') {
      window.dispatchEvent(new CustomEvent('obs:select-conversation', { detail: session }));
    } else {
      window.location.href = withBase(`/studio?conversation_id=${id}`);
    }
  };

  const handleArchive = async (e, id) => {
    e.stopPropagation();
    e.preventDefault();
    try {
      await archiveConversation(id);
      window.dispatchEvent(new CustomEvent('obs:archive-conversation', { detail: id }));
      const payload = await fetchRecentConversations();
      setConversations(payload.conversations || []);
      if (activeId === id) {
        setActiveId('');
      }
    } catch (err) {
      console.error('Failed to archive conversation from sidebar:', err);
    }
  };

  if (conversations.length === 0 && loading) {
    return null;
  }

  return (
    <div className="flex flex-col min-h-0">
      <style>{`
        @keyframes marquee-scroll {
          0% { transform: translate3d(0, 0, 0); }
          100% { transform: translate3d(-50%, 0, 0); }
        }
        .marquee-container:hover .marquee-inner {
          animation: marquee-scroll 10s linear infinite;
        }
      `}</style>

      {!collapsed && (
        <h2 className="px-3 pb-1.5 pt-4 text-[11px] font-semibold uppercase tracking-wider text-faint shrink-0">
          Recent Conversations
        </h2>
      )}

      <div className={cn("overflow-y-auto pr-1 shrink min-h-0", collapsed ? "" : "max-h-[240px] lg:max-h-[calc(100vh-26rem)]")}>
        <ul className="space-y-0.5">
          {conversations.map((session) => {
            const title = conversationTitle(session);
            const statusInfo = conversationStatusInfo(session);
            const dotClass = STATUS_DOT_CLASS[statusInfo.tone] || 'bg-muted';
            const isActive = session.conversation_id === activeId;
            const isLong = title.length > 26;

            return (
              <li key={session.conversation_id}>
                <a
                  href={withBase(`/studio?conversation_id=${session.conversation_id}`)}
                  onClick={(e) => {
                    e.preventDefault();
                    handleSelect(session);
                  }}
                  className={cn(
                    "group relative flex items-center justify-between rounded-xl transition-all w-full h-9 px-3",
                    collapsed ? "justify-center" : "",
                    isActive
                      ? "bg-brand-soft text-brand font-semibold"
                      : "text-muted hover:bg-surface-2 hover:text-fg"
                  )}
                >
                  {/* Active Indicator Bar */}
                  {isActive && !collapsed && (
                    <span
                      className="absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full brand-gradient"
                      aria-hidden="true"
                    />
                  )}

                  {/* Collapsed Tooltip only */}
                  {collapsed && (
                    <div className="pointer-events-none invisible absolute left-full top-1/2 -translate-y-1/2 z-30 ml-2.5 w-max max-w-[280px] rounded-md border border-border bg-surface px-2.5 py-1.5 text-[11px] font-medium text-fg opacity-0 shadow-md transition-opacity group-hover:visible group-hover:opacity-100 whitespace-normal break-words">
                      <div className="font-semibold text-fg mb-0.5">{title}</div>
                      <div className="text-muted text-[10px]">{statusInfo.label}</div>
                    </div>
                  )}

                  <div className="flex items-center min-w-0 flex-1">
                    <span className={cn("h-2 w-2 rounded-full shrink-0 relative group-hover:scale-110 transition-transform", dotClass)} />
                    
                    {!collapsed && (
                      <div className={cn("flex-1 min-w-0 overflow-hidden ml-3 relative", isLong ? "marquee-container" : "")}>
                        <div className={cn("flex marquee-inner text-sm font-medium text-muted group-hover:text-fg transition-colors", isLong ? "w-max" : "truncate")}>
                          {isLong ? (
                            <>
                              <span className="pr-6 shrink-0">{title}</span>
                              <span className="hidden group-hover:inline pr-6 shrink-0">{title}</span>
                            </>
                          ) : (
                            title
                          )}
                        </div>
                      </div>
                    )}
                  </div>

                  {!collapsed && (
                    <button
                      type="button"
                      onClick={(e) => handleArchive(e, session.conversation_id)}
                      className="invisible group-hover:visible ml-2 p-1 text-faint hover:text-danger rounded-md hover:bg-surface-3 transition-colors shrink-0"
                      title="Archive conversation"
                    >
                      <Archive size={12} />
                    </button>
                  )}
                </a>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

function NavItem({ item, active, collapsed, onNavigate }) {
  const Icon = item.icon;
  return (
    <li>
      <a
        href={withBase(item.href)}
        onClick={onNavigate}
        aria-current={active ? "page" : undefined}
        title={collapsed ? item.label : undefined}
        className={cn(
          "group relative flex items-center rounded-xl text-sm font-medium transition-colors",
          collapsed ? "h-11 w-11 justify-center" : "h-11 gap-3 px-3",
          active
            ? "bg-brand-soft text-brand"
            : "text-muted hover:bg-surface-2 hover:text-fg",
        )}
      >
        {active && (
          <span
            className="absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full brand-gradient"
            aria-hidden="true"
          />
        )}
        <Icon size={19} aria-hidden="true" className="shrink-0" />
        {!collapsed && <span className="truncate">{item.label}</span>}
      </a>
    </li>
  );
}

function Section({ title, items, currentRoute, collapsed, onNavigate }) {
  return (
    <div>
      {!collapsed && (
        <h2 className="px-3 pb-1.5 pt-4 text-[11px] font-semibold uppercase tracking-wider text-faint">
          {title}
        </h2>
      )}
      {collapsed && <div className="my-2 h-px bg-border" role="separator" />}
      <ul className="space-y-1">
        {items.map((item) => (
          <NavItem
            key={item.key}
            item={item}
            active={currentRoute === item.key}
            collapsed={collapsed}
            onNavigate={onNavigate}
          />
        ))}
      </ul>
    </div>
  );
}

/** Inner sidebar content, shared by the desktop rail and the mobile drawer. */
export function SidebarNav({ currentRoute, collapsed = false, onNavigate }) {
  const [creditsOpen, setCreditsOpen] = useState(false);

  return (
    <div className="flex h-full flex-col">
      <nav aria-label="Primary" className="flex-1 overflow-y-auto px-3 pb-4">
        <Section
          title="Create"
          items={PRIMARY_NAV}
          currentRoute={currentRoute}
          collapsed={collapsed}
          onNavigate={onNavigate}
        />
        <Section
          title="Manage"
          items={SECONDARY_NAV}
          currentRoute={currentRoute}
          collapsed={collapsed}
          onNavigate={onNavigate}
        />
        {/* Divider after Admin Panel */}
        <div className="my-4 h-px bg-border/60" role="separator" />
        <div className="mt-4">
          <ConversationsSection
            collapsed={collapsed}
            currentRoute={currentRoute}
          />
        </div>
      </nav>

      {/* Made with love — opens the team credits dialog */}
      <div className="px-3 pb-3">
        {collapsed ? (
          <button
            type="button"
            onClick={() => setCreditsOpen(true)}
            title="Made with ♥ by Adobe Team"
            aria-label="Made with love by Adobe Team — view credits"
            className="grid h-11 w-11 place-items-center rounded-xl bg-surface-2 text-brand transition-colors hover:bg-brand-soft"
          >
            <Heart size={18} aria-hidden="true" fill="currentColor" />
          </button>
        ) : (
          <button
            type="button"
            onClick={() => setCreditsOpen(true)}
            className="group cursor-pointer flex w-full items-center justify-center gap-1.5 rounded-2xl border border-border bg-surface-2 px-3 py-2.5 text-xs font-medium text-muted transition-colors hover:border-border-strong hover:text-fg"
          >
            Made with
            <Heart
              size={13}
              aria-hidden="true"
              fill="currentColor"
              className="text-brand transition-transform group-hover:scale-125"
            />
            by <span className="font-semibold text-fg">Adobe Team</span>
          </button>
        )}
      </div>

      <CreditsModal open={creditsOpen} onClose={() => setCreditsOpen(false)} />
    </div>
  );
}
