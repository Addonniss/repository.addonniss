# -*- coding: utf-8 -*-
import sys
import os
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

ADDON_ID = "service.translatarr"
ADDON = xbmcaddon.Addon(ADDON_ID)


def log(message, level="info"):
    levels = {
        "debug": xbmc.LOGDEBUG,
        "info": xbmc.LOGINFO,
        "warning": xbmc.LOGWARNING,
        "error": xbmc.LOGERROR
    }
    xbmc.log(f"[Translatarr][Launcher] {message}", levels.get(level, xbmc.LOGINFO))


def show_changelog():
    try:
        addon_path = ADDON.getAddonInfo('path')
        changelog_path = os.path.join(addon_path, 'changelog.txt')

        log(f"Attempting to show changelog from: {changelog_path}", "debug")

        if xbmcvfs.exists(changelog_path):
            f = xbmcvfs.File(changelog_path)
            content = f.read()
            f.close()

            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="replace")

            log("Changelog loaded successfully.", "debug")
        else:
            content = "No changelog available."
            log("Changelog not found.", "warning")

        xbmcgui.Dialog().textviewer(
            f"{ADDON.getAddonInfo('name')} - Change Log",
            content
        )

    except Exception as e:
        log(f"Failed to open changelog: {e}", "error")
        xbmcgui.Dialog().ok(
            ADDON.getAddonInfo('name'),
            f"Error opening changelog:\n{e}"
        )


if __name__ == "__main__":

    # If script called with parameter
    if len(sys.argv) > 1:
        param = sys.argv[1]

        if param == "show_changelog":
            show_changelog()
        else:
            ADDON.openSettings()

    else:
        # Default action: open settings
        ADDON.openSettings()
