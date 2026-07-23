# -*- coding: utf-8 -*-
import json
import re
from contextlib import closing
from platform import machine
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import xbmc
import xbmcaddon
import xbmcgui

ADDON_ID = "service.nextonlibrary"
ADDON = xbmcaddon.Addon(ADDON_ID)
ADDON_PATH = ADDON.getAddonInfo("path")
BUTTON_CONTROL_ID = 3012
ACTION_SELECT_ITEM = 7
ACTION_PLAYER_STOP = 13
ACTION_NAV_BACK = 92
ACTION_MOUSE_MOVE = 107
ACTION_MOUSE_LEFT_CLICK = 100
ACTION_MOUSE_DOUBLE_CLICK = 103
ACTION_MOUSE_DRAG = 106
OS_MACHINE = machine()
THEINTRODB_BASE_URL = "https://api.theintrodb.org/v2/media"
INTRODB_SEGMENTS_URL = "http://api.introdb.app/segments"
TMDB_API_URL = "https://api.themoviedb.org/3"
TMDB_API_KEY = "a07324c669cac4d96789197134ce272b"
AFTERCREDITS_SEARCH_URL = "https://aftercredits.com/wp-json/wp/v2/posts"
WIKIPEDIA_STINGER_URL = (
    "https://en.wikipedia.org/w/api.php?action=parse"
    "&page=List_of_films_with_post-credits_scenes"
    "&prop=text&format=json&utf8=1"
)
REMOTE_LOOKUP_TIMEOUT = 5
AUTO_PLAY_PROGRESS_FRAME_COUNT = 91
IDLE_POLL_INTERVAL = 1.0
ANIMATION_POLL_INTERVAL = 0.1
CONTOUR_COLOR_FOLDERS = {
    "blue": "progress-button-blue",
    "green": "progress-button-green",
    "purple": "progress-button-purple",
    "orange": "progress-button-orange",
    "pink": "progress-button-pink",
    "red": "progress-button-red",
}


def localize(string_id):
    return ADDON.getLocalizedString(string_id)


def log(message, level=xbmc.LOGINFO, force=False):
    debug_enabled = get_setting_bool("debug_logging")
    if not force and level == xbmc.LOGDEBUG and not debug_enabled:
        return
    if level == xbmc.LOGDEBUG and debug_enabled:
        level = xbmc.LOGINFO
    xbmc.log("[S.I.N.] %s" % message, level)


def get_setting_bool(setting_id):
    try:
        return ADDON.getSettingBool(setting_id)
    except AttributeError:
        return ADDON.getSetting(setting_id).lower() == "true"


def get_setting_int(setting_id, default=0, minimum=None, maximum=None):
    try:
        value = ADDON.getSettingInt(setting_id)
    except AttributeError:
        raw_value = ADDON.getSetting(setting_id)
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            value = default

    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def get_setting_string(setting_id, default=""):
    try:
        value = ADDON.getSettingString(setting_id)
    except AttributeError:
        value = ADDON.getSetting(setting_id)
    return value if value not in (None, "") else default


def is_meaningful_gap(current_value, previous_value, minimum_gap):
    return (current_value - previous_value) >= minimum_gap


def jsonrpc(method, params=None, log_errors=True):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params

    try:
        raw_result = xbmc.executeJSONRPC(json.dumps(payload))
        result = json.loads(raw_result)
    except Exception as exc:
        log("JSON-RPC failure for %s: %s" % (method, exc), xbmc.LOGERROR, force=True)
        return {}

    if result.get("error") and log_errors:
        log("JSON-RPC error for %s: %s" % (method, result["error"]), xbmc.LOGDEBUG)
    return result


class NextOnLibraryOverlay(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        if OS_MACHINE[0:5] == 'armv7':
            xbmcgui.WindowXMLDialog.__init__(self)
        else:
            xbmcgui.WindowXMLDialog.__init__(self, *args, **kwargs)
        self.service = None

    def onInit(self):  # pylint: disable=invalid-name
        try:
            self.getControl(BUTTON_CONTROL_ID).setLabel(self.service.get_overlay_label())
            self.setFocusId(BUTTON_CONTROL_ID)
            self.service.configure_overlay_controls(self)
        except RuntimeError:
            pass

    def onClick(self, control_id):  # pylint: disable=invalid-name
        if control_id == BUTTON_CONTROL_ID and self.service:
            self.service.handle_overlay_action()

    def onAction(self, action):  # pylint: disable=invalid-name
        action_id = action.getId()
        if action_id == ACTION_SELECT_ITEM and self.service:
            focused_id = self.getFocusId()
            if focused_id == BUTTON_CONTROL_ID:
                self.service.handle_overlay_action()
        elif action_id in (ACTION_MOUSE_MOVE, ACTION_MOUSE_LEFT_CLICK, ACTION_MOUSE_DOUBLE_CLICK, ACTION_MOUSE_DRAG):
            return
        elif self.service:
            user_initiated = action_id != ACTION_PLAYER_STOP
            self.service.dismiss_overlay(user_initiated=user_initiated)
        else:
            self.close()


class NextOnLibraryPlayer(xbmc.Player):
    def __init__(self, service):
        self.service = service
        xbmc.Player.__init__(self)

    if callable(getattr(xbmc.Player, "onAVStarted", None)):
        def onAVStarted(self):  # pylint: disable=invalid-name
            self.service.handle_playback_started()

        def onPlayBackStarted(self):  # pylint: disable=invalid-name
            pass
    else:
        def onPlayBackStarted(self):  # pylint: disable=invalid-name
            self.service.handle_playback_started()

    def onPlayBackStopped(self):  # pylint: disable=invalid-name
        self.service.reset_session()

    def onPlayBackEnded(self):  # pylint: disable=invalid-name
        self.service.reset_session()

    def onPlayBackError(self):  # pylint: disable=invalid-name
        self.service.reset_session()


class NextOnLibraryService(xbmc.Monitor):
    def __init__(self):
        xbmc.Monitor.__init__(self)
        self.player = NextOnLibraryPlayer(self)
        self.overlay = None
        self.remote_intro_cache = {}
        self.reset_session()

    def reset_session(self):
        self.close_overlay()
        self.current_file = ""
        self.current_item = None
        self.current_episode = None
        self.skip_intro_allowed = False
        self.next_episode = None
        self.chapter_starts = []
        self.chapter_percents = []
        self.skip_intro_target = None
        self.skip_intro_start = None
        self.skip_intro_remote_source = None
        self.skip_intro_remote_attempted = False
        self.skip_intro_prompted = False
        self.skip_intro_overlay_shown_at = None
        self.skip_intro_overlay_wall_shown_at = None
        self.skip_intro_overlay_visual_duration = 10.0
        self.auto_skip_intro_active = False
        self.auto_skip_intro_started_at = None
        self.auto_skip_intro_delay = 0
        self.auto_skip_intro_session_file = ""
        self.auto_skip_intro_target = None
        self.last_logged_skip_intro_target = None
        self.logged_remote_contexts = set()
        self.logged_skip_intro_remote_hits = set()
        self.logged_skip_intro_remote_misses = set()
        self.logged_next_remote_hits = set()
        self.logged_next_remote_misses = set()
        self.logged_next_preferences = False
        self.logged_skip_intro_preferences = False
        self.trigger_time = None
        self.next_trigger_source = None
        self.next_overlay_dismissed = False
        self.prompted = False
        self.overlay_action = None
        self.auto_play_active = False
        self.auto_play_started_at = None
        self.auto_play_delay = 0
        self.auto_play_session_file = ""
        self.auto_play_episode_id = None
        self.overlay_progress_frame_index = None
        self.current_movie = None
        self.stinger_result = None
        self.stinger_queried = False
        self.stinger_start_prompted = False

    def close_overlay(self):
        if not self.overlay:
            self.overlay_action = None
            self.skip_intro_overlay_shown_at = None
            self.skip_intro_overlay_wall_shown_at = None
            return
        try:
            self.overlay.close()
        except RuntimeError:
            pass
        self.overlay = None
        self.overlay_action = None
        self.skip_intro_overlay_shown_at = None
        self.skip_intro_overlay_wall_shown_at = None
        self.cancel_auto_skip_intro(log_message=False)
        self.overlay_progress_frame_index = None

    def handle_playback_started(self):
        self.close_overlay()
        self.bootstrap_session()

    def run(self):
        log("Service started", force=True)

        while not self.abortRequested():
            if self.waitForAbort(self.get_poll_interval()):
                break

            if not get_setting_bool("service_enabled"):
                if self.current_file:
                    log("Service disabled, clearing current session", xbmc.LOGDEBUG)
                    self.reset_session()
                continue

            if not self.player.isPlayingVideo():
                if self.current_file:
                    log("Playback stopped outside callbacks, clearing session", xbmc.LOGDEBUG)
                    self.reset_session()
                continue

            if not self.current_file:
                self.bootstrap_session()
                continue

            if not self.session_matches_current_playback():
                self.bootstrap_session()
                continue

            try:
                current_time = self.player.getTime()
                total_time = self.player.getTotalTime()
            except RuntimeError:
                continue

            if total_time <= 0:
                continue

            self.refresh_chapter_markers(total_time)

            if self.handle_skip_intro(current_time, total_time):
                continue

            if not self.current_episode:
                if self.current_movie and get_setting_bool("enable_stinger_movies"):
                    self.handle_movie_stinger(current_time, total_time)
                continue

            if self.auto_play_active:
                self.handle_auto_play(current_time)
                continue

            if self.prompted:
                continue

            if self.trigger_time is None:
                self.trigger_time = self.calculate_trigger_time(total_time)
                log("Using trigger time %.2f seconds" % self.trigger_time, xbmc.LOGDEBUG)

            if current_time < self.trigger_time:
                continue

            self.prompt_for_next_episode()

        log("Service stopped", force=True)

    def get_poll_interval(self):
        if self.overlay_action in ("skip_intro", "next_episode", "stinger") and self.overlay:
            return ANIMATION_POLL_INTERVAL
        if self.auto_skip_intro_active or self.auto_play_active:
            return ANIMATION_POLL_INTERVAL
        return IDLE_POLL_INTERVAL

    def bootstrap_session(self):
        if not get_setting_bool("service_enabled"):
            return

        if not self.player.isPlayingVideo():
            return

        try:
            current_file = self.player.getPlayingFile()
        except RuntimeError:
            return

        item = self.get_current_playback_item()
        if not item:
            if self.current_file:
                log("Current playback is not a video item Kodi can describe, clearing session", xbmc.LOGDEBUG)
                self.reset_session()
            return

        if self.current_file == current_file and self.current_item:
            return

        self.close_overlay()

        self.current_file = current_file
        self.current_item = item
        self.current_episode = self.get_library_episode(item)
        self.current_movie = self.get_library_movie(item)
        self.skip_intro_allowed = self.is_tv_show_playback(item)
        self.next_episode = None
        self.chapter_starts, self.chapter_percents = self.get_chapter_markers()
        self.skip_intro_target = None
        self.skip_intro_start = None
        self.skip_intro_prompted = False
        self.cancel_auto_skip_intro(log_message=False)
        self.trigger_time = None
        self.next_trigger_source = None
        self.next_overlay_dismissed = False
        self.prompted = False
        self.stinger_result = None
        self.stinger_queried = False
        self.stinger_start_prompted = False
        self.overlay_action = None
        self.cancel_auto_play(log_message=False)

        if self.chapter_starts:
            chapter_info = ", ".join(["%.2f" % value for value in self.chapter_starts])
        elif self.chapter_percents:
            chapter_info = "percents=%s" % ", ".join(["%.2f" % value for value in self.chapter_percents])
        else:
            chapter_info = "none"
        if self.current_episode:
            log(
                "Tracking %s S%02dE%02d, chapters=%s" % (
                    self.current_episode.get("showtitle", ""),
                    int(self.current_episode.get("season", 0)),
                    int(self.current_episode.get("episode", 0)),
                    chapter_info,
                ),
                xbmc.LOGDEBUG,
            )
        elif self.current_movie:
            log(
                "Tracking movie '%s', chapters=%s" % (
                    self.current_movie.get("title", self.current_movie.get("label", "")),
                    chapter_info,
                ),
                xbmc.LOGDEBUG,
            )
        elif self.skip_intro_allowed:
            playback_label = item.get("label") or item.get("title") or current_file
            log(
                "Tracking playback '%s' for Skip Intro only, chapters=%s" % (
                    playback_label,
                    chapter_info,
                ),
                xbmc.LOGDEBUG,
            )
        else:
            playback_label = item.get("label") or item.get("title") or current_file
            log(
                "Playback '%s' is not an eligible TV show item, chapters=%s" % (
                    playback_label,
                    chapter_info,
                ),
                xbmc.LOGDEBUG,
            )

    def session_matches_current_playback(self):
        try:
            current_file = self.player.getPlayingFile()
        except RuntimeError:
            return False
        return bool(self.current_file and current_file == self.current_file)

    def get_active_player_id(self):
        result = jsonrpc("Player.GetActivePlayers")
        players = result.get("result", [])
        for player in players:
            if player.get("type") == "video":
                return player.get("playerid")
        return None

    def get_current_playback_item(self):
        player_id = self.get_active_player_id()
        if player_id is None:
            return None

        result = jsonrpc(
            "Player.GetItem",
            {
                "playerid": player_id,
                "properties": [
                    "episode",
                    "imdbnumber",
                    "season",
                    "showtitle",
                    "title",
                    "tvshowid",
                    "uniqueid",
                    "file",
                    "playcount",
                ],
            },
        )
        item = result.get("result", {}).get("item", {})
        if item.get("type") not in ("episode", "movie", "unknown"):
            return None
        return item

    def get_library_episode(self, item):
        if not item:
            return None
        if item.get("type") != "episode":
            return None
        tvshow_id = item.get("tvshowid", -1)
        if tvshow_id in (-1, None):
            return None
        return item

    def is_tv_show_playback(self, item):
        if not item:
            return False
        if item.get("type") == "movie":
            return False
        if item.get("type") == "episode":
            return True
        tvshow_id = item.get("tvshowid", -1)
        if tvshow_id not in (-1, None, ""):
            return True
        if item.get("showtitle"):
            return True
        return (self.parse_int(item.get("season")) or 0) > 0 or (self.parse_int(item.get("episode")) or 0) > 0

    def get_library_movie(self, item):
        if not item:
            return None

        # Detect movies by characteristics — same lenient pattern as is_tv_show_playback()
        # Reject items with TV show markers (Kodi uses -1 for "not applicable")
        if item.get("showtitle"):
            return None
        tvshow_id = item.get("tvshowid")
        if tvshow_id not in (None, "", -1):
            return None
        if (item.get("season") or 0) > 0 or (item.get("episode") or 0) > 0:
            return None
        # Must have at least a title or label to query against stinger sources
        # (Kodi returns 'label' by default in Player.GetItem even without requesting it)
        if item.get("title") or item.get("label"):
            return item

        return None

    def is_movie_playback(self, item):
        if not item:
            return False
        return item.get("type") == "movie"

    def get_chapter_markers(self):
        starts = self.get_chapter_starts_from_jsonrpc()
        if starts:
            return starts, []
        return self.get_chapter_markers_from_labels()

    def get_chapter_starts_from_jsonrpc(self):
        player_id = self.get_active_player_id()
        if player_id is None:
            return []

        result = jsonrpc(
            "Player.GetProperties",
            {
                "playerid": player_id,
                "properties": ["chapters"],
            },
            log_errors=False,
        )
        chapters = result.get("result", {}).get("chapters", [])
        starts = []
        for chapter in chapters:
            start_time = self.chapter_time_to_seconds(chapter.get("time"))
            if start_time is not None:
                starts.append(start_time)

        unique_starts = sorted(set(starts))
        if unique_starts:
            log("Detected chapter starts from JSON-RPC: %s" % unique_starts, xbmc.LOGDEBUG)
        return unique_starts

    def get_chapter_markers_from_labels(self):
        try:
            chapter_count_raw = xbmc.getInfoLabel("Player.ChapterCount")
            chapter_count = int(chapter_count_raw or "0")
        except ValueError:
            chapter_count_raw = xbmc.getInfoLabel("Player.ChapterCount")
            chapter_count = 0

        chapter_percentages = self.get_chapter_percentages_from_player_label(chapter_count)
        if chapter_percentages:
            log("Detected chapter percentages from Player.Chapters: %s" % chapter_percentages, xbmc.LOGDEBUG)

        if get_setting_bool("debug_logging"):
            current_chapter = xbmc.getInfoLabel("Player.Chapter")
            current_chapter_name = xbmc.getInfoLabel("Player.ChapterName")
            legacy_count_raw = xbmc.getInfoLabel("VideoPlayer.ChapterCount")
            log(
                "Chapter label diagnostics -> count_raw=%s, current=%s, current_name=%s, legacy_count_raw=%s" % (
                    chapter_count_raw or "",
                    current_chapter or "",
                    current_chapter_name or "",
                    legacy_count_raw or "",
                ),
                xbmc.LOGDEBUG,
            )

        starts = []
        for index in range(1, chapter_count + 1):
            label = xbmc.getInfoLabel("Player.Chapter(%d)" % index)
            if not label:
                label = xbmc.getInfoLabel("VideoPlayer.Chapter(%d)" % index)
            if get_setting_bool("debug_logging") and index <= 8:
                log("Chapter label %d -> %s" % (index, label or ""), xbmc.LOGDEBUG)
            start_time = self.parse_time_string(label)
            if start_time is not None:
                starts.append(start_time)

        unique_starts = sorted(set(starts))
        if unique_starts:
            log("Detected chapter starts from labels: %s" % unique_starts, xbmc.LOGDEBUG)
        return unique_starts, chapter_percentages

    def get_chapter_percentages_from_player_label(self, chapter_count=0):
        raw_value = xbmc.getInfoLabel("Player.Chapters")
        if get_setting_bool("debug_logging"):
            log("Player.Chapters raw -> %s" % (raw_value or ""), xbmc.LOGDEBUG)

        if not raw_value:
            return []

        tokens = []
        for token in raw_value.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                tokens.append(float(token))
            except ValueError:
                return []

        if not tokens:
            return []

        # Kodi builds appear to expose Player.Chapters in different layouts:
        # - one start percentage per chapter, e.g. "0.00000,89.75975"
        # - repeated chapter boundaries, e.g. start1,end1,start2,end2,...
        # Normalize both by preserving ordered unique boundary values.
        boundaries = []
        seen = set()
        for value in tokens:
            rounded_value = round(value, 5)
            if rounded_value in seen:
                continue
            seen.add(rounded_value)
            boundaries.append(value)

        if chapter_count > 0 and len(boundaries) > chapter_count:
            boundaries = boundaries[:chapter_count]

        cleaned_starts = []
        for start_percent in boundaries:
            if 0.0 <= start_percent < 100.0:
                cleaned_starts.append(start_percent)

        return sorted(set(cleaned_starts))

    def chapter_time_to_seconds(self, value):
        if isinstance(value, dict):
            hours = int(value.get("hours", 0))
            minutes = int(value.get("minutes", 0))
            seconds = int(value.get("seconds", 0))
            milliseconds = int(value.get("milliseconds", 0))
            return hours * 3600 + minutes * 60 + seconds + (milliseconds / 1000.0)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            return self.parse_time_string(value)
        return None

    def parse_time_string(self, value):
        if not value:
            return None

        text = value.strip()
        if not text:
            return None

        match = re.search(r'(\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?)', text)
        if match:
            text = match.group(1)

        milliseconds = 0.0
        if "." in text or "," in text:
            separator = "." if "." in text else ","
            text, fraction = text.split(separator, 1)
            try:
                milliseconds = float("0.%s" % fraction)
            except ValueError:
                milliseconds = 0.0

        parts = text.split(":")
        if len(parts) == 2:
            parts = ["0"] + parts
        if len(parts) != 3:
            return None

        try:
            hours, minutes, seconds = [int(part) for part in parts]
        except ValueError:
            return None

        return hours * 3600 + minutes * 60 + seconds + milliseconds

    def parse_setting_time(self, value):
        return self.parse_time_string(value)

    def parse_int(self, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def normalize_numeric_id(self, value):
        if value in (None, ""):
            return None
        match = re.search(r"(\d+)", str(value))
        if not match:
            return None
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            return None

    def normalize_imdb_id(self, value):
        if value in (None, ""):
            return None
        match = re.search(r"(tt\d{7,8})", str(value))
        if not match:
            return None
        return match.group(1)

    def get_first_info_label(self, labels):
        for label in labels:
            value = xbmc.getInfoLabel(label)
            if value:
                return value
        return ""

    def get_library_unique_ids(self):
        current = self.current_episode
        if not current:
            return {}

        episode_id = current.get("id") or current.get("episodeid")
        if not episode_id:
            return {}

        cache_key = ("episode_uniqueids", int(episode_id))
        if cache_key in self.remote_intro_cache:
            return self.remote_intro_cache[cache_key]

        result = jsonrpc(
            "VideoLibrary.GetEpisodeDetails",
            {
                "episodeid": int(episode_id),
                "properties": ["uniqueid"],
            },
            log_errors=False,
        )
        details = result.get("result", {}).get("episodedetails", {})
        unique_ids = details.get("uniqueid", {}) or {}
        self.remote_intro_cache[cache_key] = unique_ids
        return unique_ids

    def get_library_episode_identifiers(self):
        current = self.current_episode
        if not current:
            return {}

        episode_id = current.get("id") or current.get("episodeid")
        if not episode_id:
            dbid_label = xbmc.getInfoLabel("VideoPlayer.DBID")
            episode_id = self.normalize_numeric_id(dbid_label)
        if not episode_id:
            return {}

        cache_key = ("episode_identifiers", int(episode_id))
        if cache_key in self.remote_intro_cache:
            return self.remote_intro_cache[cache_key]

        result = jsonrpc(
            "VideoLibrary.GetEpisodeDetails",
            {
                "episodeid": int(episode_id),
                "properties": ["imdbnumber", "uniqueid", "tvshowid"],
            },
            log_errors=False,
        )
        details = result.get("result", {}).get("episodedetails", {}) or {}
        identifiers = {
            "imdbnumber": details.get("imdbnumber"),
            "uniqueid": details.get("uniqueid", {}) or {},
            "tvshowid": details.get("tvshowid"),
        }
        self.remote_intro_cache[cache_key] = identifiers
        return identifiers

    def get_library_show_identifiers(self):
        current = self.current_episode
        if not current:
            return {}

        tvshow_id = current.get("tvshowid")
        if tvshow_id in (None, -1, "-1"):
            episode_identifiers = self.get_library_episode_identifiers()
            tvshow_id = episode_identifiers.get("tvshowid")
        if tvshow_id in (None, -1, "-1"):
            tvshow_id = self.normalize_numeric_id(xbmc.getInfoLabel("VideoPlayer.TvShowDBID"))
        if tvshow_id is None:
            return {}

        cache_key = ("tvshow_identifiers", int(tvshow_id))
        if cache_key in self.remote_intro_cache:
            return self.remote_intro_cache[cache_key]

        result = jsonrpc(
            "VideoLibrary.GetTVShowDetails",
            {
                "tvshowid": int(tvshow_id),
                "properties": ["imdbnumber", "uniqueid"],
            },
            log_errors=False,
        )
        details = result.get("result", {}).get("tvshowdetails", {}) or {}
        identifiers = {
            "imdbnumber": details.get("imdbnumber"),
            "uniqueid": details.get("uniqueid", {}) or {},
        }
        self.remote_intro_cache[cache_key] = identifiers
        return identifiers

    def get_playback_tmdb_id(self):
        item = self.current_item or {}
        item_unique_ids = item.get("uniqueid", {}) or {}
        tmdb_id = self.normalize_numeric_id(item_unique_ids.get("tmdb"))
        if tmdb_id is not None:
            return tmdb_id

        show_identifiers = self.get_library_show_identifiers()
        tmdb_id = self.normalize_numeric_id((show_identifiers.get("uniqueid", {}) or {}).get("tmdb"))
        if tmdb_id is not None:
            return tmdb_id

        episode_identifiers = self.get_library_episode_identifiers()
        tmdb_id = self.normalize_numeric_id((episode_identifiers.get("uniqueid", {}) or {}).get("tmdb"))
        if tmdb_id is not None:
            return tmdb_id

        unique_ids = self.get_library_unique_ids()
        tmdb_id = self.normalize_numeric_id(unique_ids.get("tmdb"))
        if tmdb_id is not None:
            return tmdb_id

        label_value = self.get_first_info_label(
            [
                "ListItem.UniqueID(tmdb)",
                "VideoPlayer.UniqueID(tmdb)",
                "VideoPlayer.Property(tmdb_id)",
                "VideoPlayer.Property(tmdb)",
            ]
        )
        return self.normalize_numeric_id(label_value)

    def get_playback_imdb_id(self):
        item = self.current_item or {}
        imdb_id = self.normalize_imdb_id(item.get("imdbnumber"))
        if imdb_id:
            return imdb_id

        item_unique_ids = item.get("uniqueid", {}) or {}
        imdb_id = self.normalize_imdb_id(item_unique_ids.get("imdb"))
        if imdb_id:
            return imdb_id

        show_identifiers = self.get_library_show_identifiers()
        imdb_id = self.normalize_imdb_id(show_identifiers.get("imdbnumber"))
        if imdb_id:
            return imdb_id
        imdb_id = self.normalize_imdb_id((show_identifiers.get("uniqueid", {}) or {}).get("imdb"))
        if imdb_id:
            return imdb_id

        episode_identifiers = self.get_library_episode_identifiers()
        imdb_id = self.normalize_imdb_id(episode_identifiers.get("imdbnumber"))
        if imdb_id:
            return imdb_id
        imdb_id = self.normalize_imdb_id((episode_identifiers.get("uniqueid", {}) or {}).get("imdb"))
        if imdb_id:
            return imdb_id

        unique_ids = self.get_library_unique_ids()
        imdb_id = self.normalize_imdb_id(unique_ids.get("imdb"))
        if imdb_id:
            return imdb_id

        label_value = self.get_first_info_label(
            [
                "VideoPlayer.IMDBNumber",
                "ListItem.IMDBNumber",
                "ListItem.UniqueID(imdb)",
                "VideoPlayer.UniqueID(imdb)",
            ]
        )
        return self.normalize_imdb_id(label_value)

    def get_playback_show_imdb_id(self):
        show_identifiers = self.get_library_show_identifiers()
        imdb_id = self.normalize_imdb_id(show_identifiers.get("imdbnumber"))
        if imdb_id:
            return imdb_id
        imdb_id = self.normalize_imdb_id((show_identifiers.get("uniqueid", {}) or {}).get("imdb"))
        if imdb_id:
            return imdb_id

        label_value = self.get_first_info_label(
            [
                "VideoPlayer.TVshowIMDBNumber",
                "Container.ListItem.TVShowIMDBNumber",
                "ListItem.TVShowIMDBNumber",
            ]
        )
        return self.normalize_imdb_id(label_value)

    def build_skip_intro_remote_context(self):
        item = self.current_item or {}
        season = self.parse_int(item.get("season"))
        episode = self.parse_int(item.get("episode"))
        if season is None or episode is None:
            log("Remote metadata skipped: playback item has no season/episode numbers", xbmc.LOGDEBUG)
            return None

        tmdb_id = self.get_playback_tmdb_id()
        imdb_id = self.get_playback_imdb_id()
        show_imdb_id = self.get_playback_show_imdb_id() or imdb_id
        if tmdb_id is None and not imdb_id and not show_imdb_id:
            log(
                "Remote metadata skipped: no usable tmdb/imdb ids for S%02dE%02d" % (
                    season,
                    episode,
                ),
                xbmc.LOGDEBUG,
            )
            return None

        context = {
            "type": "tv",
            "season": season,
            "episode": episode,
            "tmdb_id": tmdb_id,
            "imdb_id": imdb_id,
            "show_imdb_id": show_imdb_id,
        }
        self.log_remote_context_once(context)
        return context

    def build_skip_intro_cache_key(self, context):
        return (
            context.get("type"),
            context.get("tmdb_id"),
            context.get("imdb_id"),
            context.get("show_imdb_id"),
            context.get("season"),
            context.get("episode"),
        )

    def log_remote_context_once(self, context):
        context_key = self.build_skip_intro_cache_key(context)
        if context_key in self.logged_remote_contexts:
            return
        self.logged_remote_contexts.add(context_key)
        log(
            "Remote metadata context -> season=%s episode=%s tmdb_id=%s imdb_id=%s" % (
                context.get("season"),
                context.get("episode"),
                context.get("tmdb_id"),
                context.get("show_imdb_id") or context.get("imdb_id") or "",
            ),
            xbmc.LOGDEBUG,
        )

    def fetch_remote_json(self, url, source_name):
        log("%s lookup request -> %s" % (source_name, url), xbmc.LOGDEBUG)
        request = Request(
            url,
            headers={
                "User-Agent": "%s/%s" % (ADDON_ID, ADDON.getAddonInfo("version")),
                "Accept": "application/json",
            },
        )
        try:
            with closing(urlopen(request, timeout=REMOTE_LOOKUP_TIMEOUT)) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            if exc.code == 404:
                log("%s lookup returned 404 (no metadata match)" % source_name, xbmc.LOGDEBUG)
                return None
            log("%s lookup failed with HTTP %s" % (source_name, exc.code), xbmc.LOGDEBUG)
            return None
        except URLError as exc:
            log("%s lookup failed: %s" % (source_name, exc.reason), xbmc.LOGDEBUG)
            return None
        except Exception as exc:
            log("%s lookup failed: %s" % (source_name, exc), xbmc.LOGDEBUG)
            return None

        try:
            return json.loads(body)
        except (TypeError, ValueError) as exc:
            log("%s lookup returned invalid JSON: %s" % (source_name, exc), xbmc.LOGDEBUG)
            return None

    def normalize_skip_intro_window(self, start_value, end_value, total_time):
        try:
            end_seconds = float(end_value)
        except (TypeError, ValueError):
            return None

        try:
            start_seconds = float(start_value) if start_value is not None else 1.0
        except (TypeError, ValueError):
            start_seconds = 1.0

        start_seconds = max(1.0, start_seconds)
        end_seconds = min(float(total_time), end_seconds)
        if end_seconds <= start_seconds:
            return None
        return start_seconds, end_seconds

    def normalize_remote_segment_window(self, segment, total_time):
        if not isinstance(segment, dict):
            return None

        start_ms = segment.get("start_ms")
        end_ms = segment.get("end_ms")
        if end_ms is not None:
            return self.normalize_skip_intro_window(
                None if start_ms is None else (float(start_ms) / 1000.0),
                float(end_ms) / 1000.0,
                total_time,
            )

        return self.normalize_skip_intro_window(
            segment.get("start_sec"),
            segment.get("end_sec"),
            total_time,
        )

    def select_theintrodb_segment(self, payload):
        for segment_name in ("recap", "intro"):
            entries = payload.get(segment_name) or []
            valid_entries = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                try:
                    end_ms = float(entry.get("end_ms"))
                except (TypeError, ValueError):
                    continue
                start_ms = entry.get("start_ms")
                try:
                    start_ms = float(start_ms) if start_ms is not None else None
                except (TypeError, ValueError):
                    start_ms = None
                if start_ms is not None and end_ms <= start_ms:
                    continue
                valid_entries.append((end_ms, start_ms))

            if valid_entries:
                end_ms, start_ms = sorted(valid_entries, key=lambda item: item[0])[0]
                return segment_name, start_ms, end_ms
        return None, None, None

    def fetch_skip_intro_from_theintrodb(self, context, total_time):
        query = {
            "season": context.get("season"),
            "episode": context.get("episode"),
        }
        tmdb_id = context.get("tmdb_id")
        imdb_id = context.get("imdb_id")
        if tmdb_id is not None:
            query["tmdb_id"] = tmdb_id
        elif imdb_id:
            query["imdb_id"] = imdb_id
        else:
            return None

        payload = self.fetch_remote_json(
            "%s?%s" % (THEINTRODB_BASE_URL, urlencode(query)),
            "TheIntroDB",
        )
        if not payload:
            return None

        segment_name, start_ms, end_ms = self.select_theintrodb_segment(payload)
        if end_ms is None:
            return None

        window = self.normalize_skip_intro_window(
            None if start_ms is None else (start_ms / 1000.0),
            end_ms / 1000.0,
            total_time,
        )
        if window:
            log(
                "Using Skip Intro metadata from TheIntroDB (%s)" % segment_name,
                xbmc.LOGDEBUG,
            )
        return window

    def fetch_skip_intro_from_introdb(self, context, total_time):
        imdb_id = context.get("show_imdb_id")
        if not imdb_id:
            log("IntroDB.app lookup skipped: no show IMDb id available", xbmc.LOGDEBUG)
            return None

        payload = self.fetch_remote_json(
            "%s?%s" % (
                INTRODB_SEGMENTS_URL,
                urlencode(
                    {
                        "imdb_id": imdb_id,
                        "season": context.get("season"),
                        "episode": context.get("episode"),
                    }
                ),
            ),
            "IntroDB.app",
        )
        if not isinstance(payload, dict):
            return None

        for segment_name in ("recap", "intro"):
            segment = payload.get(segment_name)
            window = self.normalize_remote_segment_window(segment, total_time)
            if window:
                log("Using Skip Intro metadata from IntroDB.app (%s)" % segment_name, xbmc.LOGDEBUG)
                return window
        return None

    def fetch_next_trigger_from_introdb(self, context, total_time):
        imdb_id = context.get("show_imdb_id")
        if not imdb_id:
            log("IntroDB.app Next On lookup skipped: no show IMDb id available", xbmc.LOGDEBUG)
            return None

        payload = self.fetch_remote_json(
            "%s?%s" % (
                INTRODB_SEGMENTS_URL,
                urlencode(
                    {
                        "imdb_id": imdb_id,
                        "season": context.get("season"),
                        "episode": context.get("episode"),
                    }
                ),
            ),
            "IntroDB.app",
        )
        if not isinstance(payload, dict):
            return None

        outro = payload.get("outro")
        if not isinstance(outro, dict):
            log("Next On remote timing found no IntroDB.app outro marker", xbmc.LOGDEBUG)
            return None

        start_ms = outro.get("start_ms")
        start_sec = outro.get("start_sec")
        try:
            trigger_time = float(start_ms) / 1000.0 if start_ms is not None else float(start_sec)
        except (TypeError, ValueError):
            log("Next On remote timing found invalid IntroDB.app outro marker", xbmc.LOGDEBUG)
            return None

        if not (0 < trigger_time < total_time):
            log("Next On remote timing found unusable IntroDB.app outro marker", xbmc.LOGDEBUG)
            return None

        log("Using Next On timing metadata from IntroDB.app outro", xbmc.LOGDEBUG)
        return max(1.0, min(float(total_time) - 1.0, trigger_time))

    def get_remote_skip_intro_window(self, total_time):
        context = self.build_skip_intro_remote_context()
        if not context:
            return None

        cache_key = self.build_skip_intro_cache_key(context)
        if cache_key in self.remote_intro_cache:
            cached = self.remote_intro_cache[cache_key]
            if cached:
                self.skip_intro_remote_source = cached.get("source")
                if cache_key not in self.logged_skip_intro_remote_hits:
                    self.logged_skip_intro_remote_hits.add(cache_key)
                    log(
                        "Skip Intro remote metadata cache hit -> source=%s start=%.2f end=%.2f" % (
                            cached.get("source"),
                            cached.get("start"),
                            cached.get("end"),
                        ),
                        xbmc.LOGDEBUG,
                    )
                return self.normalize_skip_intro_window(
                    cached.get("start"),
                    cached.get("end"),
                    total_time,
                )
            if cache_key not in self.logged_skip_intro_remote_misses:
                self.logged_skip_intro_remote_misses.add(cache_key)
                log("Skip Intro remote metadata cache miss remembered for this playback", xbmc.LOGDEBUG)
            return None

        for source_name, fetcher in (
            ("theintrodb", self.fetch_skip_intro_from_theintrodb),
            ("introdb", self.fetch_skip_intro_from_introdb),
        ):
            log("Trying Skip Intro remote metadata source -> %s" % source_name, xbmc.LOGDEBUG)
            window = fetcher(context, total_time)
            if not window:
                log("Skip Intro remote metadata source %s had no usable data" % source_name, xbmc.LOGDEBUG)
                continue
            self.remote_intro_cache[cache_key] = {
                "source": source_name,
                "start": window[0],
                "end": window[1],
            }
            self.skip_intro_remote_source = source_name
            return window

        self.remote_intro_cache[cache_key] = None
        log("Skip Intro remote metadata lookup exhausted all sources", xbmc.LOGDEBUG)
        return None

    def get_manual_skip_intro_window(self, total_time):
        if not get_setting_bool("enable_skip_intro_fallback"):
            return None, None
        fallback_start = self.parse_setting_time(get_setting_string("skip_intro_fallback_start", "00:15"))
        fallback_end = self.parse_setting_time(get_setting_string("skip_intro_fallback_end", "01:30"))
        if fallback_start is None:
            fallback_start = 15.0
        if fallback_end is None:
            fallback_end = 90.0
        fallback_start = max(1.0, min(fallback_start, max(1.0, total_time - 1.0)))
        fallback_end = max(fallback_start + 1.0, min(fallback_end, total_time))
        rounded_target = round(fallback_end, 2)
        if self.last_logged_skip_intro_target != rounded_target:
            log(
                "No usable intro chapter or remote metadata found, falling back to start=%.2f end=%.2f" % (
                    fallback_start,
                    fallback_end,
                ),
                xbmc.LOGDEBUG,
            )
            self.last_logged_skip_intro_target = rounded_target
        return fallback_start, fallback_end

    def get_remote_next_trigger(self, total_time):
        context = self.build_skip_intro_remote_context()
        if not context:
            return None

        cache_key = ("next_trigger",) + self.build_skip_intro_cache_key(context)
        if cache_key in self.remote_intro_cache:
            cached_trigger = self.remote_intro_cache[cache_key]
            if cached_trigger is None:
                if cache_key not in self.logged_next_remote_misses:
                    self.logged_next_remote_misses.add(cache_key)
                    log("Next On remote timing cache miss remembered for this playback", xbmc.LOGDEBUG)
                return None
            if cache_key not in self.logged_next_remote_hits:
                self.logged_next_remote_hits.add(cache_key)
                log("Next On remote timing cache hit -> %.2f" % cached_trigger, xbmc.LOGDEBUG)
            return max(1.0, min(float(total_time) - 1.0, float(cached_trigger)))

        query = {
            "season": context.get("season"),
            "episode": context.get("episode"),
        }
        tmdb_id = context.get("tmdb_id")
        imdb_id = context.get("imdb_id")
        if tmdb_id is not None:
            query["tmdb_id"] = tmdb_id
        elif imdb_id:
            query["imdb_id"] = imdb_id

        if query.get("tmdb_id") is not None or query.get("imdb_id"):
            payload = self.fetch_remote_json(
                "%s?%s" % (THEINTRODB_BASE_URL, urlencode(query)),
                "TheIntroDB",
            )
            if isinstance(payload, dict):
                credits = payload.get("credits") or []
                credit_starts = []
                for entry in credits:
                    if not isinstance(entry, dict):
                        continue
                    start_ms = entry.get("start_ms")
                    try:
                        start_seconds = float(start_ms) / 1000.0
                    except (TypeError, ValueError):
                        continue
                    if 0 < start_seconds < total_time:
                        credit_starts.append(start_seconds)

                if credit_starts:
                    trigger_time = min(credit_starts)
                    self.remote_intro_cache[cache_key] = trigger_time
                    log("Using Next On timing metadata from TheIntroDB credits", xbmc.LOGDEBUG)
                    return max(1.0, min(float(total_time) - 1.0, trigger_time))

                log("Next On remote timing found no usable TheIntroDB credits markers", xbmc.LOGDEBUG)
            else:
                log("Next On remote timing had no TheIntroDB payload", xbmc.LOGDEBUG)

        trigger_time = self.fetch_next_trigger_from_introdb(context, total_time)
        if trigger_time is not None:
            self.remote_intro_cache[cache_key] = trigger_time
            return trigger_time

        self.remote_intro_cache[cache_key] = None
        log("Next On remote timing lookup exhausted all sources", xbmc.LOGDEBUG)
        return None

    def fetch_stinger_from_tmdb(self):
        tmdb_id = self.get_playback_tmdb_id()
        if not tmdb_id:
            imdb_id = self.get_playback_imdb_id()
            if not imdb_id:
                log("Stinger TMDB lookup skipped: no TMDB or IMDb id available", xbmc.LOGDEBUG)
                return None

            find_payload = self.fetch_remote_json(
                "%s/find/%s?external_source=imdb_id&api_key=%s" % (
                    TMDB_API_URL, imdb_id, TMDB_API_KEY,
                ),
                "TMDB Stinger",
            )
            if not isinstance(find_payload, dict):
                return None
            movie_results = find_payload.get("movie_results", [])
            if not movie_results or not isinstance(movie_results, list):
                return None
            first = movie_results[0]
            if not isinstance(first, dict):
                return None
            tmdb_id = first.get("id")
            if not tmdb_id:
                return None

        keywords_payload = self.fetch_remote_json(
            "%s/movie/%s/keywords?api_key=%s" % (
                TMDB_API_URL, int(tmdb_id), TMDB_API_KEY,
            ),
            "TMDB Stinger",
        )
        if not isinstance(keywords_payload, dict):
            return None

        keywords = keywords_payload.get("keywords") or []
        has_mid = False
        has_post = False
        has_bloopers = False
        for kw in keywords:
            name = (kw.get("name") or "").lower()
            if "duringcreditsstinger" in name:
                has_mid = True
            if "aftercreditsstinger" in name:
                has_post = True
            if "blooper" in name or "outtake" in name:
                has_bloopers = True
            if has_mid and has_post and has_bloopers:
                break

        if not has_mid and not has_post and not has_bloopers:
            log("Stinger TMDB lookup found no relevant keywords", xbmc.LOGDEBUG)
            return None

        result = {
            "mid": has_mid,
            "post": has_post,
            "bloopers": has_bloopers,
            "source": "TMDB",
            "definitive": True,
        }
        log(
            "Stinger TMDB result -> mid=%s post=%s bloopers=%s" % (
                has_mid, has_post, has_bloopers,
            ),
            xbmc.LOGDEBUG,
        )
        return result

    def fetch_stinger_from_aftercredits(self):
        movie = self.current_movie
        if not movie:
            return None
        title = (movie.get("title") or movie.get("label") or "").strip()
        if not title:
            return None

        search_query = title
        year = movie.get("year")
        if year:
            search_query = "%s %s" % (title, year)

        payload = self.fetch_remote_json(
            "%s?%s" % (
                AFTERCREDITS_SEARCH_URL,
                urlencode({
                    "search": search_query,
                    "_fields": "id,title,link",
                    "per_page": "10",
                }),
            ),
            "AfterCredits Stinger",
        )
        if not isinstance(payload, list) or not payload:
            if year:
                log("AfterCredits Stinger no results with year, retrying without year", xbmc.LOGDEBUG)
                payload = self.fetch_remote_json(
                    "%s?%s" % (
                        AFTERCREDITS_SEARCH_URL,
                        urlencode({
                            "search": title,
                            "_fields": "id,title,link",
                            "per_page": "10",
                        }),
                    ),
                    "AfterCredits Stinger",
                )
            if not isinstance(payload, list) or not payload:
                log("AfterCredits Stinger no search results", xbmc.LOGDEBUG)
                return None

        best = None
        cleaned_title = " ".join(title.lower().split())
        for post in payload:
            if not isinstance(post, dict):
                continue
            raw_title = (post.get("title", {}) or {}).get("rendered", "") if isinstance(post.get("title"), dict) else ""
            raw_title = (raw_title or "").lower().strip()
            if not raw_title:
                continue
            if cleaned_title in raw_title or raw_title in cleaned_title:
                best = post
                if "review" not in raw_title:
                    break

        if not best:
            log("AfterCredits Stinger no title match", xbmc.LOGDEBUG)
            return None

        post_id = best.get("id")
        if not post_id:
            return None

        detail_payload = self.fetch_remote_json(
            "%s/%s?%s" % (
                AFTERCREDITS_SEARCH_URL,
                int(post_id),
                urlencode({
                    "_fields": "content,_links,_embedded",
                    "_embed": "wp:term",
                }),
            ),
            "AfterCredits Stinger detail",
        )
        if not isinstance(detail_payload, dict):
            return None

        categories = set()
        embedded = detail_payload.get("_embedded") or {}
        for taxonomy in (embedded.get("wp:term") or []):
            if not isinstance(taxonomy, list):
                continue
            for term in taxonomy:
                name = (term.get("name") or "").lower().strip() if isinstance(term, dict) else ""
                if name:
                    name = name.replace("&amp;", "&").replace("&#038;", "&").replace("&#38;", "&")
                    categories.add(name)

        if "non-stingers" in categories:
            log("AfterCredits Stinger result -> non-stingers (definitive negative)", xbmc.LOGDEBUG)
            return {"mid": False, "post": False, "bloopers": False, "source": "AfterCredits", "definitive": True}

        if "unknown" in categories:
            log("AfterCredits Stinger result -> unknown", xbmc.LOGDEBUG)
            return None

        has_mid = "both during & after credits" in categories or "during credits" in categories
        has_post = "both during & after credits" in categories or "after credits" in categories
        has_bloopers = any(
            tag in categories
            for tag in ("bloopers", "outtakes", "gag reel", "behind the scenes")
        )
        has_sequel = "sequel setup" in categories

        if not has_mid and not has_post and not categories:
            log("AfterCredits Stinger no categories parsed", xbmc.LOGDEBUG)
            return None

        result = {
            "mid": has_mid,
            "post": has_post,
            "bloopers": has_bloopers,
            "sequel": has_sequel,
            "source": "AfterCredits",
            "definitive": True,
        }
        log(
            "Stinger AfterCredits result -> mid=%s post=%s bloopers=%s sequel=%s" % (
                has_mid, has_post, has_bloopers, has_sequel,
            ),
            xbmc.LOGDEBUG,
        )
        return result

    def fetch_stinger_from_wikipedia(self):
        cache_key = "wikipedia_stinger_index"
        if cache_key not in self.remote_intro_cache:
            payload = self.fetch_remote_json(WIKIPEDIA_STINGER_URL, "Wikipedia Stinger index")
            if not isinstance(payload, dict):
                self.remote_intro_cache[cache_key] = {}
                return None

            text = (payload.get("parse") or {}).get("text", {}).get("*", "") if isinstance(payload.get("parse"), dict) else ""
            if not text:
                self.remote_intro_cache[cache_key] = {}
                return None

            index = {}
            table_pattern = re.compile(r'<table[^>]*class="wikitable[^"]*"[^>]*>(.*?)</table>', re.DOTALL | re.IGNORECASE)
            for table_match in table_pattern.finditer(text):
                table_html = table_match.group(0)
                rows = re.findall(r'<tr>(.*?)</tr>', table_html, re.DOTALL | re.IGNORECASE)
                for row in rows:
                    cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.DOTALL | re.IGNORECASE)
                    if len(cells) < 2:
                        continue
                    title_text = re.sub(r'<[^>]+>', '', cells[1]).strip()
                    if not title_text:
                        continue
                    row_text = re.sub(r'<[^>]+>', '', row).lower()

                    mid_regex = r'\b(mid-|during|throughout|overlay|alongside|while the credits|accompany.*credits|as.*credits roll|before.*credits roll|during.*titles|throughout.*titles|credits crawl|credits scroll)\b'
                    post_regex = r'\b(post-|after|following|follows|at the end|very end|once the credits|final scene|last scene|after the final|after the end titles|ends with|concludes with)\b'
                    blooper_regex = r'\b(bloopers?|outtakes?|gags?|gag reel|behind-the-scenes)\b'

                    has_mid = bool(re.search(mid_regex, row_text))
                    has_post = bool(re.search(post_regex, row_text))
                    has_bloopers = bool(re.search(blooper_regex, row_text))

                    clean_title = re.sub(r'[^a-z0-9]', '', title_text.lower())
                    if clean_title:
                        index[clean_title] = {
                            "mid": has_mid,
                            "post": has_post,
                            "bloopers": has_bloopers,
                        }

            self.remote_intro_cache[cache_key] = index
            log("Wikipedia Stinger index built with %d entries" % len(index), xbmc.LOGDEBUG)

        wiki_index = self.remote_intro_cache.get(cache_key, {})
        if not wiki_index:
            return None

        movie = self.current_movie
        if not movie:
            return None
        title = (movie.get("title") or movie.get("label") or "").strip()
        if not title:
            return None

        clean_title = re.sub(r'[^a-z0-9]', '', title.lower())
        entry = wiki_index.get(clean_title)
        if not entry:
            log("Stinger Wikipedia no match for '%s'" % title, xbmc.LOGDEBUG)
            return None

        result = {
            "mid": entry.get("mid", False),
            "post": entry.get("post", False),
            "bloopers": entry.get("bloopers", False),
            "source": "Wikipedia",
            "definitive": False,
        }
        log(
            "Stinger Wikipedia result -> mid=%s post=%s bloopers=%s" % (
                result["mid"], result["post"], result["bloopers"],
            ),
            xbmc.LOGDEBUG,
        )
        return result

    def get_stinger_info(self):
        if not get_setting_bool("enable_stinger_movies"):
            return None

        if not self.current_movie:
            return None

        cache_key = ("stinger", self.current_file)
        if cache_key in self.remote_intro_cache:
            return self.remote_intro_cache[cache_key]

        sources = [
            ("tmdb", self.fetch_stinger_from_tmdb),
            ("aftercredits", self.fetch_stinger_from_aftercredits),
            ("wikipedia", self.fetch_stinger_from_wikipedia),
        ]

        merged = None
        for source_name, fetcher in sources:
            log("Stinger trying source -> %s" % source_name, xbmc.LOGDEBUG)
            result = fetcher()
            if result and result.get("definitive"):
                self.remote_intro_cache[cache_key] = result
                return result
            if result:
                if merged is None:
                    merged = dict(result)
                else:
                    if result.get("mid"):
                        merged["mid"] = True
                    if result.get("post"):
                        merged["post"] = True
                    if result.get("bloopers"):
                        merged["bloopers"] = True
                    if result.get("sequel"):
                        merged["sequel"] = True
                    if result.get("definitive"):
                        merged["definitive"] = True

        if merged:
            merged["source"] = "Aggregated"
            self.remote_intro_cache[cache_key] = merged
            return merged

        self.remote_intro_cache[cache_key] = None
        log("Stinger lookup exhausted all sources with no results", xbmc.LOGDEBUG)
        return None

    def get_stinger_trigger_time(self, total_time):
        candidates = []
        cutoff = max(1.0, total_time - 5.0)
        for start_time in self.chapter_starts:
            if 0 < start_time < cutoff:
                candidates.append(start_time)

        # Use second-to-last chapter (start of credits), not the last (stinger scene itself).
        # Require at least 3 candidates to avoid picking chapter 1 on a 2-chapter movie.
        if len(candidates) >= 3:
            return candidates[-2]

        fallback_percent = get_setting_int("stinger_trigger_percent", default=85, minimum=50, maximum=99)
        return max(1.0, total_time * (fallback_percent / 100.0))

    def calculate_trigger_time(self, total_time):
        online_metadata_priority = get_setting_bool("online_next_metadata_priority")
        if not self.logged_next_preferences:
            self.logged_next_preferences = True
            log(
                "Next On timing preferences -> online_next_metadata_priority=%s chapter_timing_enabled=True" % (
                    online_metadata_priority,
                ),
                xbmc.LOGDEBUG,
            )

        if online_metadata_priority:
            remote_trigger = self.get_remote_next_trigger(total_time)
            if remote_trigger is not None:
                self.next_trigger_source = "theintrodb"
                return remote_trigger

        chapter_trigger = self.get_last_chapter_trigger(total_time)
        if chapter_trigger is not None:
            self.next_trigger_source = "chapter"
            return chapter_trigger

        if not online_metadata_priority:
            remote_trigger = self.get_remote_next_trigger(total_time)
            if remote_trigger is not None:
                self.next_trigger_source = "theintrodb"
                return remote_trigger

        log("No usable chapter or remote trigger found, falling back to percentage trigger", xbmc.LOGDEBUG)

        fallback_percent = get_setting_int("fallback_trigger_percent", default=90, minimum=50, maximum=99)
        self.next_trigger_source = "fallback"
        return max(1.0, total_time * (fallback_percent / 100.0))

    def get_last_chapter_trigger(self, total_time):
        candidates = []
        cutoff = max(1.0, total_time - 5.0)
        for start_time in self.chapter_starts:
            if 0 < start_time < cutoff:
                candidates.append(start_time)

        if not candidates:
            return None

        return candidates[-1]

    def refresh_chapter_markers(self, total_time):
        starts, percentages = self.get_chapter_markers()
        converted_starts = list(starts)
        for start_percent in percentages:
            start_time = total_time * (start_percent / 100.0)
            if 0 < start_time < total_time:
                converted_starts.append(start_time)

        unique_starts = sorted(set(converted_starts))
        if unique_starts != self.chapter_starts or percentages != self.chapter_percents:
            self.chapter_starts = unique_starts
            self.chapter_percents = percentages
            log(
                "Refreshed chapter markers -> starts=%s percents=%s" % (
                    self.chapter_starts,
                    self.chapter_percents,
                ),
                xbmc.LOGDEBUG,
            )
        if self.skip_intro_allowed and get_setting_bool("enable_skip_intro"):
            self.skip_intro_start, self.skip_intro_target = self.calculate_skip_intro_window(total_time)

    def calculate_skip_intro_window(self, total_time):
        self.skip_intro_remote_source = None
        max_percent = 50
        early_cutoff = total_time * (max_percent / 100.0)
        minimum_intro_target = 20.0
        minimum_gap = 20.0
        online_metadata_priority = get_setting_bool("online_intro_metadata_priority")
        if not self.logged_skip_intro_preferences:
            self.logged_skip_intro_preferences = True
            log(
                "Skip Intro preferences -> online_intro_metadata_priority=%s max_percent=%s fallback_enabled=%s" % (
                    online_metadata_priority,
                    max_percent,
                    get_setting_bool("enable_skip_intro_fallback"),
                ),
                xbmc.LOGDEBUG,
            )
        candidates = []
        previous_start = 0.0
        for start_time in self.chapter_starts:
            if start_time <= 0:
                previous_start = max(previous_start, start_time)
                continue
            if start_time < minimum_intro_target:
                previous_start = start_time
                continue
            if start_time <= early_cutoff and is_meaningful_gap(start_time, previous_start, minimum_gap):
                candidates.append(start_time)
            previous_start = start_time

        def log_remote_window(remote_window):
            rounded_target = round(remote_window[1], 2)
            if self.last_logged_skip_intro_target != rounded_target:
                log(
                    "Using skip intro metadata window %.2f -> %.2f seconds from %s" % (
                        remote_window[0],
                        remote_window[1],
                        self.skip_intro_remote_source or "remote",
                    ),
                    xbmc.LOGDEBUG,
                )
                self.last_logged_skip_intro_target = rounded_target
            return remote_window

        if online_metadata_priority:
            remote_window = self.get_remote_skip_intro_window(total_time)
            if remote_window:
                return log_remote_window(remote_window)

        if candidates:
            if len(candidates) >= 2:
                window_start = candidates[0]
                target = candidates[1]
                rounded_target = round(target, 2)
                if self.last_logged_skip_intro_target != rounded_target:
                    log(
                        "Using skip intro window %.2f -> %.2f seconds" % (
                            window_start,
                            target,
                        ),
                        xbmc.LOGDEBUG,
                    )
                    self.last_logged_skip_intro_target = rounded_target
                return window_start, target

            target = candidates[0]
            rounded_target = round(target, 2)
            if self.last_logged_skip_intro_target != rounded_target:
                log("Using skip intro target %.2f seconds" % target, xbmc.LOGDEBUG)
                self.last_logged_skip_intro_target = rounded_target
            return 1.0, target

        if not online_metadata_priority:
            remote_window = self.get_remote_skip_intro_window(total_time)
            if remote_window:
                return log_remote_window(remote_window)
        return self.get_manual_skip_intro_window(total_time)

    def handle_skip_intro(self, current_time, total_time):
        if not self.skip_intro_allowed:
            if self.overlay_action == "skip_intro":
                self.close_overlay()
            return False

        if not get_setting_bool("enable_skip_intro"):
            if self.overlay_action == "skip_intro":
                self.close_overlay()
            return False

        if self.skip_intro_target is None:
            self.skip_intro_start, self.skip_intro_target = self.calculate_skip_intro_window(total_time)

        if self.skip_intro_target is None:
            return False

        if self.skip_intro_start is None:
            self.skip_intro_start = 1.0

        # Skip Intro should only be offered while playback is still before the intro-end marker.
        if current_time >= self.skip_intro_target:
            if self.overlay_action == "skip_intro":
                self.close_overlay()
            self.skip_intro_prompted = True
            self.cancel_auto_skip_intro(log_message=False)
            return False

        if current_time < self.skip_intro_start:
            return False

        hide_threshold = self.skip_intro_start + ((self.skip_intro_target - self.skip_intro_start) * (1.0 if get_setting_bool("skip_intro_full_segment") else 0.2))
        if current_time >= hide_threshold:
            if self.overlay_action == "skip_intro":
                log(
                    "Closing Skip Intro overlay early in intro window (current=%.2f, start=%.2f, target=%.2f)" % (
                        current_time,
                        self.skip_intro_start,
                        self.skip_intro_target,
                    ),
                    xbmc.LOGDEBUG,
                )
                self.close_overlay()
            self.skip_intro_prompted = True
            self.cancel_auto_skip_intro(log_message=False)
            return False

        if self.auto_skip_intro_active:
            self.handle_auto_skip_intro(current_time)
            return True

        wall_elapsed = None
        if self.skip_intro_overlay_wall_shown_at is not None:
            wall_elapsed = monotonic() - self.skip_intro_overlay_wall_shown_at

        if self.skip_intro_overlay_shown_at is not None and wall_elapsed is not None and wall_elapsed >= 10.0 and not get_setting_bool("skip_intro_full_segment"):
            if self.overlay_action == "skip_intro":
                log(
                    "Closing Skip Intro overlay after timeout (current=%.2f, shown_at=%.2f)" % (
                        current_time,
                        self.skip_intro_overlay_shown_at,
                    ),
                    xbmc.LOGDEBUG,
                )
                self.close_overlay()
            self.skip_intro_prompted = True
            self.cancel_auto_skip_intro(log_message=False)
            return False

        if self.overlay_action == "skip_intro" and self.skip_intro_overlay_shown_at is not None:
            if wall_elapsed is None:
                wall_elapsed = 0.0
            visual_duration = max(0.25, float(self.skip_intro_overlay_visual_duration or 10.0))
            self.update_overlay_progress(1.0 - min(1.0, wall_elapsed / visual_duration))
            return True

        if self.skip_intro_prompted:
            return False

        if self.overlay_action == "skip_intro":
            return True

        if self.overlay:
            return False

        auto_skip_enabled = get_setting_bool("auto_skip_intro")
        auto_skip_delay = get_setting_int("auto_skip_intro_delay", default=2, minimum=0, maximum=10)
        if auto_skip_enabled:
            delay = auto_skip_delay
            if delay <= 0:
                log("Auto-skip Intro is enabled with instant trigger", xbmc.LOGDEBUG)
                self.seek_skip_intro()
                return True

        if auto_skip_enabled:
            self.start_auto_skip_intro_countdown(auto_skip_delay)
        self.show_overlay("skip_intro")
        self.skip_intro_overlay_shown_at = current_time
        self.skip_intro_overlay_wall_shown_at = monotonic()
        self.skip_intro_overlay_visual_duration = max(0.25, hide_threshold - current_time) if get_setting_bool("skip_intro_full_segment") else max(0.25, min(10.0, hide_threshold - current_time))
        self.skip_intro_prompted = True
        if auto_skip_enabled:
            self.update_overlay_progress(0.0)
            log(
                "Displayed Skip Intro overlay with %d second auto-skip countdown" % auto_skip_delay,
                xbmc.LOGDEBUG,
            )
        else:
            self.update_overlay_progress(1.0)
            log("Displayed Skip Intro overlay at %.2f -> target %.2f" % (current_time, self.skip_intro_target), xbmc.LOGDEBUG)
            return True
        return True

    def start_auto_skip_intro_countdown(self, delay):
        self.auto_skip_intro_active = True
        self.auto_skip_intro_started_at = monotonic()
        self.auto_skip_intro_delay = delay
        self.auto_skip_intro_session_file = self.current_file
        self.auto_skip_intro_target = self.skip_intro_target

    def cancel_auto_skip_intro(self, log_message=True):
        if log_message and self.auto_skip_intro_active:
            log("Auto-skip Intro countdown cancelled", xbmc.LOGDEBUG)
        self.auto_skip_intro_active = False
        self.auto_skip_intro_started_at = None
        self.auto_skip_intro_delay = 0
        self.auto_skip_intro_session_file = ""
        self.auto_skip_intro_target = None

    def handle_auto_skip_intro(self, current_time):
        if not self.auto_skip_intro_active:
            return False

        if self.overlay_action != "skip_intro" or not self.overlay:
            self.cancel_auto_skip_intro()
            return False

        if not self.session_matches_current_playback() or self.current_file != self.auto_skip_intro_session_file:
            log("Auto-skip Intro ignored because playback session changed", xbmc.LOGDEBUG)
            self.cancel_auto_skip_intro(log_message=False)
            return False

        if self.skip_intro_target != self.auto_skip_intro_target:
            log("Auto-skip Intro ignored because the skip target changed", xbmc.LOGDEBUG)
            self.cancel_auto_skip_intro(log_message=False)
            return False

        if current_time >= self.skip_intro_target:
            self.cancel_auto_skip_intro(log_message=False)
            return False

        delay = max(1, int(self.auto_skip_intro_delay or 1))
        started_at = self.auto_skip_intro_started_at
        if started_at is None:
            started_at = monotonic()
        elapsed = max(0.0, monotonic() - float(started_at))
        progress = min(1.0, elapsed / float(delay))
        self.update_overlay_progress(progress)

        if progress >= 1.0:
            log("Auto-skip Intro countdown completed", xbmc.LOGDEBUG)
            self.seek_skip_intro()
            return True

        return True

    def get_next_episode(self):
        if self.next_episode is not None:
            return self.next_episode

        current = self.current_episode
        if not current:
            return None

        tvshow_id = current.get("tvshowid")
        current_episode_id = current.get("id") or current.get("episodeid")
        result = jsonrpc(
            "VideoLibrary.GetEpisodes",
            {
                "tvshowid": int(tvshow_id),
                "properties": [
                    "title",
                    "season",
                    "episode",
                    "showtitle",
                    "playcount",
                    "file",
                ],
                "sort": {"method": "episode"},
            },
        )

        episodes = result.get("result", {}).get("episodes", [])
        found_current = False
        for episode in episodes:
            if episode.get("episodeid") == current_episode_id:
                found_current = True
                continue
            if not found_current:
                continue
            if episode.get("file") == self.current_file:
                continue
            self.next_episode = episode
            return episode

        self.next_episode = False
        return None

    def prompt_for_next_episode(self):
        if self.next_overlay_dismissed:
            return

        self.prompted = True

        episode = self.get_next_episode()
        if not episode:
            log("No next library episode found", xbmc.LOGDEBUG)
            return

        auto_play_enabled = get_setting_bool("auto_play_next_episode")
        log("Next On auto-play setting -> %s" % auto_play_enabled, xbmc.LOGDEBUG)
        if auto_play_enabled:
            delay = get_setting_int("auto_play_delay", default=10, minimum=0, maximum=20)
            if delay <= 0:
                log(
                    "Auto-play Next Episode is enabled with instant trigger for episode %s" % (
                        episode.get("episodeid"),
                    ),
                    xbmc.LOGDEBUG,
                )
                self.play_next_episode()
                return

            self.start_auto_play_countdown(episode, delay, update_progress=False)
            self.show_overlay("next_episode")
            self.update_auto_play_progress(0.0)
            log(
                "Displayed Next overlay with %d second auto-play countdown for episode %s" % (
                    delay,
                    episode.get("episodeid"),
                ),
                xbmc.LOGDEBUG,
            )
            return

        self.show_overlay("next_episode")
        log("Displayed Next overlay for episode %s" % episode.get("episodeid"), xbmc.LOGDEBUG)

    def handle_movie_stinger(self, current_time, total_time):
        if not self.current_movie:
            return

        if self.stinger_queried and self.stinger_result is None:
            return

        if not self.stinger_queried:
            self.stinger_result = self.get_stinger_info()
            self.stinger_queried = True

        if self.stinger_result is None:
            return

        has_any = self.stinger_result.get("mid") or self.stinger_result.get("post")
        if not has_any:
            log("Stinger databases report no post-credits scene for this movie", xbmc.LOGDEBUG)
            return

        # Early notification at movie start (always on, configurable window).
        # Bypass the self.overlay check — Skip Intro may have claimed it first.
        early_seconds = get_setting_int("stinger_early_notify_seconds", default=10, minimum=0, maximum=60)
        if early_seconds > 0 and not self.stinger_start_prompted:
            if current_time >= early_seconds:
                self.stinger_start_prompted = True
                toast_duration = get_setting_int("stinger_early_toast_duration", default=12, minimum=1, maximum=30)
                xbmcgui.Dialog().notification(
                    localize(30059),
                    "%s has mid/post-credits scenes" % (self.current_movie.get("label") or ""),
                    xbmcgui.NOTIFICATION_WARNING,
                    toast_duration * 1000,
                )
                log("Displayed Stinger early notification for movie '%s'" % (
                    (self.current_movie or {}).get("label", ""),
                ), xbmc.LOGDEBUG)
                return

        # Credits-zone notification (chapter-based or percentage fallback)
        if self.prompted or self.overlay_action == "stinger":
            return

        if self.overlay:
            return

        trigger_time = self.get_stinger_trigger_time(total_time)
        if current_time < trigger_time:
            return

        self.prompt_for_stinger()

    def prompt_for_stinger(self):
        self.prompted = True
        self.show_overlay("stinger")
        log("Displayed Stinger overlay for movie '%s'" % (
            (self.current_movie or {}).get("title", ""),
        ), xbmc.LOGDEBUG)

    def start_auto_play_countdown(self, episode, delay, update_progress=True):
        self.auto_play_active = True
        self.auto_play_started_at = monotonic()
        self.auto_play_delay = delay
        self.auto_play_session_file = self.current_file
        self.auto_play_episode_id = episode.get("episodeid")
        log(
            "Auto-play Next Episode countdown started: delay=%s episode=%s started_at=%.2f" % (
                delay,
                self.auto_play_episode_id,
                self.auto_play_started_at,
            ),
            xbmc.LOGDEBUG,
        )
        if update_progress:
            self.update_auto_play_progress(0.0)

    def cancel_auto_play(self, log_message=True):
        if log_message and self.auto_play_active:
            log("Auto-play Next Episode countdown cancelled", xbmc.LOGDEBUG)
        self.auto_play_active = False
        self.auto_play_started_at = None
        self.auto_play_delay = 0
        self.auto_play_session_file = ""
        self.auto_play_episode_id = None
        self.update_overlay_progress(0.0, visible=False)

    def handle_auto_play(self, current_time):
        if not self.auto_play_active:
            return False

        if self.next_overlay_dismissed:
            self.cancel_auto_play(log_message=False)
            return False

        if self.overlay_action != "next_episode" or not self.overlay:
            self.cancel_auto_play()
            return False

        if not self.session_matches_current_playback() or self.current_file != self.auto_play_session_file:
            log("Auto-play Next Episode ignored because playback session changed", xbmc.LOGDEBUG)
            self.cancel_auto_play(log_message=False)
            return False

        episode = self.get_next_episode()
        if not episode or episode.get("episodeid") != self.auto_play_episode_id:
            log("Auto-play Next Episode ignored because the next episode changed", xbmc.LOGDEBUG)
            self.cancel_auto_play(log_message=False)
            return False

        delay = max(1, int(self.auto_play_delay or 1))
        started_at = self.auto_play_started_at
        if started_at is None:
            started_at = monotonic()
        elapsed = max(0.0, monotonic() - float(started_at))
        progress = min(1.0, elapsed / float(delay))
        self.update_overlay_progress(progress)

        if progress >= 1.0:
            log("Auto-play Next Episode countdown completed", xbmc.LOGDEBUG)
            self.play_next_episode()
            return True

        return True

    def update_auto_play_progress(self, progress, visible=True):
        self.update_overlay_progress(progress, visible=visible)

    def get_contour_frame_path(self, frame_index):
        color = get_setting_string("contour_color", "blue").lower()
        folder = CONTOUR_COLOR_FOLDERS.get(color, CONTOUR_COLOR_FOLDERS["blue"])
        return "%s/progress-button-%03d.png" % (folder, frame_index)

    def update_overlay_progress(self, progress, visible=True):
        if not self.overlay:
            return

        if not visible:
            progress = 0.0

        frame_index = int(round(max(0.0, min(1.0, progress)) * (AUTO_PLAY_PROGRESS_FRAME_COUNT - 1)))
        if frame_index == self.overlay_progress_frame_index:
            return
        self.overlay_progress_frame_index = frame_index
        self.overlay.setProperty("progress_frame_path", self.get_contour_frame_path(frame_index))
        log("Overlay progress frame set to %03d" % frame_index, xbmc.LOGDEBUG)

    def show_overlay(self, action_name):
        if self.overlay:
            if self.overlay_action == action_name:
                return
            self.close_overlay()

        self.overlay_action = action_name
        xml_filename = self.get_overlay_xml()
        self.overlay = NextOnLibraryOverlay(
            xml_filename,
            ADDON_PATH,
            "default",
            "1080i",
        )
        self.overlay.service = self
        self.overlay.show()
        log(
            "Opened overlay xml=%s for action=%s trigger_source=%s" % (
                xml_filename,
                self.overlay_action,
                self.next_trigger_source,
            ),
            xbmc.LOGDEBUG,
        )

    def configure_overlay_controls(self, overlay):
        show_progress = (
            (self.overlay_action == "next_episode" and self.auto_play_active)
            or self.overlay_action == "skip_intro"
        )
        log(
            "Overlay progress visibility -> action=%s auto_play=%s auto_skip=%s show=%s" % (
                self.overlay_action,
                self.auto_play_active,
                self.auto_skip_intro_active,
                show_progress,
            ),
            xbmc.LOGDEBUG,
        )
        if show_progress:
            if self.overlay_action == "skip_intro" and not self.auto_skip_intro_active:
                self.update_overlay_progress(1.0)
            else:
                self.update_overlay_progress(0.0)
        else:
            self.update_overlay_progress(0.0)

    def get_overlay_label(self):
        if self.overlay_action == "skip_intro":
            return localize(30017)
        if self.overlay_action == "stinger":
            return localize(30059)
        return localize(30011)

    def get_overlay_xml(self):
        return "script-nextonlibrary-overlay.xml"

    def handle_overlay_action(self):
        if self.overlay_action == "skip_intro":
            self.seek_skip_intro()
            return
        if self.overlay_action == "stinger":
            self.close_overlay()
            log("Stinger overlay dismissed by user click", xbmc.LOGDEBUG)
            return
        if self.auto_play_active:
            started_at = self.auto_play_started_at
            if started_at is not None and (monotonic() - float(started_at)) < 0.75:
                log("Ignoring immediate Next overlay activation during auto-play debounce", xbmc.LOGDEBUG)
                return
        self.play_next_episode()

    def dismiss_overlay(self, user_initiated=True):
        if self.overlay_action == "next_episode" and user_initiated:
            self.next_overlay_dismissed = True
            self.prompted = True
            self.cancel_auto_play()
            log("Next overlay dismissed by user action", xbmc.LOGDEBUG)
        elif self.overlay_action == "skip_intro" and user_initiated:
            self.cancel_auto_skip_intro()
            log("Skip Intro overlay dismissed by user action", xbmc.LOGDEBUG)
        elif self.overlay_action == "stinger" and user_initiated:
            log("Stinger overlay dismissed by user action", xbmc.LOGDEBUG)
        self.close_overlay()

    def seek_skip_intro(self):
        target_time = self.skip_intro_target
        try:
            current_time = self.player.getTime()
        except RuntimeError:
            current_time = 0.0
        self.close_overlay()
        self.cancel_auto_skip_intro(log_message=False)
        if target_time is None:
            log("Skip Intro target vanished before click handling", xbmc.LOGDEBUG)
            return
        if current_time >= target_time:
            log(
                "Skip Intro click ignored because playback already passed the target (current=%.2f, target=%.2f)" % (
                    current_time,
                    target_time,
                ),
                xbmc.LOGDEBUG,
            )
            return
        try:
            self.player.seekTime(target_time)
            self.skip_intro_overlay_shown_at = None
            log("Seeking to skip intro target %.2f seconds" % target_time, xbmc.LOGDEBUG)
        except RuntimeError:
            log("Failed to seek to skip intro target %.2f seconds" % target_time, xbmc.LOGDEBUG)

    def play_next_episode(self):
        episode = self.get_next_episode()
        self.cancel_auto_play(log_message=False)
        self.close_overlay()
        if not episode:
            log("Next episode vanished before click handling", xbmc.LOGDEBUG)
            return

        # Pause first so Kodi/Trakt can scrobble at the current position
        # before opening the next episode.
        player_id = self.get_active_player_id()
        if player_id is not None:
            jsonrpc("Player.PlayPause", {"playerid": player_id, "play": False})
            xbmc.sleep(500)

        jsonrpc("Player.Open", {"item": {"episodeid": episode.get("episodeid")}})
        log("Opening next episode %s" % episode.get("episodeid"), xbmc.LOGDEBUG)


if __name__ == "__main__":
    NextOnLibraryService().run()
