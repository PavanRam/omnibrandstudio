import { useState } from 'react';
import { Heart, Download, Copy, Check, Trash2, Wand2, Calendar } from 'lucide-react';
import { Modal } from './ui/Modal.jsx';
import { Button } from './ui/Button.jsx';
import { Badge } from './ui/Badge.jsx';
import { artDataUrl } from '@/lib/art.js';
import { GenerativeArt } from './GenerativeArt.jsx';
import { aspectStyle } from './ImageCard.jsx';

function formatDate(ts) {
  if (!ts) return 'Just now';
  try {
    return new Date(ts).toLocaleString(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    });
  } catch {
    return 'Recently';
  }
}

export function ImageDetailModal({ item, open, onClose, onLike, onRemove, onUsePrompt }) {
  const [copied, setCopied] = useState(false);
  if (!item) return null;

  const seed = item.seed ?? item.id;
  const downloadUrl = artDataUrl(seed, { w: 1600, h: 1600 });

  const copyPrompt = async () => {
    try {
      await navigator.clipboard.writeText(item.prompt);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <Modal open={open} onClose={onClose} size="xl" title="Creation details">
      <div className="grid gap-6 md:grid-cols-[1.4fr_1fr]">
        <div
          className="overflow-hidden rounded-2xl border border-border bg-surface-2"
          style={aspectStyle(item.aspect)}
          role="img"
          aria-label={item.prompt}
        >
          <GenerativeArt seed={seed} className="h-full w-full" />
        </div>

        <div className="flex flex-col">
          <div className="flex flex-wrap gap-2">
            <Badge tone="brand">{item.model}</Badge>
            <Badge>{item.aspect}</Badge>
            {item.style && item.style !== 'None' && <Badge>{item.style}</Badge>}
          </div>

          <h3 className="mt-4 text-sm font-semibold text-fg">Prompt</h3>
          <p className="mt-1.5 rounded-xl bg-surface-2 p-3 text-sm leading-relaxed text-muted">
            {item.prompt}
          </p>

          <p className="mt-3 flex items-center gap-1.5 text-xs text-faint">
            <Calendar size={13} aria-hidden="true" />
            {formatDate(item.createdAt)}
          </p>

          <div className="mt-auto grid grid-cols-2 gap-2 pt-6">
            <Button variant="secondary" onClick={copyPrompt}>
              {copied ? (
                <>
                  <Check size={16} aria-hidden="true" /> Copied
                </>
              ) : (
                <>
                  <Copy size={16} aria-hidden="true" /> Copy prompt
                </>
              )}
            </Button>
            {onLike && (
              <Button
                variant="secondary"
                onClick={() => onLike(item.id)}
                aria-pressed={item.liked}
              >
                <Heart
                  size={16}
                  aria-hidden="true"
                  className={item.liked ? 'fill-current text-rose-500' : ''}
                />
                {item.liked ? 'Liked' : 'Like'}
              </Button>
            )}
            <Button as="a" href={downloadUrl} download={`omnibrand-${item.id}.svg`} variant="secondary">
              <Download size={16} aria-hidden="true" /> Download
            </Button>
            {onUsePrompt && (
              <Button
                variant="primary"
                onClick={() => {
                  onUsePrompt(item.prompt);
                  onClose();
                }}
              >
                <Wand2 size={16} aria-hidden="true" /> Use prompt
              </Button>
            )}
            {onRemove && (
              <Button
                variant="danger"
                className="col-span-2"
                onClick={() => {
                  onRemove(item.id);
                  onClose();
                }}
              >
                <Trash2 size={16} aria-hidden="true" /> Delete creation
              </Button>
            )}
          </div>
        </div>
      </div>
    </Modal>
  );
}
