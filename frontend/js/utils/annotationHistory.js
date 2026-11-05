function copyBoxes(boxes) {
  return (boxes || []).map((box) => ({ ...box }));
}

function sameBoxes(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function createAnnotationHistory(limit = 100) {
  const past = [];
  const future = [];
  let gestureBefore = null;

  return {
    beginGesture(boxes) {
      if (gestureBefore == null) gestureBefore = copyBoxes(boxes);
    },

    endGesture(boxes) {
      if (gestureBefore == null) return false;
      const before = gestureBefore;
      gestureBefore = null;
      return this.commit(before, boxes);
    },

    commit(before, after) {
      const prev = copyBoxes(before);
      const next = copyBoxes(after);
      if (sameBoxes(prev, next)) return false;
      past.push(prev);
      if (past.length > limit) past.shift();
      future.length = 0;
      return true;
    },

    undo(current) {
      if (!past.length) return null;
      future.push(copyBoxes(current));
      return past.pop();
    },

    redo(current) {
      if (!future.length) return null;
      past.push(copyBoxes(current));
      return future.pop();
    },

    reset() {
      past.length = 0;
      future.length = 0;
      gestureBefore = null;
    },
  };
}
