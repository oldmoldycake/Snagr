import { useRef, useState, type MouseEvent, type PointerEvent, type ReactNode } from 'react'
import { flushSync } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import { listReferences } from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { ReferenceImage, ReviewQueueEntry } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogEyebrow,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/cn'
import { PHOTO_ZOOM, zoomScroll } from './zoom'

/** Pointer travel, in px, past which a press on a zoomed photo pans it instead of zooming out. */
const DRAG_SLOP = 4

const FRAME = 'h-[30dvh] sm:h-[min(46vh,400px)]'

/**
 * A photo in a fixed frame: a click zooms in on the spot clicked and another
 * zooms back out. Zoomed, the frame scrolls — a touch pans it natively, and a
 * mouse drags it, since a wheel only scrolls one way.
 */
function ZoomablePhoto({ src, alt, name }: { src: string; alt: string; name: string }) {
  const frame = useRef<HTMLDivElement>(null)
  const [zoomed, setZoomed] = useState(false)
  const drag = useRef<{ x: number; y: number; left: number; top: number; moved: boolean } | null>(null)

  const onClick = (event: MouseEvent<HTMLButtonElement>) => {
    const el = frame.current
    if (!el) return
    if (drag.current?.moved) {
      drag.current = null
      return
    }
    if (zoomed) {
      setZoomed(false)
      return
    }
    // A keyboard press has no pointer position (detail 0): zoom on the middle.
    const box = el.getBoundingClientRect()
    const point =
      event.detail === 0
        ? { x: box.width / 2, y: box.height / 2 }
        : { x: event.clientX - box.left, y: event.clientY - box.top }
    // The zoomed size has to be laid out before the frame can scroll into it.
    flushSync(() => setZoomed(true))
    el.scrollTo(zoomScroll(point, PHOTO_ZOOM))
  }

  const onPointerDown = (event: PointerEvent<HTMLButtonElement>) => {
    const el = frame.current
    if (!zoomed || !el || event.pointerType !== 'mouse' || event.button !== 0) return
    drag.current = { x: event.clientX, y: event.clientY, left: el.scrollLeft, top: el.scrollTop, moved: false }
  }

  const onPointerMove = (event: PointerEvent<HTMLButtonElement>) => {
    const d = drag.current
    const el = frame.current
    if (!d || !el || !(event.buttons & 1)) return
    const dx = event.clientX - d.x
    const dy = event.clientY - d.y
    if (!d.moved && Math.hypot(dx, dy) < DRAG_SLOP) return
    d.moved = true
    el.scrollLeft = d.left - dx
    el.scrollTop = d.top - dy
  }

  return (
    <div ref={frame} className={cn(FRAME, 'overflow-auto overscroll-contain rounded-md border border-hairline bg-well')}>
      <button
        type="button"
        aria-label={`${zoomed ? 'Zoom out of' : 'Zoom in on'} ${name}`}
        onClick={onClick}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        className={cn('block', zoomed ? 'cursor-zoom-out active:cursor-grabbing' : 'cursor-zoom-in')}
        style={{ width: `${zoomed ? PHOTO_ZOOM * 100 : 100}%`, height: `${zoomed ? PHOTO_ZOOM * 100 : 100}%` }}
      >
        <img src={src} alt={alt} draggable={false} className="size-full object-contain select-none" />
      </button>
    </div>
  )
}

function LabelBadge({ label }: { label: ReferenceImage['label'] }) {
  return (
    <Badge variant={label === 'fake' ? 'rise' : 'snagged'} className="shrink-0 font-mono text-[12px]">
      {label === 'fake' ? '✗ fake' : '✓ real'}
    </Badge>
  )
}

/** Mono caption over each photo, naming what it is. */
function PaneCaption({ children }: { children: ReactNode }) {
  return (
    <div className="mb-2 flex min-h-6 items-center gap-2 font-mono text-[12px] tracking-[0.06em] text-ink-3 uppercase">
      {children}
    </div>
  )
}

/**
 * A closer look at a review-queue photo: the capture, zoomable, beside the
 * item's reference photos — the ones its photo checks score against — so a
 * real-or-fake call can rest on the detail rather than a thumbnail. Real
 * references come first: they are what a genuine copy looks like.
 */
export function PhotoCompareDialog({
  entry,
  open,
  onOpenChange,
}: {
  entry: ReviewQueueEntry
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const references = useQuery({
    queryKey: qk.itemReferences(entry.item_id),
    queryFn: () => listReferences(entry.item_id),
    enabled: open,
  })
  const [pickedId, setPickedId] = useState<number | null>(null)

  const live = (references.data?.data ?? [])
    .filter((r) => !r.revoked)
    .sort((a, b) => Number(a.label === 'fake') - Number(b.label === 'fake'))
  const picked = live.find((r) => r.id === pickedId) ?? live[0]

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[1040px]">
        <DialogHeader>
          <DialogEyebrow>Photo review</DialogEyebrow>
          <DialogTitle>{entry.item_name}</DialogTitle>
          <DialogDescription>
            Click a photo to zoom in on that spot, and again to zoom out. Pick a reference below to compare against.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="grid gap-4 sm:grid-cols-2">
          <section aria-label="Captured photo" className="min-w-0">
            <PaneCaption>
              Captured
              <Badge
                variant={entry.suggested_label === 'fake' ? 'rise' : 'snagged'}
                className="ml-auto font-mono text-[12px] tracking-normal normal-case tnum"
              >
                suggested {entry.suggested_label} {entry.confidence}
              </Badge>
            </PaneCaption>
            <ZoomablePhoto
              src={entry.image_url}
              alt={`Captured listing photo of ${entry.item_name}`}
              name="the captured photo"
            />
          </section>
          <section aria-label="Reference photos" className="min-w-0">
            <PaneCaption>
              Reference
              {picked ? (
                <span className="ml-auto flex min-w-0 items-center gap-1.5 tracking-normal normal-case">
                  {picked.variant_tag ? (
                    <span className="truncate text-ink-2 italic">“{picked.variant_tag}”</span>
                  ) : null}
                  <LabelBadge label={picked.label} />
                </span>
              ) : null}
            </PaneCaption>
            {references.isLoading ? (
              <Skeleton className={FRAME} />
            ) : references.isError ? (
              <div className={cn(FRAME, 'grid place-items-center rounded-md border border-hairline px-6 text-center text-[14px] text-ink-2')}>
                Couldn't load this item's reference photos.
              </div>
            ) : picked ? (
              <ZoomablePhoto
                key={picked.id}
                src={picked.image_url}
                alt={`${picked.label} reference photo of ${entry.item_name}`}
                name="the reference photo"
              />
            ) : (
              <div className={cn(FRAME, 'grid place-items-center rounded-md border border-hairline px-6 text-center text-[14px] text-ink-2')}>
                This item has no reference photos yet. Confirming this photo adds the first one.
              </div>
            )}
            {live.length > 1 ? (
              <div role="group" aria-label="Choose a reference photo" className="mt-2 flex gap-2 overflow-x-auto pb-1">
                {live.map((r, i) => (
                  <button
                    key={r.id}
                    type="button"
                    aria-pressed={r.id === picked?.id}
                    aria-label={`${r.label} reference ${i + 1}${r.variant_tag ? `, ${r.variant_tag}` : ''}`}
                    onClick={() => setPickedId(r.id)}
                    className={cn(
                      'relative size-14 shrink-0 overflow-hidden rounded-sm border border-hairline',
                      'aria-pressed:border-lume aria-pressed:ring-1 aria-pressed:ring-lume',
                    )}
                  >
                    <img src={r.image_url} alt="" loading="lazy" className="size-full bg-well object-cover" />
                    <span
                      aria-hidden
                      className={cn(
                        'absolute right-0.5 bottom-0.5 rounded-[2px] bg-black/60 px-1 font-mono text-[12px] leading-4',
                        r.label === 'fake' ? 'text-rise' : 'text-drop',
                      )}
                    >
                      {r.label === 'fake' ? '✗' : '✓'}
                    </span>
                  </button>
                ))}
              </div>
            ) : null}
          </section>
        </DialogBody>
        <DialogFooter>
          <a
            href={entry.listing_url}
            target="_blank"
            rel="noreferrer"
            className="mr-auto font-mono text-[12px] text-ink-2 hover:text-lume max-sm:flex max-sm:items-center"
          >
            open listing ↗
          </a>
          <DialogClose asChild>
            <Button variant="ghost" size="sm">
              Close
            </Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
