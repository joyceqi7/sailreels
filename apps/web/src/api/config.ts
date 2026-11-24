/** Selection for the v1 catalog data layer; page wiring is a separate change. */
const apiMode = import.meta.env.VITE_API_MODE ?? 'mock';
if (apiMode !== 'mock' && apiMode !== 'live') {
  throw new Error('VITE_API_MODE must be mock or live.');
}
export const MOCK_API_ENABLED = apiMode === 'mock';
// Match the existing session wrapper, used by authenticated /access requests.
export const API_BASE = import.meta.env.VITE_API_BASE ?? '/api/v1';