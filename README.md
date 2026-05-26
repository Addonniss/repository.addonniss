# Addonniss Kodi Repository

This repository hosts the Kodi add-ons published by Addonniss, plus the companion service used by Translatarr for remote embedded subtitle extraction.

## What’s Included

| Add-on | Type | What it does | Docs |
| --- | --- | --- | --- |
| **Translatarr** (`service.translatarr`) | Kodi service | Detects subtitles during playback, translates them into your selected target language, writes a translated `.srt`, and switches playback automatically. Supports Gemini, OpenAI, DeepL Free, and LibreTranslate, plus optional dual-language display, SDH/HI cue removal, embedded subtitle extraction, and the remote extractor companion service. | [README](service.translatarr/README.md) · [Changelog](service.translatarr/changelog.txt) |
| **Skip.Intro.Next (S.I.N.)** (`service.nextonlibrary`) | Kodi service | Adds two lightweight playback helpers for TV episodes: `Skip Intro` and `Next On`. It can use online metadata from TheIntroDB and IntroDB.app, local chapter markers, a manual fallback intro window, and a fallback percentage trigger for the next-episode prompt. | [README](service.nextonlibrary/README.md) · [Changelog](service.nextonlibrary/changelog.txt) |
| **KodiARR Instant** (`script.kodiarr.instant`) | Kodi script | Adds context menu actions for sending movies to Radarr and TV shows, seasons, or episodes to Sonarr. Includes instant context menu entries, connection test actions, add-and-search flows, and a custom settings UI for quick setup. | [README](script.kodiarr.instant/README.md) · [Changelog](script.kodiarr.instant/changelog.txt) |
| **Translatarr Remote Extractor** (`translatarr-remote-extractor`) | Companion service | Docker-first companion service for `service.translatarr` that provides remote embedded subtitle extraction, `/health`, `/probe`, and `/extract` endpoints, bearer-token authentication, and path mapping for `smb://`, UNC, and `dav://` playback paths. | [README](translatarr-remote-extractor/README.md) · [Changelog](translatarr-remote-extractor/CHANGELOG.md) |

## Install

1. Add the repository as a source in Kodi's File Manager:

   `https://addonniss.github.io/repository.addonniss/zips/repository.addonniss/`

2. Or install the current repository zip directly from GitHub Pages:

   `https://addonniss.github.io/repository.addonniss/zips/repository.addonniss/repository.addonniss-1.0.1.zip`

3. In Kodi, go to `Add-ons` > `Install from zip file`, select the repository zip, then install the add-ons you want from `Install from repository`.

## Repository Notes

- This repo is structured for Kodi repository generation and GitHub Pages publishing.
- Each add-on is maintained as an independent project.


## Support

If you enjoy the project and want to support future development, you can donate here:

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-Donate-yellow.svg?style=for-the-badge&logo=buy-me-a-coffee)](https://www.buymeacoffee.com/addonniss)
