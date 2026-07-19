import { useId } from 'react';
import { Menu, Search, Sparkles } from 'lucide-react';
import { Logo } from './Logo.jsx';
import { ThemeToggle } from './ThemeToggle.jsx';
import { NotificationsMenu } from './NotificationsMenu.jsx';
import { UserMenu } from './UserMenu.jsx';
import { Button } from './ui/Button.jsx';
import { IconButton } from './ui/IconButton.jsx';

export function TopNav({ onOpenDrawer, title }) {
  const searchId = useId();

  return (
    <header
      className="sticky top-0 z-40 flex h-16 items-center gap-2 border-b border-border bg-bg/80 px-3 backdrop-blur-md sm:px-5"
    >
      {/* Left: mobile menu + logo */}
      <div className="flex items-center gap-2 lg:hidden">
        <IconButton label="Open navigation menu" onClick={onOpenDrawer}>
          <Menu size={20} aria-hidden="true" />
        </IconButton>
        <Logo compact />
      </div>

      {/* Page title (desktop) */}
      {title && (
        <h1 className="hidden text-base font-semibold text-fg lg:block">
          {title}
        </h1>
      )}

      {/* Right side: search + actions grouped together */}
      <div className="ml-auto flex items-center gap-1.5">
        {/* Search */}
        <form
          role="search"
          className="hidden md:block"
          onSubmit={(e) => e.preventDefault()}
        >
          <label htmlFor={searchId} className="sr-only">
            Search your creations and the community
          </label>
          <div className="relative">
            <Search
              size={16}
              aria-hidden="true"
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint"
            />
            <input
              id={searchId}
              type="search"
              placeholder="Search creations, styles, community…"
              className="h-10 w-56 rounded-xl border border-border bg-surface-2 pl-9 pr-3 text-sm text-fg transition-colors focus:border-brand focus:bg-surface lg:w-72"
            />
          </div>
        </form>

        <Button
          href="/text-to-image"
          variant="primary"
          size="sm"
          className="hidden sm:inline-flex"
        >
          <Sparkles size={15} aria-hidden="true" />
          Create
        </Button>
        <ThemeToggle />
        <NotificationsMenu />
        <div className="mx-0.5 hidden h-6 w-px bg-border sm:block" aria-hidden="true" />
        <UserMenu />
      </div>
    </header>
  );
}
