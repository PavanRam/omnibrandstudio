import { useEffect } from 'react';
import { AppShell } from './AppShell.jsx';
import { ConversationView } from './views/ConversationView.jsx';
import { CampaignsGalleryView } from './views/CampaignsGalleryView.jsx';
import { AdminView } from './views/AdminView.jsx';
import { checkAndRefreshToken } from '@/lib/api.js';

const ROUTES = {
  app: { title: 'Campaign Studio', View: ConversationView },
  gallery: { title: 'Campaign Gallery', View: CampaignsGalleryView },
  admin: { title: 'Admin Panel', View: AdminView },
};

/**
 * Single React root per Astro page. `route` selects the view; the shared
 * AppShell provides the sidebar, top bar, and theming around it.
 */
export default function App({ route = 'app' }) {
  const entry = ROUTES[route] ?? ROUTES.app;
  const { View, title } = entry;

  // Proactively refresh the access token on app load if it is close to expiry.
  useEffect(() => {
    checkAndRefreshToken().catch(() => {});
  }, []);

  return (
    <AppShell currentRoute={route} title={title}>
      <View />
    </AppShell>
  );
}
