import { useCallback } from 'react';
import { useLocalStorageState } from './useLocalStorageState.js';

const KEY = 'obs-generations';
const MAX = 120;

/**
 * Persisted store of generated images. Each item is a single image record
 * (denormalised with its prompt/model) so grids stay simple. A "batch" just
 * adds several items that share a prompt + timestamp.
 */
export function useGenerations() {
  const [history, setHistory, hydrated] = useLocalStorageState(KEY, []);

  const addBatch = useCallback(
    (items) => setHistory((prev) => [...items, ...prev].slice(0, MAX)),
    [setHistory],
  );

  const toggleLike = useCallback(
    (id) =>
      setHistory((prev) =>
        prev.map((it) => (it.id === id ? { ...it, liked: !it.liked } : it)),
      ),
    [setHistory],
  );

  const remove = useCallback(
    (id) => setHistory((prev) => prev.filter((it) => it.id !== id)),
    [setHistory],
  );

  const clear = useCallback(() => setHistory([]), [setHistory]);

  return { history, addBatch, toggleLike, remove, clear, hydrated };
}

/** Build a batch of image records for a prompt + settings. */
export function buildBatch(prompt, { model, aspect, style, count }) {
  const createdAt = Date.now();
  return Array.from({ length: count }, (_, i) => {
    const seed = `${prompt}-${createdAt}-${i}`;
    return {
      id: `g-${createdAt}-${i}`,
      prompt,
      model,
      aspect,
      style,
      seed,
      createdAt,
      liked: false,
    };
  });
}
