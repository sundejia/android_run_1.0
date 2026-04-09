/** Map API score to ten-point scale for display (0–1 → ×10). */
export function toDisplayScore(raw: number | null | undefined): number | null {
  if (raw == null || Number.isNaN(Number(raw))) return null
  const n = Number(raw)
  if (n >= 0 && n <= 1) return n * 10
  return n
}

export function isReviewPassingDisplay(raw: number | null | undefined): boolean {
  const d = toDisplayScore(raw)
  return d != null && d >= 6
}
