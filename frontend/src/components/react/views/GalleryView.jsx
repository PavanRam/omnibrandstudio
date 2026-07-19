import { useMemo, useState } from 'react';
import { LayoutGrid, Search, Heart, Trash2, Sparkles } from 'lucide-react';
import { Page } from '../Page.jsx';
import { ResultsGrid } from '../ResultsGrid.jsx';
import { EmptyState } from '../EmptyState.jsx';
import { Button } from '../ui/Button.jsx';
import { useGenerations } from '../hooks/useGenerations.js';
import { cn } from '@/lib/cn.js';

const TABS = [
  { id: 'all', label: 'All' },
  { id: 'liked', label: 'Favourites' },
];

export function GalleryView() {
  const { history, toggleLike, remove, clear, hydrated } = useGenerations();
  const [tab, setTab] = useState('all');
  const [query, setQuery] = useState('');

  const items = useMemo(() => {
    const q = query.trim().toLowerCase();
    return history.filter((it) => {
      if (tab === 'liked' && !it.liked) return false;
      if (q && !it.prompt.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [history, tab, query]);

  const likedCount = history.filter((h) => h.liked).length;

  return (
    <Page
      wide
      eyebrow="Workspace"
      title="My Gallery"
      description="Every image you generate is saved here on this device. Search, favourite, and manage your creations."
      actions={
        history.length > 0 ? (
          <Button variant="ghost" size="sm" onClick={clear}>
            <Trash2 size={15} aria-hidden="true" /> Clear all
          </Button>
        ) : null
      }
    >
      {/* Toolbar */}
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div
          className="inline-flex rounded-xl border border-border bg-surface-2 p-0.5"
          role="tablist"
          aria-label="Filter creations"
        >
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors',
                tab === t.id ? 'bg-surface text-fg shadow-sm' : 'text-muted hover:text-fg',
              )}
            >
              {t.id === 'liked' && <Heart size={14} aria-hidden="true" />}
              {t.label}
              <span className="text-xs text-faint">
                {t.id === 'liked' ? likedCount : history.length}
              </span>
            </button>
          ))}
        </div>

        <div className="relative sm:w-72">
          <label htmlFor="gallery-search" className="sr-only">
            Search your creations
          </label>
          <Search
            size={16}
            aria-hidden="true"
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint"
          />
          <input
            id="gallery-search"
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by prompt…"
            className="h-10 w-full rounded-xl border border-border bg-surface-2 pl-9 pr-3 text-sm text-fg transition-colors focus:border-brand focus:bg-surface"
          />
        </div>
      </div>

      {items.length > 0 ? (
        <ResultsGrid items={items} onLike={toggleLike} onRemove={remove} />
      ) : (
        hydrated && (
          <EmptyState
            icon={tab === 'liked' ? Heart : LayoutGrid}
            title={
              query
                ? 'No matches'
                : tab === 'liked'
                  ? 'No favourites yet'
                  : 'Your gallery is empty'
            }
            description={
              query
                ? 'Try a different search term.'
                : tab === 'liked'
                  ? 'Tap the heart on any creation to save it here.'
                  : 'Generate some images and they’ll show up here automatically.'
            }
            action={
              <Button href="/text-to-image" variant="primary">
                <Sparkles size={16} aria-hidden="true" /> Start creating
              </Button>
            }
          />
        )
      )}
    </Page>
  );
}
