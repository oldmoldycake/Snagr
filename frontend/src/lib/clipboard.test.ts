import { afterEach, describe, expect, it, vi } from 'vitest'
import { copyText } from './clipboard'

/** Just enough of the DOM for the selection fallback: a textarea that records
 *  being selected and removed, and an execCommand that reports `copies`. */
function stubDocument(copies: boolean | 'throws') {
  const area = { value: '', style: {}, setAttribute: vi.fn(), select: vi.fn(), remove: vi.fn() }
  const execCommand = vi.fn(() => {
    if (copies === 'throws') throw new Error('SecurityError')
    return copies
  })
  vi.stubGlobal('HTMLElement', class {})
  vi.stubGlobal('document', {
    activeElement: null,
    body: { append: vi.fn() },
    createElement: () => area,
    execCommand,
  })
  return { area, execCommand }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('copyText', () => {
  it('uses the Clipboard API when it is there', async () => {
    const writeText = vi.fn(() => Promise.resolve())
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const { execCommand } = stubDocument(true)

    expect(await copyText('snagr_pat_abc')).toBe(true)
    expect(writeText).toHaveBeenCalledWith('snagr_pat_abc')
    expect(execCommand).not.toHaveBeenCalled()
  })

  it('falls back to selecting the text over plain HTTP, where navigator.clipboard is undefined', async () => {
    vi.stubGlobal('navigator', {})
    const { area, execCommand } = stubDocument(true)

    expect(await copyText('http://nas.local/invite/t')).toBe(true)
    expect(area.value).toBe('http://nas.local/invite/t')
    expect(area.select).toHaveBeenCalled()
    expect(execCommand).toHaveBeenCalledWith('copy')
    expect(area.remove).toHaveBeenCalled()
  })

  it('falls back when the Clipboard API refuses', async () => {
    vi.stubGlobal('navigator', { clipboard: { writeText: () => Promise.reject(new Error('NotAllowedError')) } })
    const { execCommand } = stubDocument(true)

    expect(await copyText('secret')).toBe(true)
    expect(execCommand).toHaveBeenCalledWith('copy')
  })

  it('reports failure when nothing can copy', async () => {
    vi.stubGlobal('navigator', {})
    stubDocument(false)
    expect(await copyText('secret')).toBe(false)

    const { area } = stubDocument('throws')
    expect(await copyText('secret')).toBe(false)
    expect(area.remove).toHaveBeenCalled()
  })
})
