# Repository Map

This repository hosts a Kodi addon repository and multiple addons.

## Root
Responsible for packaging and publishing addons.

Main file:
- create_repository.py → builds repository zips and metadata

Generated files:
- addons.xml
- addons.xml.md5
- index.html

## Addons

### service.translatarr
Kodi service addon responsible for subtitle translation during playback.

Key files:
- addon.xml → addon metadata, Kodi service registration, and script entry definition
- service.py → service lifecycle, polling, playback monitoring, and subtitle apply/reload logic
- launcher.py → direct-launch entry that opens settings or dispatches script actions
- translator.py → provider selection, prompt construction, batch translation, and response cleanup
- languages.py → language mapping, ISO variants, and settings compatibility
- file_manager.py → subtitle path resolution, SRT parsing, and translated file writing
- ui.py → progress dialog, stats dialog, and user-facing notifications
- resources/settings.xml → addon configuration for provider, language, chunking, and behavior options
- resources/language/resource.language.en_gb/strings.po → localized labels and settings text

Primary concerns:
- subtitle flicker
- duplicate subtitle processing
- translation provider integration

### script.kodiarr.instant
Kodi script addon providing context menu actions to send items to Radarr or Sonarr.

Key files:
- addon.xml → addon metadata, script registration, and context menu visibility rules
- default.py → context menu entry point that dispatches into the router
- launcher.py → opens settings when launched directly and routes scripted actions
- resources/lib/router.py → action detection and Radarr/Sonarr routing
- resources/lib/context.py → extracts movie, show, season, and episode identifiers from Kodi
- resources/lib/radarr.py → Radarr connection test, lookup, add, and search flow
- resources/lib/sonarr.py → Sonarr connection test, lookup, add, and search flow
- resources/lib/common.py → shared logging, notifications, settings, and URL helpers
- resources/settings.xml → addon configuration for Radarr and Sonarr connectivity

Primary concerns:
- metadata extraction from Kodi ListItem
- Radarr API integration
- Sonarr API integration
- user notification reliability

## Important rule

Each addon is independent.

Agents must treat:
- service.translatarr
- script.kodiarr.instant

as separate projects.

Agents should read the AGENTS.md inside each addon before making changes.
