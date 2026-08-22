import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

/**
 * The terminal voice: one glyph map for every log surface (activity sheet,
 * run pages, price checks, the agent ticker). Color never travels alone —
 * the glyph is the semantic channel.
 */
export type LogGlyphLevel = 'info' | 'success' | 'warn' | 'error' | 'skip' | 'new'

export const LOG_GLYPHS: Record<LogGlyphLevel, { glyph: string; className: string }> = {
  info: { glyph: '›', className: 'text-ink-3' },
  success: { glyph: '✓', className: 'text-drop' },
  warn: { glyph: '⚠', className: 'text-warn' },
  error: { glyph: '✗', className: 'text-rise' },
  skip: { glyph: '○', className: 'text-ink-3' },
  new: { glyph: '✚', className: 'text-lume' },
}

export interface LogLine {
  key: string | number
  time: string
  level: LogGlyphLevel
  message: ReactNode
}

export function TerminalLogLine({ line }: { line: LogLine }) {
  const { glyph, className } = LOG_GLYPHS[line.level]
  return (
    <div className="flex gap-2">
      <span className="shrink-0 text-ink-3 tnum">{line.time}</span>
      <span aria-hidden className={cn('w-3.5 shrink-0 text-center', className)}>
        {glyph}
      </span>
      <span className="min-w-0 flex-1 text-ink-2">{line.message}</span>
    </div>
  )
}

export function TerminalLog({ lines, className }: { lines: LogLine[]; className?: string }) {
  return (
    <div className={cn('font-mono text-[11px] leading-[2.05]', className)}>
      {lines.map((line) => (
        <TerminalLogLine key={line.key} line={line} />
      ))}
    </div>
  )
}
