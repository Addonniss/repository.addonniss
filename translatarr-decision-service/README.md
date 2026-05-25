# Translatarr Decision Service

Docker-first subtitle decision service for Radarr/Sonarr imports.

Purpose:
- let Radarr/Sonarr start an independent delayed decision job on import, upgrade, or rename
- give Bazarr time to search normal Romanian subtitle providers first
- avoid paying for translation when Romanian already exists as a sidecar or embedded subtitle
- use `translatarr-remote-extractor` for embedded subtitle probing and English source extraction
- translate only after all no-cost checks have failed

This project is public-safe. Do not commit real API keys, private IPs, Discord webhooks, local hostnames, or deployment tokens. Put real values only in Portainer, Docker secrets, ignored `.env` files, or private local notes.

## Current Status

Validated behavior:
- Radarr and Sonarr Connect webhooks can call `/radarr` and `/sonarr`
- Radarr/Sonarr Test pings are accepted as no-op events
- real media events queue delayed jobs
- `MEDIA_PATH_MAPS: "[]"` works when Radarr/Sonarr already send paths visible inside the container
- Bazarr provider sidecar found during the delay stops the job before translation
- embedded Romanian subtitles stop the job before extraction or translation
- Discord decision-step notifications are available
- Gemini translation uses the proven prefixed-line strategy from `project.bazaar`

Still worth testing on your own library:
- no sidecar + no embedded Romanian + embedded English -> extract English and translate
- no sidecar + no embedded Romanian + no embedded English -> no-source notification

## Flow

Recommended production flow:

```text
Radarr/Sonarr import, upgrade, or rename
  |-- Bazarr wakes and searches Romanian providers
  `-- Translatarr Decision Service queues a delayed job

Delayed decision job:
  wait 10 minutes
  check Romanian sidecar subtitles
    yes -> stop
  probe embedded Romanian subtitles
    yes -> stop
  extract embedded English subtitles
    yes -> translate to Romanian sidecar
  no English -> log no source
```

Bazarr should remain connected to Radarr/Sonarr so its database stays current and it can search Romanian providers for new content. Disable unreliable embedded subtitle extraction in Bazarr if this service is responsible for embedded checks.

## API

- `GET /health`
- `GET /jobs`
- `POST /radarr`
- `POST /sonarr`

If `DECISION_API_TOKEN` is set, auth can be sent in any of these forms:

```text
Authorization: Bearer YOUR_TOKEN
```

```text
X-Decision-Token: YOUR_TOKEN
```

```text
http://your-decision-service-host:8098/radarr?token=YOUR_TOKEN
```

`/radarr` and `/sonarr` accept normal JSON webhook payloads. They also accept simple custom-script style keys such as:

```json
{
  "eventType": "Download",
  "movieFile": {
    "path": "/data/media/movies/Example Movie (2026)/Example Movie (2026).mkv"
  }
}
```

```json
{
  "eventType": "Download",
  "episodeFile": {
    "path": "/data/media/tv/Example Show/Season 01/Example Show - S01E01.mkv"
  }
}
```

Radarr/Sonarr Test buttons may send payloads without a real media file path. The service accepts those pings and returns success without queueing a translation job.

## Docker Compose

For normal deployment, use the published image:

```yaml
services:
  translatarr-decision-service:
    image: ghcr.io/addonniss/translatarr-decision-service:latest
    container_name: translatarr-decision-service
    restart: unless-stopped
    ports:
      - "8098:8098"
    environment:
      DECISION_API_TOKEN: "replace-with-your-token"
      DECISION_DELAY_SECONDS: "600"
      DECISION_TARGET_LANGUAGE_NAME: "Romanian"
      DECISION_TARGET_LANGUAGE_SUFFIX: "ro"
      DECISION_SOURCE_LANGUAGE_NAME: "English"
      DECISION_SOURCE_LANGUAGE_SUFFIX: "en"

      REMOTE_EXTRACTOR_URL: "http://your-extractor-host:8097"
      REMOTE_EXTRACTOR_TOKEN: "replace-with-your-token"
      REMOTE_EXTRACTOR_TIMEOUT: "900"

      # Translation provider options:
      # - gemini: paid Gemini API, requires GEMINI_API_KEY
      # - libretranslate: local/private LibreTranslate server, requires LIBRETRANSLATE_URL
      # - none: dry-run checks only; translation fails intentionally if needed
      TRANSLATION_PROVIDER: "gemini"

      # Translation style options for Gemini prompts:
      # - Family-Friendly: clean, neutral, avoids profanity
      # - Natural: conversational, realistic, avoids literal phrasing
      # - Gritty / Adult: raw adult tone, preserves profanity and insults
      # LibreTranslate does not support prompt-level style control.
      TRANSLATION_STYLE: "Gritty / Adult"

      GEMINI_API_KEY: "replace-with-your-key"
      GEMINI_MODEL: "gemini-2.0-flash"
      GEMINI_TEMPERATURE: "0.15"
      GEMINI_TOP_P: "0.95"
      # GEMINI_FAST_MODE only applies to gemini-2.5-flash.
      # false = normal model behavior; true = request thinking_budget 0 for faster/cheaper 2.5 Flash calls.
      GEMINI_FAST_MODE: "false"

      LIBRETRANSLATE_URL: ""
      LIBRETRANSLATE_API_KEY: ""
      LIBRETRANSLATE_SOURCE: "en"
      LIBRETRANSLATE_TARGET: "ro"

      TRANSLATION_BATCH_SIZE: "100"
      # Save extracted embedded English next to the movie before translation.
      # Useful for audit/debug/retry. Set false if you only want the Romanian output.
      SAVE_SOURCE_SUBTITLE: "true"
      # Applies to generated target subtitles. Uses atomic write + fsync + read-only chmod.
      PROTECT_SAVED_SUBTITLES: "true"
      DISCORD_WEBHOOK_URL: ""
      DISCORD_NOTIFY_STEPS: "true"

      # Leave [] when Radarr/Sonarr paths already exist inside this container.
      MEDIA_PATH_MAPS: "[]"

    volumes:
      # Must be writable because the service creates .ro.srt files.
      - /path/to/your/media:/data/media
```

Healthcheck is optional. The service exposes `/health`; adding a Docker healthcheck is useful for Portainer status, but the decision pipeline does not depend on it.

For local development from source:

```bash
docker compose up -d --build
```

## Environment Variables

- `DECISION_API_TOKEN`
  - optional bearer/query/header token for `/radarr`, `/sonarr`, and `/jobs`
- `DECISION_DELAY_SECONDS`
  - delay before making the final translation decision
  - default: `600`
- `DECISION_TARGET_LANGUAGE_NAME`
  - target language sent to the extractor probe
  - default: `Romanian`
- `DECISION_TARGET_LANGUAGE_SUFFIX`
  - sidecar suffix used when saving translated subtitles
  - default: `ro`
- `DECISION_SOURCE_LANGUAGE_NAME`
  - source language sent to the extractor extraction request
  - default: `English`
- `DECISION_SOURCE_LANGUAGE_SUFFIX`
  - source sidecar suffix used when saving extracted source subtitles
  - default: `en`
- `REMOTE_EXTRACTOR_URL`
  - base URL for `translatarr-remote-extractor`
- `REMOTE_EXTRACTOR_TOKEN`
  - optional bearer token for the extractor
- `REMOTE_EXTRACTOR_TIMEOUT`
  - timeout sent to extractor `/probe` and `/extract`
  - default: `900`
- `TRANSLATION_PROVIDER`
  - `gemini`, `libretranslate`, or `none`
  - default: `none`
- `TRANSLATION_STYLE`
  - Gemini prompt style: `Family-Friendly`, `Natural`, or `Gritty / Adult`
  - default: `Gritty / Adult`
  - LibreTranslate does not support prompt-level style control
- `GEMINI_API_KEY`
  - required when `TRANSLATION_PROVIDER=gemini`
- `GEMINI_MODEL`
  - default: `gemini-2.0-flash`
- `GEMINI_TEMPERATURE`
  - default: `0.1`
- `GEMINI_TOP_P`
  - default: `0.95`
- `GEMINI_FAST_MODE`
  - only applies to `gemini-2.5-flash`
  - `false` means normal model behavior
  - `true` requests `thinking_budget=0` for faster/cheaper 2.5 Flash calls
- `LIBRETRANSLATE_URL`
  - required when `TRANSLATION_PROVIDER=libretranslate`
  - example: `http://your-libretranslate-host:5000`
- `LIBRETRANSLATE_API_KEY`
  - optional LibreTranslate API key
- `LIBRETRANSLATE_SOURCE`
  - default: `en`
- `LIBRETRANSLATE_TARGET`
  - default: `ro`
- `TRANSLATION_BATCH_SIZE`
  - number of subtitle cues attempted first per translation batch
  - if validation fails, the service shrinks to `50`, then `25`
  - default: `60`
- `SAVE_SOURCE_SUBTITLE`
  - save extracted embedded source subtitles next to the media before translation
  - default: `true`
- `PROTECT_SAVED_SUBTITLES`
  - applies to generated target subtitles
  - writes atomically, fsyncs, verifies the saved file, then chmods read-only
  - default: `true`
- `DISCORD_WEBHOOK_URL`
  - optional notification webhook
- `DISCORD_NOTIFY_STEPS`
  - send Discord embed notifications for queued, checking, stopped, translating, translated, no-source, skipped, and failed decisions
  - default: `true`
- `MEDIA_PATH_MAPS`
  - JSON array mapping Radarr/Sonarr paths to paths visible inside this container

## Translation Engine

Gemini uses the proven `project.bazaar` style strategy:
- SRT text is converted to prefixed lines like `L000: text`
- Gemini must preserve the `Lxxx:` prefix
- Gemini must return the exact expected line count
- responses are retried and validated
- chunks shrink from `TRANSLATION_BATCH_SIZE` to `50` to `25` if validation fails
- `[BR]` markers preserve multi-line subtitle breaks
- localization guidance is always included for Gemini prompts, matching `service.translatarr`
- if `SAVE_SOURCE_SUBTITLE=true`, the extracted source subtitle is saved before translation, for example `.en.srt`

LibreTranslate uses the same prefixed-line validation pattern, but it cannot receive style or localization prompt instructions.

## Sidecar Detection

The service checks for Romanian sidecar `.srt` files before paying for translation.

Detected variants include:
- `.ro.srt`
- `.ro.sdh.srt`
- `.sdh.ro.srt`
- `.ron.srt`
- `.rum.srt`
- names containing `romanian`

The sidecar must belong to the same media filename stem, which avoids matching subtitles for another episode in the same season folder.

## Path Mapping

Start with:

```yaml
MEDIA_PATH_MAPS: "[]"
```

That is correct when Radarr/Sonarr send paths that already exist inside the container, such as:

```text
/data/media/movies/Example Movie (2026)/Example Movie (2026).mkv
```

Use mappings only when `/jobs` shows a media path that does not exist inside the container:

```yaml
environment:
  MEDIA_PATH_MAPS: >
    [
      {"from": "/mnt/media/", "to": "/data/media/"},
      {"from": "\\\\your-server\\media\\", "to": "/data/media/"}
    ]
```

## Radarr/Sonarr Setup

The link with Radarr and Sonarr is a Connect webhook. Radarr/Sonarr call this service; this service does not need Radarr or Sonarr API keys for the delayed decision flow.

Radarr:
- Settings -> Connect -> add Webhook
- Method: `POST`
- URL: `http://your-decision-service-host:8098/radarr?token=replace-with-your-token`
- Trigger on file import, file upgrade, and rename

Sonarr:
- Settings -> Connect -> add Webhook
- Method: `POST`
- URL: `http://your-decision-service-host:8098/sonarr?token=replace-with-your-token`
- Trigger on file import, file upgrade, and rename

Do not enable early or unrelated triggers such as grab, delete, health issue, application update, or manual interaction required.

Keep Bazarr connected to Radarr/Sonarr and configure Bazarr to search Romanian providers. The decision service waits before acting, so Bazarr has time to save a provider subtitle first.

## Operational Checks

PowerShell health check:

```powershell
Invoke-RestMethod "http://your-decision-service-host:8098/health"
```

PowerShell jobs check:

```powershell
(Invoke-RestMethod "http://your-decision-service-host:8098/jobs?token=YOUR_TOKEN").jobs |
  Format-List
```

PowerShell Radarr smoke test:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://your-decision-service-host:8098/radarr?token=YOUR_TOKEN" `
  -ContentType "application/json" `
  -Body '{"eventType":"Test","movieFile":{"path":"/data/media/movies/Test/Test.mkv"}}'
```

Expected real job outcomes:
- `Romanian sidecar already exists`
- `Embedded Romanian subtitle exists; no extraction or translation needed`
- `Translated Romanian sidecar saved`
- `No usable embedded English source subtitle found`

Discord step notifications can include:
- queued
- checking
- probing embedded Romanian
- extracting embedded English
- extracted source subtitle saved
- translating
- translated
- stopped
- no source
- failed

Discord messages use embed formatting similar to `project.bazaar`, with bold labels, inline-code values, and color status. General decision-step embeds use a `Decision Engine` footer. Translation-complete embeds use `Verified Save - Protected Mode` only after the target subtitle has been written atomically, fsynced, verified, and protected. Translation-complete embeds include model/provider, input tokens or chars, output tokens or chars, thought tokens for Gemini, and estimated cost.

## Image Publishing

This project publishes a container image to GHCR using:

```text
.github/workflows/translatarr_decision_service_image.yml
```

Published image:

```text
ghcr.io/addonniss/translatarr-decision-service:latest
```

The workflow publishes:
- `latest`
- a commit-SHA tag

If Portainer reuses a cached `latest` image, recreate the container with "Pull latest image" enabled, or deploy a commit-SHA tag for exact versioning.
