# Skip.Intro.Next (S.I.N.)

`service.nextonlibrary` is a Kodi service add-on that adds two lightweight playback helpers:

- `Skip Intro`
- `Next On`

## Current Behavior

The add-on can use both local chapter markers and online metadata.

- `Skip Intro` can use:
  - online metadata from `TheIntroDB`
  - online metadata from `IntroDB.app`
  - local chapter markers exposed by Kodi
  - an optional manual fallback intro window
- `Next On` can use:
  - online metadata from `TheIntroDB`
  - online metadata from `IntroDB.app`
  - local chapter markers near the end of playback
  - a fallback percentage trigger

## What It Does

- Monitors TV-show playback in Kodi
- Shows a `Skip Intro` overlay with a draining pill outline when an intro or recap end can be determined
- Shows a `Next` overlay near the end of playback
- Can optionally auto-play the next library episode after a configurable delay that follows the existing prompt dismiss behavior
- Can optionally auto-skip intros after a configurable delay
- Uses simple on-screen overlay buttons instead of a heavy custom interface
- Supports online-metadata-first or chapter-first behavior through settings
- Includes an `Advanced` settings group with debug logging and `View Changelog`

## Playback Scope

- `Skip Intro` works for TV-show playback only. It supports Kodi library episodes and compatible non-library streams or add-on playback when Kodi exposes TV episode metadata.
- `Skip Intro` does not run for movies.
- `Next On` works only for Kodi library episodes, because it needs Kodi library data to find and play the next episode.
- `Next On` does not run for movies, streams, or non-library items.

## Settings

### Next On

- `Enable Service`
- `Online Metadata Priority`
- `Auto-play Next Episode`
- `Auto-play Delay`
- `Fallback Trigger Percent`

Default behavior:
- `Online Metadata Priority` is `On`
- remote metadata is tried first
- local chapters are used as fallback
- `Auto-play Next Episode` is `Off`

When auto-play is enabled, `Auto-play Delay` accepts `0` to `20` seconds. A value of `0` opens the next episode immediately when the Next On trigger is reached. Values from `1` to `20` show the `Next` button with a pill progress overlay before opening the next episode. Select plays immediately; other remote or keyboard actions cancel the prompt.

### Skip Intro

- `Enable Skip Intro`
- `Online Metadata Priority`
- `Auto-skip Intro`
- `Auto-skip Delay`
- `Enable Fallback Intro Window`
- `Fallback Intro Start`
- `Fallback Intro End`

Default behavior:
- `Enable Skip Intro` is `On`
- `Online Metadata Priority` is `On`
- remote metadata is tried first
- local chapters are used as fallback
- `Auto-skip Intro` is `Off`

When auto-skip is enabled, `Auto-skip Delay` accepts `0` to `10` seconds and defaults to `2`. A value of `0` skips immediately when the Skip Intro prompt would appear. Values from `1` to `10` show the `Skip Intro` button with a filling pill progress overlay before skipping. Select skips immediately; other remote or keyboard actions cancel the prompt.

### Advanced

- `Enable Debug Logging`
- `View Changelog`

## Online Metadata Sources

The add-on currently uses:

- `TheIntroDB`
- `IntroDB.app`

For TV episode lookups:

- `TheIntroDB` is queried with `tmdb_id`, `season`, and `episode`
- `IntroDB.app` is queried with the show `imdb_id`, `season`, and `episode`

## API Limits

### TheIntroDB

Documented limits used by the add-on integration:

- `/media` rate limit: `30 requests per 10 seconds`
- authenticated `/media` usage limit: `500 requests per day`
- unauthenticated `/media` usage limit: `100 requests per day`

The API also documents response headers for both rate and usage limits:

- `X-RateLimit-Limit`
- `X-RateLimit-Remaining`
- `X-RateLimit-Reset`
- `X-UsageLimit-Limit`
- `X-UsageLimit-Remaining`
- `X-UsageLimit-Reset`

### IntroDB.app

This repository currently documents the lookup format used by the add-on, but not a published rate-limit policy for `IntroDB.app`.

## Notes

- Chapter markers remain valuable even when online metadata is enabled
- If remote metadata is unavailable, the add-on falls back to local chapter timing when possible
- If neither remote metadata nor usable chapter timing is available, `Next On` falls back to the configured percentage trigger
- `Skip Intro` can optionally fall back to a manual start/end window
- `Skip Intro` starts with a full pill outline that drains away until the prompt disappears
- Launching the add-on from Programs opens its settings
