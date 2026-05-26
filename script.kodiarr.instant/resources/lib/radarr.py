# -*- coding: utf-8 -*-
import requests
import xbmc
import xbmcgui

from .common import get_setting, get_int, clean_url, notify, alert, log, open_settings
from .context import get_movie_id


def _get_connection_values(url=None, api=None):
    return clean_url(url or get_setting("radarr_url")), (api or get_setting("radarr_api")).strip()


def _get_status(radarr_url, headers):
    return requests.get(
        "{}/api/v3/system/status".format(radarr_url),
        headers=headers,
        timeout=10
    )


def test_connection(show_notification=True, url=None, api=None):
    radarr_url, api = _get_connection_values(url, api)

    if not radarr_url or not api:
        if show_notification:
            alert("Radarr", "Please fill Radarr URL and API key.")
        log("Radarr test: missing URL or API key", xbmc.LOGERROR)
        return False

    headers = {"X-Api-Key": api}

    try:
        resp = _get_status(radarr_url, headers)

        if resp.status_code == 200:
            data = resp.json()
            version = data.get("version", "unknown")
            if show_notification:
                alert("Radarr", "Connection OK ({})".format(version))
            return True

        if show_notification:
            alert("Radarr", "Connection failed: HTTP {}".format(resp.status_code))
        log("Radarr test failed: {}".format(resp.text), xbmc.LOGERROR)
        return False

    except Exception as e:
        if show_notification:
            alert("Radarr", "Connection error:\n{}".format(e))
        log("Radarr test crash: {}".format(e), xbmc.LOGERROR)
        return False


def fetch_setup_options(url=None, api=None):
    radarr_url, api = _get_connection_values(url, api)
    if not radarr_url or not api:
        raise ValueError("Please fill Radarr URL and API key.")

    headers = {"X-Api-Key": api}

    root_resp = requests.get(
        "{}/api/v3/rootfolder".format(radarr_url),
        headers=headers,
        timeout=10
    )
    root_resp.raise_for_status()

    profile_resp = requests.get(
        "{}/api/v3/qualityprofile".format(radarr_url),
        headers=headers,
        timeout=10
    )
    profile_resp.raise_for_status()

    roots = [item.get("path", "").strip() for item in root_resp.json() if item.get("path")]
    profiles = [
        {"id": item.get("id"), "name": item.get("name", "").strip()}
        for item in profile_resp.json()
        if item.get("id") is not None and item.get("name")
    ]

    return {"roots": roots, "profiles": profiles}


def run():
    radarr_url = clean_url(get_setting("radarr_url"))
    api = get_setting("radarr_api")
    root = get_setting("radarr_root")
    profile = get_int("radarr_quality_profile", 1)

    if not radarr_url or not api or not root:
        notify("Radarr", "Please configure settings", xbmcgui.NOTIFICATION_ERROR)
        open_settings()
        return

    id_val, id_type = get_movie_id()

    if not id_val:
        notify("Radarr", "No movie ID found", xbmcgui.NOTIFICATION_ERROR)
        return

    headers = {"X-Api-Key": api}
    term = "{}:{}".format(id_type, str(id_val).strip())

    try:
        notify("Radarr", "Searching {}".format(term))

        lookup = requests.get(
            "{}/api/v3/movie/lookup?term={}".format(radarr_url, term),
            headers=headers,
            timeout=10
        )

        if lookup.status_code != 200:
            notify("Radarr", "Lookup failed: {}".format(lookup.status_code), xbmcgui.NOTIFICATION_ERROR)
            log("Radarr lookup failed: {}".format(lookup.text), xbmcgui.LOGERROR)
            return

        movies = lookup.json()
        if not movies:
            notify("Radarr", "Movie not found", xbmcgui.NOTIFICATION_ERROR)
            return

        movie = movies[0]
        title = movie.get("title", "Unknown")

        if not movie.get("tmdbId"):
            notify("Radarr", "Invalid lookup result", xbmcgui.NOTIFICATION_ERROR)
            log("Radarr invalid lookup payload: {}".format(movie), xbmcgui.LOGERROR)
            return

        if movie.get("id", 0) > 0:
            movie_id = movie["id"]

            cmd = requests.post(
                "{}/api/v3/command".format(radarr_url),
                json={"name": "MoviesSearch", "movieIds": [movie_id]},
                headers=headers,
                timeout=10
            )

            if cmd.status_code in (200, 201):
                notify("Radarr", "'{}' already exists. Search triggered.".format(title))
            else:
                notify("Radarr", "Movie exists, but search failed", xbmcgui.NOTIFICATION_ERROR)
                log("Radarr command failed: {}".format(cmd.text), xbmcgui.LOGERROR)
            return

        payload = {
            "title": movie["title"],
            "qualityProfileId": profile,
            "rootFolderPath": root,
            "tmdbId": movie["tmdbId"],
            "year": movie.get("year"),
            "images": movie.get("images", []),
            "monitored": True,
            "addOptions": {"searchForMovie": True}
        }

        add_resp = requests.post(
            "{}/api/v3/movie".format(radarr_url),
            json=payload,
            headers=headers,
            timeout=15
        )

        if add_resp.status_code == 201:
            added = add_resp.json()
            new_id = added["id"]

            requests.post(
                "{}/api/v3/command".format(radarr_url),
                json={"name": "MoviesSearch", "movieIds": [new_id]},
                headers=headers,
                timeout=10
            )

            notify("Radarr", "Added '{}'. Search started.".format(title))
        else:
            notify("Radarr", "Add failed: {}".format(add_resp.status_code), xbmcgui.NOTIFICATION_ERROR)
            log("Radarr add failed: {}".format(add_resp.text), xbmcgui.LOGERROR)

    except Exception as e:
        notify("Radarr", "Error: {}".format(e), xbmcgui.NOTIFICATION_ERROR)
        log("Radarr crash: {}".format(e), xbmcgui.LOGERROR)
