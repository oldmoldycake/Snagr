import { describe, expect, it } from 'vitest'
import { intervalOptions, intervalPresets } from './intervalOptions'

describe('intervalPresets', () => {
  it('offers the presets when the default is one of them, or not known yet', () => {
    expect(intervalPresets(30)).toEqual([15, 30, 60, 360])
    expect(intervalPresets(undefined)).toEqual([15, 30, 60, 360])
  })

  it('slots any other default in among them', () => {
    expect(intervalPresets(45)).toEqual([15, 30, 45, 60, 360])
    expect(intervalPresets(1440)).toEqual([15, 30, 60, 360, 1440])
  })
})

describe('intervalOptions', () => {
  it("marks the instance default's option", () => {
    expect(intervalOptions(30)).toEqual([
      { value: '15', label: '15m' },
      { value: '30', label: '30m (default)' },
      { value: '60', label: '1h' },
      { value: '360', label: '6h' },
      { value: 'custom', label: 'Custom' },
    ])
    expect(intervalOptions(120).map((o) => o.label)).toEqual(['15m', '30m', '1h', '2h (default)', '6h', 'Custom'])
  })

  it('marks nothing until the default is known', () => {
    expect(intervalOptions(undefined).map((o) => o.label)).toEqual(['15m', '30m', '1h', '6h', 'Custom'])
  })
})
