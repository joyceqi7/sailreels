/** Isolated, in-memory demo only. No persisted login or live entitlement is changed. */
let until = 0;
export const hasPreviewSubscription = () => until > Date.now();
export const setPreviewSubscription = (active: boolean) => { until = active ? Date.now() + 30 * 86400_000 : 0; };
