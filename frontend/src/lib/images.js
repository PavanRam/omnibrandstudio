/**
 * Small hashing helper used to turn a prompt/seed string into a stable numeric
 * seed for the local generative-art engine (see lib/art.js).
 */

/** Stable 32-bit-ish hash from an arbitrary string. */
export function hashString(str = '') {
  let hash = 0;
  for (let i = 0; i < str.length; i += 1) {
    hash = (hash << 5) - hash + str.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}
