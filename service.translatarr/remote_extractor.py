# -*- coding: utf-8 -*-
import json
import os

import xbmc
import xbmcvfs

try:
    import requests
except Exception:
    requests = None


def safe_bool(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("true", "1", "yes", "on")


def safe_int(value, fallback):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def is_android():
    return xbmc.getCondVisibility("System.Platform.Android")


def is_windows():
    return xbmc.getCondVisibility("System.Platform.Windows")


def is_linux():
    return xbmc.getCondVisibility("System.Platform.Linux")


def _safe_filename(name):
    name = os.path.basename(name or "")
    for invalid_char in '<>:"/\\|?*':
        name = name.replace(invalid_char, "_")
    return name.rstrip(". ").strip() or "embedded_subtitle"


class RemoteExtractorClient(object):
    def __init__(self, addon, log_fn=None):
        self.log_fn = log_fn or (lambda message, level="debug": None)
        self.enabled = safe_bool(addon.getSetting("remote_extractor_enabled"))
        self.base_url = (addon.getSetting("remote_extractor_url") or "").strip().rstrip("/")
        self.api_token = (addon.getSetting("remote_extractor_token") or "").strip()
        self.timeout = safe_int(addon.getSetting("remote_extractor_timeout"), 480)

    def is_configured(self):
        return self.enabled and bool(self.base_url) and requests is not None

    def should_prefer_remote(self, local_tools_available):
        if not self.is_configured():
            return False
        return not local_tools_available

    def probe_embedded_subtitle(self, video_path, language_name):
        if not self.is_configured():
            return {"success": False, "reason": "remote_extractor_not_configured"}

        if not video_path or not language_name:
            return {"success": False, "reason": "remote_extractor_missing_path"}

        payload = {
            "video_path": video_path,
            "language": language_name,
            "timeout": self.timeout,
            "prefer_non_sdh": True
        }
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = "Bearer {0}".format(self.api_token)

        url = "{0}/probe".format(self.base_url)
        self.log_fn(
            "Remote extractor probe → url: {0} | media: {1} | language: {2}".format(
                url,
                video_path,
                language_name
            )
        )

        try:
            response = requests.post(
                url,
                headers=headers,
                data=json.dumps(payload),
                timeout=self.timeout
            )
        except Exception as exc:
            return {"success": False, "reason": "remote_extractor_probe_failed", "error": str(exc)}

        try:
            data = response.json()
        except Exception:
            return {
                "success": False,
                "reason": "remote_extractor_invalid_json",
                "status_code": response.status_code
            }

        if response.status_code != 200:
            return {
                "success": False,
                "reason": "remote_extractor_http_error",
                "status_code": response.status_code,
                "message": data.get("detail") or data.get("message") or "unknown_http_error"
            }

        return {
            "success": bool(data.get("ok")),
            "found": bool(data.get("found")),
            "reason": "remote_extractor_probe_success",
            "message": data.get("message"),
            "selected_track": data.get("selected_track"),
            "all_tracks": data.get("all_tracks", []),
            "resolved_video_path": data.get("resolved_video_path"),
            "diagnostic_preview": data.get("diagnostic_preview"),
        }

    def extract_embedded_subtitle(self, video_path, source_lang_name, output_dir, source_lang_iso=None):
        if not self.is_configured():
            return {"success": False, "reason": "remote_extractor_not_configured"}

        if not video_path or not output_dir:
            return {"success": False, "reason": "remote_extractor_missing_path"}

        payload = {
            "video_path": video_path,
            "source_lang": source_lang_name,
            "timeout": self.timeout,
            "prefer_non_sdh": True,
            "allow_ffmpeg_fallback": True,
            "force_reextract": False
        }
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = "Bearer {0}".format(self.api_token)

        url = "{0}/extract".format(self.base_url)
        self.log_fn(
            "Remote extractor request → url: {0} | media: {1} | language: {2}".format(
                url,
                video_path,
                source_lang_name
            )
        )

        try:
            response = requests.post(
                url,
                headers=headers,
                data=json.dumps(payload),
                timeout=self.timeout
            )
        except Exception as exc:
            return {"success": False, "reason": "remote_extractor_request_failed", "error": str(exc)}

        try:
            data = response.json()
        except Exception:
            return {
                "success": False,
                "reason": "remote_extractor_invalid_json",
                "status_code": response.status_code
            }

        if response.status_code != 200:
            return {
                "success": False,
                "reason": "remote_extractor_http_error",
                "status_code": response.status_code,
                "message": data.get("detail") or data.get("message") or "unknown_http_error"
            }

        subtitle_text = data.get("extracted_srt_content", "")
        if not subtitle_text:
            return {
                "success": False,
                "reason": "remote_extractor_empty_content",
                "method": data.get("method"),
                "cache_hit": data.get("cache_hit", False)
            }

        if not xbmcvfs.exists(output_dir):
            xbmcvfs.mkdirs(output_dir)

        video_stem = os.path.splitext(os.path.basename(video_path))[0]
        lang_suffix = source_lang_iso or source_lang_name or "src"
        output_name = "{0}.{1}.srt".format(_safe_filename(video_stem), lang_suffix)
        output_path = (output_dir.rstrip("/\\") + "/" + output_name).replace("\\", "/")

        subtitle_file = xbmcvfs.File(output_path, "w")
        try:
            subtitle_file.write(subtitle_text)
        finally:
            subtitle_file.close()

        if not xbmcvfs.exists(output_path):
            return {"success": False, "reason": "remote_extractor_write_failed"}

        return {
            "success": True,
            "reason": "remote_extractor_success",
            "output_path": output_path,
            "method": data.get("method"),
            "cache_hit": data.get("cache_hit", False),
            "selected_track": data.get("selected_track"),
        }
