import type { Listing } from '@/api/types'
import { toCents } from '@/lib/money'

/**
 * The listings board's price rail: range-high on the left → cheapest on the
 * right, on a log scale. Log because listing prices spread multiplicatively —
 * a linear rail lets a $40–$65 tail own the width and crush the under-target
 * cluster (item 3: thirteen $6–$10 listings in 6% of the rail) into one spot.
 */
export interface Rail {
  place: (cents: number) => { pct: number; clamp: '«' | '»' | null }
  targetPct: number | null
  /** Round prices inside the domain, cheapest last; `thin` ones lose their label when crowded. */
  ticks: { cents: number; thin: boolean }[]
}

/** Below this spacing, neighbouring tick labels collide — drop the thin ones. */
const MIN_LABEL_GAP_PX = 40
/** A tick label this close to ⌖ yields to the ⌖ label, which names the same spot. */
const TARGET_LABEL_CLEARANCE_PCT = 7
/** IBM Plex Mono advance at the rail's 10px type (0.6em). */
const CHAR_PX = 6
/** Matches the ±9px dot→label offset in Track. */
const LABEL_GAP_PX = 9

/** Build the rail for the board's unfolded rows; null when none of them has a price. */
export function makeRail(
  mainRows: Listing[],
  startCents: Map<number, number>,
  targetC: number | null,
): Rail | null {
  const cents: number[] = []
  for (const l of mainRows) {
    const now = toCents(l.latest_price)
    if (now != null && now > 0) cents.push(now)
    const start = startCents.get(l.id)
    if (start != null && start > 0) cents.push(start)
  }
  if (targetC != null && targetC > 0) cents.push(targetC)
  if (cents.length === 0) return null

  // Domain covers the unfolded rows + target; opened folded rows may clamp.
  // The pad never drops under ±2% of price, so one price (or all equal) still
  // has a non-zero span and lands mid-rail.
  const lg = (c: number) => Math.log(Math.max(c, 1))
  const hi = lg(Math.max(...cents))
  const lo = lg(Math.min(...cents))
  const pad = Math.max((hi - lo) * 0.04, Math.log(1.02))
  const left = hi + pad
  const right = lo - pad
  const place = (c: number) => {
    const raw = ((left - lg(c)) / (left - right)) * 100
    return {
      pct: Math.max(0, Math.min(100, raw)),
      clamp: raw < 0 ? ('«' as const) : raw > 100 ? ('»' as const) : null,
    }
  }

  const loC = Math.exp(right)
  const hiC = Math.exp(left)
  let ticks: Rail['ticks'] = []
  for (let d = Math.floor(Math.log10(loC)); d <= Math.ceil(Math.log10(hiC)); d++) {
    for (const m of [1, 2, 5]) {
      const c = m * 10 ** d
      if (c >= loC && c <= hiC) ticks.push({ cents: c, thin: m === 2 })
    }
  }
  // A tight band (all listings within ~2.5×) holds at most one 1-2-5 value; there
  // log and linear barely differ, so fall back to even round steps.
  if (ticks.length < 3) {
    const step = niceStep((hiC - loC) / 4)
    ticks = []
    for (let k = Math.ceil(loC / step); k * step <= hiC; k++) ticks.push({ cents: k * step, thin: k % 2 === 1 })
  }
  ticks.sort((a, b) => b.cents - a.cents)

  return { place, targetPct: targetC != null && targetC > 0 ? place(targetC).pct : null, ticks }
}

/** 1-2-5 × 10ⁿ at or above `raw`, in whole cents. */
function niceStep(raw: number): number {
  const mag = 10 ** Math.floor(Math.log10(Math.max(raw, 1)))
  const m = [1, 2, 5, 10].find((n) => n * mag >= raw) ?? 10
  return Math.max(1, m * mag)
}

/** Which ticks carry a label at this rail width. */
export function labeledTicks(rail: Rail, railPx: number): number[] {
  const pcts = rail.ticks.map((t) => rail.place(t.cents).pct)
  const crowded =
    railPx > 0 && pcts.some((p, i) => i > 0 && ((p - pcts[i - 1]) / 100) * railPx < MIN_LABEL_GAP_PX)
  return rail.ticks
    .filter((t, i) => {
      if (crowded && t.thin) return false
      return rail.targetPct == null || Math.abs(pcts[i] - rail.targetPct) >= TARGET_LABEL_CLEARANCE_PCT
    })
    .map((t) => t.cents)
}

/**
 * A dot's price label sits right of the dot; it flips left when it would run
 * off the rail or print across ⌖ (and there is room on the left).
 */
export function labelFlipsLeft(
  nowPct: number,
  targetPct: number | null,
  label: string,
  railPx: number,
  fallbackFlipPct: number,
): boolean {
  if (railPx <= 0) return nowPct > fallbackFlipPct
  const labelPct = ((label.length * CHAR_PX + LABEL_GAP_PX + 2) / railPx) * 100
  if (nowPct + labelPct > 100) return true
  const crossesTarget = targetPct != null && nowPct < targetPct && nowPct + labelPct > targetPct
  return crossesTarget && nowPct - labelPct >= 0
}
