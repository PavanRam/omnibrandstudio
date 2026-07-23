import { useState } from "react";
import { Heart } from "lucide-react";
import { PRIMARY_NAV, SECONDARY_NAV } from "@/lib/nav.js";
import { cn } from "@/lib/cn.js";
import { withBase } from "@/lib/paths.js";
import { CreditsModal } from "./CreditsModal.jsx";

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
