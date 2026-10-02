/** The listing cap typed "Track up to" text stands for: rounded and held to 1–10, or `fallback` while blank. */
export function settleMaxListings(text: string, fallback: number): number {
  const n = Math.round(Number(text))
  return text.trim() && Number.isFinite(n) ? Math.min(10, Math.max(1, n)) : fallback
}
