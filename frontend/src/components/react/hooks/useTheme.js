import { useCallback, useEffect, useState } from 'react';

const KEY = 'obs-theme';

function currentTheme() {
  if (typeof document === 'undefined') return 'light';
  return document.documentElement.classList.contains('dark') ? 'dark' : 'light';
}

/** Apply a theme to <html>, persist it, and broadcast to other listeners. */
export function applyTheme(theme) {
  const root = document.documentElement;
  root.classList.toggle('dark', theme === 'dark');
  root.style.colorScheme = theme;
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new CustomEvent('obs:themechange', { detail: theme }));
}

/**
 * Theme hook. State is initialised from the DOM *after* mount to avoid a
 * hydration mismatch (the real theme is set by an inline <head> script before
 * React runs). `mounted` lets the UI defer theme-specific rendering.
 */
export function useTheme() {
  const [mounted, setMounted] = useState(false);
  const [theme, setThemeState] = useState('light');

  useEffect(() => {
    setThemeState(currentTheme());
    setMounted(true);
    const onChange = (e) => setThemeState(e?.detail ?? currentTheme());
    window.addEventListener('obs:themechange', onChange);
    return () => window.removeEventListener('obs:themechange', onChange);
  }, []);

  const setTheme = useCallback((t) => applyTheme(t), []);
  const toggle = useCallback(
    () => applyTheme(currentTheme() === 'dark' ? 'light' : 'dark'),
    [],
  );

  return { theme, setTheme, toggle, mounted };
}
