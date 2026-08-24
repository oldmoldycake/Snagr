/**
 * Single source of truth for chart colors — mirrors the CSS tokens in
 * globals.css. Recharts needs literal values, not CSS variables, for some
 * props, so they're duplicated here on purpose.
 */

export const chart = {
  surface: '#101812',
  well: '#0a0f0b',
  grid: '#202b23',
  hairline: 'rgb(193 255 208 / 0.09)',
  hairlineStrong: 'rgb(193 255 208 / 0.16)',
  lume: '#ffb454',
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

/** Mix a hex color toward white by t (0–1) — glow halos and dot cores need literal SVG colors. */
export function mixToWhite(hex: string, t: number): string {
  const n = parseInt(hex.slice(1), 16)
  const mix = (c: number) => Math.round(c + (255 - c) * t)
  const r = mix((n >> 16) & 0xff)
  const g = mix((n >> 8) & 0xff)
  const b = mix(n & 0xff)
  return `#${((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1)}`
}

export const axisTickStyle = {
  fill: chart.inkMuted,
  fontSize: 11,
  fontFamily: "'IBM Plex Mono', monospace",
} as const
