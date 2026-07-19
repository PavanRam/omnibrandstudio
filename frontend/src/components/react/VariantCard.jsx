import { Globe, Users } from 'lucide-react';
import { Badge } from './ui/Badge.jsx';
import { cn } from '@/lib/cn.js';

const CHANNEL_LABELS = {
  email: 'Email',
  linkedin: 'LinkedIn',
  instagram: 'Instagram',
  facebook: 'Facebook',
  twitter: 'Twitter',
  whatsapp: 'WhatsApp',
};

const STATUS_TONE = {
  approved: 'success',
  published: 'success',
  rejected: 'danger',
  evaluating: 'warning',
  generating: 'warning',
  pending: 'neutral',
};

function scoreTone(score) {
  if (score == null) return 'neutral';
  if (score >= 8.5) return 'success';
  if (score >= 6) return 'warning';
  return 'danger';
}

/** A single generated content variant returned by GET /campaigns/{id}. */
export function VariantCard({ variant }) {
  const channel = CHANNEL_LABELS[variant.channel] || variant.channel;
  const score = variant.composite_score;

  return (
    <article className="flex flex-col rounded-2xl border border-border bg-surface p-4 card-shadow">
      <header className="mb-3 flex flex-wrap items-center gap-2">
        <Badge tone="brand">{channel}</Badge>
        <Badge>
          <Globe size={11} aria-hidden="true" /> {variant.locale}
        </Badge>
        <Badge>
          <Users size={11} aria-hidden="true" /> {variant.segment}
        </Badge>
        <div className="ml-auto flex items-center gap-2">
          {score != null && (
            <Badge tone={scoreTone(score)}>{Number(score).toFixed(1)}/10</Badge>
          )}
          {variant.status && (
            <Badge tone={STATUS_TONE[variant.status] || 'neutral'}>{variant.status}</Badge>
          )}
        </div>
      </header>

      {variant.final_content ? (
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-fg">
          {variant.final_content}
        </p>
      ) : (
        <p className={cn('text-sm italic text-faint')}>
          No content produced for this variant yet.
        </p>
      )}
    </article>
  );
}
