# -*- coding: utf-8 -*-
import json
import os
import re
import shutil
import subprocess
import tempfile
from urllib.parse import unquote, urlsplit


SDH_MARKERS_RE = re.compile(
    r"(sdh|cc|hi|hearing.?impaired|closed.?caption|forced)",
    re.IGNORECASE
)
LOCAL_COMMAND_TIMEOUT_SECONDS = 60
NETWORK_COMMAND_TIMEOUT_SECONDS = 900
SUPPORTED_EMBEDDED_SUBTITLE_EXTENSIONS = (".mkv", ".mp4")


def _log(log_fn, message, level="debug"):
    if log_fn:
        log_fn(message, level)


def _find_tool(name, custom_path=None):
    if custom_path:
        if os.path.isdir(custom_path):
            candidates = [name]
            if os.name == "nt" and not name.lower().endswith(".exe"):
                candidates.insert(0, name + ".exe")

            for candidate in candidates:
                candidate_path = os.path.join(custom_path, candidate)
                if os.path.isfile(candidate_path):
                    return candidate_path
            return None

        if os.path.isfile(custom_path):
            return custom_path
        return None
    return shutil.which(name)


def _find_sibling_tool(reference_path, sibling_name):
    if not reference_path:
        return None

    reference_dir = os.path.dirname(reference_path)
    if not reference_dir:
        return None

    candidates = [sibling_name]
    if os.name == "nt" and not sibling_name.lower().endswith(".exe"):
        candidates.insert(0, sibling_name + ".exe")

    for candidate in candidates:
        candidate_path = os.path.join(reference_dir, candidate)
        if os.path.isfile(candidate_path):
            return candidate_path

    return None


def _is_local_path(path):
    if not path:
        return False

    lowered = path.lower()
    if lowered.startswith((
        "plugin://",
        "http://",
        "https://",
        "smb://",
        "nfs://",
        "dav://",
        "ftp://",
        "sftp://",
        "special://",
    )):
        return False

    return bool(re.match(r"^[a-zA-Z]:[\\/]", path)) or path.startswith("/")


def _resolve_filesystem_path(path):
    if not path:
        return None

    if _is_local_path(path):
        return path

    lowered = path.lower()
    if lowered.startswith("smb://") and os.name == "nt":
        parts = urlsplit(path)
        if not parts.netloc or not parts.path:
            return None

        unc_path = "\\\\{0}{1}".format(parts.netloc, unquote(parts.path).replace("/", "\\"))
        return unc_path

    return None


def _is_network_filesystem_path(path):
    return bool(path and path.startswith("\\\\"))


def _build_output_path(output_dir, media_path, source_lang_iso):
    base_name = os.path.splitext(os.path.basename(media_path))[0]
    safe_base = re.sub(r'[<>:"/\\|?*]+', "_", base_name).rstrip(". ")
    return os.path.join(output_dir, "{0}.{1}.srt".format(safe_base, source_lang_iso))


def _run_command(command, log_fn=None, timeout_seconds=LOCAL_COMMAND_TIMEOUT_SECONDS):
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="ignore",
            timeout=timeout_seconds
        )
    except subprocess.TimeoutExpired:
        _log(
            log_fn,
            "Command timed out after {0}s: {1}".format(timeout_seconds, command[0]),
            "error"
        )
        return False, "", "timeout"
    except Exception as exc:
        _log(log_fn, "Command failed to start: {0} | Error: {1}".format(command[0], exc), "error")
        return False, "", str(exc)

    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "").strip()
        return False, completed.stdout or "", stderr

    return True, completed.stdout or "", ""


def _parse_mkvinfo_tracks(output, source_variants, source_lang_name):
    source_tokens = set(v.lower() for v in source_variants)
    source_name = (source_lang_name or "").strip().lower()
    tracks = []

    current = None

    def finalize_track():
        if not current:
            return
        if current.get("is_subtitle") and current.get("is_source_language") and current.get("track_id"):
            tracks.append(
                {
                    "track_id": current["track_id"],
                    "is_sdh": current.get("is_sdh", False),
                    "name": current.get("name", ""),
                }
            )

    for raw_line in output.splitlines():
        line = raw_line.strip()

        if re.match(r"^\|\s+\+\sTrack$", line):
            finalize_track()
            current = {
                "track_id": None,
                "is_subtitle": False,
                "is_source_language": False,
                "is_sdh": False,
                "name": "",
            }
            continue

        if current is None:
            continue

        track_id_match = re.search(
            r"track ID for mkvmerge & mkvextract:\s*([0-9]+)",
            line,
            re.IGNORECASE
        )
        if track_id_match:
            current["track_id"] = track_id_match.group(1)

        if "Track type: subtitles" in line:
            current["is_subtitle"] = True

        for pattern in (
            r"Language:\s*([a-zA-Z0-9_-]+)",
            r"Language \(IETF BCP 47\):\s*([a-zA-Z0-9_-]+)",
        ):
            lang_match = re.search(pattern, line, re.IGNORECASE)
            if lang_match:
                lang_token = lang_match.group(1).lower()
                primary_token = lang_token.split("-")[0]
                if lang_token in source_tokens or primary_token in source_tokens:
                    current["is_source_language"] = True

        name_match = re.search(r"\+\sName:\s*(.+)$", line)
        if name_match:
            track_name = name_match.group(1).strip()
            current["name"] = track_name
            lowered_name = track_name.lower()
            if source_name and source_name in lowered_name:
                current["is_source_language"] = True
            if SDH_MARKERS_RE.search(track_name):
                current["is_sdh"] = True

    finalize_track()
    return tracks


def _pick_best_track(tracks):
    if not tracks:
        return None

    for track in tracks:
        if not track.get("is_sdh"):
            return track
    return tracks[0]


def _find_matching_mkv_track(
    resolved_media_path,
    language_variants,
    language_name,
    command_timeout_seconds,
    mkvinfo_path,
    mkvextract_path,
    log_fn=None
):
    mkvinfo = _find_tool("mkvinfo", mkvinfo_path)
    mkvextract = _find_tool("mkvextract", mkvextract_path)
    if not mkvinfo or not mkvextract:
        return None, "required_tools_missing"

    _log(log_fn, "Running mkvinfo for embedded subtitle inspection.")
    ok, mkvinfo_output, mkvinfo_error = _run_command(
        [mkvinfo, resolved_media_path],
        log_fn=log_fn,
        timeout_seconds=command_timeout_seconds
    )
    if not ok:
        _log(log_fn, "mkvinfo failed for {0}: {1}".format(resolved_media_path, mkvinfo_error), "error")
        return None, "mkvinfo_failed"

    tracks = _parse_mkvinfo_tracks(mkvinfo_output, language_variants, language_name)
    best_track = _pick_best_track(tracks)
    if not best_track:
        return None, "no_matching_subtitle_track"

    return best_track, None


def _find_matching_mp4_track(
    resolved_media_path,
    language_variants,
    language_name,
    command_timeout_seconds,
    ffmpeg_path,
    log_fn=None
):
    ffmpeg = _find_tool("ffmpeg", ffmpeg_path)
    ffprobe = _find_sibling_tool(ffmpeg_path, "ffprobe") if ffmpeg_path else None
    if not ffprobe:
        ffprobe = _find_tool("ffprobe")

    if not ffmpeg or not ffprobe:
        return None, "ffmpeg_or_ffprobe_missing"

    _log(log_fn, "Running ffprobe for MP4 embedded subtitle inspection.")
    ok, ffprobe_output, ffprobe_error = _run_command(
        [
            ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_entries",
            "stream=index,codec_type,codec_name:stream_tags=language,title:stream_disposition=forced,hearing_impaired",
            resolved_media_path,
        ],
        log_fn=log_fn,
        timeout_seconds=command_timeout_seconds
    )
    if not ok:
        _log(log_fn, "ffprobe failed for {0}: {1}".format(resolved_media_path, ffprobe_error), "error")
        return None, "ffprobe_failed"

    tracks = _parse_ffprobe_subtitle_streams(ffprobe_output, language_variants, language_name)
    best_track = _pick_best_track(tracks)
    if not best_track:
        return None, "no_matching_subtitle_track"

    return best_track, None


def _is_source_language_match(language_token, source_tokens):
    if not language_token:
        return False

    normalized = language_token.strip().lower()
    primary = normalized.split("-")[0]
    return normalized in source_tokens or primary in source_tokens


def _parse_ffprobe_subtitle_streams(output, source_variants, source_lang_name):
    source_tokens = set(v.lower() for v in source_variants)
    source_name = (source_lang_name or "").strip().lower()

    try:
        payload = json.loads(output or "{}")
    except Exception:
        return []

    streams = payload.get("streams") or []
    tracks = []

    for stream in streams:
        if str(stream.get("codec_type") or "").lower() != "subtitle":
            continue

        stream_index = stream.get("index")
        if stream_index is None:
            continue

        tags = stream.get("tags") or {}
        language_token = str(tags.get("language") or tags.get("LANGUAGE") or "").strip()
        title = str(tags.get("title") or tags.get("TITLE") or "").strip()
        disposition = stream.get("disposition") or {}
        lowered_title = title.lower()

        is_sdh = bool(
            disposition.get("hearing_impaired")
            or disposition.get("forced")
            or (title and SDH_MARKERS_RE.search(title))
        )

        is_source_language = _is_source_language_match(language_token, source_tokens)
        if not is_source_language and source_name and source_name in lowered_title:
            is_source_language = True

        if is_source_language:
            tracks.append(
                {
                    "track_id": str(stream_index),
                    "is_sdh": is_sdh,
                    "name": title,
                    "codec_name": str(stream.get("codec_name") or "").strip(),
                }
            )

    return tracks


def _looks_like_ass_or_ssa(path):
    try:
        with open(path, "rb") as handle:
            header = handle.read(512)
    except Exception:
        return False

    try:
        text_header = header.decode("utf-8", errors="ignore")
    except Exception:
        return False

    return "[Script Info]" in text_header or "[V4+ Styles]" in text_header


def _extract_mkv_subtitle(
    resolved_media_path,
    output_path,
    source_variants,
    source_lang_name,
    command_timeout_seconds,
    mkvinfo_path,
    mkvextract_path,
    ffmpeg_path,
    log_fn=None
):
    mkvextract = _find_tool("mkvextract", mkvextract_path)
    if not mkvextract:
        return {"success": False, "reason": "required_tools_missing"}

    best_track, error_reason = _find_matching_mkv_track(
        resolved_media_path,
        source_variants,
        source_lang_name,
        command_timeout_seconds,
        mkvinfo_path,
        mkvextract_path,
        log_fn=log_fn
    )
    if not best_track:
        return {"success": False, "reason": error_reason}

    fd, temp_path = tempfile.mkstemp(prefix="translatarr_extract_", suffix=".sub", dir=os.path.dirname(output_path))
    os.close(fd)
    try:
        extract_spec = "{0}:{1}".format(best_track["track_id"], temp_path)
        _log(log_fn, "Running mkvextract for subtitle track {0}.".format(best_track["track_id"]))
        ok, _, extract_error = _run_command(
            [mkvextract, "tracks", resolved_media_path, extract_spec],
            log_fn=log_fn,
            timeout_seconds=command_timeout_seconds
        )
        if not ok:
            _log(log_fn, "mkvextract failed for {0}: {1}".format(resolved_media_path, extract_error), "error")
            return {"success": False, "reason": "mkvextract_failed"}

        if _looks_like_ass_or_ssa(temp_path):
            ffmpeg = _find_tool("ffmpeg", ffmpeg_path)
            if not ffmpeg:
                return {"success": False, "reason": "ffmpeg_required_for_conversion"}

            _log(log_fn, "Embedded subtitle requires ASS/SSA conversion via ffmpeg.")
            ok, _, ffmpeg_error = _run_command(
                [ffmpeg, "-y", "-loglevel", "error", "-i", temp_path, output_path],
                log_fn=log_fn,
                timeout_seconds=command_timeout_seconds
            )
            if not ok:
                _log(log_fn, "ffmpeg conversion failed for {0}: {1}".format(temp_path, ffmpeg_error), "error")
                return {"success": False, "reason": "ffmpeg_conversion_failed"}
        else:
            shutil.move(temp_path, output_path)
            temp_path = None

        if not os.path.isfile(output_path) or os.path.getsize(output_path) <= 100:
            return {"success": False, "reason": "output_invalid"}

        return {
            "success": True,
            "output_path": output_path,
            "track_id": best_track["track_id"],
            "was_sdh": best_track.get("is_sdh", False),
        }
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


def _extract_mp4_subtitle(
    resolved_media_path,
    output_path,
    source_variants,
    source_lang_name,
    command_timeout_seconds,
    ffmpeg_path,
    log_fn=None
):
    ffmpeg = _find_tool("ffmpeg", ffmpeg_path)
    if not ffmpeg:
        return {"success": False, "reason": "ffmpeg_or_ffprobe_missing"}

    best_track, error_reason = _find_matching_mp4_track(
        resolved_media_path,
        source_variants,
        source_lang_name,
        command_timeout_seconds,
        ffmpeg_path,
        log_fn=log_fn
    )
    if not best_track:
        return {"success": False, "reason": error_reason}

    _log(
        log_fn,
        "Running ffmpeg for MP4 subtitle stream {0} ({1}).".format(
            best_track["track_id"],
            best_track.get("codec_name", "unknown")
        )
    )
    ok, _, ffmpeg_error = _run_command(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-i",
            resolved_media_path,
            "-map",
            "0:{0}".format(best_track["track_id"]),
            output_path,
        ],
        log_fn=log_fn,
        timeout_seconds=command_timeout_seconds
    )
    if not ok:
        _log(log_fn, "ffmpeg MP4 extraction failed for {0}: {1}".format(resolved_media_path, ffmpeg_error), "error")
        return {"success": False, "reason": "ffmpeg_mp4_extraction_failed"}

    if not os.path.isfile(output_path) or os.path.getsize(output_path) <= 100:
        return {"success": False, "reason": "output_invalid"}

    return {
        "success": True,
        "output_path": output_path,
        "track_id": best_track["track_id"],
        "was_sdh": best_track.get("is_sdh", False),
    }


def try_extract_embedded_subtitle(
    media_path,
    output_dir,
    source_lang_iso,
    source_lang_name,
    source_variants,
    mkvinfo_path=None,
    mkvextract_path=None,
    ffmpeg_path=None,
    log_fn=None
):
    resolved_media_path = _resolve_filesystem_path(media_path)
    if not resolved_media_path:
        return {"success": False, "reason": "media_path_not_local"}

    resolved_output_dir = _resolve_filesystem_path(output_dir)
    if not resolved_output_dir:
        return {"success": False, "reason": "output_dir_not_local"}

    if not resolved_media_path.lower().endswith(SUPPORTED_EMBEDDED_SUBTITLE_EXTENSIONS):
        return {"success": False, "reason": "unsupported_container"}

    if not os.path.isfile(resolved_media_path):
        return {"success": False, "reason": "media_file_missing"}

    if not os.path.isdir(resolved_output_dir):
        return {"success": False, "reason": "output_dir_missing"}

    command_timeout_seconds = (
        NETWORK_COMMAND_TIMEOUT_SECONDS
        if _is_network_filesystem_path(resolved_media_path)
        else LOCAL_COMMAND_TIMEOUT_SECONDS
    )

    _log(
        log_fn,
        "Embedded extraction paths resolved → media: {0} | output_dir: {1} | timeout={2}s".format(
            resolved_media_path,
            resolved_output_dir,
            command_timeout_seconds
        )
    )

    output_path = _build_output_path(resolved_output_dir, resolved_media_path, source_lang_iso)
    if os.path.isfile(output_path) and os.path.getsize(output_path) > 100:
        _log(log_fn, "Embedded subtitle output already exists: {0}".format(output_path))
        return {"success": True, "output_path": output_path, "reason": "already_exists"}

    media_extension = os.path.splitext(resolved_media_path)[1].lower()
    if media_extension == ".mp4":
        return _extract_mp4_subtitle(
            resolved_media_path=resolved_media_path,
            output_path=output_path,
            source_variants=source_variants,
            source_lang_name=source_lang_name,
            command_timeout_seconds=command_timeout_seconds,
            ffmpeg_path=ffmpeg_path,
            log_fn=log_fn
        )

    return _extract_mkv_subtitle(
        resolved_media_path=resolved_media_path,
        output_path=output_path,
        source_variants=source_variants,
        source_lang_name=source_lang_name,
        command_timeout_seconds=command_timeout_seconds,
        mkvinfo_path=mkvinfo_path,
        mkvextract_path=mkvextract_path,
        ffmpeg_path=ffmpeg_path,
        log_fn=log_fn
    )


def has_embedded_subtitle(
    media_path,
    language_name,
    language_variants,
    mkvinfo_path=None,
    mkvextract_path=None,
    ffmpeg_path=None,
    log_fn=None
):
    resolved_media_path = _resolve_filesystem_path(media_path)
    if not resolved_media_path:
        return {"found": False, "reason": "media_path_not_local"}

    if not resolved_media_path.lower().endswith(SUPPORTED_EMBEDDED_SUBTITLE_EXTENSIONS):
        return {"found": False, "reason": "unsupported_container"}

    if not os.path.isfile(resolved_media_path):
        return {"found": False, "reason": "media_file_missing"}

    command_timeout_seconds = (
        NETWORK_COMMAND_TIMEOUT_SECONDS
        if _is_network_filesystem_path(resolved_media_path)
        else LOCAL_COMMAND_TIMEOUT_SECONDS
    )

    _log(
        log_fn,
        "Checking for embedded subtitle → media: {0} | timeout={1}s | language={2}".format(
            resolved_media_path,
            command_timeout_seconds,
            language_name
        )
    )

    media_extension = os.path.splitext(resolved_media_path)[1].lower()
    if media_extension == ".mp4":
        best_track, error_reason = _find_matching_mp4_track(
            resolved_media_path,
            language_variants,
            language_name,
            command_timeout_seconds,
            ffmpeg_path,
            log_fn=log_fn
        )
    else:
        best_track, error_reason = _find_matching_mkv_track(
            resolved_media_path,
            language_variants,
            language_name,
            command_timeout_seconds,
            mkvinfo_path,
            mkvextract_path,
            log_fn=log_fn
        )

    if not best_track:
        return {"found": False, "reason": error_reason}

    return {
        "found": True,
        "reason": "embedded_subtitle_found",
        "track_id": best_track.get("track_id"),
        "codec_name": best_track.get("codec_name"),
        "name": best_track.get("name", ""),
    }
