import { useCallback, useEffect, useState } from 'react';
import { readSession, writeSession, removeSession } from '@/lib/storage.js';
import { clearStoredAuth, getCurrentAuthClaims, loginWithPassword, logoutSession } from '@/lib/api.js';

const KEY = 'obs-user';

function nameFromEmail(email = '') {
  const local = email.split('@')[0] || 'User';
  return local
    .replace(/[._-]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function initialsFromName(name = '') {
  const chars = name.trim().split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]);
  return (chars.join('') || 'U').toUpperCase();
}

function userFromAuthResponse(payload) {
  const user = payload?.user || {};
  const email = String(user.email || '');
  const name = nameFromEmail(email);
  return {
    user_id: String(user.user_id || ''),
    org_id: String(user.org_id || ''),
    brand_ids: Array.isArray(user.brand_ids) ? user.brand_ids : [],
    roles: Array.isArray(user.roles) ? user.roles : [],
    email,
    name,
    initials: initialsFromName(name),
  };
}

function userFromClaims(claims) {
  if (!claims || typeof claims !== 'object') return null;
  const email = String(claims.email || '');
  const name = nameFromEmail(email);
  return {
    user_id: String(claims.sub || ''),
    org_id: String(claims.org_id || ''),
    brand_ids: Array.isArray(claims.brand_ids) ? claims.brand_ids : [],
    roles: Array.isArray(claims.roles) ? claims.roles : [],
    email,
    name,
    initials: initialsFromName(name),
  };
}

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
    if (!raw) {
      const claimsUser = userFromClaims(getCurrentAuthClaims());
      if (claimsUser) {
        setUser(claimsUser);
        writeSession(KEY, JSON.stringify(claimsUser));
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

  const login = useCallback(async ({ email, password }) => {
    const authPayload = await loginWithPassword(email, password);
    const profile = userFromAuthResponse(authPayload);
    writeSession(KEY, JSON.stringify(profile));
    setUser(profile);
    window.dispatchEvent(new Event('obs:authchange'));
    return profile;
  }, []);

  const logout = useCallback(async () => {
    await logoutSession();
    clearStoredAuth();
    removeSession(KEY);
    setUser(null);
    window.dispatchEvent(new Event('obs:authchange'));
  }, []);

  return { user, login, logout, ready };
}
