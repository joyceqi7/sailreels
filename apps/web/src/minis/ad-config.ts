/**
 * Public ad unit IDs for THIS app. Ad units are created per app in the Dev Portal, so an ID from
 * another app (e.g. ZorvTales) must never be used: it would bill impressions to the wrong
 * application and the API would reject it. Each app's IDs are set in its .env.<app>; the fallbacks
 * below are SailReels' and only apply to builds without an app mode (dev, tests).
 *
 * rewarded: rewarded-video unit, activated in the Dev Portal.
 * interstitial: not created yet for any app — stays empty until one exists.
 *
 * An empty ID means that ad type is unavailable: callers must hide the option rather than call
 * createRewardedVideoAd(''), which fails at show() time after the user has already tapped.
 */
export const AD_UNIT_IDS = Object.freeze({
  rewarded: import.meta.env.VITE_REWARDED_AD_UNIT_ID?.trim() || 'ad7000000000000000001',
  interstitial: import.meta.env.VITE_INTERSTITIAL_AD_UNIT_ID?.trim() || '',
});

/** True when this app has a rewarded ad unit configured. Check before offering an ad unlock. */
export const REWARDED_AD_CONFIGURED = AD_UNIT_IDS.rewarded.length > 0;
