# Rapid Reader 1.0 — SH1106 overhaul: phase prompts (historical)

**Status: overhaul landed.** The tree now runs the SH1106 OLED HAT
single-screen app (`oled.py`, screen stack, themes, state v2). For
current behavior, hardware, and controls, use the root
[README.md](../../README.md) and [CONTROLS.md](../../CONTROLS.md) — not
the per-phase status lines inside the briefs below.

This directory keeps the detailed, self-contained brief for each phase
of the SH1106 port/rewrite. Each `phase-*.md` was written to be handed
directly to a coding agent as its task prompt. They remain useful as
design history and interface rationale, but they are **not** a live
roadmap: many files still say "not started" or refer to deleting
`lcd.py` even though that work is done.

Phase 0–3 work is reflected in the current codebase and living docs.
[phase-4-bringup-checklist.md](phase-4-bringup-checklist.md) remains a
human hardware checklist (orientation, real-panel timing, SIGTERM on
device) and is not an agent coding task.

## Which phases got a nimble-agent prompt?

"Nimble" here means a small/fast/cheap model given a single, narrow,
well-specified task with little room to improvise. That works well when
the task is mechanical or algorithmic and the interfaces it must honour
are pinned down in advance. It works badly when the task requires making
a lot of unstated design judgment calls or touches many interacting
pieces of state at once.

| Phase | Nimble-agent prompt? | Why |
|---|---|---|
| 0 — Contracts | **Yes** — [`phase-0-contracts.md`](phase-0-contracts.md) | Small in code volume, but everything else depends on it. The prompt below pins every dataclass field, constant and function signature explicitly, so there is nothing left to "design" — just transcribe the spec into `config.py`/`theme.py`/`state.py`/`screens.py` skeletons. |
| 1A — Driver (`oled.py`) | **Yes** — [`phase-1a-driver.md`](phase-1a-driver.md) | Pure algorithm + a fixed command sequence from the datasheet. Self-contained, easy to unit test bit-for-bit. |
| 1B — Input (`buttons.py`) | **Yes** — [`phase-1b-input.md`](phase-1b-input.md) | Extends the existing tap/hold timer pattern to 8 keys with a repeat mode. Self-contained, mechanical, existing tests show the shape. |
| 1C — Render/Theme (`theme.py`, `render.py`) | **Yes, but the most detailed prompt of the six** — [`phase-1c-render-theme.md`](phase-1c-render-theme.md) | Highest creative surface area (many frames, 5 theme presets, 4 pivot styles). Given pixel-level layout numbers and exact palette/preset tables up front, a nimble agent can execute it faithfully; without that level of detail it would have to invent a look-and-feel, which is exactly what we want to avoid delegating. |
| 1D — Model (`state.py`, `rsvp.py`, `books.py` additions) | **Yes** — [`phase-1d-model.md`](phase-1d-model.md) | Schema + migration + a couple of pure functions. Self-contained, testable in isolation from hardware and UI. |
| 2 — App (`screens.py`, `main.py`) | **Conditional — write the prompt, but run it on a stronger model, or split it further** — [`phase-2-app.md`](phase-2-app.md) | This is the integration phase: ~13 screens, a navigation stack, idle/dim/off/wake, power/reboot, and every Phase-1 contract used at once. That's exactly the kind of task where a nimble agent tends to silently violate one of the contracts under time/context pressure. The prompt is written so it *can* be run nimbly per-screen-group if needed (see the "sub-tasking" note inside it), but the recommendation is a more capable agent for the full integration pass. |
| 3 — Tooling/docs | **Yes** — [`phase-3-tooling-docs.md`](phase-3-tooling-docs.md) | Config-file/text edits with a clear diff target (old pin table → new pin table). Low risk if wrong, easy to review. |
| 4 — Bring-up | **No — not an agent task at all** — [`phase-4-bringup-checklist.md`](phase-4-bringup-checklist.md) | Requires physical hardware in hand (orientation, timing on the real panel, SIGTERM on the real service). Written as a human checklist, not a coding-agent prompt. |

## Recommended execution order (as originally planned)

1. Phase 0 alone first — it is a hard dependency for everything else and is
   small enough to review completely before fanning out.
2. Phases 1A, 1B, 1C, 1D in parallel (four separate nimble-agent runs), each
   against the Phase 0 contracts.
3. Phase 3 in parallel with step 2 (touches unrelated files).
4. Phase 2 once all of Phase 1 has landed and its tests pass.
5. Phase 4 manually on the device.

## Carried-over open items

- Default orientation and the SH1106 column offset are stated as "2" below
  based on the standard module; both are single config flags
  (`config.ROTATE_180`, `config.OLED_COL_OFFSET`) confirmed in Phase 4.
- These phase docs are the durable replacement for the "detailed phase
  briefs" mentioned in the original plan session, which only ever existed
  in that session's memory and were lost — writing them to the repo is
  exactly the mitigation the original plan recommended.
