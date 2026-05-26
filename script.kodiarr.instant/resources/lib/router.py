# -*- coding: utf-8 -*-
import os
import sys
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from . import radarr, sonarr
from .common import log, notify


def _get_action():
    argv = [str(x).lower() for x in sys.argv]
    argv_text = " ".join(argv)

    if "action=test_radarr" in argv_text:
        return "test_radarr"
    if "action=test_sonarr" in argv_text:
        return "test_sonarr"
    if "action=open_radarr_settings" in argv_text:
        return "open_radarr_settings"
    if "action=open_sonarr_settings" in argv_text:
        return "open_sonarr_settings"
    if "action=show_changelog" in argv_text:
        return "show_changelog"

    if "radarr" in argv:
        return "radarr"
    if "sonarr" in argv:
        return "sonarr"

    if "action=radarr" in argv_text:
        return "radarr"
    if "action=sonarr" in argv_text:
        return "sonarr"

    return None


def run():
    action = _get_action()
    log("Router action={}".format(action))
    log("sys.argv={}".format(sys.argv))

    if action == "test_radarr":
        radarr.test_connection(show_notification=True)
        return

    if action == "test_sonarr":
        sonarr.test_connection(show_notification=True)
        return

    if action == "open_radarr_settings":
        from .config_flow import open_radarr_settings
        open_radarr_settings()
        return

    if action == "open_sonarr_settings":
        from .config_flow import open_sonarr_settings
        open_sonarr_settings()
        return

    if action == "show_changelog":
        addon = xbmcaddon.Addon("script.kodiarr.instant")
        changelog_path = os.path.join(addon.getAddonInfo("path"), "changelog.txt")

        if xbmcvfs.exists(changelog_path):
            changelog_file = xbmcvfs.File(changelog_path)
            content = changelog_file.read()
            changelog_file.close()
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="replace")
        else:
            content = "No changelog available."

        xbmcgui.Dialog().textviewer(
            "{} - Change Log".format(addon.getAddonInfo("name")),
            content,
        )
        return

    if action == "radarr":
        log("Calling radarr.run()")
        radarr.run()
        return

    if action == "sonarr":
        log("Calling sonarr.run()")
        sonarr.run()
        return

    db_type = xbmc.getInfoLabel("ListItem.DBTYPE").lower()
    item_type = xbmc.getInfoLabel("ListItem.Property(item.type)").lower()

    if db_type == "movie" or item_type == "movie":
        log("Fallback routing to Radarr")
        radarr.run()
        return

    if db_type in ["tvshow", "season", "episode"] or item_type in ["tvshow", "season", "episode"]:
        log("Fallback routing to Sonarr")
        sonarr.run()
        return

    notify("KodiARR Instant", "Unsupported item type")
