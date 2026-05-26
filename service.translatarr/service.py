# -*- coding: utf-8 -*-
import xbmc
import xbmcaddon
import xbmcvfs
import xbmcgui
import os
import time
import math
import sys
import re
import json

import embedded_subtitles
import remote_extractor
import translator
import file_manager
import ui
from languages import get_lang_params, get_iso_variants, get_active_language_setting

ADDON_ID = 'service.translatarr'
ADDON = xbmcaddon.Addon(ADDON_ID)
ADDON_PATH = ADDON.getAddonInfo('path')

CONFIRM_TRANSLATION_BUTTON_CONTROL_ID = 3012
CONTINUE_TRANSLATION_BUTTON_CONTROL_ID = 3013
SKIP_TRANSLATION_BUTTON_CONTROL_ID = 3015
CONFIRM_TRANSLATION_OVERLAY_XML = "script-translatarr-confirmation-overlay.xml"
DEFAULT_CONFIRM_TRANSLATION_DELAY_SECONDS = 2
MAX_CONFIRM_TRANSLATION_DELAY_SECONDS = 60
DEFAULT_CONFIRM_TRANSLATION_REMINDER_SECONDS = 60
MIN_CONFIRM_TRANSLATION_REMINDER_SECONDS = 2
MAX_CONFIRM_TRANSLATION_REMINDER_SECONDS = 120
ACTION_MOVE_LEFT = 1
ACTION_MOVE_RIGHT = 2
ACTION_MOVE_UP = 3
ACTION_MOVE_DOWN = 4
ACTION_SELECT_ITEM = 7
ACTION_PLAYER_STOP = 13
ACTION_NAV_BACK = 92
ACTION_MOUSE_MOVE = 107
ACTION_MOUSE_LEFT_CLICK = 100
ACTION_MOUSE_DOUBLE_CLICK = 103
ACTION_MOUSE_DRAG = 106

# Special folder for Translatarr translations (profile-safe)
TRANSLATARR_SUB_FOLDER = xbmcvfs.translatePath(
    "special://profile/addon_data/service.translatarr/subtitles/"
)

A4K_SUB_FOLDER = xbmcvfs.translatePath(
    "special://profile/addon_data/service.subtitles.a4ksubtitles/temp/"
)

KODI_TEMP_SUB_FOLDER = xbmcvfs.translatePath(
    "special://temp/"
)

if not xbmcvfs.exists(TRANSLATARR_SUB_FOLDER):
    xbmcvfs.mkdir(TRANSLATARR_SUB_FOLDER)

xbmc.log("[Translatarr] SERVICE STARTED", xbmc.LOGINFO)

# ----------------------------------------------------------
# Logging
# ----------------------------------------------------------
_global_monitor = None  # module-level reference for logging

def set_global_monitor(monitor_instance):
    """Safely set the module-wide global monitor."""
    global _global_monitor
    _global_monitor = monitor_instance

def log(msg, level='info', monitor=None, force=False):
    resolved_monitor = monitor if monitor else _global_monitor
    debug_enabled = getattr(resolved_monitor, 'debug_mode', False)
    if force or level != 'debug' or debug_enabled:
        prefix = "[Translatarr]"
        if level == 'debug':
            xbmc.log(f"{prefix}[DEBUG] {msg}", xbmc.LOGINFO)
        elif level == 'error':
            xbmc.log(f"{prefix}[ERROR] {msg}", xbmc.LOGERROR)
        else:
            xbmc.log(f"{prefix} {msg}", xbmc.LOGINFO)

# ----------------------------------------------------------
# Helpers
# ----------------------------------------------------------
def normalize_name(name):
    return re.sub(r'[^a-zA-Z0-9]', '', name.lower())

def normalize_stem(name):
    if not name:
        return ""
    base_name = os.path.basename(str(name).replace("\\", "/"))
    stem, _ = os.path.splitext(base_name)
    return normalize_name(stem)
    
def vfs_join(folder, file):
    return (folder.rstrip("/\\") + "/" + file.lstrip("/\\")).replace("\\", "/")
    
def safe_filename(name):
    name = re.sub(r'[<>:"/\\|?*]+', '_', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name.rstrip('. ')

def subtitle_matches_video(video_name, subtitle_name):
    video_stem = normalize_stem(video_name)
    subtitle_stem = normalize_stem(subtitle_name)
    if not video_stem or not subtitle_stem:
        return False
    return subtitle_stem.startswith(video_stem)


def subtitle_matches_language_suffix(filename, lang_variants):
    filename_lower = (filename or "").lower()
    descriptor_suffixes = ("sdh", "hi", "cc", "forced")

    for variant in lang_variants:
        variant_lower = (variant or "").lower()
        if not variant_lower:
            continue

        if filename_lower.endswith(".{0}.srt".format(variant_lower)):
            return True

        for descriptor in descriptor_suffixes:
            if filename_lower.endswith(".{0}.{1}.srt".format(variant_lower, descriptor)):
                return True

    return False

TEMP_SUBTITLE_TOLERANCE_SECONDS = 10

def is_vfs_network_path(path):
    return bool(path) and path.startswith(
        ("smb://", "nfs://", "dav://", "ftp://", "sftp://")
    )
    
def get_best_playing_path(self):
    candidates = [
        xbmc.getInfoLabel("Player.Filenameandpath"),
        xbmc.getInfoLabel("ListItem.FileNameAndPath"),
        xbmc.Player().getPlayingFile(),
    ]

    for path in candidates:
        if not path:
            continue
        path = path.strip()

        # Prefer real playable paths over plugin paths
        if is_vfs_network_path(path):
            return path
        if path.startswith("/") or ":\\" in path:
            return path

    return xbmc.Player().getPlayingFile()


def get_preferred_video_name(best_playing_path, fallback_title=None):
    if is_real_media_path(best_playing_path):
        return os.path.splitext(os.path.basename(best_playing_path))[0]

    if fallback_title:
        fallback_title = fallback_title.strip()
        if fallback_title:
            return fallback_title

    return "Streamed_Video"


def is_real_media_path(path_value):
    value = (path_value or "").strip().lower()
    if not value:
        return False
    return not value.startswith(("plugin://", "http://", "https://"))

def get_kodi_temp_scan_folders():
    folders = [KODI_TEMP_SUB_FOLDER]

    try:
        subdirs, _ = xbmcvfs.listdir(KODI_TEMP_SUB_FOLDER)
    except Exception:
        return folders

    for subdir in subdirs:
        subfolder = vfs_join(KODI_TEMP_SUB_FOLDER, subdir)
        folders.append(subfolder)

    return folders


def _normalized_dirname(path_value):
    value = (path_value or "").strip()
    if not value:
        return ""
    return os.path.dirname(value.rstrip("/\\")) if os.path.splitext(value)[1] else value.rstrip("/\\")


def _platform_name():
    if remote_extractor.is_android():
        return "Android"
    if remote_extractor.is_windows():
        return "Windows"
    if remote_extractor.is_linux():
        return "Linux"
    return "Other"


def _normalize_candidate_path(path_value):
    return (path_value or "").replace("\\", "/").rstrip("/").lower()


def _build_translation_candidate_key(path_value, mtime_value, size_value):
    return "{0}|{1}|{2}".format(
        _normalize_candidate_path(path_value),
        int(mtime_value or 0),
        int(size_value or 0)
    )


def _foreground_ui_blocks_confirmation_overlay():
    # Kodi can report fullscreen playback chrome or invisible player dialogs as
    # the current dialog for the whole playback session. Blocking on those keeps
    # the confirmation overlay from ever opening, so only defer while seeking.
    return xbmc.getCondVisibility("Player.Seeking")


def _tool_exists(tool_name, folder_path=None):
    if folder_path:
        candidate_names = [tool_name]
        if os.name == "nt" and not tool_name.lower().endswith(".exe"):
            candidate_names.insert(0, tool_name + ".exe")
        for candidate_name in candidate_names:
            candidate_path = os.path.join(folder_path, candidate_name)
            if os.path.exists(candidate_path):
                return True

    path_value = os.environ.get("PATH", "")
    for search_dir in path_value.split(os.pathsep):
        if not search_dir:
            continue
        candidate_path = os.path.join(search_dir, tool_name)
        if os.path.exists(candidate_path):
            return True
        if os.name == "nt":
            candidate_exe = candidate_path + ".exe"
            if os.path.exists(candidate_exe):
                return True
    return False


def _local_embedded_tools_available(media_path, mkvtoolnix_folder=None, ffmpeg_folder=None):
    extension = os.path.splitext(media_path or "")[1].lower()
    if extension == ".mkv":
        return _tool_exists("mkvinfo", mkvtoolnix_folder) and _tool_exists("mkvextract", mkvtoolnix_folder)
    if extension == ".mp4":
        return _tool_exists("ffmpeg", ffmpeg_folder) and _tool_exists("ffprobe", ffmpeg_folder)
    return False
    
# ----------------------------------------------------------
# Subtitle Processing with TEMP FILES
# ----------------------------------------------------------
def process_subtitles(original_path, monitor, force_retranslate=False, save_path=None, show_source_immediately=True):
    log(f"process_subtitles called with: {original_path}, force_retranslate={force_retranslate}", "debug", monitor)

    try:
        if not xbmc.Player().isPlayingVideo():
            return False

        playing_file = xbmc.Player().getPlayingFile()
        if not playing_file:
            return False
            
        session_playing_file = playing_file
            
        raw_name = xbmc.getInfoLabel('Player.Title')
        session_best_path = get_best_playing_path(monitor)
        video_name = get_preferred_video_name(session_best_path or playing_file, raw_name)
        log(f"Processing for video: {video_name}", "debug", monitor)

        # Ensure save_path is VFS compatible (forward slashes)
        if save_path is None:
            save_path, clean_name = file_manager.get_target_path(original_path, video_name)
        else:
            # Fix slash direction for Kodi VFS
            save_path = save_path.replace('\\', '/')
            clean_name = os.path.splitext(os.path.basename(save_path))[0]

        target_display_name = os.path.basename(save_path)

        temp_path = save_path + ".tmp"
        initial_source_mtime = 0
        initial_source_size = 0

        # Check existing
        if xbmcvfs.exists(save_path) and not force_retranslate:
            log("Subtitle already exists. Loading.", "debug", monitor)
            monitor.load_subtitle_if_new(save_path)
            return True

        initial_chunk = max(10, min(int(monitor.chunk_size or 100), 150))
        model_name = translator.get_model_string()

        progress = None
        try:
            # Use a slightly cleaner title for the UI
            progress = ui.TranslationProgress(model_name=model_name, title=video_name[:30] + "...")
            
            # Read source - xbmcvfs is essential for special:// and plugin://
            # Wait briefly for subtitle to finish writing
            try:
                stat1 = xbmcvfs.Stat(original_path).st_size()
                time.sleep(0.25)
                stat2 = xbmcvfs.Stat(original_path).st_size()

                if stat1 != stat2:
                    log("Subtitle still being written. Skipping this poll.", "debug", monitor)
                    return False
            except Exception:
                pass

            try:
                initial_stat = xbmcvfs.Stat(original_path)
                initial_source_mtime = initial_stat.st_mtime()
                initial_source_size = initial_stat.st_size()
            except Exception:
                pass

            with xbmcvfs.File(original_path, 'r') as f:
                content = f.read()

            if not content:
                log("Source SRT is empty.", "debug", monitor)
                return False

            timestamps, texts = file_manager.parse_srt(content)
            if not timestamps:
                log("Invalid SRT format.", "error", monitor)
                return False

            cleaned_texts = []
            work_items = []
            for idx, text in enumerate(texts):
                if monitor.remove_sdh_hi_cues:
                    cleaned = file_manager.clean_sdh_hi_text(text)
                    cleaned_texts.append(cleaned)
                    if cleaned is not None:
                        work_items.append((idx, cleaned))
                else:
                    cleaned_texts.append(text)
                    work_items.append((idx, text))

            display_source_texts = list(cleaned_texts) if monitor.dual_language_display else None

            total_lines = len(texts)
            total_translatable = len(work_items)
            removed_line_count = total_lines - total_translatable if monitor.remove_sdh_hi_cues else 0
            if total_translatable == 0:
                log("No translatable dialogue remained after SDH/HI cue removal.", "debug", monitor)
                return False
             
            total_chunks_est = math.ceil(total_translatable / initial_chunk)
            log(
                f"Total lines: {total_lines}, translatable lines: {total_translatable}, removed by SDH/HI cleanup: {removed_line_count}, estimated chunks: {total_chunks_est}",
                "debug",
                monitor
            )
     
            all_translated = [None] * total_lines
            for idx, cleaned in enumerate(cleaned_texts):
                if cleaned is None:
                    all_translated[idx] = ""
            cum_in = 0
            cum_out = 0
            idx = 0
            completed_chunks = 0
            start_time = time.time()
            min_chunk = 5
    
            monitor.live_reload_index = 0
    
            # Immediately display new subtitle mid-playback if it's a fresh source
            if show_source_immediately and xbmcvfs.exists(original_path):
                try:
                    monitor.load_subtitle_if_new(original_path)
                    log("Displayed newly detected source subtitle instantly.", "debug", monitor)
                except Exception as e:
                    log(f"Failed to instantly display source subtitle: {e}", "error", monitor)
    
            while idx < total_translatable:
                if xbmc.Player().getPlayingFile() != session_playing_file:
                    log("Playback target changed during translation. Aborting current job.", "debug", monitor)
                    return False

                if initial_source_mtime or initial_source_size:
                    try:
                        current_stat = xbmcvfs.Stat(original_path)
                        if (
                            current_stat.st_mtime() != initial_source_mtime or
                            current_stat.st_size() != initial_source_size
                        ):
                            log("Source subtitle changed during translation. Aborting current job.", "debug", monitor)
                            return False
                    except Exception:
                        log("Source subtitle is no longer accessible during translation. Aborting current job.", "debug", monitor)
                        return False

                if progress.is_canceled() or not xbmc.Player().isPlayingVideo():
                    log("Playback stopped or user canceled.", "debug", monitor)
                    return False
    
                success = False
                chunk_size = initial_chunk
                retries = 0
    
                while retries < 3 and not success:
                    if xbmc.Player().getPlayingFile() != session_playing_file:
                        log("Playback target changed during retry. Aborting current job.", "debug", monitor)
                        return False
                        
                    curr_size = min(chunk_size, total_translatable - idx)
                    log(f"Translating chunk {idx}-{idx+curr_size}, size: {curr_size}", "debug", monitor)
     
                    batch_items = work_items[idx:idx + curr_size]
                    batch_texts = [item[1] for item in batch_items]
                    res, in_t, out_t = translator.translate_batch(batch_texts, curr_size)
     
                    if res:
                        for (line_index, _), translated_line in zip(batch_items, res):
                            all_translated[line_index] = translated_line
                        cum_in += in_t
                        cum_out += out_t
                        idx += curr_size
                        completed_chunks += 1
                        success = True
                        percent = int((idx / total_translatable) * 100)
                        log(f"Chunk translated. Progress: {percent}%", "debug", monitor)
                        progress.update(
                            percent,
                            src_name=video_name,
                            trg_name=clean_name,
                            chunk_num=completed_chunks,
                            total_chunks=total_chunks_est,
                            lines_done=idx,
                            total_lines=total_translatable
                        )
     
                        # Live translation progressive reload
                        percent_done = int((idx / total_translatable) * 100)
                        if (monitor.live_reload_index < len(monitor.live_reload_points) and
                            percent_done >= monitor.live_reload_points[monitor.live_reload_index]):
                            try:
                                prefix_count = 0
                                while prefix_count < total_lines and all_translated[prefix_count] is not None:
                                    prefix_count += 1
                                log(f"Live mode: writing partial SRT at {percent_done}%", "debug", monitor)
                                if prefix_count:
                                    file_manager.write_srt(
                                        temp_path,
                                        timestamps[:prefix_count],
                                        all_translated[:prefix_count],
                                        source_texts=display_source_texts[:prefix_count] if display_source_texts else None,
                                        dual_language=monitor.dual_language_display
                                    )
                                    monitor.load_subtitle_if_new(temp_path)
                            except Exception as e:
                                log(f"Live write failed: {e}", "error", monitor)
                            monitor.live_reload_index += 1
    
                    else:
                        retries += 1
                        chunk_size = max(chunk_size // 2, min_chunk)
                        log(f"Chunk rejected. Retry {retries}. New size {chunk_size}", "debug", monitor)
                        time.sleep(2)
    
                if not success:
                    ui.notify("Critical failure: API rejected all chunk sizes.")
                    log("Aborting translation: all retries failed.", "error", monitor)
                    return False
     
            if any(line is None for line in all_translated):
                log("Translated subtitle assembly incomplete after chunk processing.", "error", monitor)
                return False

            log("Writing translated SRT TEMP file.", "debug", monitor)
            file_manager.write_srt(
                temp_path,
                timestamps,
                all_translated,
                source_texts=display_source_texts,
                dual_language=monitor.dual_language_display
            )
    
            if xbmcvfs.exists(save_path):
                xbmcvfs.delete(save_path)
            
            # Rename is safer than delete+write for file locks
            if xbmcvfs.rename(temp_path, save_path):
                log(f"Successfully saved: {save_path}", "debug", monitor)
                monitor.load_subtitle_if_new(save_path)
                total_time = time.time() - start_time
                cost = translator.calculate_cost(cum_in, cum_out)
                trg_name = monitor.target_lang_name
                log(f"Translation finished. Total time: {total_time:.2f}s, cost: ${cost:.4f}", "debug", monitor)
        
                if monitor.show_stats:
                    ui.show_stats_box(
                        os.path.basename(original_path),
                        target_display_name,
                        trg_name,
                        save_path,
                        cost,
                        cum_in + cum_out,
                        total_chunks_est,
                        initial_chunk,
                        model_name,
                        total_time
                    )
        
                if monitor.use_notifications:
                    ui.notify(
                        f"✔ Done in {ui.format_time(total_time)} | Cost: ${cost:.4f}",
                        title=f"{model_name} → {trg_name}"
                    )
        
                return True    
                
            else:
                log("VFS Rename failed.", "error", monitor)
                return False 
            
        finally:
            if progress:
                progress.close()
            
    except Exception as e:
        xbmc.log(f"[Translatarr][ERROR] {e}", xbmc.LOGERROR)
        ui.notify(f"Error: {e}", title="Translatarr Error")
        return False

# ----------------------------------------------------------
# Translation Confirmation Overlay
# ----------------------------------------------------------
class TranslatarrConfirmationOverlay(xbmcgui.WindowXMLDialog):

    def __init__(self, *args, **kwargs):
        xbmcgui.WindowXMLDialog.__init__(self, *args, **kwargs)
        self.service = None

    def _move_focus(self, direction):
        focus_order = (
            CONFIRM_TRANSLATION_BUTTON_CONTROL_ID,
            CONTINUE_TRANSLATION_BUTTON_CONTROL_ID,
            SKIP_TRANSLATION_BUTTON_CONTROL_ID,
        )
        try:
            focused_id = self.getFocusId()
            current_index = focus_order.index(focused_id)
        except (RuntimeError, ValueError):
            current_index = 1

        next_index = (current_index + direction) % len(focus_order)
        try:
            self.setFocusId(focus_order[next_index])
        except RuntimeError:
            pass

    def onInit(self):  # pylint: disable=invalid-name
        try:
            if self.service:
                self.getControl(CONFIRM_TRANSLATION_BUTTON_CONTROL_ID).setLabel(
                    self.service.get_confirmation_overlay_label("translate")
                )
                self.getControl(CONTINUE_TRANSLATION_BUTTON_CONTROL_ID).setLabel(
                    self.service.get_confirmation_overlay_label("continue")
                )
                self.getControl(SKIP_TRANSLATION_BUTTON_CONTROL_ID).setLabel(
                    self.service.get_confirmation_overlay_label("skip")
                )
            self.setFocusId(CONTINUE_TRANSLATION_BUTTON_CONTROL_ID)
        except RuntimeError:
            pass

    def onClick(self, control_id):  # pylint: disable=invalid-name
        if control_id == CONFIRM_TRANSLATION_BUTTON_CONTROL_ID and self.service:
            self.service.approve_translation_confirmation()
        elif control_id == CONTINUE_TRANSLATION_BUTTON_CONTROL_ID and self.service:
            self.service.continue_translation_confirmation()
        elif control_id == SKIP_TRANSLATION_BUTTON_CONTROL_ID and self.service:
            self.service.skip_translation_confirmation()

    def onAction(self, action):  # pylint: disable=invalid-name
        action_id = action.getId()
        if action_id == ACTION_SELECT_ITEM and self.service:
            focused_id = self.getFocusId()
            if focused_id == CONFIRM_TRANSLATION_BUTTON_CONTROL_ID:
                self.service.approve_translation_confirmation()
                return
            if focused_id == CONTINUE_TRANSLATION_BUTTON_CONTROL_ID:
                self.service.continue_translation_confirmation()
                return
            if focused_id == SKIP_TRANSLATION_BUTTON_CONTROL_ID:
                self.service.skip_translation_confirmation()
                return
        elif action_id == ACTION_MOVE_LEFT:
            self._move_focus(-1)
            return
        elif action_id == ACTION_MOVE_RIGHT:
            self._move_focus(1)
            return
        elif action_id in (ACTION_MOVE_UP, ACTION_MOVE_DOWN):
            return
        elif action_id in (
            ACTION_MOUSE_MOVE,
            ACTION_MOUSE_LEFT_CLICK,
            ACTION_MOUSE_DOUBLE_CLICK,
            ACTION_MOUSE_DRAG,
        ):
            return

        if self.service:
            if action_id == ACTION_PLAYER_STOP:
                self.service.close_translation_confirmation_overlay()
            elif action_id == ACTION_NAV_BACK:
                self.service.continue_translation_confirmation(user_initiated=True)
            else:
                return
        else:
            self.close()


# ----------------------------------------------------------
# Monitor
# ----------------------------------------------------------
class TranslatarrMonitor(xbmc.Monitor):

    def __init__(self):
        super().__init__()
        self.reset_playback_state()
        self.reload_settings()
        log("Monitor initialized.", "debug", self)

    def is_playing_network_stream(self):
        playing_file = xbmc.Player().getPlayingFile()
        return bool(playing_file) and playing_file.startswith(
            ("plugin://", "http://", "https://", "dav://", "sftp://")
        )
            
    def onSettingsChanged(self):
        log("Settings changed → reloading monitor.", "debug", self, force=True)
        self.reload_settings()

   
    def load_subtitle_if_new(self, path):
        try:
            stat = xbmcvfs.Stat(path)
            mtime = stat.st_mtime()

            # Skip if same file and same modification time
            if (getattr(self, "last_loaded_subtitle_path", None) == path and
                getattr(self, "last_loaded_subtitle_mtime", 0) == mtime):
                return False

            xbmc.Player().setSubtitles(path)
            self.last_loaded_subtitle_path = path
            self.last_loaded_subtitle_mtime = mtime
            log(f"Loaded subtitle: {path}", "debug", self)
            return True
        except Exception as e:
            log(f"Failed to load subtitle: {e}", "error", self)
            return False

    def get_confirmation_overlay_label(self, action="translate"):
        if action == "continue":
            reminder_seconds = getattr(
                self,
                "translation_confirmation_reminder_delay",
                DEFAULT_CONFIRM_TRANSLATION_REMINDER_SECONDS
            )
            label_template = ADDON.getLocalizedString(30096) or "Remind:{0}s"
            try:
                return label_template.format(reminder_seconds)
            except Exception:
                return "Remind:{0}s".format(reminder_seconds)
        if action == "skip":
            return ADDON.getLocalizedString(30098) or "Skip"
        return ADDON.getLocalizedString(30093) or "Translate"

    def close_translation_confirmation_overlay(self):
        overlay = getattr(self, "translation_confirmation_overlay", None)
        if not overlay:
            self.translation_confirmation_overlay = None
            return
        try:
            overlay.close()
        except RuntimeError:
            pass
        self.translation_confirmation_overlay = None

    def clear_translation_confirmation_candidate(self, close_overlay=True, clear_dismissals=False):
        if close_overlay:
            self.close_translation_confirmation_overlay()
        self.pending_translation_candidate = None
        self.approved_translation_candidate_key = None
        self.translation_confirmation_eligible_at = 0
        if clear_dismissals:
            self.dismissed_translation_candidate_keys = set()

    def return_to_fullscreen_for_translation_confirmation(self, candidate):
        try:
            if xbmc.Player().isPlayingVideo():
                xbmc.executebuiltin("ActivateWindow(fullscreenvideo)")
                delay_seconds = getattr(
                    self,
                    "translation_confirmation_delay",
                    DEFAULT_CONFIRM_TRANSLATION_DELAY_SECONDS
                )
                self.translation_confirmation_eligible_at = time.time() + delay_seconds
                log(
                    "Loaded source subtitle and returned to fullscreen before translation confirmation: {0} | delay={1}s".format(
                        candidate.get("path"),
                        delay_seconds
                    ),
                    "debug",
                    self
                )
        except Exception as e:
            log(f"Failed to return to fullscreen before translation confirmation: {e}", "debug", self)

    def show_translation_confirmation_overlay(self):
        if not getattr(self, "require_translation_confirmation", False):
            return
        candidate = getattr(self, "pending_translation_candidate", None)
        if not candidate or candidate.get("key") in getattr(self, "dismissed_translation_candidate_keys", set()):
            return
        eligible_at = getattr(self, "translation_confirmation_eligible_at", 0)
        if eligible_at and time.time() < eligible_at:
            return
        if _foreground_ui_blocks_confirmation_overlay():
            log(
                "Delaying translation confirmation overlay because another Kodi dialog/player UI is in front.",
                "debug",
                self
            )
            return
        if self.translation_confirmation_overlay:
            return

        self.translation_confirmation_overlay = TranslatarrConfirmationOverlay(
            CONFIRM_TRANSLATION_OVERLAY_XML,
            ADDON_PATH,
            "default",
            "1080i",
        )
        self.translation_confirmation_overlay.service = self
        self.translation_confirmation_overlay.show()
        log(
            "Opened translation confirmation overlay for candidate: {0}".format(
                candidate.get("path")
            ),
            "debug",
            self
        )

    def approve_translation_confirmation(self):
        candidate = getattr(self, "pending_translation_candidate", None)
        if not candidate:
            self.close_translation_confirmation_overlay()
            return

        self.approved_translation_candidate_key = candidate.get("key")
        self.dismissed_translation_candidate_keys.discard(candidate.get("key"))
        log(
            "Approved translation confirmation for candidate: {0}".format(
                candidate.get("path")
            ),
            "debug",
            self
        )
        self.close_translation_confirmation_overlay()

    def continue_translation_confirmation(self, user_initiated=True):
        candidate = getattr(self, "pending_translation_candidate", None)
        if candidate:
            reminder_seconds = getattr(
                self,
                "translation_confirmation_reminder_delay",
                DEFAULT_CONFIRM_TRANSLATION_REMINDER_SECONDS
            )
            self.translation_confirmation_eligible_at = time.time() + reminder_seconds
            log(
                "Continued watching with translation confirmation pending for candidate: {0} | reminder={1}s | user_initiated={2}".format(
                    candidate.get("path"),
                    reminder_seconds,
                    user_initiated
                ),
                "debug",
                self
            )
        self.close_translation_confirmation_overlay()

    def skip_translation_confirmation(self, user_initiated=True):
        candidate = getattr(self, "pending_translation_candidate", None)
        if candidate:
            self.dismissed_translation_candidate_keys.add(candidate.get("key"))
            if self.approved_translation_candidate_key == candidate.get("key"):
                self.approved_translation_candidate_key = None
            log(
                "Skipped translation confirmation for candidate: {0} | user_initiated={1}".format(
                    candidate.get("path"),
                    user_initiated
                ),
                "debug",
                self
            )
        self.close_translation_confirmation_overlay()

    def dismiss_translation_confirmation(self, user_initiated=True):
        self.continue_translation_confirmation(user_initiated=user_initiated)

    def build_translation_candidate(self, source_path, source_mtime, source_size, force_retranslate=False, save_path=None, show_source_immediately=True):
        return {
            "path": source_path,
            "mtime": source_mtime,
            "size": source_size,
            "key": _build_translation_candidate_key(source_path, source_mtime, source_size),
            "force_retranslate": force_retranslate,
            "save_path": save_path,
            "show_source_immediately": show_source_immediately,
        }

    def should_bypass_translation_confirmation(self, source_path):
        normalized_path = _normalize_candidate_path(source_path)
        return normalized_path in getattr(self, "confirmation_bypass_source_paths", set())

    def prepare_source_candidate_for_translation(self, candidate):
        if self.should_bypass_translation_confirmation(candidate.get("path")):
            return "process_now"

        if not getattr(self, "require_translation_confirmation", False):
            return "process_now"

        candidate_key = candidate.get("key")
        if candidate_key == getattr(self, "approved_translation_candidate_key", None):
            return "process_now"

        if candidate_key in getattr(self, "dismissed_translation_candidate_keys", set()):
            return "dismissed"

        current_candidate = getattr(self, "pending_translation_candidate", None)
        if not current_candidate or current_candidate.get("key") != candidate_key:
            self.pending_translation_candidate = candidate
            self.translation_confirmation_eligible_at = 0
            if candidate.get("show_source_immediately"):
                self.load_subtitle_if_new(candidate.get("path"))
            self.return_to_fullscreen_for_translation_confirmation(candidate)
            self.show_translation_confirmation_overlay()
            return "deferred"

        self.pending_translation_candidate = candidate
        if candidate.get("show_source_immediately"):
            self.load_subtitle_if_new(candidate.get("path"))
        self.show_translation_confirmation_overlay()
        return "deferred"

    def finalize_translation_candidate_attempt(self, candidate, success):
        candidate_key = candidate.get("key") if candidate else None
        candidate_path = candidate.get("path") if candidate else ""

        if candidate_key and self.approved_translation_candidate_key == candidate_key:
            self.approved_translation_candidate_key = None

        if candidate_key and not success and getattr(self, "require_translation_confirmation", False):
            self.dismissed_translation_candidate_keys.add(candidate_key)

        if getattr(self, "pending_translation_candidate", None) and self.pending_translation_candidate.get("key") == candidate_key:
            self.pending_translation_candidate = None

        if success and candidate_path:
            self.dismissed_translation_candidate_keys.discard(candidate_key)

        self.close_translation_confirmation_overlay()

    def process_translation_candidate(self, candidate):
        self.is_busy = True
        try:
            success = process_subtitles(
                candidate.get("path"),
                self,
                force_retranslate=candidate.get("force_retranslate", False),
                save_path=candidate.get("save_path"),
                show_source_immediately=candidate.get("show_source_immediately", True)
            )
        finally:
            self.is_busy = False

        self.finalize_translation_candidate_attempt(candidate, success)
        return success

    def kodi_rpc(self, method, params=None):
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": params or {}
            }
            raw = xbmc.executeJSONRPC(json.dumps(payload))
            data = json.loads(raw) if raw else {}
            if "error" in data:
                log(f"Kodi JSON-RPC error for {method}: {data['error']}", "debug", self)
                return {}
            return data.get("result", {})
        except Exception as e:
            log(f"Kodi JSON-RPC exception for {method}: {e}", "debug", self)
            return {}

    def inspect_kodi_subtitle_location_settings(self, emit_logs=True):
        self.kodi_subtitle_storage_mode = None
        self.kodi_subtitle_custom_path = None

        result = self.kodi_rpc("Settings.GetSettings", {"level": "advanced"})
        settings = result.get("settings", [])
        if not settings:
            if emit_logs:
                log("Kodi subtitle settings probe returned no settings.", "debug", self)
            return

        relevant = []

        for setting in settings:
            sid = str(setting.get("id", "") or "")
            label = str(setting.get("label", "") or "")
            value = setting.get("value")
            haystack = f"{sid} {label}".lower()

            if "subtitle" not in haystack:
                continue

            if not any(token in haystack for token in ("storage", "location", "folder", "path", "save")):
                continue

            option_label = None
            options = setting.get("options") or []
            if isinstance(value, int) and isinstance(options, list) and 0 <= value < len(options):
                option = options[value]
                if isinstance(option, dict):
                    option_label = option.get("label")
                else:
                    option_label = option

            relevant.append({
                "id": sid,
                "label": label,
                "value": value,
                "option_label": option_label
            })

            mode_text = ""
            if option_label is not None:
                mode_text = str(option_label).lower()
            elif isinstance(value, str):
                mode_text = value.lower()

            if any(token in haystack for token in ("storage", "location", "save")):
                if "next" in mode_text and "video" in mode_text:
                    self.kodi_subtitle_storage_mode = "next_to_video"
                elif "custom" in mode_text:
                    self.kodi_subtitle_storage_mode = "custom"

            if any(token in haystack for token in ("folder", "path", "custom")) and isinstance(value, str):
                if value.startswith("special://") or "/" in value or "\\" in value:
                    self.kodi_subtitle_custom_path = value

        if relevant:
            if emit_logs:
                for item in relevant:
                    log(
                        "Kodi subtitle setting → "
                        f"id={item['id']}, label={item['label']}, value={item['value']}, option={item['option_label']}",
                        "debug",
                        self,
                        force=True
                    )

                log(
                    "Kodi subtitle location summary → "
                    f"mode={self.kodi_subtitle_storage_mode}, custom_path={self.kodi_subtitle_custom_path}",
                    "debug",
                    self,
                    force=True
                )
        elif emit_logs:
            log("No Kodi subtitle location-related settings were discovered via JSON-RPC.", "debug", self, force=True)

    def refresh_kodi_subtitle_location_settings_if_changed(self):
        previous_mode = getattr(self, "kodi_subtitle_storage_mode", None)
        previous_path = getattr(self, "kodi_subtitle_custom_path", None)

        self.inspect_kodi_subtitle_location_settings(emit_logs=False)

        changed = (
            previous_mode != getattr(self, "kodi_subtitle_storage_mode", None)
            or previous_path != getattr(self, "kodi_subtitle_custom_path", None)
        )

        if changed:
            log(
                "Kodi subtitle location changed → "
                f"mode={self.kodi_subtitle_storage_mode}, custom_path={self.kodi_subtitle_custom_path}",
                "debug",
                self,
                force=True
            )

        return changed

    def reload_settings(self):
        """
        Reload addon settings safely.
        Designed to work with both settings version="1" and version="2".
        Prevents TypeError from getSettingBool() and avoids stale runtime state.
        """
    
        addon = xbmcaddon.Addon(ADDON_ID)
        previous_service_enabled = getattr(self, "service_enabled", True)
    
        # ------------------------------------------------------------
        # Helper: Safe boolean reader (version-agnostic)
        # ------------------------------------------------------------
        def safe_bool(key, fallback=False):
            """
            Safely read boolean setting.
            Works even if Kodi returns string instead of real bool.
            """
            try:
                return addon.getSettingBool(key)
            except (TypeError, ValueError):
                raw = str(addon.getSetting(key) or '').strip().lower()
                if raw == '':
                    return fallback
                if raw in ('true', '1', 'yes', 'on'):
                    return True
                elif raw in ('false', '0', 'no', 'off'):
                    return False
                return fallback
    
        # ------------------------------------------------------------
        # Helper: Safe integer reader
        # ------------------------------------------------------------
        def safe_int(key, fallback):
            """
            Safely read integer setting.
            Prevents crashes if setting is empty or corrupted.
            """
            try:
                return int(addon.getSetting(key))
            except (TypeError, ValueError):
                log(f"Invalid integer setting for '{key}', using fallback {fallback}", "error", self)
                return fallback
    
        # ------------------------------------------------------------
        # Boolean settings
        # ------------------------------------------------------------
        mode = addon.getSetting('translation_mode')
        self.service_enabled = safe_bool('service_enabled', True)
        self.require_translation_confirmation = safe_bool('require_translation_confirmation', True)
        self.auto_mode = mode == "Auto"
        log(f"Translation mode: {mode}", "debug", self)
        self.debug_mode = safe_bool('debug_mode', False)
        self.use_notifications = safe_bool('notify_mode', True)
        self.show_stats = safe_bool('show_stats', True)
        self.remove_sdh_hi_cues = safe_bool('remove_sdh_hi_cues', False)
        self.dual_language_display = safe_bool('dual_language_display', False)
        self.enable_embedded_subtitle_extraction = safe_bool('enable_embedded_subtitle_extraction', False)
        self.force_embedded_source_extraction = safe_bool('force_embedded_source_extraction', False)
        self.remote_extractor_enabled = safe_bool('remote_extractor_enabled', False)
    
        # ------------------------------------------------------------
        # Numeric / string settings
        # ------------------------------------------------------------
        self.chunk_size = safe_int('chunk_size', 100)
        self.translation_confirmation_delay = max(
            0,
            min(
                MAX_CONFIRM_TRANSLATION_DELAY_SECONDS,
                safe_int('translation_confirmation_delay', DEFAULT_CONFIRM_TRANSLATION_DELAY_SECONDS)
            )
        )
        self.translation_confirmation_reminder_delay = max(
            MIN_CONFIRM_TRANSLATION_REMINDER_SECONDS,
            min(
                MAX_CONFIRM_TRANSLATION_REMINDER_SECONDS,
                safe_int('translation_confirmation_reminder_delay', DEFAULT_CONFIRM_TRANSLATION_REMINDER_SECONDS)
            )
        )
        self.sub_folder = addon.getSetting('sub_folder') or "/storage/emulated/0/Download/"
        legacy_mkvinfo_path = addon.getSetting('mkvinfo_path').strip()
        legacy_mkvextract_path = addon.getSetting('mkvextract_path').strip()
        legacy_ffmpeg_path = addon.getSetting('ffmpeg_path').strip()
        self.mkvtoolnix_folder = (addon.getSetting('mkvtoolnix_folder') or "").strip()
        self.ffmpeg_folder = (addon.getSetting('ffmpeg_folder') or "").strip()
        if not self.mkvtoolnix_folder:
            self.mkvtoolnix_folder = _normalized_dirname(legacy_mkvinfo_path) or _normalized_dirname(legacy_mkvextract_path)
        if not self.ffmpeg_folder:
            self.ffmpeg_folder = _normalized_dirname(legacy_ffmpeg_path)
        self.mkvinfo_path = legacy_mkvinfo_path
        self.mkvextract_path = legacy_mkvextract_path
        self.ffmpeg_path = legacy_ffmpeg_path
        self.remote_extractor_url = (addon.getSetting('remote_extractor_url') or "").strip()
        self.remote_extractor_token = (addon.getSetting('remote_extractor_token') or "").strip()
        self.remote_extractor_timeout = safe_int('remote_extractor_timeout', 480)
        self.remote_extractor_client = remote_extractor.RemoteExtractorClient(
            addon,
            log_fn=lambda message, level="debug": log(message, level, self)
        )
        self.platform_name = _platform_name()
        self.provider = addon.getSetting('provider')
        
        # ------------------------------------------------------------
        # Language settings (new select-aware, ISO-respecting)
        # ------------------------------------------------------------
        raw_source = get_active_language_setting(addon, self.provider, 'source') or "Romanian"
        raw_target = get_active_language_setting(addon, self.provider, 'target') or "Romanian"
        
        # Convert to full name and ISO
        self.source_lang_name, self.source_lang_iso = get_lang_params(raw_source)
        self.target_lang_name, self.target_lang_iso = get_lang_params(raw_target)
        
        log(
            f"Languages loaded → "
            f"source: {self.source_lang_name} ({self.source_lang_iso}), "
            f"target: {self.target_lang_name} ({self.target_lang_iso})",
            "debug",
            self,
            force=True
        )
        
        self.model = addon.getSetting('model')
        self.openai_model = addon.getSetting('openai_model')
        self.anthropic_model = addon.getSetting('anthropic_model')
        self.deepl_api_key = addon.getSetting('deepl_api_key')
        self.libretranslate_url = addon.getSetting('libretranslate_url')
        
        log(
            f"AI snapshot → provider={self.provider}, model={self.model}, openai_model={self.openai_model}, deepl_key={'set' if self.deepl_api_key else 'missing'}, libre_url={'set' if self.libretranslate_url else 'missing'}",
            "debug",
            self,
            force=True
        )
    
        # ------------------------------------------------------------
        # Live translation runtime state handling
        # Prevent stale values when feature is disabled
        # ------------------------------------------------------------
        self.live_reload_points = [5, 15, 35, 60, 85]
        self.live_reload_index = 0
        if self.service_enabled:
            log("Translation service is enabled.", "debug", self)
        else:
            log("Translation service is disabled from settings. Polling is paused.", "info", self, force=True)
    
        # ------------------------------------------------------------
        # Validate subtitle folder path
        # Auto-create if missing (Android-safe)
        # ------------------------------------------------------------
        # Kodi-safe folder creation (Android / SMB / special:// compatible)
        if not xbmcvfs.exists(self.sub_folder):
            try:
                success = xbmcvfs.mkdirs(self.sub_folder)
                if success:
                    log(f"Created missing subtitle folder: {self.sub_folder}", "info", self)
                else:
                    log(f"mkdirs returned False for: {self.sub_folder}", "error", self)
            except Exception as e:
                log(f"Exception creating subtitle folder: {self.sub_folder} | Error: {e}", "error", self)
        else:
            log(f"Subtitle folder already exists: {self.sub_folder}", "debug", self)

        self.inspect_kodi_subtitle_location_settings()
    
        # ------------------------------------------------------------
        # Final confirmation log
        # ------------------------------------------------------------
        log("Settings reloaded successfully.", "debug", self, force=True)

        settings_snapshot = (
            "Settings snapshot → "
            f"service_enabled={self.service_enabled}, "
            f"mode={'Auto' if self.auto_mode else 'Manual'}, "
            f"debug={self.debug_mode}, "
            f"notify={self.use_notifications}, "
            f"require_translation_confirmation={self.require_translation_confirmation}, "
            f"translation_confirmation_delay={self.translation_confirmation_delay}, "
            f"translation_confirmation_reminder_delay={self.translation_confirmation_reminder_delay}, "
            f"stats={self.show_stats}, "
            f"sdh_hi_removal={self.remove_sdh_hi_cues}, "
            f"dual_language={self.dual_language_display}, "
            f"chunk_size={self.chunk_size}, "
            f"source_lang={self.source_lang_name} ({self.source_lang_iso}), "
            f"target_lang={self.target_lang_name} ({self.target_lang_iso}), "
            f"provider={self.provider}, "
        )

        # Show only the active provider model
        if self.provider == "OpenAI":
            settings_snapshot += f"openai_model={self.openai_model}"
        elif self.provider == "Anthropic":
            settings_snapshot += f"anthropic_model={self.anthropic_model}"
        elif self.provider == "DeepL":
            settings_snapshot += "model=DeepL Free"
        elif self.provider == "LibreTranslate":
            settings_snapshot += "model=LibreTranslate"
        else:
            settings_snapshot += f"model={self.model}"

        # Only show subtitle folder in Manual mode
        if not self.auto_mode:
            settings_snapshot += f", subtitle_folder={self.sub_folder}"
            settings_snapshot += f", embedded_extract={self.enable_embedded_subtitle_extraction}"
            settings_snapshot += f", force_embedded_extract={self.force_embedded_source_extraction}"
            settings_snapshot += f", mkvtoolnix_folder={self.mkvtoolnix_folder or 'PATH'}"
            settings_snapshot += f", ffmpeg_folder={self.ffmpeg_folder or 'PATH'}"
            settings_snapshot += f", remote_extractor={self.remote_extractor_enabled}"
            settings_snapshot += f", remote_platform={self.platform_name}"

        if self.remote_extractor_enabled:
            settings_snapshot += f", remote_extractor_url={'set' if self.remote_extractor_url else 'missing'}"
            settings_snapshot += f", remote_extractor_timeout={self.remote_extractor_timeout}"

        log(settings_snapshot, "debug", self, force=True)

        if not self.require_translation_confirmation:
            self.clear_translation_confirmation_candidate(close_overlay=True, clear_dismissals=True)

        if previous_service_enabled and not self.service_enabled:
            self.reset_playback_state()
        elif not previous_service_enabled and self.service_enabled and xbmc.Player().isPlayingVideo():
            self.mark_playback_started("Translation service re-enabled")

    def reset_playback_state(self):
        self.close_translation_confirmation_overlay()
        self.last_source_state = {}
        self.last_processed_video = None
        self.last_processed_source_path = None
        self.last_processed_source_mtime = 0
        self.last_loaded_subtitle_path = None
        self.last_loaded_subtitle_mtime = 0
        self.live_reload_index = 0
        self.is_busy = False
        self.playback_started_at = 0
        self.last_embedded_extraction_attempt_key = None
        self.last_embedded_target_skip_notify_key = None
        self.last_embedded_unavailable_notify_key = None
        self.logged_stale_manual_source_paths = set()
        self.logged_auto_temp_skip_paths = set()
        self.pending_translation_candidate = None
        self.approved_translation_candidate_key = None
        self.dismissed_translation_candidate_keys = set()
        self.confirmation_bypass_source_paths = set()

    def handle_embedded_subtitle_fallback(self, media_path, output_dir, mode_label):
        if not self.enable_embedded_subtitle_extraction and not self.remote_extractor_enabled:
            return "disabled"

        if not media_path or not output_dir:
            return "unavailable"

        resolved_media_path = xbmcvfs.translatePath(media_path) if media_path.startswith("special://") else media_path
        resolved_output_dir = xbmcvfs.translatePath(output_dir) if output_dir.startswith("special://") else output_dir
        playback_started_at = int(getattr(self, "playback_started_at", 0))
        attempt_key = "{0}|{1}|{2}".format(mode_label, resolved_media_path, playback_started_at)

        if getattr(self, "last_embedded_extraction_attempt_key", None) == attempt_key:
            return "already_checked"

        self.last_embedded_extraction_attempt_key = attempt_key

        if not is_real_media_path(resolved_media_path):
            log(
                "Embedded extraction unavailable: media source does not expose a real file path ({0}).".format(
                    resolved_media_path
                ),
                "debug",
                self
            )
            if self.use_notifications and self.last_embedded_unavailable_notify_key != attempt_key:
                ui.notify(
                    "Embedded extraction requires a real file path.",
                    title="Translatarr",
                    duration=10000
                )
                self.last_embedded_unavailable_notify_key = attempt_key
            return "unavailable"

        local_tools_available = _local_embedded_tools_available(
            resolved_media_path,
            self.mkvtoolnix_folder or None,
            self.ffmpeg_folder or None
        )
        local_extraction_enabled = self.enable_embedded_subtitle_extraction
        local_extraction_ready = local_extraction_enabled and local_tools_available
        remote_configured = self.remote_extractor_client.is_configured()

        tool_kwargs = {
            "media_path": resolved_media_path,
            "output_dir": resolved_output_dir,
            "mkvinfo_path": self.mkvtoolnix_folder or self.mkvinfo_path or None,
            "mkvextract_path": self.mkvtoolnix_folder or self.mkvextract_path or None,
            "ffmpeg_path": self.ffmpeg_folder or self.ffmpeg_path or None,
            "log_fn": lambda message, level="debug": log(message, level, self),
        }

        def notify_extraction_result(scope_label, success, reason=None):
            if not self.use_notifications:
                return

            if success:
                return

            reason_text = (reason or "").lower()
            if "timed out" in reason_text or "timeout" in reason_text:
                message = "Embedded extraction timed out ({0})".format(scope_label)
            else:
                message = "Embedded extraction failed ({0})".format(scope_label)

            ui.notify(message, title="Translatarr", duration=5000)

        def check_local_target_skip():
            if self.force_embedded_source_extraction:
                return None
            if not local_extraction_ready:
                return None

            target_result = embedded_subtitles.has_embedded_subtitle(
                media_path=resolved_media_path,
                language_name=self.target_lang_name,
                language_variants=get_iso_variants(self.target_lang_name),
                mkvinfo_path=self.mkvtoolnix_folder or self.mkvinfo_path or None,
                mkvextract_path=self.mkvtoolnix_folder or self.mkvextract_path or None,
                ffmpeg_path=self.ffmpeg_folder or self.ffmpeg_path or None,
                log_fn=tool_kwargs["log_fn"]
            )
            if target_result.get("found"):
                log(
                    "Embedded target-language subtitle already exists (track {0}). Skipping source extraction and translation.".format(
                        target_result.get("track_id", "?")
                    ),
                    "info",
                    self
                )
                if self.use_notifications and self.last_embedded_target_skip_notify_key != attempt_key:
                    ui.notify(
                        "Embedded {0} subtitle already found. Skipping translation.".format(
                            self.target_lang_name
                        ),
                        title="Translatarr",
                        duration=5000
                    )
                    self.last_embedded_target_skip_notify_key = attempt_key
                return "target_exists_skip"

            if target_result.get("reason") != "no_matching_subtitle_track":
                log(
                    "Embedded target-language subtitle check skipped: {0}".format(
                        target_result.get("reason", "unknown")
                    ),
                    "debug",
                    self
                )
            return None

        def check_remote_target_skip():
            if self.force_embedded_source_extraction:
                return None
            if not remote_configured:
                return None

            remote_probe = self.remote_extractor_client.probe_embedded_subtitle(
                resolved_media_path,
                self.target_lang_name
            )

            if not remote_probe.get("success"):
                log(
                    "Remote embedded target-language probe skipped: {0}".format(
                        remote_probe.get("reason", "unknown")
                    ),
                    "debug",
                    self
                )
                return None

            if remote_probe.get("found"):
                selected_track = remote_probe.get("selected_track") or {}
                log(
                    "Embedded target-language subtitle already exists via remote probe (track {0}). Skipping source extraction and translation.".format(
                        selected_track.get("track_number")
                        or selected_track.get("mkvextract_id")
                        or selected_track.get("track_id")
                        or "?"
                    ),
                    "info",
                    self
                )
                if self.use_notifications and self.last_embedded_target_skip_notify_key != attempt_key:
                    ui.notify(
                        "Embedded {0} subtitle already found. Skipping translation.".format(
                            self.target_lang_name
                        ),
                        title="Translatarr",
                        duration=5000
                    )
                    self.last_embedded_target_skip_notify_key = attempt_key
                return "target_exists_skip"

            return None

        def try_remote_source_extraction():
            if not remote_configured:
                return None
            if self.use_notifications:
                ui.notify("Embedded extraction started (Remote)", title="Translatarr", duration=5000)
            remote_result = self.remote_extractor_client.extract_embedded_subtitle(
                resolved_media_path,
                self.source_lang_name,
                resolved_output_dir,
                source_lang_iso=self.source_lang_iso
            )
            if remote_result.get("success"):
                log(
                    "Remote embedded subtitle extraction succeeded via {0}{1}.".format(
                        remote_result.get("method", "remote"),
                        " (cached)" if remote_result.get("cache_hit") else ""
                    ),
                    "info",
                    self
                )
                if remote_result.get("selected_track"):
                    log(
                        "Remote extractor selected track: {0}".format(remote_result.get("selected_track")),
                        "debug",
                        self
                    )
                extracted_file = remote_result.get("extracted_file")
                if extracted_file:
                    self.confirmation_bypass_source_paths.add(_normalize_candidate_path(extracted_file))
                notify_extraction_result("Remote", True)
                return "source_extracted", True

            log(
                "Remote embedded subtitle extraction skipped: {0}".format(
                    remote_result.get("reason", "unknown")
                ),
                "debug",
                self
            )
            notify_extraction_result(
                "Remote",
                False,
                remote_result.get("error") or remote_result.get("message") or remote_result.get("reason")
            )
            return "no_action", False

        def try_local_source_extraction():
            if not local_extraction_ready:
                return "no_action", False
            if self.use_notifications:
                ui.notify("Embedded extraction started (Local)", title="Translatarr", duration=5000)

            result = embedded_subtitles.try_extract_embedded_subtitle(
                source_lang_iso=self.source_lang_iso,
                source_lang_name=self.source_lang_name,
                source_variants=get_iso_variants(self.source_lang_name),
                **tool_kwargs
            )

            if result.get("success"):
                log(
                    "Extracted embedded source subtitle track {0} to {1}".format(
                        result.get("track_id", "?"),
                        result.get("output_path", "")
                    ),
                    "info",
                    self
                )
                output_path = result.get("output_path")
                if output_path:
                    self.confirmation_bypass_source_paths.add(_normalize_candidate_path(output_path))
                notify_extraction_result("Local", True)
                return "source_extracted", True

            log(
                "Embedded subtitle extraction skipped: {0}".format(result.get("reason", "unknown")),
                "debug",
                self
            )
            notify_extraction_result("Local", False, result.get("reason"))
            return "no_action", False

        target_skip_status = check_local_target_skip()
        if not target_skip_status and not local_extraction_ready:
            target_skip_status = check_remote_target_skip()
        if target_skip_status:
            return target_skip_status

        if local_extraction_ready:
            log(
                "Embedded extraction decision → using local extraction first (platform={0}, remote_configured={1})".format(
                    self.platform_name,
                    remote_configured
                ),
                "debug",
                self
            )
            status, success = try_local_source_extraction()
            if success:
                return status
            if remote_configured:
                log("Falling back to remote embedded extraction after local extraction failure.", "debug", self)
                status, success = try_remote_source_extraction()
                if success:
                    return status
            return "no_action"

        if remote_configured:
            log(
                "Embedded extraction decision → using remote extractor (local_enabled={0}, local_tools_available={1}).".format(
                    local_extraction_enabled,
                    local_tools_available
                ),
                "debug",
                self
            )
            status, success = try_remote_source_extraction()
            if success:
                return status
        return "no_action"
        
    def mark_playback_started(self, reason="Playback started"):
        if getattr(self, "playback_started_at", 0) and xbmc.Player().isPlayingVideo():
            log(
                f"{reason}. Playback session already active at {self.playback_started_at}. Keeping current marker.",
                "debug",
                self
            )
            return

        log(f"{reason}. Activating polling.", "debug", self)
        self.reset_playback_state()
        self.playback_started_at = time.time()

    def mark_playback_stopped(self, reason="Playback stopped"):
        log(f"{reason}. Resetting state.", "debug", self)
        self.reset_playback_state()

    def check_for_subs(self):
        if not self.service_enabled:
            return

        if not xbmc.Player().isPlayingVideo():
            return

        if not getattr(self, "playback_started_at", 0):
            self.mark_playback_started("Playback session inferred during poll")

        self.refresh_kodi_subtitle_location_settings_if_changed()
    
        if self.auto_mode:
            self.check_auto_mode_unified()
        else:
            self.check_manual_mode()
  
    # ------------------------------------------------------------
    # check_auto_mode_unified
    # ------------------------------------------------------------
    def check_auto_mode_unified(self):
        if not xbmc.Player().isPlayingVideo() or self.is_busy:
            return

        playing_file = xbmc.Player().getPlayingFile()
        best_playing_path = get_best_playing_path(self)

        if not playing_file and not best_playing_path:
            return

        raw_name = xbmc.getInfoLabel('Player.Title')
        video_name = get_preferred_video_name(best_playing_path or playing_file, raw_name)

        video_name_normalized = normalize_stem(video_name)
        
        kodi_temp_folders = get_kodi_temp_scan_folders()
        kodi_temp_folder_set = set(kodi_temp_folders)
        temp_like_folders = set(kodi_temp_folders + [A4K_SUB_FOLDER])
        folders_to_scan = [TRANSLATARR_SUB_FOLDER] + kodi_temp_folders + [A4K_SUB_FOLDER]
        kodi_custom_path = getattr(self, "kodi_subtitle_custom_path", None)
        kodi_storage_mode = getattr(self, "kodi_subtitle_storage_mode", None)
        playback_started_at = getattr(self, "playback_started_at", 0)
        custom_folder = None

        if is_real_media_path(best_playing_path):
            movie_folder = os.path.dirname(best_playing_path)
            if movie_folder:
                folders_to_scan.insert(0, movie_folder)

        if kodi_storage_mode == "custom" and kodi_custom_path and xbmcvfs.exists(kodi_custom_path):
            custom_folder = kodi_custom_path
            folders_to_scan.insert(0, kodi_custom_path)

        deduped_folders = []
        seen_folders = set()
        for folder in folders_to_scan:
            if not folder:
                continue
            normalized_folder = folder.rstrip("/\\").replace("\\", "/").lower()
            if normalized_folder in seen_folders:
                continue
            seen_folders.add(normalized_folder)
            deduped_folders.append(folder)
        folders_to_scan = deduped_folders

        if best_playing_path != playing_file:
            log(
                f"Resolved playable path for auto mode: {best_playing_path}",
                "debug",
                self
            )

        log(f"Auto scan folders: {folders_to_scan}", "debug", self)
        log(f"Auto current video: {video_name} | normalized: {video_name_normalized}", "debug", self)

        newest_target_file = None
        newest_target_mtime = 0

        newest_source_file = None
        newest_source_mtime = 0
        src_variants = get_iso_variants(self.source_lang_name)
        trg_variants = get_iso_variants(self.target_lang_name)

        for folder in folders_to_scan:
            if not folder:
                continue

            if (
                folder not in kodi_temp_folder_set and
                not is_vfs_network_path(folder) and
                not xbmcvfs.exists(folder)
            ):
                continue

            try:
                _, files = xbmcvfs.listdir(folder)
                log(f"Scanning folder: {folder} | files: {len(files)}", "debug", self)
            except Exception as e:
                log(f"Failed to list folder {folder}: {e}", "debug", self)
                continue

            for f in files:
                if not f.lower().endswith(".srt"):
                    continue

                f_lower = f.lower()
                f_normalized = normalize_stem(f)
                full_path = vfs_join(folder, f)

                try:
                    # Detect files still being written
                    size_check = xbmcvfs.Stat(full_path).st_size()
                    time.sleep(0.2)
                    if xbmcvfs.Stat(full_path).st_size() != size_check:
                        log(f"Subtitle still being written: {full_path}", "debug", self)
                        continue

                    stat = xbmcvfs.Stat(full_path)
                    f_mtime = stat.st_mtime()
                    f_size = stat.st_size()
                except Exception:
                    continue

                is_temp_folder = folder in temp_like_folders
                recent_session_file = bool(playback_started_at) and f_mtime >= playback_started_at - TEMP_SUBTITLE_TOLERANCE_SECONDS
                current_session_temp_file = recent_session_file
                name_match = subtitle_matches_video(video_name, f)
                allow_nonmatching_custom = folder == custom_folder and recent_session_file

                if not name_match and not is_temp_folder and not allow_nonmatching_custom:
                    continue

                if is_temp_folder and not name_match and not current_session_temp_file:
                    logged_auto_temp_skip_paths = getattr(self, "logged_auto_temp_skip_paths", set())
                    if full_path not in logged_auto_temp_skip_paths:
                        log(
                            "Skipping non-matching temp subtitle from before current playback: "
                            f"{full_path} | file_mtime={f_mtime} | playback_started_at={playback_started_at} "
                            f"| tolerance={TEMP_SUBTITLE_TOLERANCE_SECONDS}",
                            "debug",
                            self
                        )
                        logged_auto_temp_skip_paths.add(full_path)
                        self.logged_auto_temp_skip_paths = logged_auto_temp_skip_paths
                    continue
 
                if is_temp_folder and playback_started_at and f_mtime < playback_started_at - TEMP_SUBTITLE_TOLERANCE_SECONDS:
                    logged_auto_temp_skip_paths = getattr(self, "logged_auto_temp_skip_paths", set())
                    if full_path not in logged_auto_temp_skip_paths:
                        log(
                            "Skipping stale temp subtitle from older session: "
                            f"{full_path} | file_mtime={f_mtime} | playback_started_at={playback_started_at} "
                            f"| tolerance={TEMP_SUBTITLE_TOLERANCE_SECONDS}",
                            "debug",
                            self
                        )
                        logged_auto_temp_skip_paths.add(full_path)
                        self.logged_auto_temp_skip_paths = logged_auto_temp_skip_paths
                    continue

                if f_size < 50:
                    continue

                # Prefer already translated subtitle if available
                if subtitle_matches_language_suffix(f_lower, trg_variants):
                    if f_mtime > newest_target_mtime:
                        newest_target_mtime = f_mtime
                        newest_target_file = full_path
                    continue

                if not subtitle_matches_language_suffix(f_lower, src_variants):
                    continue

                # Otherwise treat as a source subtitle candidate
                if f_mtime > newest_source_mtime:
                    newest_source_mtime = f_mtime
                    newest_source_file = full_path

        log(
            "Auto scan result -> source: {0} | target: {1}".format(
                newest_source_file or "none",
                newest_target_file or "none"
            ),
            "debug",
            self
        )

        if not newest_source_file and not getattr(self, "approved_translation_candidate_key", None):
            self.clear_translation_confirmation_candidate(close_overlay=True)

        if not newest_source_file:
            extraction_media_path = best_playing_path or playing_file
            embedded_status = self.handle_embedded_subtitle_fallback(
                extraction_media_path,
                TRANSLATARR_SUB_FOLDER,
                "auto"
            )
            if embedded_status == "source_extracted":
                self.check_auto_mode_unified()
                return
            if embedded_status == "target_exists_skip":
                return

        # 1. Load newest translated target if one already exists
        if newest_target_file:
            if newest_target_file.startswith(TRANSLATARR_SUB_FOLDER.replace("\\", "/")):
                log(f"Auto found existing translated subtitle in Translatarr folder: {newest_target_file}", "debug", self)
            self.load_subtitle_if_new(newest_target_file)

        # 2. Translate newest source only when needed
        last_processed_source_path = getattr(self, "last_processed_source_path", None)
        last_processed_source_mtime = getattr(self, "last_processed_source_mtime", 0)

        source_changed = (
            newest_source_file and (
                newest_source_file != last_processed_source_path
                or newest_source_mtime != last_processed_source_mtime
            )
        )

        target_covers_source = (
            newest_target_file is not None and
            newest_target_mtime >= newest_source_mtime
        )

        pending_candidate = getattr(self, "pending_translation_candidate", None)
        if (
            pending_candidate and
            newest_source_file and
            pending_candidate.get("path") == newest_source_file and
            target_covers_source
        ):
            self.clear_translation_confirmation_candidate(close_overlay=True)

        if source_changed and not target_covers_source:
            safe_video_name = safe_filename(video_name)
            final_file_name = f"{safe_video_name}.{self.target_lang_iso}.srt"
            save_path = vfs_join(TRANSLATARR_SUB_FOLDER, final_file_name)

            log(f"Newest source subtitle detected: {newest_source_file}", "debug", self)

            try:
                source_size = xbmcvfs.Stat(newest_source_file).st_size()
            except Exception:
                source_size = 0

            candidate = self.build_translation_candidate(
                newest_source_file,
                newest_source_mtime,
                source_size,
                force_retranslate=True,
                save_path=save_path,
                show_source_immediately=True
            )
            candidate_action = self.prepare_source_candidate_for_translation(candidate)

            if candidate_action == "deferred":
                return
            if candidate_action == "dismissed":
                return

            success = self.process_translation_candidate(candidate)

            if success:
                self.last_processed_source_path = newest_source_file
                self.last_processed_source_mtime = newest_source_mtime
                self.load_subtitle_if_new(save_path)
        elif newest_source_file and newest_target_file and newest_target_mtime >= newest_source_mtime:
            log("Target subtitle already exists and is same-age or newer than source. Skipping translation.", "debug", self)

        if not newest_target_file and not newest_source_file:
            log("No subtitles found in auto mode.", "debug", self)


    # ------------------------------------------------------------
    # check_manual_mode
    # ------------------------------------------------------------
    def check_manual_mode(self):
        log("Polling for subtitles...", "debug", self)

        if not xbmc.Player().isPlayingVideo() or self.is_busy:
            return

        playing_file = xbmc.Player().getPlayingFile()
        best_playing_path = get_best_playing_path(self)
        if not playing_file and not best_playing_path:
            return

        # 1. FIX: Derives video name (Prevents crash on plugins)
        raw_name = xbmc.getInfoLabel('Player.Title')
        video_name = get_preferred_video_name(best_playing_path or playing_file, raw_name)

        video_name_normalized = normalize_stem(video_name)
        
        # Check if we switched movies to clear size cache if necessary
        if getattr(self, 'last_processed_video', None) != video_name:
            self.last_source_state = {}
            self.last_processed_video = video_name

        custom_dir = self.sub_folder
        if not custom_dir or not xbmcvfs.exists(custom_dir):
            return

        folders_to_scan = [custom_dir]
        if is_real_media_path(best_playing_path):
            movie_folder = os.path.dirname(best_playing_path)
            if movie_folder:
                movie_folder_normalized = movie_folder.rstrip("/\\").replace("\\", "/").lower()
                custom_dir_normalized = custom_dir.rstrip("/\\").replace("\\", "/").lower()
                if movie_folder_normalized != custom_dir_normalized:
                    folders_to_scan.insert(0, movie_folder)

        src_variants = get_iso_variants(self.source_lang_name)
        trg_variants = get_iso_variants(self.target_lang_name)

        matched_source_candidates = []
        matched_target_candidates = []
        fallback_source_candidates = []
        fallback_target_candidates = []
        playback_started_at = getattr(self, "playback_started_at", 0)

        for folder in folders_to_scan:
            try:
                _, files = xbmcvfs.listdir(folder)
            except Exception as e:
                log(f"Listdir error in manual mode for {folder}: {e}", "error", self)
                continue

            for f in files:
                f_lower = f.lower()
                full_path = vfs_join(folder, f)

                try:
                    f_stat = xbmcvfs.Stat(full_path)
                    f_mtime = f_stat.st_mtime()
                except Exception:
                    f_mtime = 0

                name_match = subtitle_matches_video(video_name, f)
                recent_session_file = bool(playback_started_at) and (
                    f_mtime >= playback_started_at - TEMP_SUBTITLE_TOLERANCE_SECONDS
                )

                is_target = subtitle_matches_language_suffix(f_lower, trg_variants)
                is_source = subtitle_matches_language_suffix(f_lower, src_variants)

                candidate = (folder, f)

                if is_target:
                    if name_match:
                        matched_target_candidates.append(candidate)
                    elif recent_session_file:
                        fallback_target_candidates.append(candidate)
                elif is_source:
                    if name_match:
                        matched_source_candidates.append(candidate)
                    elif recent_session_file:
                        fallback_source_candidates.append(candidate)

        target_candidates = matched_target_candidates or fallback_target_candidates
        source_candidates = matched_source_candidates or fallback_source_candidates

        if not source_candidates and not getattr(self, "approved_translation_candidate_key", None):
            self.clear_translation_confirmation_candidate(close_overlay=True)

        if not source_candidates and not target_candidates:
            extraction_media_path = best_playing_path or playing_file
            embedded_status = self.handle_embedded_subtitle_fallback(
                extraction_media_path,
                self.sub_folder,
                "manual"
            )
            if embedded_status == "source_extracted":
                self.check_manual_mode()
                return
            if embedded_status == "target_exists_skip":
                return

        # 3. Sorting by mtime (using xbmcvfs)
        def safe_mtime(candidate):
            folder, filename = candidate
            try:
                return xbmcvfs.Stat(vfs_join(folder, filename)).st_mtime()
            except Exception:
                return 0

        target_candidates.sort(key=safe_mtime, reverse=True)
        source_candidates.sort(key=safe_mtime, reverse=True)

        # Load newest target if already present
        if target_candidates:
            target_folder, target_file = target_candidates[0]
            target_path = vfs_join(target_folder, target_file)
            try:
                stat = xbmcvfs.Stat(target_path)
                target_mtime = stat.st_mtime()

                if stat.st_size() <= 100:
                    log(f"Skipping tiny/broken target subtitle: {target_path}", "debug", self)
                elif (
                    getattr(self, "last_loaded_subtitle_path", None) != target_path
                    or getattr(self, "last_loaded_subtitle_mtime", 0) != target_mtime
                ):
                    self.load_subtitle_if_new(target_path)

            except Exception as e:
                log(f"Failed to stat target subtitle: {e}", "error", self)

        for folder, f in source_candidates:
            full_path = vfs_join(folder, f)
            try:
                # Detect files still being written
                try:
                    size_check = xbmcvfs.Stat(full_path).st_size()
                    time.sleep(0.2)
                    if xbmcvfs.Stat(full_path).st_size() != size_check:
                        log(f"Source subtitle still being written: {full_path}", "debug", self)
                        continue
                except Exception:
                    pass

                stat = xbmcvfs.Stat(full_path)
                size = stat.st_size()
                mtime = stat.st_mtime()

                if playback_started_at and mtime < playback_started_at - TEMP_SUBTITLE_TOLERANCE_SECONDS:
                    if matched_target_candidates:
                        logged_stale_manual_source_paths = getattr(self, "logged_stale_manual_source_paths", set())
                        if full_path not in logged_stale_manual_source_paths:
                            log(
                                f"Skipping stale manual subtitle from older session (matching target already exists): {full_path}",
                                "debug",
                                self
                            )
                            logged_stale_manual_source_paths.add(full_path)
                            self.logged_stale_manual_source_paths = logged_stale_manual_source_paths
                        continue
                    log(
                        f"Pre-existing manual source subtitle has no matching target yet. Proceeding: {full_path}",
                        "debug",
                        self
                    )
                
                if size < 500: 
                    continue
                    
                # Skip translation if an existing target already covers this source
                if target_candidates:
                    newest_target_path = vfs_join(target_candidates[0][0], target_candidates[0][1])
                    try:
                        target_stat = xbmcvfs.Stat(newest_target_path)
                        target_mtime = target_stat.st_mtime()

                        if target_stat.st_size() > 100 and target_mtime >= mtime:
                            pending_candidate = getattr(self, "pending_translation_candidate", None)
                            if pending_candidate and pending_candidate.get("path") == full_path:
                                self.clear_translation_confirmation_candidate(close_overlay=True)
                            log(
                                f"Target subtitle already exists and is same-age or newer than source. Skipping translation for: {full_path}",
                                "debug",
                                self
                            )
                            return
                    except Exception as e:
                        log(f"Failed to stat target subtitle for source comparison: {e}", "error", self)

                force_retranslate = False
                last_state = self.last_source_state.get(f.lower())

                if last_state is not None:
                    last_size, last_mtime = last_state
                    if size != last_size or mtime != last_mtime:
                        log("Subtitle changed (size or mtime), forcing retranslation.", "debug", self)
                        force_retranslate = True
                    else:
                        continue

                candidate = self.build_translation_candidate(
                    full_path,
                    mtime,
                    size,
                    force_retranslate=force_retranslate,
                    save_path=None,
                    show_source_immediately=True
                )
                candidate_action = self.prepare_source_candidate_for_translation(candidate)

                if candidate_action == "deferred":
                    return
                if candidate_action == "dismissed":
                    return

                success = self.process_translation_candidate(candidate)

                if success:
                    try:
                        final_stat = xbmcvfs.Stat(full_path)
                        self.last_source_state[f.lower()] = (final_stat.st_size(), final_stat.st_mtime())
                    except Exception:
                        self.last_source_state[f.lower()] = (size, mtime)
                
                return # always stop after trying the newest valid candidate

            except Exception as e:
                log(f"Manual poll processing error: {e}", "error", self)
                return
 

# ----------------------------------------------------------
# Player Callbacks
# ----------------------------------------------------------
class TranslatarrPlayer(xbmc.Player):

    def __init__(self, monitor):
        super().__init__()
        self.monitor = monitor

    def onAVStarted(self):
        self.monitor.mark_playback_started("AV started")

    def onPlayBackStarted(self):
        self.monitor.mark_playback_started("Playback started")

    def onPlayBackResumed(self):
        if not getattr(self.monitor, "playback_started_at", 0):
            self.monitor.mark_playback_started("Playback resumed")

    def onPlayBackStopped(self):
        self.monitor.mark_playback_stopped("Playback stopped")

    def onPlayBackEnded(self):
        self.monitor.mark_playback_stopped("Playback ended")


# ----------------------------------------------------------
# ENTRY POINT (Safe for RD / Torbox)
# ----------------------------------------------------------
if __name__ == '__main__':
    window = xbmcgui.Window(10000)

    if window.getProperty("TranslatarrRunning") == "true":
        xbmc.log("[Translatarr] Another instance already running. Exiting.", xbmc.LOGINFO)
        sys.exit()

    window.setProperty("TranslatarrRunning", "true")

    try:
        monitor = TranslatarrMonitor()
        set_global_monitor(monitor)
        player = TranslatarrPlayer(monitor)

        while not monitor.abortRequested():
            if xbmc.Player().isPlayingVideo():
                monitor.check_for_subs()
            else:
                log("Playback stopped. Skipping poll.", "debug", monitor)
            
            monitor.waitForAbort(3)  # still responsive to abort

    finally:
        window.clearProperty("TranslatarrRunning")
        xbmc.log("[Translatarr] Instance stopped. Lock released.", xbmc.LOGINFO)
