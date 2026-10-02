/**
 * The `max` rows that moved furthest either way, ordered biggest drop to
 * biggest rise. Picking by size before sign keeps a category's rises on the
 * price-change chart when it has more drops than bars, and the other way round.
 */
export function biggestMovers<T extends { pct: number }>(rows: T[], max: number): T[] {
  return [...rows]
    .sort((a, b) => Math.abs(b.pct) - Math.abs(a.pct))
    .slice(0, max)
    .sort((a, b) => a.pct - b.pct)
}
