# -*- coding: utf-8 -*-
import xbmc
import xbmcgui
import xbmcaddon

ADDON_ID = "script.kodiarr.instant"


def _get_addon():
    return xbmcaddon.Addon(ADDON_ID)


def log(msg, level=xbmc.LOGINFO):
    xbmc.log("[KodiARR Instant] {}".format(msg), level)


def notify(title, message, icon=xbmcgui.NOTIFICATION_INFO):
    xbmcgui.Dialog().notification(title, message, icon, 5000)


def alert(title, message):
    xbmcgui.Dialog().ok(title, message)


def get_setting(key, default=""):
    try:
        value = _get_addon().getSetting(key)
        return value if value != "" else default
    except Exception:
        return default


def get_int(key, default=0):
    try:
        return int(get_setting(key, str(default)))
    except Exception:
        return default


def set_setting(key, value):
    try:
        _get_addon().setSetting(key, "" if value is None else str(value))
        return True
    except Exception:
        return False


def get_addon_path():
    try:
        return _get_addon().getAddonInfo("path")
    except Exception:
        return ""


def clean_url(url):
    return (url or "").strip().rstrip("/")


def open_settings():
    try:
        _get_addon().openSettings()
    except Exception:
        pass
