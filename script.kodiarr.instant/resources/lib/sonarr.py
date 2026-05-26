# -*- coding: utf-8 -*-
import requests
import xbmc
import xbmcgui

from .common import get_setting, get_int, clean_url, notify, alert, log, open_settings
from .context import get_sonarr_context


def _get_connection_values(url=None, api=None):
    return clean_url(url or get_setting("sonarr_url")), (api or get_setting("sonarr_api")).strip()


def _get_status(sonarr_url, headers):
    return requests.get(
        "{}/api/v3/system/status".format(sonarr_url),
        headers=headers,
        timeout=10
    )


def test_connection(show_notification=True, url=None, api=None):
    sonarr_url, api = _get_connection_values(url, api)

    if not sonarr_url or not api:
        if show_notification:
            alert("Sonarr", "Please fill Sonarr URL and API key.")
        log("Sonarr test: missing URL or API key", xbmc.LOGERROR)
        return False

    headers = {"X-Api-Key": api}

    try:
        resp = _get_status(sonarr_url, headers)

        if resp.status_code == 200:
            data = resp.json()
            version = data.get("version", "unknown")
            if show_notification:
                alert("Sonarr", "Connection OK ({})".format(version))
            return True

        if show_notification:
            alert("Sonarr", "Connection failed: HTTP {}".format(resp.status_code))
        log("Sonarr test failed: {}".format(resp.text), xbmc.LOGERROR)
        return False

    except Exception as e:
        if show_notification:
            alert("Sonarr", "Connection error:\n{}".format(e))
        log("Sonarr test crash: {}".format(e), xbmc.LOGERROR)
        return False


def fetch_setup_options(url=None, api=None):
    sonarr_url, api = _get_connection_values(url, api)
    if not sonarr_url or not api:
        raise ValueError("Please fill Sonarr URL and API key.")

    headers = {"X-Api-Key": api}

    root_resp = requests.get(
        "{}/api/v3/rootfolder".format(sonarr_url),
        headers=headers,
        timeout=10
    )
    root_resp.raise_for_status()

    profile_resp = requests.get(
        "{}/api/v3/qualityprofile".format(sonarr_url),
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


def _build_monitored_seasons(series, info):
    seasons = list(series.get("seasons", []))
    target_season = info.get("season")

    if info["type"] == "tvshow" or not str(target_season).isdigit():
        return seasons

    target_season = int(target_season)
    updated = []

    for season in seasons:
        season_copy = dict(season)
        season_number = season_copy.get("seasonNumber")
        season_copy["monitored"] = (season_number == target_season)
        updated.append(season_copy)

    return updated


def _ensure_monitored_season(sonarr_url, headers, series_db_id, info):
    target_season = info.get("season")
    if info["type"] == "tvshow" or not str(target_season).isdigit():
        return True

    target_season = int(target_season)
    series_resp = requests.get(
        "{}/api/v3/series/{}".format(sonarr_url, series_db_id),
        headers=headers,
        timeout=10
    )

    if series_resp.status_code != 200:
        log("Sonarr series fetch for monitoring failed: {}".format(series_resp.text), xbmc.LOGERROR)
        return False

    series_payload = series_resp.json()
    seasons = list(series_payload.get("seasons", []))
    changed = False

    for season in seasons:
        if season.get("seasonNumber") == target_season and not season.get("monitored", False):
            season["monitored"] = True
            changed = True

    if not changed:
        return True

    series_payload["seasons"] = seasons
    update_resp = requests.put(
        "{}/api/v3/series/{}".format(sonarr_url, series_db_id),
        json=series_payload,
        headers=headers,
        timeout=15
    )

    if update_resp.status_code not in (200, 202):
        log("Sonarr season monitor update failed: {}".format(update_resp.text), xbmc.LOGERROR)
        return False

    log("Sonarr marked season {} as monitored for series {}".format(target_season, series_db_id))
    return True


def _get_episode_list(sonarr_url, headers, series_db_id):
    ep_resp = requests.get(
        "{}/api/v3/episode?seriesId={}".format(sonarr_url, series_db_id),
        headers=headers,
        timeout=15
    )

    if ep_resp.status_code != 200:
        log("Sonarr episode lookup failed: {}".format(ep_resp.text), xbmc.LOGERROR)
        return None

    return ep_resp.json()


def _search_released_season_episodes(sonarr_url, headers, series_db_id, info):
    episodes = _get_episode_list(sonarr_url, headers, series_db_id)
    if episodes is None:
        notify("Sonarr", "Episode lookup failed", xbmcgui.NOTIFICATION_ERROR)
        return False

    season_number = int(info["season"])
    target_ids = []

    for episode in episodes:
        if episode.get("seasonNumber") != season_number:
            continue

        if not episode.get("monitored", True):
            continue

        air_date_utc = (episode.get("airDateUtc") or "").strip()
        if not air_date_utc:
            continue

        if episode.get("hasFile"):
            continue

        target_ids.append(episode["id"])

    if not target_ids:
        notify("Sonarr", "No released episodes to search in season {}".format(info["season"]))
        log("Sonarr season {} has no released missing episodes to search".format(info["season"]))
        return True

    cmd = requests.post(
        "{}/api/v3/command".format(sonarr_url),
        json={"name": "EpisodeSearch", "episodeIds": target_ids},
        headers=headers,
        timeout=15
    )

    if cmd.status_code in (200, 201):
        notify("Sonarr", "Season {} episode search started".format(info["season"]))
        log("Sonarr episode-based season search started for season {} ids={}".format(info["season"], target_ids))
        return True

    notify("Sonarr", "Season search failed", xbmcgui.NOTIFICATION_ERROR)
    log("Sonarr episode-based season search failed: {}".format(cmd.text), xbmc.LOGERROR)
    return False


def run():
    sonarr_url = clean_url(get_setting("sonarr_url"))
    api = get_setting("sonarr_api")
    root = get_setting("sonarr_root")
    profile = get_int("sonarr_quality_profile", 1)

    if not sonarr_url or not api or not root:
        notify("Sonarr", "Please configure settings", xbmcgui.NOTIFICATION_ERROR)
        open_settings()
        return

    info = get_sonarr_context()
    series_id = info.get("series_id")
    series_title = info.get("series_title", "").strip()
    year = info.get("year", "").strip()

    log("Sonarr context: {}".format(info))
    log(
        "Sonarr raw labels: db_type='{}' item_type='{}' title='{}' tvshow='{}' year='{}' season='{}' episode='{}' path='{}' folder='{}'".format(
            xbmc.getInfoLabel("ListItem.DBTYPE"),
            xbmc.getInfoLabel("ListItem.Property(item.type)"),
            xbmc.getInfoLabel("ListItem.Title"),
            xbmc.getInfoLabel("ListItem.TVShowTitle"),
            xbmc.getInfoLabel("ListItem.Year"),
            xbmc.getInfoLabel("ListItem.Season"),
            xbmc.getInfoLabel("ListItem.Episode"),
            xbmc.getInfoLabel("ListItem.Path"),
            xbmc.getInfoLabel("Container.FolderPath"),
        )
    )

    headers = {"X-Api-Key": api}
    if series_id:
        term = "{}:{}".format(info["id_type"], series_id)
    elif series_title:
        term = "{} {}".format(series_title, year).strip()
        log("Sonarr fallback lookup term='{}'".format(term))
    else:
        notify("Sonarr", "No series ID found", xbmcgui.NOTIFICATION_ERROR)
        log("Sonarr abort: no series ID or title found", xbmc.LOGERROR)
        return

    try:
        lookup = requests.get(
            "{}/api/v3/series/lookup?term={}".format(sonarr_url, term),
            headers=headers,
            timeout=10
        )

        log("Sonarr lookup term='{}' status={}".format(term, lookup.status_code))

        if lookup.status_code != 200:
            notify("Sonarr", "Lookup failed: {}".format(lookup.status_code), xbmcgui.NOTIFICATION_ERROR)
            log("Sonarr lookup failed: {}".format(lookup.text), xbmcgui.LOGERROR)
            return

        results = lookup.json()
        if not results:
            notify("Sonarr", "Show not found", xbmcgui.NOTIFICATION_ERROR)
            log("Sonarr lookup returned no results for term='{}'".format(term), xbmc.LOGERROR)
            return

        series = results[0]
        title = series.get("title", "Unknown")
        series_db_id = series.get("id")

        if not series_db_id:
            should_search_missing = (info["type"] == "tvshow")

            payload = dict(series)
            payload.update({
                "qualityProfileId": profile,
                "rootFolderPath": root,
                "monitored": True,
                "seasons": _build_monitored_seasons(series, info),
                "addOptions": {
                    "searchForMissingEpisodes": should_search_missing
                }
            })

            add_resp = requests.post(
                "{}/api/v3/series".format(sonarr_url),
                json=payload,
                headers=headers,
                timeout=15
            )

            if add_resp.status_code != 201:
                notify("Sonarr", "Add failed: {}".format(add_resp.status_code), xbmcgui.NOTIFICATION_ERROR)
                log("Sonarr add failed: {}".format(add_resp.text), xbmcgui.LOGERROR)
                return

            series_db_id = add_resp.json()["id"]
            log("Sonarr added series '{}' with id={}".format(title, series_db_id))

            if info["type"] == "tvshow":
                notify("Sonarr", "Added '{}'. Search started.".format(title))
                return

        if info["type"] == "tvshow":
            cmd = requests.post(
                "{}/api/v3/command".format(sonarr_url),
                json={"name": "SeriesSearch", "seriesId": series_db_id},
                headers=headers,
                timeout=10
            )

            if cmd.status_code in (200, 201):
                notify("Sonarr", "Series search started: {}".format(title))
            else:
                notify("Sonarr", "Series search failed", xbmcgui.NOTIFICATION_ERROR)
                log("Sonarr series search failed: {}".format(cmd.text), xbmcgui.LOGERROR)
            return

        if info["type"] == "season":
            if not str(info["season"]).isdigit():
                notify("Sonarr", "Invalid season number", xbmcgui.NOTIFICATION_ERROR)
                return

            if not _ensure_monitored_season(sonarr_url, headers, series_db_id, info):
                notify("Sonarr", "Failed to monitor selected season", xbmcgui.NOTIFICATION_ERROR)
                return
            _search_released_season_episodes(sonarr_url, headers, series_db_id, info)
            return

        if info["type"] == "episode":
            if not str(info["season"]).isdigit() or not str(info["episode"]).isdigit():
                notify("Sonarr", "Invalid episode info", xbmcgui.NOTIFICATION_ERROR)
                return

            if not _ensure_monitored_season(sonarr_url, headers, series_db_id, info):
                notify("Sonarr", "Failed to monitor selected season", xbmcgui.NOTIFICATION_ERROR)
                return

            episodes = _get_episode_list(sonarr_url, headers, series_db_id)
            if episodes is None:
                notify("Sonarr", "Episode lookup failed", xbmcgui.NOTIFICATION_ERROR)
                return
            target = next(
                (
                    e for e in episodes
                    if e.get("seasonNumber") == int(info["season"])
                    and e.get("episodeNumber") == int(info["episode"])
                ),
                None
            )

            if not target:
                notify("Sonarr", "Episode not found in Sonarr DB", xbmcgui.NOTIFICATION_ERROR)
                return

            cmd = requests.post(
                "{}/api/v3/command".format(sonarr_url),
                json={"name": "EpisodeSearch", "episodeIds": [target["id"]]},
                headers=headers,
                timeout=10
            )

            if cmd.status_code in (200, 201):
                notify(
                    "Sonarr",
                    "S{:02d}E{:02d} search started".format(int(info["season"]), int(info["episode"]))
                )
            else:
                notify("Sonarr", "Episode search failed", xbmcgui.NOTIFICATION_ERROR)
                log("Sonarr episode search failed: {}".format(cmd.text), xbmcgui.LOGERROR)
            return

        notify("Sonarr", "Unsupported TV item", xbmcgui.NOTIFICATION_ERROR)

    except Exception as e:
        notify("Sonarr", "Error: {}".format(e), xbmcgui.NOTIFICATION_ERROR)
        log("Sonarr crash: {}".format(e), xbmcgui.LOGERROR)
