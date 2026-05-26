# Changelog

## 2026-03-30

### Changed
- Moved timeout control into the `/probe` and `/extract` request payload so `service.translatarr` now drives the real extractor command timeout directly
- Simplified timeout configuration to one shared `EXTRACTOR_TIMEOUT` for probe and extraction commands across both `MKV` and `MP4`
- Updated Docker Compose examples and environment-variable documentation to remove the separate `EXTRACTOR_FFMPEG_TIMEOUT`
- Updated the README to reflect the current live API: `GET /health`, `POST /probe`, and `POST /extract`
- Updated deployment guidance to describe current production-validated Docker / Portainer behavior instead of earlier scaffold/planned wording
- Added generic `dav://` path-mapping examples alongside `smb://` and UNC examples
- Added a controlled fallback for unlabeled text subtitle tracks when no explicit language match exists, preferring unlabeled non-SDH tracks before unlabeled SDH tracks

### Fixed
- Fixed embedded subtitle track selection so `/probe` and `/extract` now require a real language match instead of incorrectly accepting unrelated text subtitle tracks based on generic scoring or short ISO-code substring matches inside track names
- Kept `/probe` strict for target-language detection so unlabeled subtitle fallback is only used during source extraction, not when deciding whether a target-language embedded subtitle already exists
- Removed the previous timeout mismatch where Kodi could wait longer than the extractor server, or the extractor server could stop earlier than Kodi expected
- Clarified that successful path mapping alone is not enough if the container cannot resolve the real underlying symlink or mounted target path

## 2026-03-29

### Added
- Documented the current production-validated remote extractor workflow for `service.translatarr`
- Documented support expectations for path mapping from Kodi playback paths to mounted container paths
- Documented symlink-backed media as a supported scenario when the real target path is also mounted inside the container
