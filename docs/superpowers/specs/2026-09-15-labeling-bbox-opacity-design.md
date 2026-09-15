# Labeling page: default bbox tool, draw priority, fill opacity

**Date:** 2026-09-15  
**Status:** approved (conversation); updated for serial labeling UX  
**Scope:** frontend labeling canvas / toolbar only

## Problem

1. Annotate page defaults to the select (arrow) tool. Resizing a bbox requires switching to select; draw mode ignores resize handles.
2. The **ОП** fill-opacity control does not visibly change fills: selected/hovered boxes use a hardcoded alpha (`"4D"`), so the slider appears broken.
3. Class popover on every `box-drawn` blocks serial multi-box labeling.
4. DRAW hit-tests existing boxes first, so nested boxes cannot be drawn inside larger ones.
5. System crosshair alone is hard to align to opposite edges of a part.

## Goals

- Default tool on the labeling page is **bbox / DRAW**.
- In **DRAW**, left-click always starts a new box (even over existing boxes). Move/resize only in **SELECT** (`V`) or with **Alt** held in DRAW.
- Class popover opens only on demand (`C` / right-click) when the project has 2+ classes — never on `box-drawn`.
- DRAW shows full-viewport crosshair guides under the cursor.
- **ОП** slider controls fill opacity for all boxes (including selected/hovered).

## Non-goals

- Changing hotkeys (V / W remain SELECT / DRAW; plain `C` opens class popover).
- Removing the SELECT tool.
- Persisting opacity across sessions.
- Backend / API changes.

## Behavior

### Default mode

- Initial `store.mode` is `"DRAW"`.
- Boot calls `setMode("DRAW")`.
- Toolbar: `tool-draw` starts in the active style; `tool-select` idle.

### Pointer handling

Shared priority on left-click (after pan via middle mouse / Space+drag):

1. If **SELECT** or **Alt+DRAW**: hit resize handle of the currently selected box → start resize.
2. If **SELECT** or **Alt+DRAW**: hit interior of any visible box → select and start move.
3. Otherwise:
   - **DRAW:** start drawing a new box (active class / need-class flow).
   - **SELECT:** clear selection (`selectedBoxId = null`).

Hover cursor:

- In DRAW without Alt → always `crosshair` (guides also drawn).
- On handle (SELECT / Alt+DRAW) → resize cursor for that handle.
- On box (SELECT / Alt+DRAW) → `move` / `pointer`.
- Else in SELECT → `default`.

### Class popover

- Never open when `classes.length <= 1`.
- With 2+ classes: open on plain `C` (selected box) or right-click on a box.
- Do **not** open on `box-drawn`; new boxes keep `activeClassId`.

### Fill opacity (ОП)

- Slider continues to write `store.boxOpacity` (range `0`–`0.5`, step `0.05`, default `0.2`).
- `drawBox` always derives fill alpha from `boxOpacity` via `hexAlphaFromFloat`.
- Selected or hovered boxes use a slight boost: `min(1, boxOpacity + 0.15)`, not a fixed `"4D"`.
- Stroke and labels unchanged.

## Approach

**Mode-aware hit-pipeline** in `AnnotationCanvas`: DRAW prefers draw-through; SELECT/Alt keep manipulate. Crosshair guides rendered in DRAW. Popover gated in `app.js` / `hotkeys.js`.

## Files to change

| File | Change |
|------|--------|
| `frontend/js/store.js` | Default `mode: "DRAW"` |
| `frontend/js/app.js` | Boot `setMode("DRAW")`; popover on demand |
| `frontend/index.html` | Initial active class on `tool-draw` |
| `frontend/js/components/canvas.js` | DRAW priority, Alt manipulate, crosshair guides, RMB popover event |
| `frontend/js/hotkeys.js` | Plain `C` → open class popover |

## Testing

Manual on annotate tab:

1. Open project → annotate: DRAW active, crosshair guides follow pointer.
2. Draw several boxes with one active class → no popover; boxes keep that class.
3. With 2+ classes: `C` or right-click opens popover; digits reassign.
4. Click inside a large box in DRAW → starts a nested box; Alt+click moves the large box.
5. Switch to SELECT (V): empty click clears selection; no new draw.
6. Move **ОП** slider: fill of all boxes (including selected) changes.

## Out of scope follow-ups

- Persist `boxOpacity` in localStorage.
- Resize handles on hover without selection.
