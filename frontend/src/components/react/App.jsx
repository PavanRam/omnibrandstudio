import { AppShell } from './AppShell.jsx';
import { ConversationView } from './views/ConversationView.jsx';
import { CampaignsGalleryView } from './views/CampaignsGalleryView.jsx';
import { AdminView } from './views/AdminView.jsx';

const ROUTES = {
  studio: { title: 'Campaign Copilot', View: ConversationView },
  campaigns: { title: 'Campaigns', View: CampaignsGalleryView },
  admin: { title: 'Admin', View: AdminView },
};

/**
 * Single React root per Astro page. `route` selects the view; the shared
 * AppShell provides the sidebar, top bar, and theming around it.
 */
export default function App({ route = 'studio' }) {
  const entry = ROUTES[route] ?? ROUTES.studio;
  const { View, title } = entry;
  return (
    <AppShell currentRoute={route} title={title}>
      <View />
    </AppShell>
  );
}
