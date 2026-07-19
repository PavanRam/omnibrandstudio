import { useCallback, useEffect, useState } from 'react';
import { readJSON, writeJSON } from '@/lib/storage.js';

/**
 * useState mirrored to localStorage. Starts from `initial` on both server and
 * first client render (so hydration matches), then loads the stored value in
 * an effect. Returns [value, setValue, hydrated].
 */
export function useLocalStorageState(key, initial) {
  const [value, setValue] = useState(initial);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setValue(readJSON(key, initial));
    setHydrated(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const set = useCallback(
    (next) => {
      setValue((prev) => {
        const resolved = typeof next === 'function' ? next(prev) : next;
        writeJSON(key, resolved);
        return resolved;
      });
    },
    [key],
  );

  return [value, set, hydrated];
}
