import type {
  MinisPlayerChannel,
  MinisPlayerConstructor,
  TTMinisPlayerApi,
} from './types';

const DEFAULT_CHANNEL: MinisPlayerChannel = 'byteplus';

const constructorCache = new Map<MinisPlayerChannel, MinisPlayerConstructor>();
const constructorPromises = new Map<MinisPlayerChannel, Promise<MinisPlayerConstructor>>();

function readTTMinis(): TTMinisPlayerApi | undefined {
  if (typeof window === 'undefined') return undefined;
  return (window as Window & { TTMinis?: TTMinisPlayerApi }).TTMinis;
}

/** True only when the SDK reports that the page runs in a Minis container. */
export function isMinisContainerEnvironment(): boolean {
  return readTTMinis()?.isMinisRuntime === true;
}

/**
 * Resolves and caches the Player constructor exposed by the Minis script.
 * TTMinis.init() must have completed before this is called.
 */
export async function resolveMinisPlayer(
  channel: MinisPlayerChannel = DEFAULT_CHANNEL,
): Promise<MinisPlayerConstructor> {
  const cachedConstructor = constructorCache.get(channel);
  if (cachedConstructor) return cachedConstructor;
  const pendingConstructor = constructorPromises.get(channel);
  if (pendingConstructor) return pendingConstructor;

  const constructorPromise = (async () => {
    const minis = readTTMinis();
    if (!minis?.getPlayer) throw new Error('TikTok Minis SDK is unavailable.');

    const Player = await Promise.resolve(minis.getPlayer(channel));
    if (!Player) throw new Error('TTMinis.getPlayer() returned no player constructor.');
    constructorCache.set(channel, Player);
    return Player;
  })().catch((error) => {
    constructorPromises.delete(channel);
    throw error;
  });

  constructorPromises.set(channel, constructorPromise);
  return constructorPromise;
}

export function playerEvent(
  Player: MinisPlayerConstructor,
  key: string,
  fallback: string,
): string {
  return typeof Player.Events?.[key] === 'string'
    ? (Player.Events[key] as string)
    : fallback;
}
