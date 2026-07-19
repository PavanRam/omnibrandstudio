import { useEffect, useRef, useState } from 'react';
import { PanelLeftClose, PanelLeftOpen, X } from 'lucide-react';
import { Logo } from './Logo.jsx';
import { SidebarNav } from './SidebarNav.jsx';
import { TopNav } from './TopNav.jsx';
import { SkipLink } from './SkipLink.jsx';
import { IconButton } from './ui/IconButton.jsx';
import { useLocalStorageState } from './hooks/useLocalStorageState.js';
import { useMediaQuery } from './hooks/useMediaQuery.js';
import { useDismissable } from './hooks/useDismissable.js';
import { cn } from '@/lib/cn.js';

/**
 * Application shell: persistent desktop rail (collapsible), off-canvas mobile
 * drawer, sticky top bar, and the main content region. `currentRoute` drives
 * the active nav state; `title` is the desktop page heading.
 */
export function AppShell({ currentRoute, title, children }) {
  const [collapsed, setCollapsed] = useLocalStorageState('obs-sidebar-collapsed', false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const isDesktop = useMediaQuery('(min-width: 1024px)');
  const drawerRef = useRef(null);

  // The drawer is a mobile-only concern — never leave it "open" on desktop.
  useEffect(() => {
    if (isDesktop && drawerOpen) setDrawerOpen(false);
  }, [isDesktop, drawerOpen, setDrawerOpen]);

  useDismissable(drawerOpen, () => setDrawerOpen(false), drawerRef);

  useEffect(() => {
    if (!drawerOpen) return undefined;
    const { overflow } = document.body.style;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = overflow;
    };
  }, [drawerOpen]);

  return (
    <div className="flex min-h-dvh bg-bg text-fg">
      <SkipLink />

      {/* Desktop rail */}
      <aside
        aria-label="Sidebar"
        className={cn(
          'sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-border bg-surface',
          'transition-[width] duration-200 ease-out lg:flex',
          collapsed ? 'w-[4.75rem]' : 'w-64',
        )}
      >
        <div
          className={cn(
            'flex h-16 items-center border-b border-border',
            collapsed ? 'justify-center px-2' : 'justify-between px-4',
          )}
        >
          {!collapsed && <Logo />}
          <IconButton
            label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            onClick={() => setCollapsed((v) => !v)}
          >
            {collapsed ? (
              <PanelLeftOpen size={18} aria-hidden="true" />
            ) : (
              <PanelLeftClose size={18} aria-hidden="true" />
            )}
          </IconButton>
        </div>
        <div className="flex-1 overflow-hidden">
          <SidebarNav currentRoute={currentRoute} collapsed={collapsed} />
        </div>
      </aside>

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col">
        <TopNav title={title} onOpenDrawer={() => setDrawerOpen(true)} />
        <main id="main-content" tabIndex={-1} className="flex-1 outline-none">
          {children}
        </main>
      </div>

      {/* Mobile drawer */}
      {drawerOpen && (
        <div className="fixed inset-0 z-[90] lg:hidden">
          <div
            className="absolute inset-0 bg-black/50 backdrop-blur-sm animate-fade-up"
            aria-hidden="true"
          />
          <div
            ref={drawerRef}
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            className="absolute left-0 top-0 flex h-full w-[17rem] flex-col border-r border-border bg-surface shadow-2xl animate-fade-up"
          >
            <div className="flex h-16 items-center justify-between border-b border-border px-4">
              <Logo />
              <IconButton label="Close navigation menu" onClick={() => setDrawerOpen(false)}>
                <X size={20} aria-hidden="true" />
              </IconButton>
            </div>
            <div className="flex-1 overflow-hidden">
              <SidebarNav
                currentRoute={currentRoute}
                onNavigate={() => setDrawerOpen(false)}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
