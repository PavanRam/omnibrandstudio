import { Zap } from 'lucide-react';
import { PRIMARY_NAV, SECONDARY_NAV } from '@/lib/nav.js';
import { cn } from '@/lib/cn.js';
import { withBase } from '@/lib/paths.js';

function NavItem({ item, active, collapsed, onNavigate }) {
  const Icon = item.icon;
  return (
    <li>
      <a
        href={withBase(item.href)}
        onClick={onNavigate}
        aria-current={active ? 'page' : undefined}
        title={collapsed ? item.label : undefined}
        className={cn(
          'group relative flex items-center rounded-xl text-sm font-medium transition-colors',
          collapsed ? 'h-11 w-11 justify-center' : 'h-11 gap-3 px-3',
          active
            ? 'bg-brand-soft text-brand'
            : 'text-muted hover:bg-surface-2 hover:text-fg',
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

      {/* Credits widget */}
      <div className="px-3 pb-3">
        {collapsed ? (
          <div
            className="grid h-11 w-11 place-items-center rounded-xl bg-surface-2 text-brand"
            title="420 of 500 credits left"
          >
            <Zap size={18} aria-hidden="true" />
          </div>
        ) : (
          <div className="rounded-2xl border border-border bg-surface-2 p-3">
            <div className="flex items-center justify-between text-xs font-medium">
              <span className="flex items-center gap-1.5 text-fg">
                <Zap size={14} aria-hidden="true" className="text-brand" />
                Credits
              </span>
              <span className="text-muted">420 / 500</span>
            </div>
            <div
              className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-3"
              role="progressbar"
              aria-valuenow={420}
              aria-valuemin={0}
              aria-valuemax={500}
              aria-label="Monthly generation credits used"
            >
              <div className="h-full w-[84%] rounded-full brand-gradient" />
            </div>
            <a
              href={withBase('/gallery')}
              className="mt-2.5 block text-center text-xs font-medium text-brand hover:underline"
            >
              Upgrade plan
            </a>
          </div>
        )}
      </div>
    </div>
  );
}
