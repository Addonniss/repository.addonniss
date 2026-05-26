# -*- coding: utf-8 -*-
import os
import re
import xbmcvfs
import xbmcaddon
from languages import get_lang_params, get_active_language_setting

ADDON = xbmcaddon.Addon('service.translatarr')

MUSIC_NOTE_CHARS = u"\u266a\u266b\u266c\u2669"


# -----------------------------------
# Filename Sanitization
# -----------------------------------
def sanitize_filename(filename):
    """
    Aggressively clean filenames for Windows/Linux.
    Removes illegal characters and fixes reserved names.
    """
    # Remove illegal characters
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)

    # Check for Windows reserved names
    name_part = os.path.splitext(sanitized)[0].upper()
    reserved = [
        'CON', 'PRN', 'AUX', 'NUL',
        'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
        'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
    ]
    if name_part in reserved:
        sanitized = "_" + sanitized

    # Remove trailing periods or spaces
    return sanitized.strip('. ')


# -----------------------------------
# Get Target Path
# -----------------------------------
def get_target_path(original_path, video_name):
    """
    Determine where the translated SRT should be saved.
    Handles source/target language, Windows-safe names.
    """
    provider = ADDON.getSetting('provider')
    _, src_iso = get_lang_params(get_active_language_setting(ADDON, provider, 'source'))
    _, trg_iso = get_lang_params(get_active_language_setting(ADDON, provider, 'target'))
    if trg_iso == "auto":
        trg_iso = "ro"

    save_dir = ADDON.getSetting('sub_folder')
    base_name = os.path.basename(original_path)

    # Logic: Swap the extension for target language
    if src_iso != "auto" and f".{src_iso}.srt" in base_name.lower():
        clean_name = re.sub(rf'\.{src_iso}\.srt$', f'.{trg_iso}.srt', base_name, flags=re.IGNORECASE)
    else:
        clean_name = re.sub(r'\.(en|eng)\.srt$', f'.{trg_iso}.srt', base_name, flags=re.IGNORECASE)
        if not clean_name.endswith(f'.{trg_iso}.srt'):
            clean_name = re.sub(r'\.srt$', f'.{trg_iso}.srt', clean_name, flags=re.IGNORECASE)

    # Windows-proof filename
    clean_name = sanitize_filename(clean_name)

    # Full validated path
    full_path = xbmcvfs.validatePath(os.path.join(save_dir, clean_name))

    return full_path, clean_name


def _normalize_sdh_hi_fragment(fragment):
    cleaned = fragment.strip().strip("[](){}")
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned.strip()


def _looks_like_spoken_dialogue_fragment(fragment):
    cleaned = _normalize_sdh_hi_fragment(fragment)
    if not cleaned:
        return False

    words = re.findall(r"[A-Za-z0-9']+", cleaned)
    if not words:
        return False

    if any(ch in cleaned for ch in '"?!'):
        return True

    if "..." in cleaned or "\u2026" in cleaned:
        return False

    if "," in cleaned or ";" in cleaned:
        return True

    if "." in cleaned and len(words) <= 2:
        return True

    return False


def _clean_sdh_hi_line(line):
    stripped = line.strip()
    if not stripped:
        return ""

    no_music = stripped.translate({ord(ch): None for ch in MUSIC_NOTE_CHARS}).strip()
    if stripped != no_music:
        if not no_music:
            return ""
        if stripped.startswith(tuple(MUSIC_NOTE_CHARS)) or stripped.endswith(tuple(MUSIC_NOTE_CHARS)):
            return ""

    if re.match(r'^\s*(\[[^\[\]]{1,80}\]|\([^\(\)]{1,80}\))\s*$', stripped):
        if not _looks_like_spoken_dialogue_fragment(stripped):
            return ""

    working = stripped
    prefix_pattern = r'^\s*(\[[^\[\]]{1,80}\]|\([^\(\)]{1,80}\))\s*'
    while True:
        match = re.match(prefix_pattern, working)
        if not match:
            break
        fragment = match.group(1)
        if _looks_like_spoken_dialogue_fragment(fragment):
            break
        working = working[match.end():].lstrip()

    suffix_pattern = r'\s*(\[[^\[\]]{1,80}\]|\([^\(\)]{1,80}\))\s*$'
    while True:
        match = re.search(suffix_pattern, working)
        if not match:
            break
        fragment = match.group(1)
        if _looks_like_spoken_dialogue_fragment(fragment):
            break
        working = working[:match.start()].rstrip()

    speaker_match = re.match(r"^\s*[A-Z][A-Z0-9 .'\-]{1,24}:\s+(.+)$", working)
    if speaker_match:
        working = speaker_match.group(1).strip()

    return working.strip()


def clean_sdh_hi_text(text):
    """
    Conservatively remove high-confidence SDH/HI cues while preserving dialogue.
    Returns None when the entry is cue-only and should be skipped.
    """
    lines = text.split(' [BR] ')
    cleaned_lines = []

    for line in lines:
        cleaned = _clean_sdh_hi_line(line)
        if cleaned:
            cleaned_lines.append(cleaned)

    if not cleaned_lines:
        return None

    return ' [BR] '.join(cleaned_lines)


# -----------------------------------
# Parse SRT
# -----------------------------------
def parse_srt(content):
    """
    Parse an SRT file and return timestamps + text lines.
    Newlines inside a block are replaced with [BR].
    """
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    blocks = re.findall(
        r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})\n(.*?)(?=\n\n|\n$|$)',
        content,
        re.DOTALL
    )
    if not blocks:
        return None, None

    timestamps = [(b[0], b[1]) for b in blocks]
    texts = [b[2].replace('\n', ' [BR] ') for b in blocks]

    return timestamps, texts


# -----------------------------------
# Write SRT
# -----------------------------------
def _compose_dual_language_text(source_text, translated_text):
    source_text = (source_text or "").strip()
    translated_text = (translated_text or "").strip()

    if source_text and translated_text:
        return source_text + "\n" + translated_text
    if source_text:
        return source_text
    return translated_text


def _restore_block_breaks(text):
    text = re.sub(r'\s*\[BR\]\s*', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'\n([,.;:!?])', r'\1\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def write_srt(path, timestamps, translated_texts, source_texts=None, dual_language=False):
    """
    Write translated texts to SRT file with proper formatting.
    Ensures Lxxx prefixes are removed and [BR] is converted back to line breaks.
    """
    nl = "\n"
    final_srt = []

    for idx, (t, txt) in enumerate(zip(timestamps, translated_texts)):
        # Remove any surviving Lxxx prefixes
        scrubbed_txt = re.sub(r'^[ \t]*L\d{1,4}[:\-\s\.]*', '', txt, flags=re.IGNORECASE).strip()
        if dual_language:
            source_txt = ""
            if source_texts and idx < len(source_texts):
                source_txt = (source_texts[idx] or "").strip()
            scrubbed_txt = _compose_dual_language_text(source_txt, scrubbed_txt)

        # Convert [BR] markers back to real line breaks, including loose variants.
        final_txt = _restore_block_breaks(scrubbed_txt).replace('\n', nl).strip()
        if not final_txt:
            continue
        # Build SRT block
        final_srt.append(f"{t[0]}{nl}{t[1]}{nl}{final_txt}{nl}")

    # Write to file using xbmcvfs
    with xbmcvfs.File(path, 'w') as f:
        f.write(nl.join(final_srt))
