# Labeling page: default bbox tool, edit-in-draw, fill opacity

**Date:** 2026-09-15  
**Status:** approved (conversation); awaiting written-spec sign-off  
**Scope:** frontend labeling canvas / toolbar only

## Problem

1. Annotate page defaults to the select (arrow) tool. Resizing a bbox requires switching to select; draw mode ignores resize handles.
2. The **ОП** fill-opacity control does not visibly change fills: selected/hovered boxes use a hardcoded alpha (`"4D"`), so the slider appears broken.

## Goals

- Default tool on the labeling page is **bbox / DRAW**.
- In DRAW mode, users can select, move, and resize existing boxes without switching to SELECT; new boxes are drawn only on empty canvas.
- **ОП** slider controls fill opacity for all boxes (including selected/hovered).

## Non-goals

- Changing hotkeys (V / W remain SELECT / DRAW).
- Removing the SELECT tool.
- Persisting opacity across sessions.
- Backend / API changes.

## Behavior

### Default mode

- Initial `store.mode` is `"DRAW"`.
- Boot calls `setMode("DRAW")`.
- Toolbar: `tool-draw` starts in the active style; `tool-select` idle.

### Pointer handling (DRAW and SELECT)

Shared priority on left-click (after pan via middle mouse / Space+drag):

1. Hit resize handle of the **currently selected** box → start resize.
2. Hit interior of any visible box → select that box and start move.
3. Otherwise:
   - **DRAW:** start drawing a new box (existing class / need-class flow unchanged).
   - **SELECT:** clear selection (`selectedBoxId = null`).

Hover cursor:

- On handle → resize cursor for that handle.
- On box → `move` (selected) or `pointer`.
- Else in DRAW → `crosshair`; in SELECT → `default`.

### Fill opacity (ОП)

- Slider continues to write `store.boxOpacity` (range `0`–`0.5`, step `0.05`, default `0.2`).
- `drawBox` always derives fill alpha from `boxOpacity` via `hexAlphaFromFloat`.
- Selected or hovered boxes use a slight boost: `min(1, boxOpacity + 0.15)`, not a fixed `"4D"`.
- Stroke and labels unchanged.

## Approach

**Unified hit-pipeline before mode branch** in `AnnotationCanvas` (recommended). No new tool mode.

## Files to change

| File | Change |
|------|--------|
| `frontend/js/store.js` | Default `mode: "DRAW"` |
| `frontend/js/app.js` | Boot `setMode("DRAW")` |
| `frontend/index.html` | Initial active class on `tool-draw` |
| `frontend/js/components/canvas.js` | Hit order in `onMouseDown` / `updateHoverCursor`; opacity in `drawBox` |

## Testing

Manual on annotate tab:

1. Open project → annotate: DRAW active, crosshair on empty canvas.
2. Draw a box → selected with handles → drag handle without switching tool.
3. Click another box → selects/moves; empty area starts a new draw.
4. Switch to SELECT (V): empty click clears selection; no new draw.
5. Move **ОП** slider: fill of all boxes (including selected) changes.

## Out of scope follow-ups

- Persist `boxOpacity` in localStorage.
- Resize handles on hover without selection.
