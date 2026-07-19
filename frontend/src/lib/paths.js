/**
 * Prefix a root-relative path with the app's deploy base path so links work
 * both locally (base "/") and under a GitHub Pages project sub-path
 * (e.g. "/omnibrandstudio/"). Absolute URLs and hash/anchor links pass through.
 *
 * `import.meta.env.BASE_URL` is set by Astro from the `base` config and always
 * ends with a trailing slash.
 */
const BASE = import.meta.env.BASE_URL || '/';

export function withBase(path = '/') {
  if (!path || /^(https?:)?\/\//.test(path) || path.startsWith('#') || path.startsWith('mailto:')) {
    return path;
  }
  return `${BASE}/${path}`.replace(/\/{2,}/g, '/');
}
