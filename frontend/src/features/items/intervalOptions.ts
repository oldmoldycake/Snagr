import { formatInterval } from '@/lib/time'

const INTERVAL_PRESETS = [15, 30, 60, 360]

/**
 * The check intervals "Check every" offers, in minutes: the presets, plus the
 * instance default when the operator set it to something else, so an item on
 * the default always has an option to show checked.
 */
export function intervalPresets(defaultInterval: number | undefined): number[] {
  return defaultInterval == null || INTERVAL_PRESETS.includes(defaultInterval)
    ? INTERVAL_PRESETS
    : [...INTERVAL_PRESETS, defaultInterval].sort((a, b) => a - b)
}

/** The "Check every" options: each preset, the instance default's marked as such, then Custom. */
export function intervalOptions(defaultInterval: number | undefined): { value: string; label: string }[] {
  return [
    ...intervalPresets(defaultInterval).map((m) => ({
      value: String(m),
      label: m === defaultInterval ? `${formatInterval(m)} (default)` : formatInterval(m),
    })),
    { value: 'custom', label: 'Custom' },
  ]
}
