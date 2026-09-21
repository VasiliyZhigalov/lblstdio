import assert from "node:assert/strict";
import test from "node:test";

import { firstReviewImage } from "./activeLearning.js";

test("firstReviewImage returns the first review frame in queue order", () => {
  const images = [
    { id: "raw-1", status: "UNANNOTATED" },
    { id: "review-1", status: "REQUIRES_REVIEW" },
    { id: "review-2", status: "REQUIRES_REVIEW" },
  ];

  assert.deepEqual(firstReviewImage(images), images[1]);
});

test("firstReviewImage returns null when the review queue is empty", () => {
  assert.equal(
    firstReviewImage([{ id: "verified", status: "VERIFIED" }]),
    null
  );
});
