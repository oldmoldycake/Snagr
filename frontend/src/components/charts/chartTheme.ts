/**
 * Single source of truth for chart colors — mirrors the CSS tokens in
 * globals.css. Recharts needs literal values, not CSS variables, for some
 * props, so they're duplicated here on purpose.
 */

export const chart = {
  surface: '#16191d',
  grid: '#262b30',
  ink: '#f2f4f5',
  inkSecondary: '#a8b0b8',
  inkMuted: '#6c7680',
  drop: '#2fbf71',
  rise: '#e5484d',
  sparkDim: '#4a4f55',
  /** categorical series — assigned by listing id, color follows the entity */
  series: ['#3987e5', '#199e70', '#c98500', '#9085e9', '#d55181', '#d95926'],
  othersGray: '#565d66',
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
