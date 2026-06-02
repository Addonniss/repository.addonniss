# Translatarr Decision Service — Flowchart

```
╔══════════════════════════════════════════════════════════════════════════════════╗
║                     TRANSLATARR DECISION SERVICE — FULL PIPELINE                ║
╚══════════════════════════════════════════════════════════════════════════════════╝

                               ┌─────────────┐     ┌─────────────┐
                               │   📡 Radarr  │     │   📡 Sonarr │
                               │ POST /radarr │     │ POST /sonarr│
                               └──────┬──────┘     └──────┬──────┘
                                      │                   │
                                      ▼                   ▼
                          ┌─────────────────────────────────────┐
              ┌───────────│     🔐 TOKEN AUTHENTICATION         │──────────┐
              │           │  Bearer / X-Decision-Token / ?token │          │
              │           └────────────────┬────────────────────┘          │
              │                            │                               │
              ▼                            ▼                               ▼
   ┌────────────────────┐      ┌──────────────────────┐      ┌──────────────────┐
   │   📄 Parse Payload │─────▶│  eventType = Test?   │─────▶│  No media_path?  │
   └────────────────────┘      └──────────┬───────────┘      └────────┬─────────┘
                                          │                          │
                              ┌───────────┴───────────┐              │
                              │        YES (both)     │◀─────────────┘
                              ▼                       
                    ┌─────────────────────┐
                    │  ✅ No‑op Accept    │
                    │  No job created     │
                    └─────────────────────┘
                              │
                              │ NO
                              ▼
                    ┌─────────────────────┐      YES
                    │  Duplicate Check    │─────────▶ ┌─────────────────────┐
                    │  Active job exists? │           │  Return existing    │
                    └──────────┬──────────┘           │  job_id + status    │
                               │ NO                   └─────────────────────┘
                               ▼
                    ┌─────────────────────┐
                    │  📝 Create Job      │
                    │  status = 'queued'  │
                    │  asyncio task spun  │
                    └──────────┬──────────┘
                               │
                     ╔════════╧══════════════════════════════════════════════════╗
                     ║         🔄 BACKGROUND DECISION PIPELINE                  ║
                     ╚══════════════════════════════════════════════════════════╝
                               │
                    ┌──────────┴──────────┐
                    │  ⏳ DELAY 600s      │ ◀── Lets Bazarr search Romanian first
                    │  (DECISION_DELAY)   │
                    └──────────┬──────────┘
                               │
                    ┌──────────┴──────────┐
                    │  🗺️ PATH MAPPING    │
                    │  apply MEDIA_PATH_  │
                    │  MAPS (host→ctnr)   │
                    └──────────┬──────────┘
                               │
                    ┌──────────┴──────────┐
                    │  Supported ext?     │──── NO ──▶ ⏭️ Skipped: unsupported ext
                    │  .mkv/.mp4/.m4v     │
                    └──────────┬──────────┘
                               │ YES
                               ▼
                    ┌──────────┴──────────┐
                    │  File exists in     │──── NO ──▶ ❌ Failed: file not found
                    │  container?         │
                    └──────────┬──────────┘
                               │ YES
                               ▼
          ╔════════════════════╧══════════════════════════════════╗
          ║           🆓  ZERO-COST CHECKS (Phase 1)             ║
          ╚═══════════════════════════════════════════════════════╝
                               │
                    ┌──────────┴──────────┐
                    │  📁 Sidecar scan    │
                    │  glob *.srt near    │
                    │  media file         │
                    │  Token match: ro/   │
                    │  ron/rum/romanian   │
                    └──────────┬──────────┘
                               │
                    ┌──────────┴──────────┐
                    │  .ro.srt found?     │──── YES ──▶ 🛑 COMPLETED
                    └──────────┬──────────┘              Sidecar exists
                               │ NO                      No cost incurred
                               ▼
                    ┌──────────┴──────────┐
                    │  🔍 Probe embedded  │
                    │  POST /probe → ext  │
                    │  Language: Romanian │
                    │  prefer_non_sdh: T  │
                    └──────────┬──────────┘
                               │
                    ┌──────────┴──────────┐
                    │  Embedded RO track  │──── YES ──▶ 🛑 COMPLETED
                    │  found?             │              Embedded RO exists
                    └──────────┬──────────┘              No cost incurred
                               │ NO
                               ▼
          ╔════════════════════╧══════════════════════════════════╗
          ║        ⬇️  SOURCE EXTRACTION (Phase 2)               ║
          ╚═══════════════════════════════════════════════════════╝
                               │
                    ┌──────────┴──────────┐
                    │  Extract embedded   │
                    │  English subtitles  │
                    │  POST /extract → ext│
                    │  source_lang: EN    │
                    │  timeout: 900s      │
                    └──────────┬──────────┘
                               │
                    ┌──────────┴──────────┐
                    │  ok=true & content  │──── NO ──▶ ℹ️ NO SOURCE
                    │  present?           │              No embedded EN found
                    └──────────┬──────────┘
                               │ YES
                               ▼
                    ┌──────────┴──────────┐
                    │  🔎 SRT VALIDATION  │
                    │  ─────────────────  │
                    │  ✓ Not empty?       │
                    │  ✓ Size ≤ 1 MB?     │
                    │  ✓ No null bytes?   │
                    │  ✓ Control chars OK?│
                    │  ✓ Valid SRT parse? │
                    │  ✓ Has dialogue?    │
                    └──────────┬──────────┘
                               │
                    ┌──────────┴──────────┐
                    │  Source SRT valid?  │──── NO ──▶ ℹ️ NO SOURCE
                    └──────────┬──────────┘              Unusable content
                               │ YES
                               ▼
                    ┌──────────┴──────────┐
                    │  SAVE_SOURCE_SUBTITLE?                │
                    └──────────┬──────────┘
                    ┌──────────┴──────────┐     ┌──────────────────┐
                    │  YES                │     │  NO             │
                    │  💾 Write .en.srt   │     │  Skip source    │
                    │  Atomic + fsync     │     │  save           │
                    └──────────┬──────────┘     └────────┬─────────┘
                               │                         │
                               └──────────┬──────────────┘
                                          ▼
                    ┌──────────────────────┐
                    │  Recheck sidecar     │
                    │  (race condition)    │
                    │  .ro.srt appeared    │
                    │  during extraction?  │
                    └──────────┬──────────┘
                               │
                    ┌──────────┴──────────┐
                    │  Sidecar now exists?│──── YES ──▶ 🛑 COMPLETED
                    └──────────┬──────────┘              Race win (Bazarr)
                               │ NO
                               ▼
          ╔════════════════════╧══════════════════════════════════╗
          ║       🌐  TRANSLATION ENGINE (Phase 3 — Paid)        ║
          ╚═══════════════════════════════════════════════════════╝
                               │
                    ┌──────────┴──────────┐
                    │  Split SRT into     │
                    │  text chunks        │
                    │  Collapse [BR]→\n   │
                    └──────────┬──────────┘
                               │
                    ┌──────────┴──────────┐
                    │  BATCH + RETRY LOOP │
                    │  ─────────────────  │
                    │  Try BATCH_SIZE(100)│
                    │  Fallback: 50       │
                    │  Fallback: 25       │
                    │  3 retries per chunk│
                    │  1s delay between   │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
   ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
   │  🤖 GEMINI       │ │  📖 LIBRETRANSLATE│ │  ❌ NONE         │
   │  ─────────────── │ │  ─────────────── │ │  ─────────────── │
   │  Lxxx: prefix    │ │  POST /translate │ │  Dry-run mode    │
   │  Style prompt    │ │  Batch array     │ │  Always fails    │
   │  Cost tracking   │ │  Char-based bill │ │  if translation  │
   │  Fast mode opt   │ │  No style ctrl   │ │  needed          │
   └────────┬─────────┘ └────────┬─────────┘ └────────┬─────────┘
            └────────────────────┼────────────────────┘
                                 ▼
                    ┌────────────────────────┐
                    │  Scrub Lxxx: prefix    │
                    │  Replace [BR] → \n     │
                    │  Render SRT blocks     │
                    │  with indices          │
                    └───────────┬────────────┘
                                │
          ╔════════════════════╧══════════════════════════════════╗
          ║           💾  SIDECAR OUTPUT (Phase 4)                ║
          ╚═══════════════════════════════════════════════════════╝
                                │
                    ┌───────────┴────────────┐
                    │  Write .ro.srt          │
                    │  ────────────────────  │
                    │  1. mkstemp()           │
                    │  2. Write + fsync       │
                    │  3. os.replace (atomic) │
                    │  4. fsync file handle   │
                    │  5. chmod 0444 (if opt) │
                    │  6. Verify exists+size  │
                    └───────────┬────────────┘
                                │
                    ┌───────────┴────────────┐
                    │  ✅ COMPLETED           │
                    │  Translated .ro.srt    │
                    │  saved & protected     │
                    └────────────────────────┘


╔══════════════════════════════════════════════════════════════════════════════════╗
║                       📢 DISCORD NOTIFICATIONS                                  ║
║  Every step fires a color-coded embed to DISCORD_WEBHOOK_URL                    ║
║  ─────────────────────────────────────────────────────────────────────────────  ║
║  Queued (blue) → Checking (blue) → Probing (blue) → Extracting (blue)          ║
║  → Translating (blue) → Translated (green) / Stopped (green) / Failed (red)    ║
╚══════════════════════════════════════════════════════════════════════════════════╝


╔══════════════════════════════════════════════════════════════════════════════════╗
║                            TERMINAL STATES LEGEND                                ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║  🛑 COMPLETED (green) — Sidecar existed or appeared — no cost                   ║
║  🛑 COMPLETED (green) — Embedded RO found — no cost                             ║
║  ℹ️  NO SOURCE (yellow) — No embedded EN or invalid content                     ║
║  ✅ COMPLETED (green) — Translated .ro.srt written successfully                 ║
║  ❌ FAILED (red) — File missing, translation error, etc.                        ║
║  ⏭️ SKIPPED (gray) — Unsupported media extension                                ║
╚══════════════════════════════════════════════════════════════════════════════════╝
```
