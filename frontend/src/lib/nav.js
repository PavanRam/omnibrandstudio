/**
 * Central navigation model, shared by the sidebar and the command surfaces.
 * `key` matches the `route` prop passed to <App /> by each Astro page.
 */
import {
  Home,
  ImagePlus,
  Wand2,
  LayoutGrid,
  Sparkles,
  ShieldCheck,
} from 'lucide-react';

export const PRIMARY_NAV = [
  { key: 'home', label: 'Home', href: '/', icon: Home },
  { key: 'text-to-image', label: 'Text to Image', href: '/text-to-image', icon: ImagePlus },
  { key: 'tools', label: 'AI Tools', href: '/tools', icon: Wand2 },
  { key: 'gallery', label: 'My Gallery', href: '/gallery', icon: LayoutGrid },
];

export const SECONDARY_NAV = [
  { key: 'admin', label: 'Admin Panel', href: '/admin', icon: ShieldCheck },
];

export const BRAND = {
  name: 'OmniBrand',
  suffix: 'Studio',
  icon: Sparkles,
};
