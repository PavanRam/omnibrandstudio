/** Mock data powering the admin dashboard. */

export const ADMIN_STATS = [
  { id: 'gen', label: 'Generations (24h)', value: '48,912', delta: '+12.4%', trend: 'up' },
  { id: 'users', label: 'Active users', value: '9,240', delta: '+3.1%', trend: 'up' },
  { id: 'gpu', label: 'GPU utilisation', value: '73%', delta: '-4.0%', trend: 'down' },
  { id: 'flagged', label: 'Flagged for review', value: '27', delta: '+6', trend: 'up' },
];

/** 14-day generations series for the mini chart. */
export const USAGE_SERIES = [
  32, 41, 38, 45, 52, 49, 61, 58, 67, 72, 65, 78, 84, 91,
];

export const ADMIN_USERS = [
  { id: 'u-1', name: 'Aria Kapoor', email: 'aria.k@studio.io', plan: 'Pro', gens: 1204, status: 'active' },
  { id: 'u-2', name: 'Devin Marsh', email: 'devin.m@studio.io', plan: 'Team', gens: 842, status: 'active' },
  { id: 'u-3', name: 'Sana Reyes', email: 'sana.r@studio.io', plan: 'Free', gens: 96, status: 'active' },
  { id: 'u-4', name: 'Leo Tanaka', email: 'leo.t@studio.io', plan: 'Pro', gens: 2310, status: 'suspended' },
  { id: 'u-5', name: 'Mira Patel', email: 'mira.p@studio.io', plan: 'Team', gens: 1508, status: 'active' },
  { id: 'u-6', name: 'Omar Said', email: 'omar.s@studio.io', plan: 'Free', gens: 41, status: 'invited' },
];

export const MODERATION_QUEUE = [
  { id: 'm-1', prompt: 'Realistic photo of a public figure endorsing a product', reason: 'Likeness policy', severity: 'high', reporter: 'auto-filter' },
  { id: 'm-2', prompt: 'Brand logo recreation with slight changes', reason: 'Trademark', severity: 'medium', reporter: 'devin.m' },
  { id: 'm-3', prompt: 'Graphic violence in a game concept', reason: 'Violence', severity: 'medium', reporter: 'auto-filter' },
  { id: 'm-4', prompt: 'Ambiguous request flagged by classifier', reason: 'Low confidence', severity: 'low', reporter: 'auto-filter' },
];
