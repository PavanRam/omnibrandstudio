import { useCallback, useState } from 'react';
import { useGenerations, buildBatch } from './useGenerations.js';

/**
 * Wraps the persisted generation store with a simulated async "generate" call.
 * Swap the setTimeout for a real API request when a backend exists.
 */
export function useGenerate() {
  const store = useGenerations();
  const [generating, setGenerating] = useState(false);
  const [pending, setPending] = useState(0);
  const [latestIds, setLatestIds] = useState([]);

  const generate = useCallback(
    (prompt, settings) => {
      setGenerating(true);
      setPending(settings.count);
      const batch = buildBatch(prompt, settings);
      return new Promise((resolve) => {
        setTimeout(() => {
          store.addBatch(batch);
          setLatestIds(batch.map((b) => b.id));
          setPending(0);
          setGenerating(false);
          resolve(batch);
        }, 1500);
      });
    },
    [store],
  );

  return { ...store, generate, generating, pending, latestIds };
}
