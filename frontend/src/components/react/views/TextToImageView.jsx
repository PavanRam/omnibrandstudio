import { useEffect, useState } from 'react';
import { ImagePlus, Trash2, Sparkles } from 'lucide-react';
import { Page, SectionHeading } from '../Page.jsx';
import { PromptComposer } from '../PromptComposer.jsx';
import { ResultsGrid } from '../ResultsGrid.jsx';
import { SkeletonGrid } from '../SkeletonGrid.jsx';
import { EmptyState } from '../EmptyState.jsx';
import { Button } from '../ui/Button.jsx';
import { useGenerate } from '../hooks/useGenerate.js';

export function TextToImageView() {
  const [prompt, setPrompt] = useState('');
  const [lastAspect, setLastAspect] = useState('1:1');
  const { history, generate, generating, pending, latestIds, toggleLike, remove, clear, hydrated } =
    useGenerate();

  // Prefill from a ?prompt= query (e.g. "remix" from Home / community).
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get('prompt');
    if (q) setPrompt(q);
  }, []);

  const latest = history.filter((h) => latestIds.includes(h.id));
  const older = history.filter((h) => !latestIds.includes(h.id));

  const handleGenerate = async (text, settings) => {
    setLastAspect(settings.aspect);
    await generate(text, settings);
    window.scrollTo({ top: 320, behavior: 'smooth' });
  };

  return (
    <Page
      wide
      eyebrow="AI Tools"
      title="Text to Image"
      description="Describe your vision and generate multiple variations. Refine settings, remix results, and build up your gallery."
    >
      <PromptComposer
        value={prompt}
        onChange={setPrompt}
        onGenerate={handleGenerate}
        generating={generating}
      />

      {generating && (
        <section className="mt-8" aria-live="polite">
          <SectionHeading title="Generating…" />
          <SkeletonGrid count={pending || 4} aspect={lastAspect} />
        </section>
      )}

      {!generating && latest.length > 0 && (
        <section className="mt-8">
          <SectionHeading title="Latest generation" />
          <ResultsGrid
            items={latest}
            onLike={toggleLike}
            onRemove={remove}
            onUsePrompt={setPrompt}
          />
        </section>
      )}

      {older.length > 0 && (
        <section className="mt-10">
          <SectionHeading
            title="History"
            description={`${older.length} earlier ${older.length === 1 ? 'creation' : 'creations'}`}
            action={
              <Button variant="ghost" size="sm" onClick={clear}>
                <Trash2 size={15} aria-hidden="true" /> Clear all
              </Button>
            }
          />
          <ResultsGrid
            items={older}
            onLike={toggleLike}
            onRemove={remove}
            onUsePrompt={setPrompt}
          />
        </section>
      )}

      {hydrated && !generating && history.length === 0 && (
        <div className="mt-8">
          <EmptyState
            icon={ImagePlus}
            title="No creations yet"
            description="Enter a prompt above and hit Generate to see your first batch of images appear here."
            action={
              <Button
                variant="primary"
                onClick={() => setPrompt('A bioluminescent forest at night, magical, ultra detailed')}
              >
                <Sparkles size={16} aria-hidden="true" /> Use a sample prompt
              </Button>
            }
          />
        </div>
      )}
    </Page>
  );
}
