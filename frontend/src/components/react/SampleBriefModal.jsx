import { useState } from 'react';
import { Copy, Check } from 'lucide-react';
import { Modal } from './ui/Modal.jsx';

const SAMPLE_BRIEF = `Objective: Drive enterprise adoption and increase qualified leads

Key Messages:
• Industry-leading performance and ROI
• Cost savings and operational efficiency
• Security-first approach and compliance
• Easy integration with existing systems

Channels: LinkedIn, Email, Landing Page

Segments: Enterprise IT leaders, Security buyers, C-suite executives

Locales: en-US, es-ES, fr-FR

Call-to-Action: Schedule a personalized demo or request a trial

Target Metrics: Increase qualified demo requests by 25%, improve email open rates to 35%+`;

/**
 * Sample brief modal — shows a generic template that users can copy
 * and paste into the conversation to quickly start building a campaign brief.
 * Displayed in empty state when no conversation exists.
 */
export function SampleBriefModal({ open, onClose }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(SAMPLE_BRIEF);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Sample Brief" description="Template to get started" size="md">
      <div className="space-y-4">
        <div className="rounded-xl border border-border bg-surface-2 p-4">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-faint">
            Example brief template
          </p>
          <pre className="whitespace-pre-wrap rounded-lg border border-border bg-surface px-3 py-2.5 text-xs leading-relaxed text-fg font-mono overflow-auto max-h-64">
            {SAMPLE_BRIEF}
          </pre>
        </div>

        <div className="flex gap-2">
          <button
            type="button"
            onClick={handleCopy}
            className="inline-flex items-center gap-1.5 rounded-lg border border-brand/40 bg-brand-soft/40 px-3 py-2 text-xs font-medium text-brand transition-colors hover:border-brand hover:bg-brand-soft/60 active:bg-brand-soft"
          >
            {copied ? (
              <>
                <Check size={14} aria-hidden="true" />
                Copied!
              </>
            ) : (
              <>
                <Copy size={14} aria-hidden="true" />
                Copy to clipboard
              </>
            )}
          </button>
        </div>

        <p className="text-xs text-muted">
          Paste this into the chat and tailor it to your specific campaign. Our assistant will help you refine and organize all the details.
        </p>
      </div>
    </Modal>
  );
}
