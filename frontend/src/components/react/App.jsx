import { AppShell } from "./AppShell.jsx";
import { HomeView } from "./views/HomeView.jsx";
import { GalleryView } from "./views/GalleryView.jsx";
import { ToolsView } from "./views/ToolsView.jsx";
import { AdminGate } from "./views/AdminGate.jsx";
import { CampaignView } from "./views/CampaignView.jsx";

const ROUTES = {
  home: { title: "Image Generation", View: HomeView },
  campaign: { title: "Campaign Studio", View: CampaignView },
  tools: { title: "AI Tools", View: ToolsView },
  gallery: { title: "My Gallery", View: GalleryView },
  admin: { title: "Admin Panel", View: AdminGate },
};

/**
 * Single React root per Astro page. `route` selects the view; the shared
 * AppShell provides the sidebar, top bar, and theming around it.
 */
export default function App({ route = "home" }) {
  const entry = ROUTES[route] ?? ROUTES.home;
  const { View, title } = entry;
  return (
    <AppShell currentRoute={route} title={title}>
      <View />
    </AppShell>
  );
}
