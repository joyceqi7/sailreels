# Minis Player plugin

This directory is the portable player integration boundary. It has no React or
demo-specific imports and can be copied as a folder into another TypeScript app.

## Files

- `config.ts`: customer-editable definition, preload and cache policy shared by
  every playback path.
- `types.ts`: public SDK and playback data contracts.
- `sdk.ts`: `window.TTMinis.getPlayer()` resolution, constructor cache and
  public `TTMinis.isMinisRuntime` environment detection.
- `playback-config.ts`: playback identity and visual Player configuration.
- `playback.ts`: initial Player creation and instance-reusing `playNext()`.
- `preload.ts`: early preparation, discovery MANUAL preload and
  first-frame-to-AUTO handoff.
- `index.ts`: stable public exports; consumers should import from this file.

The host app remains responsible for loading and initializing the Minis SDK
script before calling this plugin, attaching player events, switching MANUAL
preload to AUTO after the first frame, and destroying the Player on page
teardown. The plugin uses documented SDK capabilities only; it does not inspect
private runtime flags or contain environment-specific request headers.

Keep `MINIS_DRAMA_PLAYER_POLICY.definition` aligned with the actual encoded
definition. Both media-info cache and video preload cache depend on that value.
Player creation explicitly sets `muted: false` only when
`TTMinis.isMinisRuntime === true`; normal browsers keep the Player's standard
autoplay/degrade behavior.

## Host integration order

1. Load the Minis script, call `TTMinis.init()`, then call
   `prepareMinisDramaPreload()` as early as possible.
2. On the discovery page, call `preloadDramaEpisode()` for the likely entry
   episode as soon as list data arrives. Card hover/focus intent may replace
   that single MANUAL target.
3. Before creating a Player, check `hasManualEntryPreload()`. A direct theater
   entry configures AUTO first; a MANUAL-warmed entry calls
   `setupDramaAutoPreload()` after its first-frame event.
4. Create one Player with `createMinisDramaPlayer()`, switch normal episodes
   with `playNextEpisode()`, and destroy it only when the theater unmounts.

`useMinisPlayer.ts` in the host demo is the complete React example for this
order, including transactional switching and WebView foreground/background
handling.
