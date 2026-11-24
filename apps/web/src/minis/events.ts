/**
 * Middle-funnel events (docs/official/41-event-postback.md). Event names and params are fixed by TikTok —
 * do not rename. episode_number is a string; if_* flags are 0/1, or null when not applicable.
 */
import { reportEvent } from './sdk';

export interface EpisodeContext {
  dramaId: string;
  dramaName: string;
  episodeNumber: number;
  totalEpisodes: number;
  freeEpisodes: number;
}

function base(ctx: EpisodeContext) {
  const n = ctx.episodeNumber;
  return {
    minis_drama_name: ctx.dramaName,
    minis_drama_id: ctx.dramaId,
    episode_number: String(n),
    if_last_free_ep: n === ctx.freeEpisodes ? 1 : 0,
    if_first_paid_ep: n === ctx.freeEpisodes + 1 ? 1 : 0,
    if_last_ep: n === ctx.totalEpisodes ? 1 : 0,
  };
}

export const funnel = {
  videoPlayRequest: (ctx: EpisodeContext) => reportEvent('video_play_request', base(ctx)),
  epPlay: (ctx: EpisodeContext) => reportEvent('ep_play', base(ctx)),
  /** All free episodes watched. */
  addToWishlist: (ctx: EpisodeContext) => reportEvent('add_to_wishlist', base(ctx)),
  /** First paid episode of this drama unlocked. */
  startUnlock: (ctx: EpisodeContext) => reportEvent('start_unlock', base(ctx)),
  /** Last paid episode unlocked. */
  completeWatching: (ctx: EpisodeContext) => reportEvent('complete_watching', base(ctx)),
  unlockPanelShowRequest: (ctx: EpisodeContext) => reportEvent('unlock_panel_show_request', base(ctx)),
  unlockPanelShow: (ctx: EpisodeContext) => reportEvent('unlock_panel_show', base(ctx)),
  unlockPanelClick: (ctx: EpisodeContext) => reportEvent('unlock_panel_click', base(ctx)),
  unlockSuccess: (ctx: EpisodeContext) => reportEvent('unlock_success', base(ctx)),
  /** Every ad impression. episodeNumber = the episode watched just before the ad. */
  adShow: (ctx: EpisodeContext, extra: {
    firstTimeForDrama: boolean;
    minisName: string;
    minisId: string;
    openId: string;
    adType: 'RewardedVideoAd' | 'InterstitialAd';
  }) =>
    reportEvent('minis_ad_show', {
      minis_drama_name: ctx.dramaName,
      minis_drama_id: ctx.dramaId,
      episode_number: String(ctx.episodeNumber),
      if_last_ep: ctx.episodeNumber === ctx.totalEpisodes ? 1 : 0,
      if_first_time: extra.firstTimeForDrama ? 1 : 0,
      minis_name: extra.minisName,
      minis_id: extra.minisId,
      open_id: extra.openId,
      ad_type: extra.adType,
    }),
};
