import { ArrowUpRight } from 'lucide-react';
import { Page } from '../Page.jsx';
import { Badge } from '../ui/Badge.jsx';
import { TOOLS } from '@/data/tools.js';
import { cn } from '@/lib/cn.js';
import { withBase } from '@/lib/paths.js';

const STATUS = {
  ready: { tone: 'success', label: 'Ready' },
  beta: { tone: 'brand', label: 'Beta' },
  soon: { tone: 'neutral', label: 'Coming soon' },
};

export function ToolsView() {
  return (
    <Page
      eyebrow="Explore"
      title="AI Tools"
      description="A complete creative toolkit. Generate, edit, and transform your visuals — all in one place."
      wide
    >
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {TOOLS.map((tool) => {
          const Icon = tool.icon;
          const status = STATUS[tool.status];
          const disabled = tool.status === 'soon';
          return (
            <a
              key={tool.id}
              href={disabled ? undefined : withBase(tool.href)}
              aria-disabled={disabled}
              onClick={(e) => disabled && e.preventDefault()}
              className={cn(
                'group relative flex flex-col overflow-hidden rounded-3xl border border-border bg-surface p-5',
                'transition-all duration-200 card-shadow',
                disabled
                  ? 'cursor-default opacity-70'
                  : 'hover:-translate-y-0.5 hover:border-border-strong',
              )}
            >
              <div className="flex items-start justify-between">
                <span
                  className={cn(
                    'grid h-12 w-12 place-items-center rounded-2xl bg-gradient-to-br text-white shadow-sm',
                    tool.accent,
                  )}
                >
                  <Icon size={22} aria-hidden="true" />
                </span>
                <Badge tone={status.tone}>{status.label}</Badge>
              </div>

              <h2 className="mt-4 flex items-center gap-1 text-base font-semibold text-fg">
                {tool.name}
                {!disabled && (
                  <ArrowUpRight
                    size={16}
                    aria-hidden="true"
                    className="text-faint transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-brand"
                  />
                )}
              </h2>
              <p className="mt-1 text-sm text-muted">{tool.desc}</p>
            </a>
          );
        })}
      </div>
    </Page>
  );
}
