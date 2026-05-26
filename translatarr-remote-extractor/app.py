import json
import os
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Translatarr Remote Extractor")


API_TOKEN = os.environ.get("EXTRACTOR_API_TOKEN", "").strip()
CACHE_DIR = os.environ.get("EXTRACTOR_CACHE_DIR", "/cache").strip()
WORK_DIR = os.environ.get("EXTRACTOR_WORK_DIR", "/work").strip()

# Keep these language tables aligned with service.translatarr/languages.py.
LANG_NAME_TO_ISO = {
    "Arabic": "ar",
    "Bengali": "bn",
    "Bulgarian": "bg",
    "Catalan": "ca",
    "Chinese": "zh",
    "Croatian": "hr",
    "Czech": "cs",
    "Danish": "da",
    "Dutch": "nl",
    "English": "en",
    "Estonian": "et",
    "Finnish": "fi",
    "French": "fr",
    "German": "de",
    "Greek": "el",
    "Hebrew": "he",
    "Hindi": "hi",
    "Hungarian": "hu",
    "Indonesian": "id",
    "Italian": "it",
    "Japanese": "ja",
    "Korean": "ko",
    "Latvian": "lv",
    "Lithuanian": "lt",
    "Norwegian": "no",
    "Polish": "pl",
    "Portuguese": "pt",
    "Romanian": "ro",
    "Russian": "ru",
    "Serbian": "sr",
    "Slovak": "sk",
    "Slovenian": "sl",
    "Spanish": "es",
    "Swahili": "sw",
    "Swedish": "sv",
    "Thai": "th",
    "Turkish": "tr",
    "Ukrainian": "uk",
    "Vietnamese": "vi",
}

ISO_VARIANTS = {
    "ar": ["ar", "ara"],
    "bn": ["bn", "ben"],
    "bg": ["bg", "bul"],
    "ca": ["ca", "cat"],
    "zh": ["zh", "chi", "zho"],
    "hr": ["hr", "hrv"],
    "cs": ["cs", "cze", "ces"],
    "da": ["da", "dan"],
    "nl": ["nl", "dut", "nld"],
    "en": ["en", "eng"],
    "et": ["et", "est"],
    "fi": ["fi", "fin"],
    "fr": ["fr", "fra", "fre"],
    "de": ["de", "ger", "deu"],
    "el": ["el", "gre", "ell"],
    "he": ["he", "heb"],
    "hi": ["hi", "hin"],
    "hu": ["hu", "hun"],
    "id": ["id", "ind"],
    "it": ["it", "ita"],
    "ja": ["ja", "jpn"],
    "ko": ["ko", "kor"],
    "lv": ["lv", "lav"],
    "lt": ["lt", "lit"],
    "no": ["no", "nor"],
    "pl": ["pl", "pol"],
    "pt": ["pt", "por"],
    "ro": ["ro", "ron", "rum"],
    "ru": ["ru", "rus"],
    "sr": ["sr", "srp"],
    "sk": ["sk", "slk", "slo"],
    "sl": ["sl", "slv"],
    "es": ["es", "spa"],
    "sw": ["sw", "swa"],
    "sv": ["sv", "swe"],
    "th": ["th", "tha"],
    "tr": ["tr", "tur"],
    "uk": ["uk", "ukr"],
    "vi": ["vi", "vie"],
}

PATH_MAPS_RAW = os.environ.get("EXTRACTOR_PATH_MAPS", "[]")
try:
    PATH_MAPS = json.loads(PATH_MAPS_RAW)
    if not isinstance(PATH_MAPS, list):
        PATH_MAPS = []
except Exception:
    PATH_MAPS = []


class ExtractRequest(BaseModel):
    video_path: str
    source_lang: str
    timeout: int
    prefer_non_sdh: bool = True
    allow_ffmpeg_fallback: bool = True
    force_reextract: bool = False


class ExtractResponse(BaseModel):
    ok: bool
    message: str
    method: Optional[str] = None
    cache_hit: bool = False
    extracted_srt_path: Optional[str] = None
    extracted_srt_content: Optional[str] = None
    selected_track: Optional[Dict[str, Any]] = None
    all_tracks: List[Dict[str, Any]] = []
    resolved_video_path: Optional[str] = None
    diagnostic_preview: Optional[str] = None


class ProbeRequest(BaseModel):
    video_path: str
    language: str
    timeout: int
    prefer_non_sdh: bool = True


class ProbeResponse(BaseModel):
    ok: bool
    found: bool = False
    message: str
    selected_track: Optional[Dict[str, Any]] = None
    all_tracks: List[Dict[str, Any]] = []
    resolved_video_path: Optional[str] = None
    diagnostic_preview: Optional[str] = None


def normalize_lang(lang: str) -> str:
    value = (lang or "").strip()
    if not value:
        return ""

    if value in LANG_NAME_TO_ISO:
        return LANG_NAME_TO_ISO[value]

    lowered = value.lower()
    for name, iso in LANG_NAME_TO_ISO.items():
        if lowered == name.lower():
            return iso

    for iso, variants in ISO_VARIANTS.items():
        if lowered == iso:
            return iso
        if lowered in {variant.lower() for variant in variants}:
            return iso

    return lowered


def get_lang_variants(lang: str) -> set:
    base = normalize_lang(lang)
    if not base:
        return set()

    variants = set(ISO_VARIANTS.get(base, [base]))
    variants.add(base)

    for name, iso in LANG_NAME_TO_ISO.items():
        if iso == base:
            variants.add(name)

    return {item.lower() for item in variants if item}


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def run_cmd(cmd: List[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False
    )


def parse_mkvinfo_output(text: str) -> List[Dict[str, Any]]:
    tracks = []
    current = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        normalized_line = line.replace('"', "")

        if "Track number:" in line and "mkvextract:" in line:
            if current and current.get("type") == "subtitles":
                tracks.append(current)

            mkvextract_match = re.search(r"mkvextract:\s*(\d+)", line)
            track_num_match = re.search(r"Track number:\s*(\d+)", line)

            current = {
                "track_number": int(track_num_match.group(1)) if track_num_match else None,
                "mkvextract_id": int(mkvextract_match.group(1)) if mkvextract_match else None,
                "type": None,
                "codec_id": "",
                "language": "",
                "name": "",
                "forced": False,
                "default": False,
            }
            continue

        if current is None:
            continue

        if "Track type:" in normalized_line:
            current["type"] = line.split(":", 1)[1].strip().lower()
        elif "Codec ID:" in normalized_line:
            current["codec_id"] = line.split(":", 1)[1].strip()
        elif "Language:" in normalized_line:
            current["language"] = line.split(":", 1)[1].strip().lower()
        elif "Name:" in normalized_line:
            current["name"] = line.split(":", 1)[1].strip()
        elif "Forced flag:" in normalized_line:
            current["forced"] = "1" in line or "true" in line.lower()
        elif "Default track flag:" in normalized_line or "Default flag:" in normalized_line:
            current["default"] = "1" in line or "true" in line.lower()

    if current and current.get("type") == "subtitles":
        tracks.append(current)

    return tracks


def is_sdh_track(track: Dict[str, Any]) -> bool:
    name = (track.get("name") or "").lower()
    return any(token in name for token in ["sdh", "hearing impaired", "cc", "closed captions"])


def score_track(track: Dict[str, Any], wanted_lang: str, prefer_non_sdh: bool) -> int:
    score = 0
    variants = get_lang_variants(wanted_lang)
    language = (track.get("language") or "").lower()
    name = (track.get("name") or "").lower()
    codec = (track.get("codec_id") or "").lower()

    if language in variants:
        score += 100
    elif any(variant in name for variant in variants):
        score += 40

    if prefer_non_sdh and not is_sdh_track(track):
        score += 20

    if track.get("default"):
        score += 5
    if track.get("forced"):
        score -= 10

    if "s_text" in codec or "subrip" in codec or "ass" in codec or "ssa" in codec:
        score += 25
    if "pgs" in codec or "vobsub" in codec:
        score -= 50

    return score


def has_language_match(track: Dict[str, Any], wanted_lang: str) -> bool:
    variants = get_lang_variants(wanted_lang)
    language = (track.get("language") or "").lower()
    name = (track.get("name") or "").lower()

    if language in variants:
        return True

    normalized_name = re.sub(r"[^a-z0-9]+", " ", name).strip()
    if not normalized_name:
        return False

    name_tokens = [token for token in normalized_name.split() if token]
    for variant in variants:
        normalized_variant = re.sub(r"[^a-z0-9]+", " ", variant.lower()).strip()
        if not normalized_variant:
            continue
        if len(normalized_variant) <= 2:
            if normalized_variant in name_tokens:
                return True
            continue
        if normalized_variant == normalized_name:
            return True
        if normalized_variant in name_tokens:
            return True

    return False


def choose_best_track(
    tracks: List[Dict[str, Any]],
    source_lang: str,
    prefer_non_sdh: bool,
    allow_unlabeled_fallback: bool = False
) -> Optional[Dict[str, Any]]:
    if not tracks:
        return None

    matching_tracks = [
        track for track in tracks
        if has_language_match(track, source_lang)
    ]
    if not matching_tracks and allow_unlabeled_fallback:
        unlabeled_tracks = [
            track for track in tracks
            if not (track.get("language") or "").strip()
        ]
        if not unlabeled_tracks:
            return None

        ranked_unlabeled = sorted(
            unlabeled_tracks,
            key=lambda track: score_track(track, source_lang, prefer_non_sdh),
            reverse=True
        )
        return ranked_unlabeled[0]
    if not matching_tracks:
        return None

    ranked = sorted(
        matching_tracks,
        key=lambda track: score_track(track, source_lang, prefer_non_sdh),
        reverse=True
    )
    best = ranked[0]
    return best


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value or "")


def parse_ffprobe_streams(streams: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    parsed = []
    subtitle_index = 0

    for stream in streams or []:
        codec_type = (stream.get("codec_type") or "").lower()
        codec_name = (stream.get("codec_name") or "").lower()

        if codec_type != "subtitle" and "sub" not in codec_name:
            continue

        tags = stream.get("tags") or {}
        disposition = stream.get("disposition") or {}
        language = (
            tags.get("language")
            or tags.get("LANGUAGE")
            or tags.get("Language")
            or ""
        ).lower()
        track_name = (
            tags.get("title")
            or tags.get("TITLE")
            or tags.get("handler_name")
            or tags.get("HANDLER_NAME")
            or ""
        )

        parsed.append({
            "track_number": stream.get("index"),
            "ffmpeg_sub_index": subtitle_index,
            "type": "subtitles",
            "codec_id": stream.get("codec_name") or "",
            "language": language,
            "name": track_name,
            "forced": bool(disposition.get("forced")),
            "default": bool(disposition.get("default")),
        })
        subtitle_index += 1

    return parsed


def require_auth(authorization: Optional[str]) -> None:
    if not API_TOKEN:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization.split(" ", 1)[1].strip()
    if token != API_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid bearer token")


def apply_path_maps(video_path: str) -> str:
    original = (video_path or "").strip()
    if not original:
        return ""

    normalized = original.replace("\\", "/")

    for rule in PATH_MAPS:
        src = (rule.get("from") or "").strip()
        dst = (rule.get("to") or "").strip()
        if not src or not dst:
            continue

        if original.startswith(src):
            return original.replace(src, dst, 1)

        normalized_src = src.replace("\\", "/")
        if normalized.startswith(normalized_src):
            return normalized.replace(normalized_src, dst, 1)

    return original


def ensure_runtime_dirs() -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(WORK_DIR, exist_ok=True)


def get_cache_path(video_path: str, source_lang: str, track_id: int) -> str:
    import hashlib
    cache_key = hashlib.sha1(
        "{0}|{1}|{2}".format(video_path, normalize_lang(source_lang), track_id).encode("utf-8")
    ).hexdigest()
    return os.path.join(CACHE_DIR, cache_key + ".srt")


def probe_embedded_tracks(video_path: str, language: str, timeout: int, prefer_non_sdh: bool = True) -> ProbeResponse:
    resolved_video_path = apply_path_maps((video_path or "").strip())
    extension = os.path.splitext(resolved_video_path)[1].lower()

    if extension not in (".mkv", ".mp4"):
        return ProbeResponse(
            ok=False,
            found=False,
            message="Only MKV and MP4 probing are implemented currently.",
            resolved_video_path=resolved_video_path
        )

    if extension == ".mkv":
        if not command_exists("mkvinfo"):
            return ProbeResponse(
                ok=False,
                found=False,
                message="mkvinfo not found on extractor host",
                resolved_video_path=resolved_video_path
            )

        try:
            info_result = run_cmd(["mkvinfo", resolved_video_path], timeout=timeout)
        except subprocess.TimeoutExpired:
            return ProbeResponse(
                ok=False,
                found=False,
                message="mkvinfo timed out after {0}s".format(timeout),
                resolved_video_path=resolved_video_path
            )

        if info_result.returncode != 0:
            return ProbeResponse(
                ok=False,
                found=False,
                message="mkvinfo failed: {0}".format(info_result.stderr.strip() or info_result.stdout.strip() or "unknown_error"),
                resolved_video_path=resolved_video_path,
                diagnostic_preview=(info_result.stderr or info_result.stdout or "")[:4000]
            )

        tracks = parse_mkvinfo_output(info_result.stdout)
        selected = choose_best_track(tracks, language, prefer_non_sdh, allow_unlabeled_fallback=False)
        if not tracks:
            return ProbeResponse(
                ok=True,
                found=False,
                message="No subtitle tracks found in MKV",
                all_tracks=[],
                resolved_video_path=resolved_video_path,
                diagnostic_preview=(info_result.stdout or "")[:4000]
            )

        if not selected:
            return ProbeResponse(
                ok=True,
                found=False,
                message="No suitable subtitle track found for language '{0}'".format(language),
                all_tracks=tracks,
                resolved_video_path=resolved_video_path
            )

        return ProbeResponse(
            ok=True,
            found=True,
            message="Embedded subtitle track found",
            selected_track=selected,
            all_tracks=tracks,
            resolved_video_path=resolved_video_path
        )

    if not command_exists("ffprobe"):
        return ProbeResponse(
            ok=False,
            found=False,
            message="ffprobe not found on extractor host",
            resolved_video_path=resolved_video_path
        )

    try:
        probe_result = run_cmd(
            [
                "ffprobe",
                "-v", "error",
                "-print_format", "json",
                "-show_streams",
                resolved_video_path,
            ],
            timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return ProbeResponse(
            ok=False,
            found=False,
            message="ffprobe timed out after {0}s".format(timeout),
            resolved_video_path=resolved_video_path
        )

    if probe_result.returncode != 0:
        return ProbeResponse(
            ok=False,
            found=False,
            message="ffprobe failed: {0}".format(probe_result.stderr.strip() or probe_result.stdout.strip() or "unknown_error"),
            resolved_video_path=resolved_video_path,
            diagnostic_preview=(probe_result.stderr or probe_result.stdout or "")[:4000]
        )

    try:
        probe_data = json.loads(probe_result.stdout or "{}")
    except Exception:
        return ProbeResponse(
            ok=False,
            found=False,
            message="ffprobe returned invalid JSON",
            resolved_video_path=resolved_video_path,
            diagnostic_preview=(probe_result.stdout or "")[:4000]
        )

    tracks = parse_ffprobe_streams(probe_data.get("streams") or [])
    selected = choose_best_track(tracks, language, prefer_non_sdh, allow_unlabeled_fallback=False)

    if not tracks:
        return ProbeResponse(
            ok=True,
            found=False,
            message="No subtitle streams found in MP4",
            all_tracks=[],
            resolved_video_path=resolved_video_path,
            diagnostic_preview=json.dumps(probe_data.get("streams") or [], ensure_ascii=False)[:4000]
        )

    if not selected:
        return ProbeResponse(
            ok=True,
            found=False,
            message="No suitable subtitle stream found for language '{0}'".format(language),
            all_tracks=tracks,
            resolved_video_path=resolved_video_path,
            diagnostic_preview=json.dumps(probe_data.get("streams") or [], ensure_ascii=False)[:4000]
        )

    return ProbeResponse(
        ok=True,
        found=True,
        message="Embedded subtitle stream found",
        selected_track=selected,
        all_tracks=tracks,
        resolved_video_path=resolved_video_path
    )


@app.get("/health")
def health():
    ensure_runtime_dirs()
    return {
        "ok": True,
        "service": "translatarr-remote-extractor",
        "status": "api_contract_ready",
        "cache_dir": CACHE_DIR,
        "work_dir": WORK_DIR,
        "path_maps": len(PATH_MAPS),
        "auth_enabled": bool(API_TOKEN),
    }


@app.post("/probe", response_model=ProbeResponse)
def probe_subtitle(req: ProbeRequest, authorization: Optional[str] = Header(default=None)):
    require_auth(authorization)
    ensure_runtime_dirs()

    video_path = (req.video_path or "").strip()
    language = (req.language or "").strip()
    timeout = req.timeout

    if not video_path:
        raise HTTPException(status_code=400, detail="video_path is required")
    if not language:
        raise HTTPException(status_code=400, detail="language is required")
    if timeout <= 0:
        raise HTTPException(status_code=400, detail="timeout must be greater than 0")

    return probe_embedded_tracks(video_path, language, timeout, req.prefer_non_sdh)


@app.post("/extract", response_model=ExtractResponse)
def extract_subtitle(req: ExtractRequest, authorization: Optional[str] = Header(default=None)):
    require_auth(authorization)
    ensure_runtime_dirs()

    video_path = (req.video_path or "").strip()
    source_lang = (req.source_lang or "").strip()
    timeout = req.timeout

    if not video_path:
        raise HTTPException(status_code=400, detail="video_path is required")
    if not source_lang:
        raise HTTPException(status_code=400, detail="source_lang is required")
    if timeout <= 0:
        raise HTTPException(status_code=400, detail="timeout must be greater than 0")

    resolved_video_path = apply_path_maps(video_path)
    extension = os.path.splitext(resolved_video_path)[1].lower()
    if extension not in (".mkv", ".mp4"):
        return ExtractResponse(
            ok=False,
            message="Only MKV and MP4 extraction are implemented currently.",
            resolved_video_path=resolved_video_path
        )

    if extension == ".mkv":
        if not command_exists("mkvinfo"):
            return ExtractResponse(
                ok=False,
                message="mkvinfo not found on extractor host",
                resolved_video_path=resolved_video_path
            )

        if not command_exists("mkvextract"):
            return ExtractResponse(
                ok=False,
                message="mkvextract not found on extractor host",
                resolved_video_path=resolved_video_path
            )

        try:
            info_result = run_cmd(["mkvinfo", resolved_video_path], timeout=timeout)
        except subprocess.TimeoutExpired:
            return ExtractResponse(
                ok=False,
                message="mkvinfo timed out after {0}s".format(timeout),
                resolved_video_path=resolved_video_path
            )

        if info_result.returncode != 0:
            return ExtractResponse(
                ok=False,
                message="mkvinfo failed: {0}".format(info_result.stderr.strip() or info_result.stdout.strip() or "unknown_error"),
                resolved_video_path=resolved_video_path
            )

        tracks = parse_mkvinfo_output(info_result.stdout)
        selected = choose_best_track(tracks, source_lang, req.prefer_non_sdh, allow_unlabeled_fallback=True)

        if not tracks:
            return ExtractResponse(
                ok=False,
                message="No subtitle tracks found in MKV",
                all_tracks=[],
                resolved_video_path=resolved_video_path,
                diagnostic_preview=(info_result.stdout or "")[:4000]
            )

        if not selected:
            return ExtractResponse(
                ok=False,
                message="No suitable subtitle track found for language '{0}'".format(source_lang),
                all_tracks=tracks,
                resolved_video_path=resolved_video_path
            )

        cache_path = get_cache_path(resolved_video_path, source_lang, selected["mkvextract_id"])
        if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0 and not req.force_reextract:
            with open(cache_path, "r", encoding="utf-8", errors="ignore") as cached_file:
                cached_content = cached_file.read()
            return ExtractResponse(
                ok=True,
                message="Using cached extracted subtitle",
                method="cache",
                cache_hit=True,
                extracted_srt_path=cache_path,
                extracted_srt_content=cached_content,
                selected_track=selected,
                all_tracks=tracks,
                resolved_video_path=resolved_video_path
            )

        temp_output = os.path.join(
            WORK_DIR,
            "{0}.track{1}.srt".format(
                safe_name(os.path.splitext(os.path.basename(resolved_video_path))[0]),
                selected["mkvextract_id"]
            )
        )

        if os.path.exists(temp_output):
            os.remove(temp_output)

        try:
            extract_result = run_cmd(
                ["mkvextract", "tracks", resolved_video_path, "{0}:{1}".format(selected["mkvextract_id"], temp_output)],
                timeout=timeout
            )
        except subprocess.TimeoutExpired:
            return ExtractResponse(
                ok=False,
                message="mkvextract timed out after {0}s".format(timeout),
                selected_track=selected,
                all_tracks=tracks,
                resolved_video_path=resolved_video_path
            )

        if extract_result.returncode != 0:
            return ExtractResponse(
                ok=False,
                message="mkvextract failed: {0}".format(extract_result.stderr.strip() or extract_result.stdout.strip() or "unknown_error"),
                selected_track=selected,
                all_tracks=tracks,
                resolved_video_path=resolved_video_path
            )

        if not os.path.exists(temp_output) or os.path.getsize(temp_output) == 0:
            return ExtractResponse(
                ok=False,
                message="mkvextract produced no subtitle file",
                selected_track=selected,
                all_tracks=tracks,
                resolved_video_path=resolved_video_path
            )

        shutil.copy2(temp_output, cache_path)
        with open(cache_path, "r", encoding="utf-8", errors="ignore") as subtitle_file:
            subtitle_text = subtitle_file.read()

        return ExtractResponse(
            ok=True,
            message="mkvextract success",
            method="mkvextract",
            cache_hit=False,
            extracted_srt_path=cache_path,
            extracted_srt_content=subtitle_text,
            selected_track=selected,
            all_tracks=tracks,
            resolved_video_path=resolved_video_path
        )

    if not command_exists("ffprobe"):
        return ExtractResponse(
            ok=False,
            message="ffprobe not found on extractor host",
            resolved_video_path=resolved_video_path
        )

    if not command_exists("ffmpeg"):
        return ExtractResponse(
            ok=False,
            message="ffmpeg not found on extractor host",
            resolved_video_path=resolved_video_path
        )

    try:
        probe_result = run_cmd(
            [
                "ffprobe",
                "-v", "error",
                "-print_format", "json",
                "-show_streams",
                resolved_video_path,
            ],
            timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return ExtractResponse(
            ok=False,
            message="ffprobe timed out after {0}s".format(timeout),
            resolved_video_path=resolved_video_path
        )

    if probe_result.returncode != 0:
        return ExtractResponse(
            ok=False,
            message="ffprobe failed: {0}".format(probe_result.stderr.strip() or probe_result.stdout.strip() or "unknown_error"),
            resolved_video_path=resolved_video_path,
            diagnostic_preview=(probe_result.stderr or probe_result.stdout or "")[:4000]
        )

    try:
        probe_data = json.loads(probe_result.stdout or "{}")
    except Exception:
        return ExtractResponse(
            ok=False,
            message="ffprobe returned invalid JSON",
            resolved_video_path=resolved_video_path,
            diagnostic_preview=(probe_result.stdout or "")[:4000]
        )

    tracks = parse_ffprobe_streams(probe_data.get("streams") or [])
    selected = choose_best_track(tracks, source_lang, req.prefer_non_sdh, allow_unlabeled_fallback=True)

    if not tracks:
        return ExtractResponse(
            ok=False,
            message="No subtitle streams found in MP4",
            all_tracks=[],
            resolved_video_path=resolved_video_path,
            diagnostic_preview=json.dumps(probe_data.get("streams") or [], ensure_ascii=False)[:4000]
        )

    if not selected:
        return ExtractResponse(
            ok=False,
            message="No suitable subtitle stream found for language '{0}'".format(source_lang),
            all_tracks=tracks,
            resolved_video_path=resolved_video_path,
            diagnostic_preview=json.dumps(probe_data.get("streams") or [], ensure_ascii=False)[:4000]
        )

    cache_path = get_cache_path(resolved_video_path, source_lang, selected["track_number"])
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0 and not req.force_reextract:
        with open(cache_path, "r", encoding="utf-8", errors="ignore") as cached_file:
            cached_content = cached_file.read()
        return ExtractResponse(
            ok=True,
            message="Using cached extracted subtitle",
            method="cache",
            cache_hit=True,
            extracted_srt_path=cache_path,
            extracted_srt_content=cached_content,
            selected_track=selected,
            all_tracks=tracks,
            resolved_video_path=resolved_video_path
        )

    temp_output = os.path.join(
        WORK_DIR,
        "{0}.stream{1}.srt".format(
            safe_name(os.path.splitext(os.path.basename(resolved_video_path))[0]),
            selected["ffmpeg_sub_index"]
        )
    )

    if os.path.exists(temp_output):
        os.remove(temp_output)

    try:
        extract_result = run_cmd(
            [
                "ffmpeg",
                "-y",
                "-loglevel", "error",
                "-i", resolved_video_path,
                "-map", "0:s:{0}".format(selected["ffmpeg_sub_index"]),
                temp_output,
            ],
            timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return ExtractResponse(
            ok=False,
            message="ffmpeg timed out after {0}s".format(timeout),
            selected_track=selected,
            all_tracks=tracks,
            resolved_video_path=resolved_video_path
        )

    if extract_result.returncode != 0:
        return ExtractResponse(
            ok=False,
            message="ffmpeg failed: {0}".format(extract_result.stderr.strip() or extract_result.stdout.strip() or "unknown_error"),
            selected_track=selected,
            all_tracks=tracks,
            resolved_video_path=resolved_video_path
        )

    if not os.path.exists(temp_output) or os.path.getsize(temp_output) == 0:
        return ExtractResponse(
            ok=False,
            message="ffmpeg produced no subtitle file",
            selected_track=selected,
            all_tracks=tracks,
            resolved_video_path=resolved_video_path
        )

    shutil.copy2(temp_output, cache_path)
    with open(cache_path, "r", encoding="utf-8", errors="ignore") as subtitle_file:
        subtitle_text = subtitle_file.read()

    return ExtractResponse(
        ok=True,
        message="ffmpeg success",
        method="ffmpeg",
        cache_hit=False,
        extracted_srt_path=cache_path,
        extracted_srt_content=subtitle_text,
        selected_track=selected,
        all_tracks=tracks,
        resolved_video_path=resolved_video_path
    )
