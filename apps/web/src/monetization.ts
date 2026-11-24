/**
 * "iaa": rewarded ads are the only way to unlock — Beans, VIP and the wallet are hidden, and a locked
 * episode the user opened directly can be unlocked with an ad right away. "hybrid": Beans + VIP + ads.
 * Set per app in .env.<app>; must match the API's MONETIZATION_MODE (the API refuses orders in iaa).
 * Unset (dev, tests) keeps every flow visible.
 */
const mode = import.meta.env.VITE_MONETIZATION?.trim() || 'hybrid';
if (mode !== 'iaa' && mode !== 'hybrid') {
  throw new Error('VITE_MONETIZATION must be iaa or hybrid.');
}
export const IAP_ENABLED = mode === 'hybrid';
