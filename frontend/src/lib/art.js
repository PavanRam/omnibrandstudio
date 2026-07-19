/**
 * Deterministic, fully-local "generative art" — layered mesh gradients + soft
 * blobs + film grain + vignette, seeded from a string. This replaces the
 * previous external image dependency (picsum), which rate-limited on grids and
 * left tiles blank. Everything here renders offline and always looks the same
 * for a given seed. Swap this for a real generation API when a backend exists.
 */
import { hashString } from './images.js';

// mulberry32 — tiny, fast, deterministic PRNG.
function makeRng(seed) {
  let a = seed >>> 0;
  return function next() {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const PALETTES = [
  ['#ff8a4c', '#ff4f8b', '#8b5cff', '#4c7dff'],
  ['#4c7dff', '#8b5cff', '#ff4f8b', '#ffb14c'],
  ['#17c07d', '#4cc9ff', '#8b5cff', '#ff6fae'],
  ['#ff5f6d', '#ffc371', '#ff8a4c', '#ff4f8b'],
  ['#7b5cff', '#00c2ff', '#37e6b4', '#ffd166'],
  ['#f857a6', '#ff5858', '#ffae4c', '#ff4f8b'],
  ['#2af598', '#009efd', '#8b5cff', '#5c8bff'],
  ['#e96443', '#904e95', '#4c5bff', '#00c2ff'],
  ['#0ba360', '#3cba92', '#4cc9ff', '#5c8bff'],
  ['#c471f5', '#fa71cd', '#ff8a4c', '#ffd166'],
];

/**
 * Build a standalone SVG string for a seed. `responsive:true` makes it fill its
 * container (for inline rendering); otherwise it uses explicit px (for download).
 */
export function sceneSvg(seedInput, { w = 800, h = 800, responsive = false } = {}) {
  const seed = hashString(String(seedInput || 'omnibrand'));
  const rnd = makeRng(seed);
  const uid = seed.toString(36);
  const palette = PALETTES[seed % PALETTES.length];
  const range = (min, max) => min + rnd() * (max - min);
  const paint = () => palette[Math.floor(rnd() * palette.length)];

  const angle = Math.floor(range(0, 360));
  const bgA = palette[0];
  const bgB = palette[1 + Math.floor(rnd() * (palette.length - 1))];

  // A handful of large, soft blobs form the "mesh gradient".
  const blobCount = 4 + Math.floor(rnd() * 3);
  let blobs = '';
  for (let i = 0; i < blobCount; i += 1) {
    const cx = range(-15, 135).toFixed(1);
    const cy = range(-15, 135).toFixed(1);
    const r = range(34, 74).toFixed(1);
    const op = range(0.55, 0.95).toFixed(2);
    blobs += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${paint()}" opacity="${op}"/>`;
  }

  const dims = responsive ? 'width="100%" height="100%"' : `width="${w}" height="${h}"`;

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" preserveAspectRatio="xMidYMid slice" ${dims}>` +
    `<defs>` +
    `<linearGradient id="bg${uid}" gradientTransform="rotate(${angle} 0.5 0.5)">` +
    `<stop offset="0" stop-color="${bgA}"/><stop offset="1" stop-color="${bgB}"/>` +
    `</linearGradient>` +
    `<filter id="soft${uid}" x="-40%" y="-40%" width="180%" height="180%">` +
    `<feGaussianBlur stdDeviation="11"/></filter>` +
    `<filter id="grain${uid}">` +
    `<feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" stitchTiles="stitch"/>` +
    `<feColorMatrix type="saturate" values="0"/>` +
    `<feComponentTransfer><feFuncA type="linear" slope="0.09"/></feComponentTransfer>` +
    `<feComposite operator="in" in2="SourceGraphic"/></filter>` +
    `<radialGradient id="vig${uid}" cx="0.5" cy="0.4" r="0.75">` +
    `<stop offset="0.5" stop-color="#000" stop-opacity="0"/>` +
    `<stop offset="1" stop-color="#000" stop-opacity="0.3"/></radialGradient>` +
    `</defs>` +
    `<rect width="120" height="120" fill="url(#bg${uid})"/>` +
    `<g filter="url(#soft${uid})">${blobs}</g>` +
    `<rect width="120" height="120" fill="#000" filter="url(#grain${uid})" opacity="0.55"/>` +
    `<rect width="120" height="120" fill="url(#vig${uid})"/>` +
    `</svg>`;
}

/** Same scene as a data: URL — usable for downloads or <img src>. */
export function artDataUrl(seed, opts) {
  return `data:image/svg+xml,${encodeURIComponent(sceneSvg(seed, opts))}`;
}
