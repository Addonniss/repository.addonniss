# Translatarr

Translatarr is a Kodi service add-on that detects subtitles during playback, translates them into your selected target language, writes a translated `.srt`, and switches playback to the translated subtitle automatically.

It supports these translation providers:

- Gemini: [model docs](https://ai.google.dev/gemini-api/docs/models/gemini)
- OpenAI: [GPT-5.4 nano](https://platform.openai.com/docs/models/gpt-5.4-nano), [GPT-5 mini](https://platform.openai.com/docs/models/gpt-5-mini/), [GPT-4o mini](https://platform.openai.com/docs/models/gpt-4o-mini)
- Anthropic Claude: [models overview](https://platform.claude.com/docs/en/about-claude/models/overview)
- DeepSeek: [platform](https://platform.deepseek.com/) — V4 Flash
- DeepL Free: [API Free plan](https://support.deepl.com/hc/en-us/articles/360021200939-DeepL-API-Free)
- LibreTranslate: [documentation](https://docs.libretranslate.com/)

## What New Users Need To Know

Translatarr runs as a background service in Kodi. Once configured, it watches for subtitles while a video is playing and processes them according to the selected mode.

Main capabilities:

- automatic subtitle translation during playback
- manual subtitle-folder workflow for users who want a fixed watch folder
- optional dual-language display
- optional SDH/HI cue removal
- optional embedded subtitle extraction from MKV and MP4 files
- optional remote embedded-subtitle extraction through the companion [Translatarr Remote Extractor](https://github.com/addonniss/repository.addonniss/blob/main/translatarr-remote-extractor/README.md)

## What's New in v2.5.8

- Added **Thinking Level** control for Gemini 3.x models and **Reasoning Effort** control for OpenAI GPT-5 models, letting you choose how much the AI reasons before translating.
- Simplified model lists across all AI providers, keeping only the most cost-effective options for subtitle translation.
- Added **GPT-5.4 nano** as the new OpenAI default, the cheapest GPT-5 class model.
- Fixed and verified pricing for all AI providers against their current official rates.

## Previous Highlights in v2.5.2

- Added `Require translation confirmation (ALPHA)` for users who want to approve a detected source subtitle before Translatarr starts translating it.
- Source subtitles are loaded first so you can check whether they are usable before spending time or provider credits on translation.
- Added top-right `Translate`, `Remind in 60s`, and `Skip` playback overlay buttons for confirmation in Auto and Manual modes.
- Added `Translation confirmation delay` and `Reminder delay` settings so you can control the first prompt and later reminders.

## Previous Highlights in v2.4.17

- Added new Gemini model choices:
  - `Gemini 3.5 Flash`
  - `Gemini 3.1 Flash-Lite`
  - `Fast Mode - Gemini 3.1 Flash-Lite`
- Refined the Kodi settings flow so categories now read more naturally

## Quick Setup

Open:

`Kodi -> Add-ons -> Programs -> Translatarr -> Settings`

Configure these items first:

1. Enable the service.
2. Choose `Auto` or `Manual` translation mode.
3. Select a provider.
4. Enter the required provider credentials or server URL.
5. Set source and target languages.
6. Choose a model if you use Gemini, OpenAI, Anthropic Claude, or DeepSeek.

After that, start video playback and download or load subtitles as you normally would in Kodi.

## Translation Confirmation (ALPHA)

Translation Confirmation is optional. It is for users who download or switch source subtitles during playback and want to check sync before translation starts.

When enabled:

- Translatarr detects a source-language subtitle as usual.
- The source subtitle is loaded first.
- Translation is held as a pending candidate.
- After the configured delay, `Translate`, `Remind:XXs`, and `Skip` buttons appear during playback.
- `Translate` starts the normal translation flow.
- `Remind:XXs`, Back, navigation, or seeking hides the prompt temporarily and shows it again after the configured reminder delay.
- `Skip` suppresses that subtitle candidate for the current playback session.

Important limitations:

- This is marked ALPHA because Kodi overlay focus is not seamless on all skins and devices.
- When the confirmation prompt appears, it takes focus.
- The default focused action is the reminder button, so accidental select/back/navigation behavior should not skip the subtitle candidate.
- If your subtitle download UI or player controls stay visible, increase `Translation confirmation delay` to give yourself more time to close Kodi UI and judge subtitle sync.

This confirmation applies to normal detected external source subtitles in Auto and Manual modes. Existing target-language subtitles still skip translation, and embedded source extraction keeps its direct flow.

## Translation Modes

### Auto

Auto mode is the default. Translatarr looks for usable subtitles during playback in the normal locations Kodi and subtitle add-ons use, including sidecar subtitles next to the video when available.

Use Auto if you want the least manual setup.

### Manual

Manual mode watches a specific subtitle folder that you choose in the Translatarr settings.

For Manual mode to work reliably:

- set a writable subtitle folder in Translatarr
- set Kodi's subtitle storage location to the same folder

Use Manual if you want predictable folder-based behavior or if your subtitle add-on saves files into a custom location.

## Providers

### Gemini

Requires a Gemini API key. Model selection is available in settings:

- `Gemini 3.1 Flash-Lite` (default) — best balance of quality and cost for most users
- `Gemini 2.5 Flash-Lite` — the cheapest option for high-throughput translation

A **Thinking Level** setting is available for Gemini 3.x models, controlling how much the model reasons before translating. Options are Minimal (default, fastest), Low, Medium, and High.

### OpenAI

Requires an OpenAI API key. Model selection is available in settings:

- `gpt-5.4-nano` (default) — the cheapest GPT-5 class model, ideal for high-volume translation
- `gpt-5-mini` — a faster GPT-5 option with good quality
- `gpt-4o-mini` — a proven low-cost non-reasoning model

A **Reasoning Effort** setting is available for GPT-5 models, controlling how much the model reasons before translating. Options are Minimal (default, fastest), Low, Medium, and High.

### Anthropic Claude

Requires an Anthropic API key. Translatarr uses **Claude Haiku 4.5**, the most cost-effective Claude model for translation.

### DeepSeek

DeepSeek uses an OpenAI-compatible API. Translatarr sends translation requests directly to the DeepSeek chat completions endpoint.

Translatarr uses **DeepSeek V4 Flash**, a fast, low-cost option that delivers strong translation quality for everyday subtitle translation.

### DeepL Free

Requires a DeepL API key. DeepL API Free includes 500,000 characters per month, which is roughly enough for about 10 movies on average. Available languages depend on what DeepL Free supports.

Recommended usage:

- `DeepL Free`: best when you want very fast, predictable machine translation with simple setup and supported-language pairs.
- It is a strong choice for users who value speed and consistency more than LLM-style tone shaping.

### LibreTranslate

Requires a LibreTranslate server URL. An API key is optional if your server requires one.

Use a full base URL, for example:

`http://your-server:5000`

Recommended usage:

- `LibreTranslate`: best when you want a self-hosted or home-network translation option with more privacy and no dependency on commercial cloud APIs.
- It is especially useful if you already run your own server and want local-network control over subtitle translation.

## Pricing

All LLM-based providers charge per token (input + output). Prices below are in **USD per 1 million tokens**, which is the standard unit used by most providers.

| Provider | Model | Input ($/1M) | Output ($/1M) |
|---|---|---|---|
| **DeepSeek** | V4 Flash | $0.14 | $0.28 |
| **Gemini** | 2.5 Flash-Lite | $0.10 | $0.40 |
| **OpenAI** | gpt-4o-mini | $0.15 | $0.60 |
| | gpt-5.4-nano | $0.20 | $1.25 |
| **Gemini** | 3.1 Flash-Lite | $0.25 | $1.50 |
| **OpenAI** | gpt-5-mini | $0.25 | $2.00 |
| **Anthropic** | Claude Haiku 4.5 | $1.00 | $5.00 |

**DeepL Free** — Free tier with 500,000 characters per month (~10 movies). No per-token billing.

**LibreTranslate** — Free. You host the server yourself, so there are no API costs.

> **Tip:** For a typical movie subtitle (~3,000–5,000 tokens), even the most expensive model costs only a few cents per translation. Budget-friendly options like Gemini 2.5 Flash-Lite or DeepSeek V4 Flash cost fractions of a cent.

## Embedded Subtitle Extraction

Enable embedded subtitle extraction only if you need to work from subtitle tracks stored inside MKV or MP4 files.

There are two supported extraction paths:

- local extraction tools
- remote extraction through Translatarr Remote Extractor

### Local Extraction

If you enable local extraction, configure the tool folders in settings:

- `mkvinfo` and `mkvextract` for MKV
- `ffmpeg` and `ffprobe` for MP4

Local extraction works best when Kodi exposes the video as a real filesystem path.

### Remote Extraction

Use Translatarr Remote Extractor if Kodi cannot run local extraction tools reliably on the playback device, or if the media is better accessed from another machine.

It is the recommended setup for Android and NVIDIA Shield devices.

If you enable it, configure:

- Remote Extractor URL
- bearer token if your remote service uses authentication
- timeout

The remote service must be able to resolve the playing media path to a real mounted media path on the server.

See the companion project here:

[Translatarr Remote Extractor](https://github.com/addonniss/repository.addonniss/blob/main/translatarr-remote-extractor/README.md)

## Optional Settings

These settings are not required for first-time setup, but they affect output:

- `Dual-Language Display`: shows source text together with the translation
- `Translation Style`: controls tone for supported LLM providers
- `Dialogue Lines Per Chunk`: adjusts request size and can help with provider stability
- `Remove SDH/HI Cues`: removes hearing-impaired subtitle cues while keeping dialogue
- `Show Stats` and `Notifications`: controls user-facing feedback in Kodi

## Troubleshooting

If translation does not start:

- confirm the service is enabled
- confirm a video is actively playing
- confirm the correct provider is selected
- confirm the provider key or LibreTranslate URL is valid
- in Manual mode, confirm Kodi and Translatarr use the same subtitle folder

If embedded extraction does not work:

- confirm embedded extraction is enabled
- confirm the required local tools are configured, or the remote extractor is configured
- confirm the media path is accessible to the selected extraction method

If subtitles are detected but translation fails:

- lower the chunk size
- verify the selected source and target languages
- verify the provider-specific configuration for the selected service

## Notes

- Translatarr is designed for subtitle translation during playback, not bulk subtitle processing outside Kodi.
- The add-on includes a changelog viewer in Kodi through the launcher entry point.
