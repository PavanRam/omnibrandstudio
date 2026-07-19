/**
 * Small, SSR-safe wrappers around Web Storage.
 * All reads/writes are guarded so components can call them during render
 * without crashing on the server (where `window` is undefined).
 */

const canUse = () => typeof window !== 'undefined';

export function readJSON(key, fallback) {
  if (!canUse()) return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

export function writeJSON(key, value) {
  if (!canUse()) return;
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* quota / private mode — ignore */
  }
}

export function readSession(key, fallback = null) {
  if (!canUse()) return fallback;
  try {
    return window.sessionStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

export function writeSession(key, value) {
  if (!canUse()) return;
  try {
    window.sessionStorage.setItem(key, value);
  } catch {
    /* ignore */
  }
}

export function removeSession(key) {
  if (!canUse()) return;
  try {
    window.sessionStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}
