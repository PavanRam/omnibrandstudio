# OmniBrand Studio

A Firefly-style generative AI studio UI — a prompt-to-image chatbot experience with a
separate, password-protected admin panel. Built as a polished, accessible, responsive
reference frontend.

> **Stack:** Vite + Astro + React (`.jsx`) + Tailwind CSS v4 · light/dark theme · no TypeScript.

---

## Quick start

```bash
npm install
npm run dev        # http://localhost:4321
```

| Script            | Description                          |
| ----------------- | ------------------------------------ |
| `npm run dev`     | Start the dev server                 |
| `npm run build`   | Production build → `dist/`           |
| `npm run preview` | Preview the production build locally |

## Features

- **Firefly-style home** — hero prompt composer, live results, recent creations, and a community showcase.
- **Text to Image workspace** — model / style / aspect-ratio / count controls, simulated generation, batch history.
- **My Gallery** — every creation is saved to `localStorage`; search, favourite, filter, and manage.
- **AI Tools hub** — a grid of creative tools (ready / beta / coming-soon states).
- **Admin panel** — password-gated dashboard: usage chart, stat cards, user table, moderation queue, platform settings.
- **App chrome** — collapsible icon-rail sidebar (→ off-canvas drawer on mobile), sticky top bar with search, notifications, theme toggle, and login/account menu.
- **Light & dark mode** — semantic CSS-variable tokens; no flash of the wrong theme; respects `prefers-color-scheme`.
- **Accessible** — landmarks, skip link, focus-visible rings, keyboard-operable menus/dialogs (Esc + focus trap + restore), ARIA roles/labels, reduced-motion support, and AA-contrast palettes.
- **Responsive** — mobile-first layouts from phone → ultrawide.

## Project structure

```
src/
├── layouts/BaseLayout.astro      # HTML shell, fonts, no-flash theme script, view transitions
├── pages/                        # One Astro page per route → mounts <App route="…"/>
│   ├── index.astro   text-to-image.astro   tools.astro   gallery.astro   admin.astro
├── components/react/
│   ├── App.jsx                   # Route → view map, wrapped in AppShell
│   ├── AppShell.jsx              # Sidebar rail + mobile drawer + top bar + <main>
│   ├── TopNav / Sidebar / *      # Navigation & chrome
│   ├── PromptComposer, ImageCard, ResultsGrid, ImageDetailModal, ShowcaseGallery …
│   ├── views/                    # HomeView, TextToImageView, GalleryView, ToolsView, AdminGate, AdminView
│   ├── ui/                       # Button, IconButton, Badge, Modal
│   └── hooks/                    # useTheme, useAuth, useGenerate, useGenerations, useMediaQuery, …
├── data/                         # Mock showcase / tools / notifications / admin data
├── lib/                          # nav model, image + storage + classNames helpers
└── styles/global.css             # Tailwind v4 + design tokens (light/dark)
```

Each Astro page mounts a single React island (`<App client:load route="…"/>`), giving real
URLs and deep-linking while keeping the app cohesive. Smooth navigation uses Astro's
`<ClientRouter />` view transitions.

## Admin panel

Navigate to **/admin**. The default demo password is `firefly` (shown on the lock screen).
Override it in `.env`:

```bash
cp .env.example .env
# PUBLIC_ADMIN_PASSWORD=your-password
```

> ⚠️ **This is a client-side demo gate, not real security.** `PUBLIC_` variables are bundled
> into the client. For production, replace `useAuth` and `AdminGate` with a real server-side
> auth flow (session cookies / OAuth) and protect the route on the server.

## Deploy to GitHub Pages

A workflow is included at [.github/workflows/deploy.yml](.github/workflows/deploy.yml). To publish:

1. Push this repo to GitHub.
2. In the repo, go to **Settings → Pages → Build and deployment → Source** and choose **GitHub Actions**.
3. Push to `main` (or run the workflow manually from the **Actions** tab).

The workflow builds with Node 22 and **auto-derives the correct paths for your repo** — no editing required:

- **Project site** (`sarthakworks/omnibrandstudio`) → served at `https://sarthakworks.github.io/omnibrandstudio/`, `base` = `/omnibrandstudio`.
- **User/org site** (`sarthakworks/sarthakworks.github.io`) → served at `https://sarthakworks.github.io/`, `base` = `/`.

All internal links go through [`withBase()`](src/lib/paths.js) and `astro.config.mjs` reads `base`/`site` from the workflow's env vars, so the same code works locally (`base` = `/`) and under a Pages sub-path. A `public/.nojekyll` file ensures Astro's `_astro/` assets are served.

## Backend Connection

The frontend is **fully connected** to the OmniBrand Studio FastAPI backend (`http://localhost:8000` by default).

Key integrations in `src/lib/api.js`:

| Feature | Backend endpoint |
|---|---|
| Login / logout / token refresh | `POST /auth/token`, `POST /auth/logout`, `POST /auth/refresh` |
| Campaign creation + status poll | `POST /campaigns`, `GET /campaigns/{id}/status` |
| Conversation chat (real-time) | `WS /conversations/{id}` (WebSocket) |
| Pipeline event stream (live) | `GET /campaigns/{id}/stream` (SSE) |
| Campaign replay / rerun | `GET /campaigns/{id}/events/replay`, `POST /campaigns/{id}/rerun` |
| Brand guide / segment upload | `POST /knowledge/brand-guides`, `POST /knowledge/segments` |
| Human review decisions | `GET /reviews`, `POST /reviews/{id}/decide` |
| User management | `GET/POST /users` |

**Auth:** Bearer JWT (stored in `localStorage`, auto-refreshed on 401) with fallback to `X-API-Key`. On localhost with no config, defaults to `dev-local-chat-key`.

**To start:**

```bash
# 1. Make sure the backend is running first:  make up && make run && make worker
# 2. Copy and configure frontend env:
cp .env.example .env

# 3. Install and run
npm install
npm run dev   # → http://localhost:4321
```

The `GenerativeArt` component in `src/lib/art.js` is still used for visual previews of generated content variants inside the UI — it is not a substitute for the real LLM pipeline. Campaign content is generated by the backend LangGraph pipeline.

> **Admin panel** (`/admin`): Demo password gate only — not real security. Default password: `firefly` (override with `PUBLIC_ADMIN_PASSWORD` in `.env`).
