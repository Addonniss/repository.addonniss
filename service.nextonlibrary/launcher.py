# -*- coding: utf-8 -*-
import os
import sys

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

ADDON_ID = "service.nextonlibrary"
ADDON = xbmcaddon.Addon(ADDON_ID)


def log(message, level=xbmc.LOGINFO):
    xbmc.log("[S.I.N.][Launcher] %s" % message, level)


def show_changelog():
    try:
        addon_path = ADDON.getAddonInfo("path")
        changelog_path = os.path.join(addon_path, "changelog.txt")

        if xbmcvfs.exists(changelog_path):
            handle = xbmcvfs.File(changelog_path)
            content = handle.read()
            handle.close()
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="replace")
        else:
            content = "No changelog available."
            log("Changelog not found at %s" % changelog_path, xbmc.LOGWARNING)

        xbmcgui.Dialog().textviewer(
            "%s - Changelog" % ADDON.getAddonInfo("name"),
            content,
        )
    except Exception as exc:
        log("Failed to open changelog: %s" % exc, xbmc.LOGERROR)
        xbmcgui.Dialog().ok(
            ADDON.getAddonInfo("name"),
            "Error opening changelog:\n%s" % exc,
        )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "show_changelog":
        show_changelog()
    else:
        ADDON.openSettings()
