export function firstReviewImage(images) {
  return (images || []).find((image) => image.status === "REQUIRES_REVIEW") || null;
}
