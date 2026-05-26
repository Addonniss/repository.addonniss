# Translation Confirmation UX

## Goal

Add an optional playback overlay that lets the user explicitly approve subtitle translation before Translatarr starts translating a detected source subtitle.

This is meant to prevent wasted translation time and provider cost when the currently loaded subtitle is out of sync and the user wants to try a different subtitle first.

## Agreed UX Direction

- Setting name: `Require translation confirmation`
- Setting default: `true`
- Setting placement:
  - `Mode` category
  - directly after `Enable Translation Service`
- Applies to:
  - `Auto` mode
  - `Manual` mode
  - embedded source subtitle extraction results
- Does **not** apply to:
  - existing target-language subtitle detection
  - target-language embedded subtitle skip logic
- UI style:
  - same playback-overlay pattern as `service.nextonlibrary`
  - not a blocking yes/no dialog
  - not a timed notification
- Overlay action:
  - `Translate`: approve and start translation
  - `Remind in Ns`: hide the prompt temporarily and remind later
  - `Skip`: suppress this subtitle candidate for the current playback session
- Dismiss behavior:
  - Back, navigation, seeking, or closing the overlay behave like the reminder action
  - only explicit `Skip` rejects the current subtitle candidate
  - playback stop/end clears the current playback state
- Overlay lifetime:
  - no timeout
  - stays visible until user explicitly acts or dismisses it
- Overlay placement:
  - top right corner
  - should not interfere with lower subtitle display

## Core Product Rules

### 1. Confirmation is only for source subtitles

If Translatarr detects a usable target subtitle, current logic still wins:

- no confirmation overlay
- no source translation

This applies to:
- sidecar target subtitles
- already translated subtitles
- embedded target-language subtitles found locally or through remote probe

### 2. Skip suppresses only the current candidate

If the user presses `Skip`:

- do not translate that exact subtitle candidate immediately
- do not keep re-showing the overlay on every poll
- but also do not permanently suppress that candidate just because focus was lost or the overlay was dismissed unintentionally
- do show the overlay again automatically when a different subtitle is loaded/detected

This avoids hard-blocking the session if the user dismisses the overlay accidentally or changes their mind later by loading another subtitle.

If the user presses the reminder button, Back, navigation, or seeking:

- hide the overlay temporarily
- keep the current subtitle candidate pending
- show the prompt again after the configured reminder delay

### 3. Approval is one-time per candidate

If the user presses `Translate`:

- approve only that current candidate
- run the normal translation flow once
- if a different subtitle later appears, it is treated as a new candidate and requires confirmation again

### 4. Embedded extraction should keep the current flow

Embedded subtitle extraction should remain on the current direct flow.

Reason:

- embedded extraction is already an intentional user-driven path
- if the user triggered embedded extraction, the assumption is that the subtitle situation is already understood and this is not the same trial-and-error sync problem as external downloaded subtitles
- adding a second confirmation step here would add friction without solving the main user problem

So:

- embedded source extraction should continue normally without confirmation UI
- embedded target-language skip behavior remains unchanged
- greenlight/confirmation applies only to the normal detected external source-subtitle flow

## Important Behavior Assumption

The confirmation should be tied to the subtitle candidate that Translatarr is preparing to translate, and that subtitle should also be the one currently shown to the user whenever possible.

Why this matters:

- users are approving based on sync quality
- approval is only meaningful if the visible subtitle is the same subtitle candidate Translatarr would translate

## Focus / Input Notes

Using the `service.nextonlibrary` overlay pattern likely means the overlay button will take focus while it is visible.

This is acceptable for the first implementation because:

- the user explicitly needs an action target during playback
- the overlay is non-blocking compared with a modal dialog
- accidental dismissal can be treated as "remind me later"

Still, this creates some UX caveats:

- remote-control navigation may move focus to the overlay immediately
- some users may press navigation/back/select unintentionally
- accidental input must be safe and non-destructive

That is why we keep the behavior simple:

- default focus is the reminder action
- only explicit `Skip` rejects a candidate
- new candidate can open the overlay later

## Candidate Identity

To avoid repeated overlay spam, candidate identity should be tracked per playback session using at least:

- subtitle path
- subtitle mtime
- subtitle size

Optional extra guard:

- content hash if needed later

For the first implementation, path + mtime + size should be enough.

## Candidate State Model

Recommended per-playback candidate states:

- `none`
  - no pending source candidate
- `pending`
  - source candidate detected
  - overlay visible or eligible to be visible
- `dismissed`
  - user explicitly skipped this candidate
  - do not immediately re-show on the next poll
  - suppress it for the rest of the current playback session
  - but do not permanently block the same candidate across future playback sessions
- `approved`
  - user pressed translate
  - run normal translation flow
- `translated`
  - translation completed for this candidate

State resets when:

- playback stops/ends
- a different source subtitle candidate appears
- the active media item changes

### Dismissal refinement

Because overlay focus can be lost unintentionally, accidental dismissal should not become `dismissed`.

Recommended behavior:

- The reminder action, Back, and navigation hide the overlay for now
- the candidate is not translated automatically
- the candidate remains pending
- the overlay can be shown again after the configured reminder delay
- `Skip` suppresses the candidate for the current playback session

For the first implementation, the important rule is:

- do not suppress a candidate just because the overlay was dismissed once
- do not re-show before the configured reminder delay

Session rule summary:

- same candidate + same playback session + reminded:
  - re-show after reminder delay
- same candidate + same playback session + skipped:
  - do not re-show
- different candidate + same playback session:
  - may show
- same or different candidate + new playback session:
  - may show again

## Proposed Service Flow

### Auto Mode

Current flow:

- detect source subtitle
- if target does not already cover it, translate immediately

New flow with confirmation enabled:

- detect source subtitle
- load/show it if needed
- if target already exists, stop as today
- if source candidate is new:
  - register pending candidate
  - show confirmation overlay
- only call `process_subtitles(...)` after user approval

### Manual Mode

Current flow:

- detect newest usable source subtitle
- translate immediately if target does not already cover it

New flow with confirmation enabled:

- detect newest usable source subtitle
- if target already exists, stop as today
- if source candidate is new:
  - register pending candidate
  - show confirmation overlay
- only call `process_subtitles(...)` after user approval

### Embedded Extraction

Current flow:

- extract source subtitle
- recurse back into normal auto/manual detection flow

Desired behavior:

- keep the current direct path
- do not introduce a confirmation overlay for embedded extraction
- keep embedded target skip logic exactly as it is now

This keeps the UX focused on the real problem:

- external downloaded/loaded subtitles may be out of sync and need user validation
- embedded extraction is a more intentional path and should not gain extra confirmation friction

## Implementation Shape

## Implementation Status

- [x] Phase 1: Settings and strings
- [x] Phase 2: Overlay infrastructure
- [x] Phase 3: Playback candidate state
- [x] Phase 4: Auto/Manual gate
- [x] Phase 5: Approval action
- [ ] Phase 6: Embedded-source validation

### New Setting

Add a boolean setting:

- id: `require_translation_confirmation`
- label: `Require translation confirmation`
- default: `true`
- placement:
  - `Mode` category
  - immediately after `Enable Translation Service`

### Overlay Window

Use the same structural pattern as `service.nextonlibrary`:

- `xbmcgui.WindowXMLDialog`
- dedicated skin XML in `resources/skins/default/1080i/`
- one primary action button
- optional close/dismiss control

Recommended new assets:

- `service.translatarr/resources/skins/default/1080i/script-translatarr-confirmation-overlay.xml`
- maybe a fallback XML only if really needed later

### Likely Runtime Placement

Most of the logic belongs in [service.py](c:/Users/angel/repository.addonniss/service.translatarr/service.py):

- candidate tracking state
- show/hide overlay
- approval/dismiss handlers
- interception before `process_subtitles(...)`

Possible UI helper functions can live in [ui.py](c:/Users/angel/repository.addonniss/service.translatarr/ui.py), but the overlay/service coordination will likely still need to stay near the service state machine.

## Recommended File-Level Roadmap

### Phase 1: Settings and strings

- add `require_translation_confirmation` to `resources/settings.xml`
- add matching text to `resources/language/resource.language.en_gb/strings.po`

### Phase 2: Overlay infrastructure

- add a Translatarr overlay dialog class in `service.py` or `ui.py`
- create overlay XML skin file modeled after `service.nextonlibrary`
- place button top-right

### Phase 3: Playback candidate state

- add pending/dismissed/approved candidate state to the monitor/service object
- reset it cleanly on playback stop/end/media change

### Phase 4: Auto/Manual gate

- intercept translation start in:
  - `check_auto_mode_unified()`
  - `check_manual_mode()`
- if confirmation disabled:
  - keep current behavior
- if confirmation enabled:
  - register/show overlay instead of immediate translation

### Phase 5: Approval action

- when user presses `Translate`:
  - mark candidate approved
  - call existing translation path for that candidate
- when user presses the reminder action or dismisses:
  - keep candidate pending
  - set reminder delay before re-showing
- when user presses `Skip`:
  - mark candidate dismissed

### Phase 6: Embedded-source validation

- verify embedded-source extraction still follows the current direct flow
- verify no confirmation overlay appears for embedded extraction
- verify target-language embedded skip still bypasses confirmation

## Acceptance Criteria

The feature is done when:

1. With `Require translation confirmation = false`
   - current Auto/Manual behavior remains unchanged

2. With `Require translation confirmation = true`
   - detected source subtitle does not translate immediately
   - top-right overlay appears
   - pressing `Translate` starts normal translation
   - pressing the reminder action or Back hides the prompt temporarily and reminds later
   - pressing `Skip` suppresses that candidate for the current playback session
   - loading/detecting a different subtitle shows the overlay again

3. If target subtitle already exists
   - no confirmation overlay appears
   - current skip logic still wins

4. If embedded source subtitle is extracted
   - it follows the current direct flow without confirmation UI

5. Overlay does not cover the lower subtitle display

## Main Risks

- repeated overlay spam if candidate identity is not tracked carefully
- mismatch between the visible subtitle and the subtitle candidate Translatarr is about to translate
- focus behavior during playback
- subtitle add-ons rewriting temp files and accidentally producing false "new candidate" events
- forgetting to clear pending state on playback stop/end

## Out of Scope for First Implementation

- timed auto-dismiss
- persistent approval across playback sessions
- translating arbitrary currently loaded subtitles unrelated to Translatarr's detected candidate model

## Final Recommendation

Proceed with the overlay-first implementation.

It is the right UX for this problem, it matches the established `service.nextonlibrary` playback-helper pattern, and it avoids the major usability problem of a blocking confirmation dialog that prevents the user from judging subtitle sync before spending translation time or money.
