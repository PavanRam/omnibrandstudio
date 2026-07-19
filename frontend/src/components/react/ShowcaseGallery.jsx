import { ResultsGrid } from './ResultsGrid.jsx';
import { SHOWCASE } from '@/data/showcase.js';

const ITEMS = SHOWCASE.map((s) => ({ ...s, seed: s.id }));

/** Curated community showcase (read-only, remixable). */
export function ShowcaseGallery({ onUsePrompt }) {
  return <ResultsGrid items={ITEMS} onUsePrompt={onUsePrompt} />;
}
