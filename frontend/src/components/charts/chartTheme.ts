/**
 * Single source of truth for chart colors — mirrors the CSS tokens in
 * globals.css. Recharts needs literal values, not CSS variables, for some
 * props, so they're duplicated here on purpose.
 */

export const chart = {
  surface: '#101812',
  grid: '#202b23',
  ink: '#e9f1e9',
  inkSecondary: '#a6b5a7',
  inkMuted: '#69796e',
  drop: '#42d07c',
  rise: '#f0565c',
  sparkDim: '#4e5d53',
  /** categorical series — "Embers", assigned by listing id, color follows the entity */
  series: ['#c05a35', '#2aa08d', '#bd8a2b', '#5585c9', '#b25a78', '#86973a'],
  othersGray: '#5a685e',
} as const

/** Stable slot assignment: listings sorted by id, fixed order, never recycled. */
export function seriesColor(index: number): string {
  return chart.series[index % chart.series.length]
}

export const axisTickStyle = {
  fill: chart.inkMuted,
  fontSize: 11,
  fontFamily: "'IBM Plex Mono', monospace",
} as const
