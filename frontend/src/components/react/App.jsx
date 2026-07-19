import { AppShell } from './AppShell.jsx';
import { ConversationView } from './views/ConversationView.jsx';
import { CampaignsGalleryView } from './views/CampaignsGalleryView.jsx';
import { AdminGate } from './views/AdminGate.jsx';

const ROUTES = {
  home: { title: 'Conversation', View: ConversationView },
  gallery: { title: 'Campaign Gallery', View: CampaignsGalleryView },
  admin: { title: 'Admin Panel', View: AdminGate },
};

/**
 * Single React root per Astro page. `route` selects the view; the shared
 * AppShell provides the sidebar, top bar, and theming around it.
 */
export default function App({ route = 'home' }) {
  const entry = ROUTES[route] ?? ROUTES.home;
  const { View, title } = entry;
  return (
    <AppShell currentRoute={route} title={title}>
      <View />
    </AppShell>
  );
}
