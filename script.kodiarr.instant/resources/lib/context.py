# -*- coding: utf-8 -*-
import xbmc
from urllib.parse import urlparse, parse_qs


def get_movie_id():
    prop_id = xbmc.getInfoLabel("ListItem.Property(tmdb_id)")
    if prop_id and prop_id.isdigit():
        return prop_id, "tmdb"

    imdb = xbmc.getInfoLabel("ListItem.IMDBNumber")
    if imdb and imdb.startswith("tt"):
        return imdb, "imdb"

    std_id = xbmc.getInfoLabel("ListItem.TmdbId")
    if std_id and std_id.isdigit():
        return std_id, "tmdb"

    return None, None


def find_series_id():
    tmdb_prop = xbmc.getInfoLabel("ListItem.Property(tmdb_id)")
    tvdb_prop = xbmc.getInfoLabel("ListItem.Property(tvdb_id)")

    if tmdb_prop and tmdb_prop.isdigit():
        return tmdb_prop, "tmdb"

    if tvdb_prop and tvdb_prop.isdigit():
        return tvdb_prop, "tvdb"

    path_item = xbmc.getInfoLabel("ListItem.Path")
    if path_item and path_item.startswith("plugin://"):
        try:
            parsed = urlparse(path_item)
            params = parse_qs(parsed.query)
            if "tmdb_id" in params:
                return params["tmdb_id"][0], "tmdb"
            if "tvdb_id" in params:
                return params["tvdb_id"][0], "tvdb"
        except Exception:
            pass

    path_container = xbmc.getInfoLabel("Container.FolderPath")
    if path_container and path_container.startswith("plugin://"):
        try:
            parsed = urlparse(path_container)
            params = parse_qs(parsed.query)
            if "tmdb_id" in params:
                return params["tmdb_id"][0], "tmdb"
            if "tvdb_id" in params:
                return params["tvdb_id"][0], "tvdb"
        except Exception:
            pass

    return None, None


def get_sonarr_context():
    info = {}
    info["series_id"], info["id_type"] = find_series_id()
    info["series_title"] = (
        xbmc.getInfoLabel("ListItem.TVShowTitle")
        or xbmc.getInfoLabel("ListItem.Title")
        or xbmc.getInfoLabel("ListItem.Label")
        or ""
    ).strip()
    info["year"] = xbmc.getInfoLabel("ListItem.Year").strip()

    raw_season = xbmc.getInfoLabel("ListItem.Season")
    raw_episode = xbmc.getInfoLabel("ListItem.Episode")
    db_type = xbmc.getInfoLabel("ListItem.DBTYPE").lower()
    item_type = xbmc.getInfoLabel("ListItem.Property(item.type)").lower()

    info["db_type"] = db_type
    info["item_type"] = item_type

    effective_type = db_type or item_type

    if effective_type == "tvshow":
        info["type"] = "tvshow"
        info["season"] = None
        info["episode"] = None

    elif effective_type == "season":
        info["type"] = "season"
        info["season"] = raw_season
        info["episode"] = None

    elif effective_type == "episode":
        info["type"] = "episode"
        info["season"] = raw_season
        info["episode"] = raw_episode

    else:
        if raw_season.isdigit() and raw_episode.isdigit():
            info["type"] = "episode"
            info["season"] = raw_season
            info["episode"] = raw_episode
        elif raw_season.isdigit():
            info["type"] = "season"
            info["season"] = raw_season
            info["episode"] = None
        else:
            info["type"] = "tvshow"
            info["season"] = None
            info["episode"] = None

    return info
