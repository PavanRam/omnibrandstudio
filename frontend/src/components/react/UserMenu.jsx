import { useId, useRef, useState } from 'react';
import { LogOut, Settings, ShieldCheck } from 'lucide-react';
import { useAuth } from './hooks/useAuth.js';
import { useDismissable } from './hooks/useDismissable.js';
import { LoginModal } from './LoginModal.jsx';
import { Button } from './ui/Button.jsx';
import { cn } from '@/lib/cn.js';
import { withBase } from '@/lib/paths.js';

const MENU_LINKS = [
  { label: 'Admin panel', icon: ShieldCheck, href: '/admin' },
  { label: 'Settings', icon: Settings, href: '/gallery' },
];

export function UserMenu() {
  const { user, login, logout, ready } = useAuth();
  const [open, setOpen] = useState(false);
  const [loginOpen, setLoginOpen] = useState(false);
  const ref = useRef(null);
  const menuId = useId();

  const handleLogout = async () => {
    try {
      await logout();
    } finally {
      setOpen(false);
      window.location.replace(withBase('/'));
    }
  };

  useDismissable(open, () => setOpen(false), ref);

  // Avoid a flash of the wrong state before sessionStorage is read.
  if (!ready) {
    return <div className="h-10 w-24" aria-hidden="true" />;
  }

  if (!user) {
    return (
      <>
        <Button variant="primary" size="md" onClick={() => setLoginOpen(true)}>
          Log in
        </Button>
        <LoginModal
          open={loginOpen}
          onClose={() => setLoginOpen(false)}
          onLogin={login}
        />
      </>
    );
  }

  return (
    <div ref={ref} className="relative">
      <div className="flex items-center gap-2">
        <button
          type="button"
          aria-haspopup="menu"
          aria-expanded={open}
          aria-controls={menuId}
          onClick={() => setOpen((v) => !v)}
          className={cn(
            'flex items-center gap-2 rounded-xl p-1 pr-2 transition-colors hover:bg-surface-2',
            open && 'bg-surface-2',
          )}
        >
          <span className="grid h-8 w-8 place-items-center rounded-full brand-gradient text-sm font-semibold text-white">
            {user.initials}
          </span>
          <span className="hidden max-w-28 truncate text-sm font-medium text-fg sm:block">
            {user.name}
          </span>
        </button>

        <Button
          variant="outline"
          size="sm"
          className="hidden sm:inline-flex"
          onClick={handleLogout}
        >
          <LogOut size={15} aria-hidden="true" /> Log out
        </Button>
      </div>

      {open && (
        <div
          id={menuId}
          role="menu"
          aria-label="Account menu"
          className="absolute right-0 z-50 mt-2 w-60 origin-top-right rounded-2xl border border-border bg-surface p-1.5 shadow-xl card-shadow animate-fade-up"
        >
          <div className="flex items-center gap-3 rounded-xl px-2.5 py-2">
            <span className="grid h-9 w-9 place-items-center rounded-full brand-gradient text-sm font-semibold text-white">
              {user.initials}
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-fg">{user.name}</p>
              <p className="truncate text-xs text-muted">{user.email}</p>
            </div>
          </div>
          <hr className="my-1 border-border" />
          {MENU_LINKS.map(({ label, icon: Icon, href }) => (
            <a
              key={label}
              href={withBase(href)}
              role="menuitem"
              className="flex items-center gap-2.5 rounded-xl px-2.5 py-2 text-sm text-fg transition-colors hover:bg-surface-2"
            >
              <Icon size={16} aria-hidden="true" className="text-muted" />
              {label}
            </a>
          ))}
          <hr className="my-1 border-border" />
          <button
            type="button"
            role="menuitem"
            onClick={handleLogout}
            className="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-sm text-danger transition-colors hover:bg-danger/10"
          >
            <LogOut size={16} aria-hidden="true" /> Log out
          </button>
        </div>
      )}
    </div>
  );
}
