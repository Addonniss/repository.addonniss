# Translatarr Remote Extractor — Flowchart

```
╔══════════════════════════════════════════════════════════════════════════════════════════════════╗
║                     TRANSLATARR REMOTE EXTRACTOR — FULL PIPELINE                                ║
╚══════════════════════════════════════════════════════════════════════════════════════════════════╝

                               ┌─────────────────────┐
                               │  🖥️  service.translatarr │
                               │  (Kodi addon client)  │
                               └──────────┬──────────┘
                                          │
                    ┌─────────────────────┼────────────────────┐
                    ▼                     ▼                     ▼
          ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
          │  GET /health     │  │  POST /probe     │  │  POST /extract   │
          │  Health check    │  │  Check if RO     │  │  Extract EN      │
          │                  │  │  embedded exists │  │  embedded subs   │
          └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘
                   │                     │                      │
                   ▼                     ▼                      ▼
          ┌─────────────────────────────────────────────────────────────┐
          │             🔐 BEARER TOKEN AUTHENTICATION                 │
          │  require_auth(authorization) → "Bearer {EXTRACTOR_API_TOKEN}" │
          └──────────────────────────┬──────────────────────────────────┘
                                     │
                                     ▼
          ┌─────────────────────────────────────────────────────────────┐
          │             🗺️ PATH MAPPING (apply_path_maps)              │
          │  ─────────────────────────────────────────────────────────  │
          │  Translate remote playback paths to container paths:       │
          │                                                             │
          │  Input:  smb://server/share/movies/Example.mkv              │
          │          \\\\server\\share\\movies\\Example.mkv                │
          │          dav://server:3000/content/Example.mkv              │
          │                                                             │
          │  Rule:   {"from":"smb://server/share/","to":"/data/media/"} │
          │                                                             │
          │  Output: /data/media/movies/Example.mkv                     │
          └──────────────────────────┬──────────────────────────────────┘
                                     │
                                     ▼
          ┌─────────────────────────────────────────────────────────────┐
          │             📂 RUNTIME DIRECTORIES ENSURED                 │
          │  ensure_runtime_dirs() → CACHE_DIR + WORK_DIR exist        │
          └──────────────────────────┬──────────────────────────────────┘
                                     │
                                     ▼
          ┌─────────────────────────────────────────────────────────────┐
          │             📐 VALIDATION GATE                             │
          │  ─────────────────────────────────────────────────────────  │
          │  Is video_path provided?                                   │
          │  Is language/source_lang provided?                         │
          │  Is timeout > 0?                                           │
          │  Is file extension .mkv or .mp4?                           │
          └──────────┬─────────────────────────────────┬───────────────┘
                     │                                 │
                     │ VALID                           │ INVALID
                     ▼                                 ▼
          ╔════════════╧══════════════════════════════════════════════════╗
          ║         📋  ROUTING — MKV vs MP4                             ║
          ╚═══════════════════════════════════════════════════════════════╝
                     │
            ┌────────┴────────┐
            ▼                  ▼
   ┌─────────────────┐  ┌─────────────────┐
   │   🎞️ MKV PATH   │  │   🎞️ MP4 PATH   │
   │  mkvinfo +      │  │  ffprobe +      │
   │  mkvextract     │  │  ffmpeg         │
   └────────┬────────┘  └────────┬────────┘
            │                    │
            ▼                    ▼
   ┌────────────────────────────────────────────────────────────────────┐
   │                    🔍 TRACK PROBING                                │
   │  ────────────────────────────────────────────────────────────────  │
   │                                                                     │
   │  ┌─── MKV ──────────────────────────────────────────────────────┐  │
   │  │  mkvinfo <video> → parse_mkvinfo_output() → List[Tracks]     │  │
   │  │                                                              │  │
   │  │  Track parsing extracts:                                     │  │
   │  │  • Track number / mkvextract ID                              │  │
   │  │  • Track type (subtitles only)                               │  │
   │  │  • Codec ID (S_TEXT/UTF8, SubRip, PGS, VobSub, etc.)        │  │
   │  │  • Language                                                  │  │
   │  │  • Name (SDH, hearing-impaired markers)                      │  │
   │  │  • Forced flag / Default flag                                │  │
   │  └──────────────────────────────────────────────────────────────┘  │
   │                                                                     │
   │  ┌─── MP4 ──────────────────────────────────────────────────────┐  │
   │  │  ffprobe -v error -print_format json -show_streams <video>   │  │
   │  │  → parse_ffprobe_streams() → List[Streams]                   │  │
   │  │                                                              │  │
   │  │  Stream parsing extracts:                                    │  │
   │  │  • Stream index + ffmpeg_sub_index                           │  │
   │  │  • Codec type (subtitle only)                                │  │
   │  │  • Codec name                                                │  │
   │  │  • Language from tags                                        │  │
   │  │  • Track name / title from tags                              │  │
   │  │  • Forced / Default disposition                              │  │
   │  └──────────────────────────────────────────────────────────────┘  │
   └──────────────────────────┬─────────────────────────────────────────┘
                              │
                              ▼
          ┌─────────────────────────────────────────────────────────────┐
          │           ⭐ TRACK SCORING & SELECTION                      │
          │  ─────────────────────────────────────────────────────────  │
          │                                                             │
          │  choose_best_track() with scoring algorithm:                │
          │                                                             │
          │  🎯 Language match:         +100  (exact ISO/full name)     │
          │  🎯 Name contains lang:      +40   (token in track name)    │
          │  ✅ Non-SDH:                 +20   (prefer_non_sdh=true)    │
          │  📌 Default track:            +5                            │
          │  ⛔ Forced track:            -10                            │
          │  📝 Text codec:              +25   (s_text/subrip/ass/ssa) │
          │  🖼️ Image codec:             -50   (pgs/vobsub/dvd_sub)    │
          │                                                             │
          │  Filter modes per endpoint:                                 │
          │  ┌─────────────┬──────────────┬─────────────────────────┐  │
          │  │ Endpoint    │ /probe       │ /extract                │  │
          │  ├─────────────┼──────────────┼─────────────────────────┤  │
          │  │ Filter      │ All subs     │ MKV: direct_srt_only    │  │
          │  │             │              │ MP4: text_only          │  │
          │  ├─────────────┼──────────────┼─────────────────────────┤  │
          │  │ Unlabeled   │ ❌ No        │ ✅ Yes (fallback)       │  │
          │  │ fallback    │              │                         │  │
          │  └─────────────┴──────────────┴─────────────────────────┘  │
          └──────────────────────────┬──────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
          ┌──────────────────┐            ┌──────────────────┐
          │  Track found?    │            │  No track found  │
          └────────┬─────────┘            └────────┬─────────┘
                   │ YES                           │
                   ▼                               ▼
          ┌──────────────────┐            ┌──────────────────┐
          │  🔍 /probe only  │            │  Return failure  │
          │  Return found    │            │  ok=false        │
          │  = true + track  │            │  + message       │
          └──────────────────┘            └──────────────────┘

                 ▼ (for /extract only)
          ╔══════════════════════════════════════════════════════════════╗
          ║         💾  CACHE CHECK                                     ║
          ╚══════════════════════════════════════════════════════════════╝
                               │
                    ┌──────────┴──────────┐
                    │  Cache path derived  │
                    │  SHA1(video_path|    │
                    │    source_lang|      │
                    │    track_id).srt     │
                    │  in CACHE_DIR        │
                    └──────────┬──────────┘
                               │
                    ┌──────────┴──────────┐
                    │  Cache exists +      │
                    │  non-empty +         │
                    │  force_reextract?    │
                    └──────────┬──────────┘
                    ┌──────────┴──────────┐     ┌──────────────────┐
                    │  YES (cache hit)    │     │  NO              │
                    └──────────┬──────────┘     │  (skip cache)    │
                               │                └────────┬─────────┘
                    ┌──────────┴──────────┐              │
                    │  read_valid_srt_file│              │
                    │  on cached file     │              │
                    └──────────┬──────────┘              │
                               │                         │
                    ┌──────────┴──────────┐              │
                    │  Cache valid?       │              │
                    └──────────┬──────────┘              │
                    ┌──────────┴──────────┐              │
                    │  YES ──▶ Return     │              │
                    │  ok=true + cached   │              │
                    │  content            │              │
                    └─────────────────────┘              │
                    ┌──────────┴──────────┐              │
                    │  NO ──▶ Return      │              │
                    │  ok=false + why     │              │
                    │  cache is unsafe    │              │
                    └─────────────────────┘              │
                                                         │
                                                         ▼
          ╔══════════════════════════════════════════════════════════════╗
          ║         ⬇️  SUBTITLE EXTRACTION                             ║
          ╚══════════════════════════════════════════════════════════════╝
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
   ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
   │  🎞️ MKV EXTRACT  │ │  🎞️ MP4 EXTRACT  │ │  ❌ ERROR        │
   │  ─────────────── │ │  ─────────────── │ │  ─────────────── │
   │  mkvextract      │ │  ffmpeg          │ │  Tool missing    │
   │  tracks <file>   │ │  -y -i <file>    │ │  Command failed  │
   │  <id>:<output>   │ │  -map 0:s:<idx>  │ │  Timed out       │
   │                  │ │  <output.srt>    │ │  No output file  │
   │  Output: SRT     │ │                  │ │                  │
   │  text subtitle   │ │  Output: may     │ │  Return ok=false │
   │  (direct from    │ │  need validation │ │  + message       │
   │  container)      │ │  as proper SRT   │ │                  │
   └────────┬─────────┘ └────────┬─────────┘ └────────┬─────────┘
            │                    │                     │
            └────────────────────┼─────────────────────┘
                                 ▼
                     ┌──────────────────────┐
                     │  Copy to cache       │
                     │  shutil.copy2(temp,   │
                     │  cache_path)         │
                     └──────────┬───────────┘
                                │
                                ▼
          ╔════════════════════╧══════════════════════════════════╗
          ║         🔎  TRANSLATION-SAFETY VALIDATION              ║
          ║         (read_valid_srt_file)                          ║
          ╚════════════════════════════════════════════════════════╝
                                │
                     ┌──────────┴──────────┐
                     │  ⚖️ Size check       │
                     │  File size > 0?     │
                     │  ≤ MAX_EXTRACTED_   │
                     │  SRT_BYTES (1 MB)?  │
                     └──────────┬──────────┘
                                │
                     ┌──────────┴──────────┐
                     │  🔬 Binary check    │
                     │  No null bytes in   │
                     │  first 4096 bytes   │
                     └──────────┬──────────┘
                                │
                     ┌──────────┴──────────┐
                     │  📖 Decode check    │
                     │  Try UTF-8-SIG →    │
                     │  UTF-16 → CP1252    │
                     │  Must decode as     │
                     │  readable text      │
                     └──────────┬──────────┘
                                │
                     ┌──────────┴──────────┐
                     │  🧹 Control char    │
                     │  ratio check        │
                     │  ≤ 20 or ≤ 1% of    │
                     │  total length       │
                     └──────────┬──────────┘
                                │
                     ┌──────────┴──────────┐
                     │  📝 SRT parse check │
                     │  parse_srt_blocks() │
                     │  Must have valid    │
                     │  timecodes + text   │
                     └──────────┬──────────┘
                                │
                     ┌──────────┴──────────┐
                     │  💬 Dialogue check  │
                     │  Text chars ≥ 20    │
                     │  unless total is    │
                     │  very short         │
                     └──────────┬──────────┘
                                │
                     ┌──────────┴──────────┐
                     │  All checks passed? │
                     └──────────┬──────────┘
                    ┌───────────┴───────────┐
                    │                       │
                    ▼                       ▼
          ┌──────────────────┐   ┌──────────────────┐
          │  ✅ VALID         │   │  ❌ INVALID       │
          │  Return ok=true   │   │  Return ok=false  │
          │  + srt_content    │   │  + validation     │
          │  + srt_path       │   │  error message    │
          │  + track info     │   │                   │
          └──────────────────┘   └──────────────────┘


╔══════════════════════════════════════════════════════════════════════════════════════════════════╗
║                          ENDPOINT RESPONSE SUMMARY                                              ║
╠══════════════════════════════════════════════════════════════════════════════════════════════════╣
║                                                                                                   ║
║  ┌───────────┬────────────────────────────────────────────────────────────────────────────────┐  ║
║  │ /probe    │ Returns: ok, found(bool), message, selected_track, all_tracks,                 │  ║
║  │           │ resolved_video_path, diagnostic_preview                                        │  ║
║  │           │ NEVER returns extracted_srt_content — probe only, no extraction               │  ║
║  ├───────────┼────────────────────────────────────────────────────────────────────────────────┤  ║
║  │ /extract  │ Returns: ok, message, method(cache|mkvextract|ffmpeg), cache_hit(bool),        │  ║
║  │           │ extracted_srt_path, extracted_srt_content, selected_track, all_tracks,         │  ║
║  │           │ resolved_video_path, diagnostic_preview                                        │  ║
║  │           │ ok=true ONLY after passing translation-safety validation                       │  ║
║  └───────────┴────────────────────────────────────────────────────────────────────────────────┘  ║
║                                                                                                   ║
╚══════════════════════════════════════════════════════════════════════════════════════════════════════╝


╔══════════════════════════════════════════════════════════════════════════════════════════════════╗
║                          TOOLS REQUIRED                                                         ║
╠══════════════════════════════════════════════════════════════════════════════════════════════════╣
║                                                                                                   ║
║  ┌──────────────┬────────────────────┬────────────────────────────────────────────────────────┐  ║
║  │ Format       │ Probe              │ Extract                                                │  ║
║  ├──────────────┼────────────────────┼────────────────────────────────────────────────────────┤  ║
║  │ MKV (.mkv)   │ mkvinfo            │ mkvinfo + mkvextract                                   │  ║
║  │ MP4 (.mp4)   │ ffprobe            │ ffprobe + ffmpeg                                       │  ║
║  └──────────────┴────────────────────┴────────────────────────────────────────────────────────┘  ║
║                                                                                                   ║
║  Container image includes: ffmpeg, mkvtoolnix (mkvinfo + mkvextract), ca-certificates            ║
║                                                                                                   ║
╚══════════════════════════════════════════════════════════════════════════════════════════════════════╝


╔══════════════════════════════════════════════════════════════════════════════════════════════════╗
║                          TERMINAL STATES LEGEND                                                  ║
╠══════════════════════════════════════════════════════════════════════════════════════════════════╣
║                                                                                                   ║
║  ✅ ok=true  — Probe found a track / Extract returned validated SRT content                      ║
║  ❌ ok=false — Various failure modes:                                                             ║
║     • Unsupported file format (not .mkv/.mp4)                                                     ║
║     • Required tool missing (mkvinfo/mkvextract/ffprobe/ffmpeg)                                   ║
║     • Command timed out                                                                            ║
║     • Command returned non-zero exit code                                                          ║
║     • No subtitle tracks found in file                                                             ║
║     • No matching language track found                                                             ║
║     • Extract produced empty/no output file                                                        ║
║     • Validation failed (binary/empty/malformed/oversized SRT)                                     ║
║     • Cached subtitle failed validation                                                            ║
║                                                                                                   ║
╚══════════════════════════════════════════════════════════════════════════════════════════════════════╝


╔══════════════════════════════════════════════════════════════════════════════════════════════════╗
║                     KEY DIFFERENCES: /probe vs /extract                                         ║
╠══════════════════════════════════════════════════════════════════════════════════════════════════╣
║                                                                                                   ║
║  ┌────────────┬─────────────────────────────────────┬──────────────────────────────────────────┐  ║
║  │ Aspect     │ /probe                              │ /extract                                 │  ║
║  ├────────────┼─────────────────────────────────────┼──────────────────────────────────────────┤  ║
║  │ Purpose    │ Check if RO subtitle exists         │ Extract EN subtitle for translation      │  ║
║  │ Track      │ All subtitle types (text+image)     │ MKV: direct SRT only (no PGS/VobSub)    │  ║
║  │ filter     │                                     │ MP4: text subs only                      │  ║
║  │ Unlabeled  │ ❌ Strict — no unlabeled fallback   │ ✅ Allows unlabeled track fallback       │  ║
║  │ fallback   │                                     │                                          │  ║
║  │ Caching    │ ❌ No cache involved                │ ✅ Cache checked and updated             │  ║
║  │ Output     │ Track metadata only                 │ Full SRT file content + path             │  ║
║  │ Validation │ None needed                         │ Full translation-safety validation       │  ║
║  │ Cost       │ Free (fast, no extraction)          │ More expensive (extraction + validation) │  ║
║  └────────────┴─────────────────────────────────────┴──────────────────────────────────────────┘  ║
║                                                                                                   ║
╚══════════════════════════════════════════════════════════════════════════════════════════════════════╝
```
