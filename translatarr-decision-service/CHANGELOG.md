# Changelog

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
