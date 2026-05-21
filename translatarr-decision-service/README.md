# Translatarr Decision Service

Docker-first decision service for Radarr/Sonarr subtitle workflows.

Purpose:
- let Radarr/Sonarr start an independent subtitle decision job on import, upgrade, or rename
- give Bazarr time to search normal Romanian subtitle providers
- avoid paying for translation when Romanian already exists as a sidecar or embedded subtitle
- use `translatarr-remote-extractor` for embedded subtitle probing and source extraction

This service is designed for public GitHub. Do not commit real API keys, private IPs, Discord webhooks, or local hostnames. Put real values only in Portainer, Docker secrets, `.env` files that are not committed, or your local deployment notes.

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

Bazarr should remain connected to Radarr/Sonarr so it can keep its database current and search Romanian providers for new content. Disable unreliable embedded subtitle extraction in Bazarr if this service is responsible for embedded checks.

## API

- `GET /health`
- `GET /jobs`
- `POST /radarr`
- `POST /sonarr`

If `DECISION_API_TOKEN` is set, send:

```text
Authorization: Bearer YOUR_TOKEN
```

The service also accepts either of these forms for integrations where custom bearer headers are awkward:

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

## Docker Compose

For normal deployment, use the published image:

```yaml
services:
  translatarr-decision-service:
    image: ghcr.io/addonniss/translatarr-decision-service:latest
    container_name: translatarr-decision-service
    ports:
      - "8098:8098"
    environment:
      DECISION_API_TOKEN: "replace-with-your-token"
      DECISION_DELAY_SECONDS: "600"
      REMOTE_EXTRACTOR_URL: "http://your-extractor-host:8097"
      REMOTE_EXTRACTOR_TOKEN: "replace-with-your-token"
      REMOTE_EXTRACTOR_TIMEOUT: "900"
      TRANSLATION_PROVIDER: "gemini"
      GEMINI_API_KEY: "replace-with-your-key"
      GEMINI_MODEL: "gemini-2.0-flash"
      LIBRETRANSLATE_URL: ""
      LIBRETRANSLATE_API_KEY: ""
      LIBRETRANSLATE_SOURCE: "en"
      LIBRETRANSLATE_TARGET: "ro"
      MEDIA_PATH_MAPS: >
        [
          {"from": "/path/on/radarr-or-sonarr/media/", "to": "/data/media/"}
        ]
    volumes:
      - /path/to/your/media:/data/media
    restart: unless-stopped
```

For local development from source:

```bash
docker compose up -d --build
```

## Image Publishing

This project is set up to publish a container image to GHCR using:

```text
.github/workflows/translatarr_decision_service_image.yml
```

Published image name:

```text
ghcr.io/addonniss/translatarr-decision-service:latest
```

The workflow publishes:
- `latest`
- a commit-SHA tag

## Environment Variables

- `DECISION_API_TOKEN`
  - optional bearer token for `/radarr`, `/sonarr`, and `/jobs`
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
- `GEMINI_API_KEY`
  - required when `TRANSLATION_PROVIDER=gemini`
- `GEMINI_MODEL`
  - default: `gemini-2.0-flash`
- `GEMINI_TEMPERATURE`
  - default: `0.1`
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
  - number of subtitle cues sent through each translation batch
  - default: `60`
- `DISCORD_WEBHOOK_URL`
  - optional notification webhook
- `MEDIA_PATH_MAPS`
  - JSON array mapping Radarr/Sonarr paths to paths visible inside this container

Example path mapping:

```yaml
environment:
  MEDIA_PATH_MAPS: >
    [
      {"from": "/mnt/media/", "to": "/data/media/"},
      {"from": "\\\\your-server\\media\\", "to": "/data/media/"}
    ]
```

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

## Radarr/Sonarr Setup

The link with Radarr and Sonarr is a Connect webhook. Radarr/Sonarr call this service; this service does not need Radarr or Sonarr API keys for the delayed decision flow.

Radarr:
- Settings -> Connect -> add Webhook
- Method: `POST`
- URL: `http://your-decision-service-host:8098/radarr?token=replace-with-your-token`
- Trigger on import, upgrade, and rename events

Sonarr:
- Settings -> Connect -> add Webhook
- Method: `POST`
- URL: `http://your-decision-service-host:8098/sonarr?token=replace-with-your-token`
- Trigger on import, upgrade, and rename events

Generic webhook URL examples:

```text
http://your-decision-service-host:8098/radarr
http://your-decision-service-host:8098/sonarr
```

Keep Bazarr connected to Radarr/Sonarr and configure Bazarr to search Romanian providers. The decision service waits before acting, so Bazarr has time to save a provider subtitle first.
