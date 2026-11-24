/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_MODE?: 'mock' | 'live';
  readonly VITE_API_BASE?: string;
  readonly VITE_REWARDED_AD_UNIT_ID?: string;
  readonly VITE_INTERSTITIAL_AD_UNIT_ID?: string;
  readonly VITE_MONETIZATION?: 'iaa' | 'hybrid';
}
