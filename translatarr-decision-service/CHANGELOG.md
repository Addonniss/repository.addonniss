# Changelog

## 2026-07-22

### Added
- Added `describe_subtitle_track()` helper that builds human-readable track labels (`Full`, `SDH`, `Forced`) with codec and track number from the extractor's `selected_track` data
- Enriched Discord notifications for embedded subtitle extraction and target probing with detailed track info so the exact track type, codec, and number are visible

### Changed
- Added `"track"` and `"cues"` to the `code_labels` set in `format_discord_description` for consistent backtick formatting of track and cue lines in Discord embeds

## Unreleased

### Added
- Added `GEMINI_THINKING_LEVEL` environment variable with thinking map (Minimal → minimal, Low → low, Medium → medium, High → high), applied to Gemini 3.x models via `thinking_config.thinking_level`
- Added Gemini model and thinking level to the `/health` endpoint when the provider is Gemini
- Added thinking-level-aware billing label for Gemini 3.x models (e.g., `Gemini (gemini-3.1-flash-lite, think=minimal)`)

### Changed
- Removed `GEMINI_FAST_MODE` and the `thinking_budget: 0` workaround for Gemini 2.5 Flash — superseded by `GEMINI_THINKING_LEVEL`
- Removed `gemini-2.5-flash` from `MODEL_PRICING`; only `gemini-3.1-flash-lite` and `gemini-2.5-flash-lite` remain

### Added (previous)
- Added optional rolling source context for Gemini and LibreTranslate translation batches, controlled by `ROLLING_SOURCE_CONTEXT_ENABLED`
- Added `ROLLING_SOURCE_CONTEXT_WINDOW` with the same 3 to 8 previous-line limits and default-off behavior as `service.translatarr`
- Kept rolling context out of parsed subtitle output by labeling context as `Cxxx:` lines and accepting only translated `Lxxx:` lines

## 2026-06-02

### Added
- Added source SRT validation before saving extracted embedded subtitles or sending them to translation
- Added `DECISION_MAX_SOURCE_SRT_BYTES`, defaulting to `1048576` bytes, to reject oversized source subtitles before translation
- Added extracted source cue counts to extraction-complete Discord notifications
- Added `gemini-3.1-flash-lite` and `gemini-2.5-flash-lite` as supported Gemini decision-service models

### Changed
- Changed the default Gemini decision-service model from deprecated `gemini-2.0-flash` to `gemini-2.5-flash-lite`

### Fixed
- Prevented empty, malformed, binary-looking, or oversized extractor output from being saved as a source sidecar or translated
- Removed the deprecated `gemini-2.0-flash` decision-service pricing/config references

## 2026-05-21

### Added
- Added initial Docker / Portainer-ready `translatarr-decision-service` scaffold
- Added delayed Radarr/Sonarr decision jobs so translation starts only after provider searches and sidecar checks have had time to settle
- Added duplicate job suppression per media path
- Added broad Romanian sidecar detection for variants such as `.ro.srt`, `.ro.sdh.srt`, `.sdh.ro.srt`, `.ron.srt`, and `.rum.srt`
- Added remote embedded Romanian probing through `translatarr-remote-extractor`
- Added remote embedded English extraction through `translatarr-remote-extractor`
- Added Gemini and LibreTranslate provider support with all secrets supplied through environment variables
- Added public-safe Docker Compose and README examples with placeholder values only
- Added GitHub Actions publishing workflow for `ghcr.io/addonniss/translatarr-decision-service`
- Documented Radarr/Sonarr webhook setup and added query/header token auth options for easier integration
- Accepted Radarr/Sonarr test webhook pings without requiring a real media file path
- Treated path-less Radarr/Sonarr webhook payloads as accepted no-op pings instead of returning `400 BadRequest`
- Documented `TRANSLATION_PROVIDER` options directly in the Docker Compose example
- Added Discord notifications for queued, checking, stopped, translating, translated, no-source, and failed decision steps
- Ported the proven `project.bazaar` translation strategy: prefixed `Lxxx:` lines, exact line-count validation, retry/shrink chunks, `[BR]` line-break preservation, Gemini SDK usage metadata, and LibreTranslate batch-list handling
- Documented `GEMINI_FAST_MODE=false` meaning directly in the Docker Compose example
- Added `TRANSLATION_STYLE` for Gemini prompt control, aligned with `service.translatarr` style modes
- Kept localization guidance always enabled for Gemini prompts, matching `service.translatarr`
- Added Discord notifications for embedded target probing, embedded source extraction start, and source extraction completion
- Added `SAVE_SOURCE_SUBTITLE` and `DECISION_SOURCE_LANGUAGE_SUFFIX` so extracted embedded source subtitles can be saved next to media before translation
- Added `TRANSLATION_BATCH_SIZE: "100"` to the Docker Compose example to match the tested Portainer stack
- Switched Discord notifications from plain text to embed formatting similar to `project.bazaar`
- Included Gemini thought-token usage in translated Discord summaries
- Made the `Verified Save - Protected Mode` Discord footer reflect real save logic: atomic write, fsync, file verification, and optional read-only chmod through `PROTECT_SAVED_SUBTITLES`
