/** Tiny classNames joiner — filters falsy values. */
export function cn(...parts) {
  return parts.filter(Boolean).join(' ');
}
