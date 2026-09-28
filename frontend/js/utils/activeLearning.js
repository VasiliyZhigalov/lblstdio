export function firstReviewImage(images) {
  return (images || []).find((image) => image.status === "REQUIRES_REVIEW") || null;
}

function uncertaintyScore(image) {
  const value = image?.min_model_confidence;
  if (value == null || Number.isNaN(Number(value))) return null;
  return Number(value);
}

/** Least confident model frames first. Frames without a model score stay in place, after scored ones. */
export function sortByModelUncertainty(images) {
  return [...(images || [])].sort((left, right) => {
    const a = uncertaintyScore(left);
    const b = uncertaintyScore(right);
    if (a == null && b == null) return 0;
    if (a == null) return 1;
    if (b == null) return -1;
    return a - b;
  });
}
