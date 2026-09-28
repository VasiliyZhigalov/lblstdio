import assert from "node:assert/strict";
import test from "node:test";

import { createAnnotationHistory } from "./annotationHistory.js";

const box = (id, x = 0.5) => ({
  id,
  class_id: "cls",
  x_center: x,
  y_center: 0.5,
  width: 0.2,
  height: 0.2,
});

test("undo restores the previous boxes and redo puts the edit back", () => {
  const history = createAnnotationHistory();
  const before = [box("a")];
  const after = [box("a"), box("b")];

  assert.equal(history.commit(before, after), true);
  assert.deepEqual(history.undo(after), before);
  assert.deepEqual(history.redo(before), after);
});

test("an unchanged edit is not an undo step", () => {
  const history = createAnnotationHistory();
  const boxes = [box("a")];

  assert.equal(history.commit(boxes, boxes.map((item) => ({ ...item }))), false);
  assert.equal(history.undo(boxes), null);
});

test("a drag gesture collapses into one undo step", () => {
  const history = createAnnotationHistory();
  const start = [box("a", 0.2)];
  history.beginGesture(start);
  history.beginGesture([box("a", 0.4)]);
  assert.equal(history.endGesture([box("a", 0.8)]), true);

  assert.deepEqual(history.undo([box("a", 0.8)]), start);
  assert.equal(history.undo(start), null);
});

test("a new edit clears the redo stack", () => {
  const history = createAnnotationHistory();
  const first = [box("a")];
  const second = [box("a"), box("b")];
  const third = [box("b")];

  history.commit(first, second);
  history.undo(second);
  history.commit(first, third);

  assert.equal(history.redo(third), null);
  assert.deepEqual(history.undo(third), first);
});
