import asyncio
import hashlib
import json
import os
import re
import stat
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

try:
    from google import genai
except ImportError:
    genai = None


app = FastAPI(title="Translatarr Decision Service")


API_TOKEN = os.environ.get("DECISION_API_TOKEN", "").strip()
DELAY_SECONDS = int(os.environ.get("DECISION_DELAY_SECONDS", "600"))
TARGET_LANGUAGE_NAME = os.environ.get("DECISION_TARGET_LANGUAGE_NAME", "Romanian").strip()
TARGET_LANGUAGE_SUFFIX = os.environ.get("DECISION_TARGET_LANGUAGE_SUFFIX", "ro").strip()
SOURCE_LANGUAGE_NAME = os.environ.get("DECISION_SOURCE_LANGUAGE_NAME", "English").strip()
SOURCE_LANGUAGE_SUFFIX = os.environ.get("DECISION_SOURCE_LANGUAGE_SUFFIX", "en").strip()
REMOTE_EXTRACTOR_URL = os.environ.get("REMOTE_EXTRACTOR_URL", "").strip().rstrip("/")
REMOTE_EXTRACTOR_TOKEN = os.environ.get("REMOTE_EXTRACTOR_TOKEN", "").strip()
REMOTE_EXTRACTOR_TIMEOUT = int(os.environ.get("REMOTE_EXTRACTOR_TIMEOUT", "900"))
TRANSLATION_PROVIDER = os.environ.get("TRANSLATION_PROVIDER", "none").strip().lower()
TRANSLATION_STYLE = os.environ.get("TRANSLATION_STYLE", "Gritty / Adult").strip()
ROLLING_SOURCE_CONTEXT_ENABLED = os.environ.get("ROLLING_SOURCE_CONTEXT_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
ROLLING_SOURCE_CONTEXT_WINDOW = max(
    3,
    min(8, int(os.environ.get("ROLLING_SOURCE_CONTEXT_WINDOW", "5"))),
)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite").strip()
GEMINI_TEMPERATURE = float(os.environ.get("GEMINI_TEMPERATURE", "0.1"))
GEMINI_TOP_P = float(os.environ.get("GEMINI_TOP_P", "0.95"))

GEMINI_THINKING_MAP = {"Minimal": "minimal", "Low": "low", "Medium": "medium", "High": "high"}
GEMINI_THINKING_LEVEL = GEMINI_THINKING_MAP.get(os.environ.get("GEMINI_THINKING_LEVEL", "Minimal").strip(), "minimal")
LIBRETRANSLATE_URL = os.environ.get("LIBRETRANSLATE_URL", "").strip().rstrip("/")
LIBRETRANSLATE_API_KEY = os.environ.get("LIBRETRANSLATE_API_KEY", "").strip()
LIBRETRANSLATE_SOURCE = os.environ.get("LIBRETRANSLATE_SOURCE", "en").strip()
LIBRETRANSLATE_TARGET = os.environ.get("LIBRETRANSLATE_TARGET", "ro").strip()
TRANSLATION_BATCH_SIZE = int(os.environ.get("TRANSLATION_BATCH_SIZE", "60"))
SAVE_SOURCE_SUBTITLE = os.environ.get("SAVE_SOURCE_SUBTITLE", "true").strip().lower() in {"1", "true", "yes", "on"}
PROTECT_SAVED_SUBTITLES = os.environ.get("PROTECT_SAVED_SUBTITLES", "true").strip().lower() in {"1", "true", "yes", "on"}
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
DISCORD_NOTIFY_STEPS = os.environ.get("DISCORD_NOTIFY_STEPS", "true").strip().lower() in {"1", "true", "yes", "on"}
MAX_SOURCE_SRT_BYTES = int(os.environ.get("DECISION_MAX_SOURCE_SRT_BYTES", str(1024 * 1024)))
SRT_TIME_RE = re.compile(
    r"^\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*"
    r"\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}"
)

MODEL_PRICING = {
    "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.50, "thought": 0.00},
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40, "thought": 0.00},
}

TARGET_SIDECAR_TOKENS = {"ro", "ron", "rum", "romanian", "romana"}
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".m4v"}
PATH_MAPS_RAW = os.environ.get("MEDIA_PATH_MAPS", "[]")

try:
    PATH_MAPS = json.loads(PATH_MAPS_RAW)
    if not isinstance(PATH_MAPS, list):
        PATH_MAPS = []
except Exception:
    PATH_MAPS = []

JOBS: Dict[str, Dict[str, Any]] = {}
MEDIA_TO_JOB: Dict[str, str] = {}


class TriggerResponse(BaseModel):
    ok: bool
    job_id: str
    status: str
    media_path: str
    message: str


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_auth(authorization: Optional[str], x_decision_token: Optional[str] = None, token: Optional[str] = None) -> None:
    if not API_TOKEN:
        return
    expected = "Bearer {0}".format(API_TOKEN)
    if authorization == expected:
        return
    if x_decision_token == API_TOKEN:
        return
    if token == API_TOKEN:
        return
    raise HTTPException(status_code=401, detail="Unauthorized")


def require_request_auth(request: Request, authorization: Optional[str], x_decision_token: Optional[str]) -> None:
    token = request.query_params.get("token")
    require_auth(authorization, x_decision_token, token)


def update_job(job_id: str, status: str, detail: str = "", **extra: Any) -> None:
    job = JOBS[job_id]
    job["status"] = status
    job["detail"] = detail
    job["updated_at"] = now_iso()
    job.update(extra)


def apply_path_maps(path: str) -> str:
    result = (path or "").strip()
    for item in PATH_MAPS:
        source = str(item.get("from", ""))
        target = str(item.get("to", ""))
        if source and target and result.lower().startswith(source.lower()):
            tail = result[len(source):].lstrip("/\\")
            separator = "\\" if "\\" in target and "/" not in target else "/"
            if not tail:
                return target.rstrip("/\\")
            return target.rstrip("/\\") + separator + tail
    return result


def nested_get(payload: Dict[str, Any], dotted_key: str) -> Optional[Any]:
    current: Any = payload
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def first_payload_value(payload: Dict[str, Any], keys: List[str]) -> str:
    for key in keys:
        value = nested_get(payload, key) if "." in key else payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def extract_media_path(payload: Dict[str, Any], source: str) -> str:
    shared_keys = [
        "path",
        "media_path",
        "video_path",
        "file.path",
    ]
    if source == "radarr":
        keys = [
            "movieFile.path",
            "moviefile.path",
            "radarr_moviefile_path",
            "movie_file_path",
            "moviefile_path",
        ] + shared_keys
    else:
        keys = [
            "episodeFile.path",
            "episodefile.path",
            "sonarr_episodefile_path",
            "episode_file_path",
            "episodefile_path",
        ] + shared_keys
    return first_payload_value(payload, keys)


def make_job_id(media_path: str) -> str:
    digest = hashlib.sha1(media_path.lower().encode("utf-8")).hexdigest()
    return digest[:16]


def subtitle_tokens(stem: str) -> set:
    return {part for part in re.split(r"[\s._\-\[\]\(\)]+", stem.lower()) if part}


def belongs_to_media(subtitle_stem: str, media_stem: str) -> bool:
    sub = subtitle_stem.lower()
    media = media_stem.lower()
    return sub == media or sub.startswith(media + ".") or sub.startswith(media + " ")


def find_target_sidecars(media_path: Path) -> List[str]:
    media_stem = media_path.stem
    matches = []
    if not media_path.parent.exists():
        return matches

    for subtitle in media_path.parent.glob("*.srt"):
        if not belongs_to_media(subtitle.stem, media_stem):
            continue
        tokens = subtitle_tokens(subtitle.stem)
        if tokens.intersection(TARGET_SIDECAR_TOKENS):
            matches.append(str(subtitle))
    return sorted(matches)


def headers_for_extractor() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if REMOTE_EXTRACTOR_TOKEN:
        headers["Authorization"] = "Bearer {0}".format(REMOTE_EXTRACTOR_TOKEN)
    return headers


def require_extractor_config() -> None:
    if not REMOTE_EXTRACTOR_URL:
        raise RuntimeError("REMOTE_EXTRACTOR_URL is not configured")


def probe_embedded_target(media_path: str) -> Dict[str, Any]:
    require_extractor_config()
    payload = {
        "video_path": media_path,
        "language": TARGET_LANGUAGE_NAME,
        "timeout": REMOTE_EXTRACTOR_TIMEOUT,
        "prefer_non_sdh": True,
    }
    response = requests.post(
        "{0}/probe".format(REMOTE_EXTRACTOR_URL),
        json=payload,
        headers=headers_for_extractor(),
        timeout=REMOTE_EXTRACTOR_TIMEOUT + 30,
    )
    response.raise_for_status()
    return response.json()


def describe_subtitle_track(track: Dict[str, Any]) -> str:
    """Build a human-readable label for a subtitle track (Full / SDH / Forced)."""
    if not track:
        return "unknown track"
    name = (track.get("name") or "").strip()
    forced = track.get("forced", False)
    codec = (track.get("codec_id") or "").strip()
    track_num = track.get("track_number") or "?"

    if forced:
        label = "Forced"
    elif name and any(t in name.lower() for t in ["sdh", "hearing impaired", "cc", "closed captions"]):
        label = "SDH"
    elif name:
        label = name
    else:
        label = "Full"

    parts = [label]
    if codec:
        parts.append("({0})".format(codec))
    parts.append("[track {0}]".format(track_num))
    return " ".join(parts)


def extract_embedded_source(media_path: str) -> Dict[str, Any]:
    require_extractor_config()
    payload = {
        "video_path": media_path,
        "source_lang": SOURCE_LANGUAGE_NAME,
        "timeout": REMOTE_EXTRACTOR_TIMEOUT,
        "prefer_non_sdh": True,
    }
    response = requests.post(
        "{0}/extract".format(REMOTE_EXTRACTOR_URL),
        json=payload,
        headers=headers_for_extractor(),
        timeout=REMOTE_EXTRACTOR_TIMEOUT + 30,
    )
    response.raise_for_status()
    return response.json()


def parse_srt_blocks(content: str) -> List[Dict[str, Any]]:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    blocks = []
    for raw_block in re.split(r"\n\s*\n", normalized):
        lines = raw_block.splitlines()
        if len(lines) < 2:
            continue

        index_line = lines[0] if lines[0].strip().isdigit() else ""
        time_pos = 1 if index_line else 0
        if time_pos >= len(lines) or not SRT_TIME_RE.match(lines[time_pos]):
            continue

        text_lines = lines[time_pos + 1:]
        if not any(line.strip() for line in text_lines):
            continue
        blocks.append({
            "index": index_line,
            "time": lines[time_pos],
            "text": "\n".join(text_lines),
        })
    return blocks


def validate_source_srt(content: str) -> tuple:
    if not content or not content.strip():
        return False, "subtitle content is empty", []

    encoded_size = len(content.encode("utf-8", errors="ignore"))
    if encoded_size > MAX_SOURCE_SRT_BYTES:
        return False, "subtitle content is too large for safe translation ({0} bytes)".format(encoded_size), []

    if "\x00" in content[:4096]:
        return False, "subtitle content looks binary, not text", []

    control_chars = sum(1 for char in content if ord(char) < 32 and char not in "\r\n\t")
    if control_chars > max(20, len(content) // 100):
        return False, "subtitle content has too many control characters", []

    blocks = parse_srt_blocks(content)
    if not blocks:
        return False, "subtitle content is not valid SRT", []

    text_chars = sum(len(block.get("text") or "") for block in blocks)
    if text_chars < 20 and len(content) > 1000:
        return False, "subtitle content has no usable subtitle dialogue", []

    return True, "", blocks


def render_srt_blocks(blocks: List[Dict[str, Any]]) -> str:
    rendered = []
    for i, block in enumerate(blocks, start=1):
        rendered.append(str(block.get("index") or i))
        rendered.append(block["time"])
        rendered.extend((block.get("text") or "").splitlines() or [""])
        rendered.append("")
    return "\n".join(rendered).rstrip() + "\n"


def strip_json_fence(text: str) -> str:
    value = (text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value)
    first = value.find("{")
    last = value.rfind("}")
    if first >= 0 and last > first:
        return value[first:last + 1]
    return value


def build_prefixed_lines(text_list: List[str]) -> List[str]:
    return ["L{0:03}: {1}".format(i, text) for i, text in enumerate(text_list)]


def build_source_context_lines(context_list: Optional[List[str]]) -> List[str]:
    if not context_list:
        return []
    return ["C{0:03}: {1}".format(i, text) for i, text in enumerate(context_list)]


def build_source_context_block(context_list: Optional[List[str]]) -> str:
    context_lines = build_source_context_lines(context_list)
    if not context_lines:
        return ""

    return (
        "READ-ONLY SOURCE CONTEXT FROM PREVIOUS SUBTITLES:\n"
        "- Use these previous source lines only to understand references, pronouns, tone, and sentence continuity.\n"
        "- Do NOT translate these context lines.\n"
        "- Do NOT output Cxxx anchors.\n"
        + "\n".join(context_lines)
        + "\n\n"
        "CURRENT LINES TO TRANSLATE:\n"
    )


def scrub_prefixed_lines(raw_text: str, expected_count: int) -> Optional[List[str]]:
    if not raw_text:
        return None

    cleaned = [
        re.sub(r"^L\d{3}:\s*", "", line.strip())
        for line in raw_text.strip().split("\n")
        if re.match(r"^L\d{3}:", line.strip())
    ]

    if len(cleaned) != expected_count:
        return None

    return cleaned


def is_gemini3() -> bool:
    return GEMINI_MODEL.startswith("gemini-3")


def calculate_translation_cost(input_count: int, output_count: int) -> float:
    if TRANSLATION_PROVIDER != "gemini":
        return 0.0
    pricing = MODEL_PRICING.get(GEMINI_MODEL, {})
    return (
        (input_count / 1_000_000) * pricing.get("input", 0.0)
        + (output_count / 1_000_000) * pricing.get("output", 0.0)
    )


def get_billing_label() -> str:
    if TRANSLATION_PROVIDER == "libretranslate":
        return "LibreTranslate"
    if is_gemini3():
        return "Gemini ({0}, think={1})".format(GEMINI_MODEL, GEMINI_THINKING_LEVEL)
    return GEMINI_MODEL


def normalize_translation_style(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"2", "gritty", "adult", "gritty / adult", "gritty/adult", "gritty-adult"}:
        return "Gritty / Adult"
    if normalized in {"1", "natural"}:
        return "Natural"
    if normalized in {"0", "family", "family-friendly", "family friendly", "clean"}:
        return "Family-Friendly"
    return "Gritty / Adult"


def build_style_instruction(trg_name: str) -> str:
    style_mode = normalize_translation_style(TRANSLATION_STYLE)

    if style_mode == "Gritty / Adult":
        return (
            "STYLE REQUIREMENT:\n"
            "- Tone: gritty, raw, adult {0}.\n"
            "- Preserve profanity and strong language.\n"
            "- Do NOT soften insults.\n"
            "- Maintain emotional intensity.\n"
        ).format(trg_name)

    if style_mode == "Natural":
        return (
            "STYLE REQUIREMENT:\n"
            "- Tone: natural conversational {0}.\n"
            "- Sound realistic and fluid.\n"
            "- Avoid overly literal translation.\n"
            "- Always translate the dialogue, even when the source contains profanity or strong insults.\n"
            "- Render profanity and insults naturally for the target language without intensifying them.\n"
        ).format(trg_name)

    return (
        "STYLE REQUIREMENT:\n"
        "- Tone: clean, neutral, broadcast-safe {0}.\n"
        "- Always translate the dialogue, even when the source contains profanity or strong insults.\n"
        "- Render profanity and strong insults as mild, non-profane alternatives.\n"
        "- Keep dialogue suitable for general audiences.\n"
    ).format(trg_name)


def build_localization_instruction() -> str:
    return (
        "LOCALIZATION REQUIREMENT:\n"
        "- Translate idiomatic expressions by meaning rather than word-for-word when needed.\n"
        "- Use context to choose grammatical gender correctly when the target language requires it.\n"
    )


def gemini_translate_lines(text_list: List[str], expected_count: int, context_list: Optional[List[str]] = None) -> tuple:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    if genai is None:
        raise RuntimeError("google-genai is not installed")

    client = genai.Client(api_key=GEMINI_API_KEY)
    prefixed_lines = build_prefixed_lines(text_list)
    input_text = build_source_context_block(context_list) + "\n".join(prefixed_lines)

    prompt = (
        "### ROLE\n"
        "Professional {0}-to-{1} subtitle localizer.\n\n"
        "{2}\n"
        "{3}\n"
        "### RULES\n"
        "1. Preserve 'Lxxx:' prefix.\n"
        "2. Return exactly {4} lines.\n"
        "3. Preserve [BR] markers exactly where subtitle line breaks belong.\n"
        "4. Return ONLY prefixes and translation.\n"
        "5. If read-only Cxxx source context is provided, use it for meaning only and never include it in the output."
    ).format(
        SOURCE_LANGUAGE_NAME,
        TARGET_LANGUAGE_NAME,
        build_style_instruction(TARGET_LANGUAGE_NAME),
        build_localization_instruction(),
        expected_count,
    )

    attempts = 0
    while attempts < 3:
        try:
            config = {
                "temperature": GEMINI_TEMPERATURE,
                "top_p": GEMINI_TOP_P,
            }
            if is_gemini3():
                config["thinking_config"] = {"thinking_level": GEMINI_THINKING_LEVEL}

            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[prompt, input_text],
                config=config,
            )

            if not response or not getattr(response, "text", None):
                attempts += 1
                time.sleep(2)
                continue

            translated_lines = scrub_prefixed_lines(response.text, expected_count)
            if not translated_lines:
                attempts += 1
                time.sleep(2)
                continue

            usage = getattr(response, "usage_metadata", None)
            thought_tokens = int(getattr(usage, "thoughts_token_count", 0) or 0) if usage else 0
            input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0) if usage else 0
            output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0) if usage else 0

            return translated_lines, thought_tokens, input_tokens, output_tokens
        except Exception:
            attempts += 1
            time.sleep(3)

    return None, 0, 0, 0


def libretranslate_translate_lines(text_list: List[str], expected_count: int, context_list: Optional[List[str]] = None) -> tuple:
    if not LIBRETRANSLATE_URL:
        raise RuntimeError("LIBRETRANSLATE_URL is not configured")

    prefixed_lines = build_prefixed_lines(text_list)
    submitted_lines = build_source_context_lines(context_list) + prefixed_lines
    payload = {
        "q": submitted_lines,
        "source": LIBRETRANSLATE_SOURCE,
        "target": LIBRETRANSLATE_TARGET,
        "format": "text",
    }
    if LIBRETRANSLATE_API_KEY:
        payload["api_key"] = LIBRETRANSLATE_API_KEY

    attempts = 0
    while attempts < 3:
        try:
            response = requests.post("{0}/translate".format(LIBRETRANSLATE_URL), json=payload, timeout=30)
            if response.status_code != 200:
                attempts += 1
                time.sleep(2)
                continue

            data = response.json()
            translated = data.get("translatedText")
            if isinstance(translated, list):
                joined = "\n".join(str(item).strip() for item in translated)
            else:
                joined = str(translated or "")

            translated_lines = scrub_prefixed_lines(joined, expected_count)
            if not translated_lines:
                attempts += 1
                time.sleep(2)
                continue

            input_chars = sum(len(item) for item in submitted_lines)
            output_chars = sum(len(item) for item in translated_lines)
            return translated_lines, 0, input_chars, output_chars
        except Exception:
            attempts += 1
            time.sleep(3)

    return None, 0, 0, 0


def translate_text_only(text_list: List[str], expected_count: int, context_list: Optional[List[str]] = None) -> tuple:
    if TRANSLATION_PROVIDER == "gemini":
        return gemini_translate_lines(text_list, expected_count, context_list=context_list)
    if TRANSLATION_PROVIDER == "libretranslate":
        return libretranslate_translate_lines(text_list, expected_count, context_list=context_list)
    raise RuntimeError("Unsupported TRANSLATION_PROVIDER: {0}".format(TRANSLATION_PROVIDER))


def translate_srt_to_target(content: str) -> Dict[str, Any]:
    if TRANSLATION_PROVIDER == "none":
        raise RuntimeError("TRANSLATION_PROVIDER is set to none")

    valid, validation_error, blocks = validate_source_srt(content)
    if not valid:
        raise RuntimeError("Source subtitle rejected: {0}".format(validation_error))

    texts = [
        (block.get("text") or "").replace("\n", " [BR] ")
        for block in blocks
    ]

    all_translated = []
    cum_thought = 0
    cum_in = 0
    cum_out = 0
    idx = 0

    while idx < len(texts):
        success = False
        for size in [TRANSLATION_BATCH_SIZE, 50, 25]:
            chunk = texts[idx:idx + min(size, len(texts) - idx)]
            context_texts = None
            if ROLLING_SOURCE_CONTEXT_ENABLED and idx > 0:
                context_start = max(0, idx - ROLLING_SOURCE_CONTEXT_WINDOW)
                context_texts = texts[context_start:idx]
            translated, thought, input_count, output_count = translate_text_only(
                chunk,
                len(chunk),
                context_list=context_texts,
            )
            if translated:
                all_translated.extend(translated)
                cum_thought += thought or 0
                cum_in += input_count or 0
                cum_out += output_count or 0
                idx += len(chunk)
                success = True
                time.sleep(1)
                break
        if not success:
            raise RuntimeError("Translation failed after retries")

    for i, block in enumerate(blocks):
        txt = all_translated[i] if i < len(all_translated) else ""
        scrubbed = re.sub(r"^[ \t]*L\d{1,4}[:\-\s\.]*", "", txt, flags=re.IGNORECASE).strip()
        final_txt = re.sub(r"\s*\[BR\]\s*", "\n", scrubbed, flags=re.IGNORECASE).strip()
        block["text"] = final_txt

    return {
        "content": render_srt_blocks(blocks),
        "lines": len(all_translated),
        "thought_count": cum_thought,
        "input_count": cum_in,
        "output_count": cum_out,
        "cost": calculate_translation_cost(cum_in, cum_out),
    }


def format_translation_stat_lines(translation: Dict[str, Any]) -> List[str]:
    if TRANSLATION_PROVIDER == "libretranslate":
        return [
            "Provider: {0}".format(get_billing_label()),
            "Input Chars: {0:,}".format(translation["input_count"]),
            "Output Chars: {0:,}".format(translation["output_count"]),
            "Cost: ${0:.4f}".format(translation["cost"]),
        ]

    return [
        "Model: {0}".format(get_billing_label()),
        "Input Tokens: {0:,}".format(translation["input_count"]),
        "Output Tokens: {0:,}".format(translation["output_count"]),
        "Thought: {0:,}".format(translation["thought_count"]),
        "Cost: ${0:.4f}".format(translation["cost"]),
    ]


def write_atomic_verified(path: Path, content: str, protect: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temp_path), str(path))

        with open(path, "rb") as handle:
            os.fsync(handle.fileno())

        if protect and PROTECT_SAVED_SUBTITLES:
            read_only_mode = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
            os.chmod(path, read_only_mode)

        if not path.exists() or path.stat().st_size <= 0:
            raise OSError("subtitle save verification failed: {0}".format(path))

        return path
    finally:
        if temp_path.exists():
            temp_path.unlink()


def write_sidecar(media_path: Path, content: str) -> Path:
    target = media_path.with_suffix(".{0}.srt".format(TARGET_LANGUAGE_SUFFIX))
    existing = find_target_sidecars(media_path)
    if existing:
        raise FileExistsError("Romanian sidecar appeared before save: {0}".format(existing[0]))

    return write_atomic_verified(target, content, protect=True)


def write_language_sidecar(media_path: Path, language_suffix: str, content: str, overwrite: bool = False) -> Path:
    target = media_path.with_suffix(".{0}.srt".format(language_suffix))
    if target.exists() and not overwrite:
        return target

    return write_atomic_verified(target, content, protect=False)


def format_discord_description(lines: List[str]) -> str:
    code_labels = {
        "media",
        "source",
        "target",
        "subtitle",
        "source subtitle",
        "path",
        "origin",
        "event",
        "provider",
        "model",
        "input tokens",
        "output tokens",
        "input chars",
        "output chars",
        "thought",
        "cost",
        "style",
        "target suffix",
        "track",
        "cues",
    }
    formatted = []
    for line in lines:
        if not line:
            formatted.append("")
            continue
        if line.startswith("- "):
            formatted.append(line)
            continue
        if ": " in line:
            label, value = line.split(": ", 1)
            if label.lower() in code_labels:
                formatted.append("**{0}:** `{1}`".format(label, value))
            else:
                formatted.append("**{0}:** {1}".format(label, value))
            continue
        formatted.append(line)
    return "\n".join(formatted)


def discord_color_for_title(title: str) -> int:
    lowered = title.lower()
    if "failed" in lowered or "skipped" in lowered or "no source" in lowered:
        return 15158332
    if "extracting" in lowered or "checking" in lowered or "probing" in lowered or "translating" in lowered:
        return 3447003
    return 3066993


def notify_discord(title: str, lines: List[str], footer: str = "Decision Engine") -> None:
    if not DISCORD_WEBHOOK_URL or not DISCORD_NOTIFY_STEPS:
        return
    try:
        requests.post(
            DISCORD_WEBHOOK_URL,
            json={
                "username": "Translatarr",
                "embeds": [{
                    "title": title,
                    "description": format_discord_description(lines),
                    "color": discord_color_for_title(title),
                    "footer": {"text": footer},
                }],
            },
            timeout=15,
        )
    except Exception:
        pass


def notify_job(job_id: str, title: str, lines: List[str], footer: str = "Decision Engine") -> None:
    job = JOBS.get(job_id, {})
    prefix = [
        "Origin: {0}".format(job.get("source", "unknown")),
        "Event: {0}".format(job.get("event_type", "") or "unknown"),
        "Media: {0}".format(Path(job.get("media_path", "")).name or job.get("media_path", "")),
    ]
    notify_discord(title, prefix + lines, footer=footer)


async def run_decision_job(job_id: str) -> None:
    job = JOBS[job_id]
    update_job(job_id, "waiting", "Waiting {0}s before checks".format(DELAY_SECONDS))
    notify_job(job_id, "Translatarr Decision: queued", [
        "Waiting: {0}s before checks".format(DELAY_SECONDS),
    ])
    await asyncio.sleep(DELAY_SECONDS)

    try:
        update_job(job_id, "running", "Starting delayed decision checks")
        notify_job(job_id, "Translatarr Decision: checking", [
            "Starting delayed Romanian subtitle checks",
        ])
        mapped_media = apply_path_maps(job["media_path"])
        media_path = Path(mapped_media)
        update_job(job_id, "running", "Mapped media path", mapped_media_path=str(media_path))

        if media_path.suffix.lower() not in VIDEO_EXTENSIONS:
            update_job(job_id, "skipped", "Unsupported media extension: {0}".format(media_path.suffix))
            notify_job(job_id, "Translatarr Decision: skipped", [
                "Unsupported media extension: {0}".format(media_path.suffix),
            ])
            return
        if not media_path.exists():
            update_job(job_id, "failed", "Media file does not exist inside container: {0}".format(media_path))
            notify_job(job_id, "Translatarr Decision: failed", [
                "Media file does not exist inside container",
                "Path: {0}".format(media_path),
            ])
            return

        sidecars = find_target_sidecars(media_path)
        if sidecars:
            update_job(job_id, "completed", "Romanian sidecar already exists", sidecars=sidecars)
            notify_job(job_id, "Translatarr Decision: stopped", [
                "Romanian sidecar already exists",
                "Subtitle: {0}".format(Path(sidecars[0]).name),
            ])
            return

        notify_job(job_id, "Translatarr Decision: probing", [
            "No Romanian sidecar found",
            "Checking embedded {0}".format(TARGET_LANGUAGE_NAME),
        ])
        probe = await asyncio.to_thread(probe_embedded_target, str(media_path))
        if probe.get("ok") and probe.get("found"):
            update_job(job_id, "completed", "Embedded Romanian subtitle exists; no extraction or translation needed", probe=probe)
            selected = probe.get("selected_track") or {}
            notify_job(job_id, "Translatarr Decision: stopped", [
                "Embedded Romanian subtitle exists",
                "Action: no extraction, no translation",
                "Track: {0}".format(describe_subtitle_track(selected)),
            ])
            return

        notify_job(job_id, "Translatarr Decision: extracting", [
            "No Romanian sidecar or embedded Romanian subtitle found",
            "Extracting embedded {0}".format(SOURCE_LANGUAGE_NAME),
        ])
        extract = await asyncio.to_thread(extract_embedded_source, str(media_path))
        if not extract.get("ok"):
            update_job(job_id, "completed", "No usable embedded English source subtitle found", extractor=extract)
            notify_job(job_id, "Translatarr Decision: no source", [
                "No usable embedded English source subtitle found",
                "Extractor: {0}".format(extract.get("message", "no message")),
            ])
            return

        source_srt = extract.get("extracted_srt_content") or ""
        if not source_srt.strip():
            update_job(job_id, "failed", "Extractor returned no subtitle content", extractor=extract)
            notify_job(job_id, "Translatarr Decision: failed", [
                "Extractor returned no subtitle content",
            ])
            return

        source_valid, source_validation_error, source_blocks = validate_source_srt(source_srt)
        if not source_valid:
            update_job(job_id, "completed", "Extractor returned unusable subtitle content: {0}".format(source_validation_error), extractor=extract)
            notify_job(job_id, "Translatarr Decision: no source", [
                "Extractor returned unusable subtitle content",
                "Reason: {0}".format(source_validation_error),
            ])
            return

        source_saved_path = None
        if SAVE_SOURCE_SUBTITLE:
            source_saved_path = write_language_sidecar(media_path, SOURCE_LANGUAGE_SUFFIX, source_srt)
            update_job(job_id, "running", "Embedded source subtitle extracted", source_saved_path=str(source_saved_path))
            notify_job(job_id, "Translatarr Decision: extracted", [
                "Embedded {0} subtitle extracted".format(SOURCE_LANGUAGE_NAME),
                "Track: {0}".format(describe_subtitle_track(extract.get("selected_track"))),
                "Source subtitle: {0}".format(source_saved_path.name),
                "Cues: {0}".format(len(source_blocks)),
            ])
        else:
            update_job(job_id, "running", "Embedded source subtitle extracted")
            notify_job(job_id, "Translatarr Decision: extracted", [
                "Embedded {0} subtitle extracted".format(SOURCE_LANGUAGE_NAME),
                "Track: {0}".format(describe_subtitle_track(extract.get("selected_track"))),
                "Source subtitle save: disabled",
                "Cues: {0}".format(len(source_blocks)),
            ])

        sidecars = find_target_sidecars(media_path)
        if sidecars:
            update_job(job_id, "completed", "Romanian sidecar appeared after extraction", sidecars=sidecars)
            notify_job(job_id, "Translatarr Decision: stopped", [
                "Romanian sidecar appeared after extraction",
                "Subtitle: {0}".format(Path(sidecars[0]).name),
            ])
            return

        notify_job(job_id, "Translatarr Decision: translating", [
            "Provider: {0}".format(TRANSLATION_PROVIDER),
            "Style: {0}".format(normalize_translation_style(TRANSLATION_STYLE)),
            "Source: {0}".format(source_saved_path.name if source_saved_path else "embedded {0}".format(SOURCE_LANGUAGE_NAME)),
            "Target suffix: .{0}.srt".format(TARGET_LANGUAGE_SUFFIX),
        ])
        translation = await asyncio.to_thread(translate_srt_to_target, source_srt)
        saved_path = write_sidecar(media_path, translation["content"])
        update_job(job_id, "completed", "Translated Romanian sidecar saved", saved_path=str(saved_path))
        notify_job(job_id, "Translatarr Decision: translated", [
            "Source: {0}".format(source_saved_path.name if source_saved_path else "embedded {0}".format(SOURCE_LANGUAGE_NAME)),
            "Target: {0}".format(saved_path.name),
            "Lines: {0}".format(translation["lines"]),
            "",
        ] + format_translation_stat_lines(translation), footer="Verified Save - Protected Mode")
    except FileExistsError as exc:
        update_job(job_id, "completed", str(exc))
        notify_job(job_id, "Translatarr Decision: stopped", [
            str(exc),
        ])
    except Exception as exc:
        update_job(job_id, "failed", "{0}: {1}".format(type(exc).__name__, exc))
        notify_job(job_id, "Translatarr Decision: failed", [
            "{0}: {1}".format(type(exc).__name__, exc),
        ])


def queue_job(source: str, payload: Dict[str, Any]) -> TriggerResponse:
    media_path = extract_media_path(payload, source)
    event_type = first_payload_value(payload, ["eventType", "event_type", "radarr_eventtype", "sonarr_eventtype"])
    if not media_path:
        payload_text = json.dumps(payload, ensure_ascii=False).lower()
        if event_type.lower() == "test" or "test" in payload_text:
            return TriggerResponse(
                ok=True,
                job_id="test",
                status="accepted",
                media_path="",
                message="{0} test webhook accepted".format(source.capitalize()),
            )
        return TriggerResponse(
            ok=True,
            job_id="ignored-no-media-path",
            status="ignored",
            media_path="",
            message="{0} webhook accepted but ignored because no media file path was present".format(source.capitalize()),
        )

    normalized_media = media_path.strip()
    job_id = make_job_id(normalized_media)
    existing_id = MEDIA_TO_JOB.get(normalized_media.lower())
    if existing_id and JOBS.get(existing_id, {}).get("status") in {"queued", "waiting", "running"}:
        existing = JOBS[existing_id]
        return TriggerResponse(
            ok=True,
            job_id=existing_id,
            status=existing["status"],
            media_path=normalized_media,
            message="Duplicate active job already exists",
        )

    JOBS[job_id] = {
        "id": job_id,
        "source": source,
        "event_type": event_type,
        "media_path": normalized_media,
        "status": "queued",
        "detail": "Queued",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    MEDIA_TO_JOB[normalized_media.lower()] = job_id
    asyncio.create_task(run_decision_job(job_id))
    return TriggerResponse(
        ok=True,
        job_id=job_id,
        status="queued",
        media_path=normalized_media,
        message="Decision job queued",
    )


@app.get("/health")
def health() -> Dict[str, Any]:
    result = {
        "ok": True,
        "service": "translatarr-decision-service",
        "delay_seconds": DELAY_SECONDS,
        "remote_extractor_configured": bool(REMOTE_EXTRACTOR_URL),
        "translation_provider": TRANSLATION_PROVIDER,
        "translation_style": normalize_translation_style(TRANSLATION_STYLE),
        "rolling_source_context_enabled": ROLLING_SOURCE_CONTEXT_ENABLED,
        "rolling_source_context_window": ROLLING_SOURCE_CONTEXT_WINDOW,
        "save_source_subtitle": SAVE_SOURCE_SUBTITLE,
        "protect_saved_subtitles": PROTECT_SAVED_SUBTITLES,
    }
    if TRANSLATION_PROVIDER == "gemini":
        result["gemini_model"] = GEMINI_MODEL
        if is_gemini3():
            result["gemini_thinking_level"] = GEMINI_THINKING_LEVEL
    return result


@app.get("/jobs")
def list_jobs(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_decision_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    require_request_auth(request, authorization, x_decision_token)
    return {"jobs": list(JOBS.values())}


@app.post("/radarr", response_model=TriggerResponse)
async def radarr(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_decision_token: Optional[str] = Header(default=None),
) -> TriggerResponse:
    require_request_auth(request, authorization, x_decision_token)
    payload = await request.json()
    return queue_job("radarr", payload)


@app.post("/sonarr", response_model=TriggerResponse)
async def sonarr(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_decision_token: Optional[str] = Header(default=None),
) -> TriggerResponse:
    require_request_auth(request, authorization, x_decision_token)
    payload = await request.json()
    return queue_job("sonarr", payload)
