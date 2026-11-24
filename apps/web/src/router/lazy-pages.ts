import { lazy } from 'react';

const importTheaterPage = () => import('../pages/TheaterPage');

/** Keeps theater-only gesture/UI code out of the discovery-page entry chunk. */
export const LazyTheaterPage = lazy(async () => {
  const module = await importTheaterPage();
  return { default: module.TheaterPage };
});

/** The feed owns a Player too; keep it out of the entry chunk like the theater. */
export const LazyForYouPage = lazy(async () => {
  const module = await import('../pages/ForYouPage');
  return { default: module.ForYouPage };
});

/** Warms the theater code chunk while the user is still viewing a card. */
export async function preloadTheaterPageCode(): Promise<void> {
  await importTheaterPage();
}
