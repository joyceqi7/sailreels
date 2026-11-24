/** Display name of the app this bundle was built for (.env.<app>, see vite.config.ts). */
export const APP_NAME: string = import.meta.env.VITE_APP_NAME?.trim() || 'SailReels';
