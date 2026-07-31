import { useState } from 'react';
import { Button } from './ui/Button.jsx';
import { Badge } from './ui/Badge.jsx';

// Approve/Reject only — reviewers make a call on content as generated, they
// don't rewrite it. Keeping the decision binary is deliberate: an "edit"
// path would let a reviewer silently change what the creator is judged
// against, which defeats the point of a separate review step.
export function ReviewCard({ review, onDecide, busy }) {
  const score = typeof review.composite_score === 'number' ? review.composite_score.toFixed(2) : 'n/a';
  // The backend requires a non-empty reviewer_note on rejection, so collect a
  // reason inline before firing the decision instead of failing with a 422.
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState('');

  const submitReject = () => {
    const trimmed = note.trim();
    if (!trimmed) return;
    onDecide(review.review_request_id, 'rejected', { reviewerNote: trimmed });
  };

  return (
    <div className="rounded-xl border border-warning/40 bg-warning/5 p-3 text-sm">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <Badge tone="warning">Needs review</Badge>
        <span className="text-xs text-muted">{review.task_id}</span>
        <span className="text-xs text-faint">score {score}</span>
      </div>
      {review.routing_reason ? (
        <p className="mb-2 text-xs text-muted">{review.routing_reason}</p>
      ) : null}
      <p className="mb-2 whitespace-pre-wrap rounded-lg border border-border bg-surface px-2 py-2 text-xs text-fg">
        {review.content || '(no content captured)'}
      </p>
      {rejecting ? (
        <div className="space-y-2">
          <textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Why are you rejecting this? (required)"
            rows={2}
            autoFocus
            disabled={busy}
            className="w-full rounded-lg border border-border bg-surface px-2 py-1.5 text-xs text-fg placeholder:text-faint focus:border-border-strong focus:outline-none"
          />
          <div className="flex flex-wrap gap-2">
            <Button
              variant="danger"
              size="sm"
              disabled={busy || !note.trim()}
              onClick={submitReject}
            >
              Confirm rejection
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => {
                setRejecting(false);
                setNote('');
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button
            variant="primary"
            size="sm"
            disabled={busy}
            onClick={() => onDecide(review.review_request_id, 'approved')}
          >
            Approve
          </Button>
          <Button
            variant="danger"
            size="sm"
            disabled={busy}
            onClick={() => setRejecting(true)}
          >
            Reject
          </Button>
        </div>
      )}
    </div>
  );
}
