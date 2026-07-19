/** Keyboard-only "skip to content" link — first focusable element on the page. */
export function SkipLink() {
  return (
    <a
      href="#main-content"
      className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[200] focus:rounded-xl focus:bg-brand focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-brand-fg focus:shadow-lg"
    >
      Skip to main content
    </a>
  );
}
