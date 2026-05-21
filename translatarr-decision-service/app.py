import asyncio
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel


app = FastAPI(title="Translatarr Decision Service")


API_TOKEN = os.environ.get("DECISION_API_TOKEN", "").strip()
DELAY_SECONDS = int(os.environ.get("DECISION_DELAY_SECONDS", "600"))
TARGET_LANGUAGE_NAME = os.environ.get("DECISION_TARGET_LANGUAGE_NAME", "Romanian").strip()
TARGET_LANGUAGE_SUFFIX = os.environ.get("DECISION_TARGET_LANGUAGE_SUFFIX", "ro").strip()
SOURCE_LANGUAGE_NAME = os.environ.get("DECISION_SOURCE_LANGUAGE_NAME", "English").strip()
REMOTE_EXTRACTOR_URL = os.environ.get("REMOTE_EXTRACTOR_URL", "").strip().rstrip("/")
REMOTE_EXTRACTOR_TOKEN = os.environ.get("REMOTE_EXTRACTOR_TOKEN", "").strip()
REMOTE_EXTRACTOR_TIMEOUT = int(os.environ.get("REMOTE_EXTRACTOR_TIMEOUT", "900"))
TRANSLATION_PROVIDER = os.environ.get("TRANSLATION_PROVIDER", "none").strip().lower()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash").strip()
GEMINI_TEMPERATURE = float(os.environ.get("GEMINI_TEMPERATURE", "0.1"))
LIBRETRANSLATE_URL = os.environ.get("LIBRETRANSLATE_URL", "").strip().rstrip("/")
LIBRETRANSLATE_API_KEY = os.environ.get("LIBRETRANSLATE_API_KEY", "").strip()
LIBRETRANSLATE_SOURCE = os.environ.get("LIBRETRANSLATE_SOURCE", "en").strip()
LIBRETRANSLATE_TARGET = os.environ.get("LIBRETRANSLATE_TARGET", "ro").strip()
TRANSLATION_BATCH_SIZE = int(os.environ.get("TRANSLATION_BATCH_SIZE", "60"))
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

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
        if time_pos >= len(lines) or "-->" not in lines[time_pos]:
            continue

        text_lines = lines[time_pos + 1:]
        blocks.append({
            "index": index_line,
            "time": lines[time_pos],
            "text": "\n".join(text_lines),
        })
    return blocks


def render_srt_blocks(blocks: List[Dict[str, Any]]) -> str:
    rendered = []
    for i, block in enumerate(blocks, start=1):
        rendered.append(str(i))
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


def gemini_translate_batch(items: List[Dict[str, Any]]) -> Dict[int, str]:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    prompt_items = [
        {"id": item["id"], "text": item["text"].replace("\n", " [BR] ")}
        for item in items
    ]
    prompt = (
        "Translate the subtitle text from {0} to {1}. ".format(SOURCE_LANGUAGE_NAME, TARGET_LANGUAGE_NAME) +
        "Keep names, formatting tags, punctuation, and meaning. "
        "Do not add explanations. Preserve [BR] markers. "
        "Return strict JSON only in this exact shape: "
        '{"translations":[{"id":0,"text":"translated text"}]}\n\n'
        "Items:\n{0}".format(json.dumps(prompt_items, ensure_ascii=False))
    )

    url = "https://generativelanguage.googleapis.com/v1beta/models/{0}:generateContent".format(GEMINI_MODEL)
    response = requests.post(
        url,
        params={"key": GEMINI_API_KEY},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": GEMINI_TEMPERATURE},
        },
        timeout=180,
    )
    response.raise_for_status()
    data = response.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    parsed = json.loads(strip_json_fence(text))
    result = {}
    for item in parsed.get("translations", []):
        result[int(item["id"])] = str(item.get("text", "")).replace(" [BR] ", "\n").replace("[BR]", "\n")
    return result


def libretranslate_translate_batch(items: List[Dict[str, Any]]) -> Dict[int, str]:
    if not LIBRETRANSLATE_URL:
        raise RuntimeError("LIBRETRANSLATE_URL is not configured")

    result = {}
    for item in items:
        payload = {
            "q": item["text"],
            "source": LIBRETRANSLATE_SOURCE,
            "target": LIBRETRANSLATE_TARGET,
            "format": "text",
        }
        if LIBRETRANSLATE_API_KEY:
            payload["api_key"] = LIBRETRANSLATE_API_KEY

        response = requests.post(
            "{0}/translate".format(LIBRETRANSLATE_URL),
            json=payload,
            timeout=180,
        )
        response.raise_for_status()
        data = response.json()
        result[int(item["id"])] = str(data.get("translatedText", "")).strip()
    return result


def translate_batch(items: List[Dict[str, Any]]) -> Dict[int, str]:
    if TRANSLATION_PROVIDER == "gemini":
        return gemini_translate_batch(items)
    if TRANSLATION_PROVIDER == "libretranslate":
        return libretranslate_translate_batch(items)
    raise RuntimeError("Unsupported TRANSLATION_PROVIDER: {0}".format(TRANSLATION_PROVIDER))


def translate_srt_to_target(content: str) -> str:
    if TRANSLATION_PROVIDER == "none":
        raise RuntimeError("TRANSLATION_PROVIDER is set to none")

    blocks = parse_srt_blocks(content)
    translatable = [
        {"id": i, "text": block["text"]}
        for i, block in enumerate(blocks)
        if (block.get("text") or "").strip()
    ]

    translations: Dict[int, str] = {}
    for start in range(0, len(translatable), TRANSLATION_BATCH_SIZE):
        batch = translatable[start:start + TRANSLATION_BATCH_SIZE]
        translations.update(translate_batch(batch))

    for i, block in enumerate(blocks):
        if i in translations and translations[i].strip():
            block["text"] = translations[i].strip()

    return render_srt_blocks(blocks)


def write_sidecar(media_path: Path, content: str) -> Path:
    target = media_path.with_suffix(".{0}.srt".format(TARGET_LANGUAGE_SUFFIX))
    existing = find_target_sidecars(media_path)
    if existing:
        raise FileExistsError("Romanian sidecar appeared before save: {0}".format(existing[0]))

    fd, temp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(str(temp_path), str(target))
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return target


def notify_discord(title: str, lines: List[str]) -> None:
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        requests.post(
            DISCORD_WEBHOOK_URL,
            json={"content": "**{0}**\n{1}".format(title, "\n".join(lines))},
            timeout=15,
        )
    except Exception:
        pass


async def run_decision_job(job_id: str) -> None:
    job = JOBS[job_id]
    update_job(job_id, "waiting", "Waiting {0}s before checks".format(DELAY_SECONDS))
    await asyncio.sleep(DELAY_SECONDS)

    try:
        update_job(job_id, "running", "Starting delayed decision checks")
        mapped_media = apply_path_maps(job["media_path"])
        media_path = Path(mapped_media)
        update_job(job_id, "running", "Mapped media path", mapped_media_path=str(media_path))

        if media_path.suffix.lower() not in VIDEO_EXTENSIONS:
            update_job(job_id, "skipped", "Unsupported media extension: {0}".format(media_path.suffix))
            return
        if not media_path.exists():
            update_job(job_id, "failed", "Media file does not exist inside container: {0}".format(media_path))
            return

        sidecars = find_target_sidecars(media_path)
        if sidecars:
            update_job(job_id, "completed", "Romanian sidecar already exists", sidecars=sidecars)
            return

        probe = await asyncio.to_thread(probe_embedded_target, str(media_path))
        if probe.get("ok") and probe.get("found"):
            update_job(job_id, "completed", "Embedded Romanian subtitle exists; no extraction or translation needed", probe=probe)
            return

        extract = await asyncio.to_thread(extract_embedded_source, str(media_path))
        if not extract.get("ok"):
            update_job(job_id, "completed", "No usable embedded English source subtitle found", extractor=extract)
            return

        source_srt = extract.get("extracted_srt_content") or ""
        if not source_srt.strip():
            update_job(job_id, "failed", "Extractor returned no subtitle content", extractor=extract)
            return

        sidecars = find_target_sidecars(media_path)
        if sidecars:
            update_job(job_id, "completed", "Romanian sidecar appeared after extraction", sidecars=sidecars)
            return

        translated = await asyncio.to_thread(translate_srt_to_target, source_srt)
        saved_path = write_sidecar(media_path, translated)
        update_job(job_id, "completed", "Translated Romanian sidecar saved", saved_path=str(saved_path))
        notify_discord("Translatarr Decision Service", [
            "Translated: {0}".format(media_path.name),
            "Target: {0}".format(saved_path.name),
        ])
    except FileExistsError as exc:
        update_job(job_id, "completed", str(exc))
    except Exception as exc:
        update_job(job_id, "failed", "{0}: {1}".format(type(exc).__name__, exc))


def queue_job(source: str, payload: Dict[str, Any]) -> TriggerResponse:
    media_path = extract_media_path(payload, source)
    event_type = first_payload_value(payload, ["eventType", "event_type", "radarr_eventtype", "sonarr_eventtype"])
    if not media_path:
        if event_type.lower() == "test":
            return TriggerResponse(
                ok=True,
                job_id="test",
                status="accepted",
                media_path="",
                message="{0} test webhook accepted".format(source.capitalize()),
            )
        raise HTTPException(status_code=400, detail="Could not find media path in payload")

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
    return {
        "ok": True,
        "service": "translatarr-decision-service",
        "delay_seconds": DELAY_SECONDS,
        "remote_extractor_configured": bool(REMOTE_EXTRACTOR_URL),
        "translation_provider": TRANSLATION_PROVIDER,
    }


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
