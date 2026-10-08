import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

/**
 * The terminal voice: one glyph map for every log surface (the activity page
 * and sheet, job pages, price checks, the hunter ticker). Color never travels
 * alone — the glyph is the semantic channel, and the level word is what a
 * screen reader hears in its place.
 */
export type LogGlyphLevel = 'info' | 'success' | 'warn' | 'error' | 'skip' | 'new'

/** Glyph, spoken level and color for each log level. */
export const LOG_GLYPHS: Record<LogGlyphLevel, { glyph: string; label: string; className: string }> = {
  info: { glyph: '›', label: 'Info', className: 'text-ink-3' },
  success: { glyph: '✓', label: 'Success', className: 'text-drop' },
  warn: { glyph: '⚠', label: 'Warning', className: 'text-warn' },
  error: { glyph: '✗', label: 'Error', className: 'text-rise' },
  skip: { glyph: '○', label: 'Skipped', className: 'text-ink-3' },
  new: { glyph: '✚', label: 'New', className: 'text-lume' },
}

/** A level's glyph, read out as its level word ("Error: …") rather than the symbol. */
export function LogGlyph({ level, className }: { level: LogGlyphLevel; className?: string }) {
  const { glyph, label, className: color } = LOG_GLYPHS[level]
  return (
    <>
      <span aria-hidden className={cn(color, className)}>
        {glyph}
      </span>
      <span className="sr-only">{label}: </span>
    </>
  )
}

/** One log entry: a stable key, a preformatted time, its level and the message. */
export interface LogLine {
  key: string | number
  time: string
  level: LogGlyphLevel
  message: ReactNode
}

/** One log line: time, level glyph, message. */
export function TerminalLogLine({ line }: { line: LogLine }) {
  return (
    <div className="flex gap-2">
      <span className="shrink-0 text-ink-3 tnum">{line.time}</span>
      <LogGlyph level={line.level} className="w-3.5 shrink-0 text-center" />
      <span className="min-w-0 flex-1 text-ink-2">{line.message}</span>
    </div>
  )
}

/** A block of log lines in the terminal voice. */
export function TerminalLog({ lines, className }: { lines: LogLine[]; className?: string }) {
  return (
    <div className={cn('font-mono text-[12px] leading-[2.05]', className)}>
      {lines.map((line) => (
        <TerminalLogLine key={line.key} line={line} />
      ))}
    </div>
  )
}
