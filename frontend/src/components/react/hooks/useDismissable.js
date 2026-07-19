import { useEffect } from 'react';

/**
 * Close a popover/menu on outside pointer press or the Escape key.
 * Attach `ref` to the popover's outer container.
 */
export function useDismissable(open, onClose, ref) {
  useEffect(() => {
    if (!open) return undefined;

    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    const onPointer = (e) => {
      if (ref.current && !ref.current.contains(e.target)) onClose();
    };

    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointer);
    };
  }, [open, onClose, ref]);
}
