import { useRef, useState } from 'react';
import { Sparkles, ArrowRight, Wand2 } from 'lucide-react';
import { Page, SectionHeading } from '../Page.jsx';
import { PromptComposer } from '../PromptComposer.jsx';
import { ResultsGrid } from '../ResultsGrid.jsx';
import { ShowcaseGallery } from '../ShowcaseGallery.jsx';
import { SkeletonGrid } from '../SkeletonGrid.jsx';
import { Button } from '../ui/Button.jsx';
import { useGenerate } from '../hooks/useGenerate.js';

export function HomeView() {
  const [prompt, setPrompt] = useState('');
  const [lastAspect, setLastAspect] = useState('1:1');
  const composerRef = useRef(null);
  const { history, generate, generating, pending, latestIds, toggleLike, remove } =
    useGenerate();

  const latest = history.filter((h) => latestIds.includes(h.id));
  const recent = history.filter((h) => !latestIds.includes(h.id)).slice(0, 8);

  const handleGenerate = async (text, settings) => {
    setLastAspect(settings.aspect);
    await generate(text, settings);
  };

  const remix = (text) => {
    setPrompt(text);
    composerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <Page wide>
      {/* Hero */}
      <section
        ref={composerRef}
        className="relative overflow-hidden rounded-4xl border border-border bg-surface px-4 py-12 sm:px-8 sm:py-16"
      >
        <div className="brand-glow pointer-events-none absolute inset-0 opacity-60" aria-hidden="true" />
        <div className="relative mx-auto max-w-3xl text-center">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface/80 px-3 py-1 text-xs font-medium text-muted backdrop-blur">
            <Sparkles size={13} aria-hidden="true" className="text-brand" />
            Powered by OmniImage 3
          </span>
          <h1 className="mt-5 text-3xl font-semibold tracking-tight text-fg sm:text-5xl">
            Turn words into <span className="brand-text">stunning images</span>
          </h1>
          <p className="mx-auto mt-4 max-w-xl text-base text-muted">
            Describe your idea and generate beautiful, on-brand visuals in seconds.
            Explore styles, iterate fast, and keep every creation in your gallery.
          </p>
        </div>

        <div className="relative mx-auto mt-8 max-w-3xl text-left">
          <PromptComposer
            value={prompt}
            onChange={setPrompt}
            onGenerate={handleGenerate}
            generating={generating}
          />
        </div>
      </section>

      {/* Generating / latest results */}
      {(generating || latest.length > 0) && (
        <section className="mt-10">
          <SectionHeading
            title="Your results"
            description={generating ? 'Conjuring your images…' : 'Fresh from your last prompt.'}
            action={
              <Button href="/gallery" variant="ghost" size="sm">
                Open gallery <ArrowRight size={15} aria-hidden="true" />
              </Button>
            }
          />
          {generating ? (
            <SkeletonGrid count={pending || 4} aspect={lastAspect} />
          ) : (
            <ResultsGrid
              items={latest}
              onLike={toggleLike}
              onRemove={remove}
              onUsePrompt={remix}
            />
          )}
        </section>
      )}

      {/* Recent history */}
      {recent.length > 0 && (
        <section className="mt-10">
          <SectionHeading
            title="Recent creations"
            action={
              <Button href="/gallery" variant="ghost" size="sm">
                View all <ArrowRight size={15} aria-hidden="true" />
              </Button>
            }
          />
          <ResultsGrid
            items={recent}
            onLike={toggleLike}
            onRemove={remove}
            onUsePrompt={remix}
          />
        </section>
      )}

      {/* Community showcase */}
      <section className="mt-12">
        <SectionHeading
          title="Featured in the community"
          description="Get inspired — click any creation to remix its prompt."
          action={
            <Button href="/tools" variant="ghost" size="sm">
              Explore tools <Wand2 size={15} aria-hidden="true" />
            </Button>
          }
        />
        <ShowcaseGallery onUsePrompt={remix} />
      </section>
    </Page>
  );
}
