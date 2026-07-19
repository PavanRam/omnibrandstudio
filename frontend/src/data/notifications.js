/** Mock notifications for the top-bar bell menu. */
export const NOTIFICATIONS = [
  {
    id: 'n-1',
    title: 'Your batch is ready',
    body: '4 new images finished generating from "neon koi fish".',
    time: '2m ago',
    unread: true,
    type: 'success',
  },
  {
    id: 'n-2',
    title: 'New model available',
    body: 'OmniImage 3 Turbo is now live — up to 3× faster.',
    time: '1h ago',
    unread: true,
    type: 'info',
  },
  {
    id: 'n-3',
    title: 'Credits topped up',
    body: '500 monthly generation credits have been added.',
    time: 'Yesterday',
    unread: false,
    type: 'info',
  },
  {
    id: 'n-4',
    title: 'Someone liked your creation',
    body: '"Surreal floating islands" reached 1,000 likes.',
    time: '2d ago',
    unread: false,
    type: 'like',
  },
];
