import { useState } from 'react';
import {
  TrendingUp,
  TrendingDown,
  LockKeyhole,
  ShieldCheck,
  Check,
  X,
  Users,
} from 'lucide-react';
import { Page, SectionHeading } from '../Page.jsx';
import { Badge } from '../ui/Badge.jsx';
import { Button } from '../ui/Button.jsx';
import {
  ADMIN_STATS,
  USAGE_SERIES,
  ADMIN_USERS,
  MODERATION_QUEUE,
} from '@/data/adminData.js';
import { cn } from '@/lib/cn.js';

function StatCard({ stat }) {
  const up = stat.trend === 'up';
  const Trend = up ? TrendingUp : TrendingDown;
  return (
    <div className="rounded-2xl border border-border bg-surface p-4 card-shadow">
      <p className="text-sm text-muted">{stat.label}</p>
      <div className="mt-2 flex items-end justify-between gap-2">
        <span className="text-2xl font-semibold tracking-tight text-fg">
          {stat.value}
        </span>
        <span
          className={cn(
            'inline-flex items-center gap-1 text-xs font-medium',
            up ? 'text-success' : 'text-danger',
          )}
        >
          <Trend size={14} aria-hidden="true" />
          {stat.delta}
        </span>
      </div>
    </div>
  );
}

function UsageChart({ data }) {
  const max = Math.max(...data);
  const bw = 100 / data.length;
  return (
    <svg
      viewBox="0 0 100 40"
      preserveAspectRatio="none"
      role="img"
      aria-label="Daily generations over the last 14 days, trending upward"
      className="h-28 w-full"
    >
      {data.map((v, i) => {
        const h = (v / max) * 36;
        return (
          <rect
            key={i}
            x={i * bw + 0.6}
            y={40 - h}
            width={bw - 1.2}
            height={h}
            rx="0.8"
            className="fill-brand"
            opacity={0.35 + (i / data.length) * 0.65}
          />
        );
      })}
    </svg>
  );
}

function Switch({ label, defaultOn = false }) {
  const [on, setOn] = useState(defaultOn);
  return (
    <div className="flex items-center justify-between gap-4 py-2.5">
      <span className="text-sm text-fg">{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label={label}
        onClick={() => setOn((v) => !v)}
        className={cn(
          'relative h-6 w-11 shrink-0 rounded-full transition-colors',
          on ? 'bg-brand' : 'bg-surface-3',
        )}
      >
        <span
          className={cn(
            'absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform',
            on ? 'translate-x-[22px]' : 'translate-x-0.5',
          )}
        />
      </button>
    </div>
  );
}

const PLAN_TONE = { Pro: 'brand', Team: 'success', Free: 'neutral' };
const USER_STATUS = {
  active: { tone: 'success', label: 'Active' },
  suspended: { tone: 'danger', label: 'Suspended' },
  invited: { tone: 'warning', label: 'Invited' },
};
const SEVERITY = { high: 'danger', medium: 'warning', low: 'neutral' };

export function AdminView({ onLock }) {
  const [queue, setQueue] = useState(MODERATION_QUEUE);
  const resolve = (id) => setQueue((prev) => prev.filter((q) => q.id !== id));

  return (
    <Page
      wide
      eyebrow="Restricted"
      title="Admin Panel"
      description="Operations dashboard — usage, users, and content moderation."
      actions={
        <>
          <Badge tone="brand">
            <ShieldCheck size={12} aria-hidden="true" /> Signed in as admin
          </Badge>
          <Button variant="outline" size="sm" onClick={onLock}>
            <LockKeyhole size={15} aria-hidden="true" /> Lock
          </Button>
        </>
      }
    >
      {/* Stats */}
      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        {ADMIN_STATS.map((s) => (
          <StatCard key={s.id} stat={s} />
        ))}
      </div>

      {/* Chart + settings */}
      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <div className="rounded-2xl border border-border bg-surface p-5 card-shadow lg:col-span-2">
          <SectionHeading
            title="Generation volume"
            description="Last 14 days"
          />
          <UsageChart data={USAGE_SERIES} />
        </div>
        <div className="rounded-2xl border border-border bg-surface p-5 card-shadow">
          <h2 className="text-lg font-semibold text-fg">Platform settings</h2>
          <div className="mt-2 divide-y divide-border">
            <Switch label="Public community feed" defaultOn />
            <Switch label="NSFW content filter" defaultOn />
            <Switch label="Allow new sign-ups" defaultOn />
            <Switch label="Maintenance mode" />
          </div>
        </div>
      </div>

      {/* Users */}
      <section className="mt-6">
        <SectionHeading
          title="Users"
          description={`${ADMIN_USERS.length} accounts`}
          action={
            <Button variant="secondary" size="sm">
              <Users size={15} aria-hidden="true" /> Invite user
            </Button>
          }
        />
        <div className="overflow-x-auto rounded-2xl border border-border bg-surface card-shadow">
          <table className="w-full min-w-[38rem] text-left text-sm">
            <caption className="sr-only">List of platform users</caption>
            <thead>
              <tr className="border-b border-border text-xs uppercase tracking-wider text-faint">
                <th scope="col" className="px-4 py-3 font-semibold">User</th>
                <th scope="col" className="px-4 py-3 font-semibold">Plan</th>
                <th scope="col" className="px-4 py-3 font-semibold">Generations</th>
                <th scope="col" className="px-4 py-3 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody>
              {ADMIN_USERS.map((u) => {
                const st = USER_STATUS[u.status];
                return (
                  <tr key={u.id} className="border-b border-border last:border-0 hover:bg-surface-2">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <span className="grid h-8 w-8 place-items-center rounded-full brand-gradient text-xs font-semibold text-white">
                          {u.name.split(' ').map((p) => p[0]).join('')}
                        </span>
                        <div>
                          <p className="font-medium text-fg">{u.name}</p>
                          <p className="text-xs text-muted">{u.email}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <Badge tone={PLAN_TONE[u.plan]}>{u.plan}</Badge>
                    </td>
                    <td className="px-4 py-3 tabular-nums text-muted">
                      {u.gens.toLocaleString()}
                    </td>
                    <td className="px-4 py-3">
                      <Badge tone={st.tone}>{st.label}</Badge>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* Moderation */}
      <section className="mt-6">
        <SectionHeading
          title="Moderation queue"
          description={`${queue.length} items awaiting review`}
        />
        {queue.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-border-strong bg-surface/50 px-6 py-10 text-center text-sm text-muted">
            🎉 The moderation queue is clear.
          </div>
        ) : (
          <ul className="space-y-3">
            {queue.map((m) => (
              <li
                key={m.id}
                className="flex flex-col gap-3 rounded-2xl border border-border bg-surface p-4 card-shadow sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={SEVERITY[m.severity]}>{m.severity}</Badge>
                    <span className="text-xs text-muted">{m.reason}</span>
                    <span className="text-xs text-faint">· by {m.reporter}</span>
                  </div>
                  <p className="mt-1.5 truncate text-sm text-fg">“{m.prompt}”</p>
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button variant="secondary" size="sm" onClick={() => resolve(m.id)}>
                    <Check size={15} aria-hidden="true" /> Approve
                  </Button>
                  <Button variant="danger" size="sm" onClick={() => resolve(m.id)}>
                    <X size={15} aria-hidden="true" /> Reject
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </Page>
  );
}
