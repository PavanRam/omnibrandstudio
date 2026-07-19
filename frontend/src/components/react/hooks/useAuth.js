import { useCallback, useEffect, useState } from 'react';
import { readSession, writeSession, removeSession } from '@/lib/storage.js';

const KEY = 'obs-user';

/**
 * Demo auth backed by sessionStorage. This is NOT real authentication — it
 * exists to drive the logged-in/out UI. Replace with a real provider + server
 * session for production.
 */
export function useAuth() {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const raw = readSession(KEY);
    if (raw) {
      try {
        setUser(JSON.parse(raw));
      } catch {
        /* ignore */
      }
    }
    setReady(true);

    const sync = () => {
      const next = readSession(KEY);
      setUser(next ? JSON.parse(next) : null);
    };
    window.addEventListener('obs:authchange', sync);
    return () => window.removeEventListener('obs:authchange', sync);
  }, []);

  const login = useCallback((profile) => {
    writeSession(KEY, JSON.stringify(profile));
    setUser(profile);
    window.dispatchEvent(new Event('obs:authchange'));
  }, []);

  const logout = useCallback(() => {
    removeSession(KEY);
    setUser(null);
    window.dispatchEvent(new Event('obs:authchange'));
  }, []);

  return { user, login, logout, ready };
}
