import { useState } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { confirmReviewEntry, discardReviewEntry, listReviewQueue } from '@/api/endpoints'
import { ApiError } from '@/api/client'
import { qk } from '@/api/queries'
import type { LlmAuthenticityRead, ReferenceLabel, ReviewQueueEntry } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { Pagination } from '@/components/ui/pagination'
import { Segmented } from '@/components/ui/segmented'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/cn'
import { relativeTime } from '@/lib/time'
import { useInstance } from '@/features/auth/useSession'

const LLM_READ_LABELS: Record<LlmAuthenticityRead, string> = {
  looks_authentic: 'looks authentic',
  suspect: 'suspect',
  unsure: 'unsure',
}

const LABEL_OPTIONS = [
  { value: 'real', label: 'Real' },
  { value: 'fake', label: 'Fake' },
] as const

function QueueCard({ entry }: { entry: ReviewQueueEntry }) {
  const queryClient = useQueryClient()
  // the suggestion pre-selects the label; the reviewer may flip it
  const [label, setLabel] = useState<ReferenceLabel>(entry.suggested_label)
  const [variantTag, setVariantTag] = useState('')

  const confirm = useMutation({
    mutationFn: () => confirmReviewEntry(entry.id, { label, variant_tag: variantTag.trim() || null }),
    onSuccess: () => {
      toast.success(`Added to ${entry.item_name}'s ${label} references`)
      void queryClient.invalidateQueries({ queryKey: ['items'] })
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not confirm the photo'),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ['vision'] }),
  })

  const discard = useMutation({
    mutationFn: () => discardReviewEntry(entry.id),
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not discard the photo'),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ['vision'] }),
  })

  const pending = confirm.isPending || discard.isPending

  return (
    <Card className="flex flex-col">
      <a href={entry.listing_url} target="_blank" rel="noreferrer" className="block">
        <img
          src={entry.image_url}
          alt={`Captured listing photo of ${entry.item_name}`}
          loading="lazy"
          className="aspect-[4/3] w-full border-b border-hairline bg-well object-cover"
        />
      </a>
      <CardBody className="flex flex-1 flex-col gap-2.5 pt-3">
        <div className="flex items-center justify-between gap-2">
          <Link
            to={`/items/${entry.item_id}`}
            className="min-w-0 truncate text-[13px] font-medium text-ink hover:text-lume hover:underline"
          >
            {entry.item_name}
          </Link>
          <Badge
            variant={entry.suggested_label === 'fake' ? 'rise' : 'snagged'}
            className="shrink-0 font-mono text-[10px] tnum"
          >
            {entry.suggested_label === 'fake' ? '✗' : '✓'} {entry.suggested_label} {entry.confidence}
          </Badge>
        </div>
        <p className="font-mono text-[11px] text-ink-3">
          {entry.llm_authenticity_read
            ? `agent read: ${LLM_READ_LABELS[entry.llm_authenticity_read]} · `
            : ''}
          captured {relativeTime(entry.created_at)} ·{' '}
          <a
            href={entry.listing_url}
            target="_blank"
            rel="noreferrer"
            className="text-ink-2 hover:text-lume"
          >
            open listing ↗
          </a>
        </p>
        <Input
          value={variantTag}
          onChange={(e) => setVariantTag(e.target.value)}
          placeholder="Variant tag (optional)"
          className="h-7 text-xs"
          aria-label="Variant tag"
        />
        <div className="mt-auto flex items-center gap-2">
          <Segmented
            options={LABEL_OPTIONS}
            value={label}
            onChange={setLabel}
            ariaLabel="Reference label"
          />
          <span className="flex-1" />
          <Button variant="ghost" size="sm" disabled={pending} onClick={() => discard.mutate()}>
            {discard.isPending ? <Loader2 className="animate-spin" /> : null}
            Discard
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={pending}
            onClick={() => confirm.mutate()}
            className={cn(label === 'fake' && 'bg-rise/80 hover:bg-rise')}
          >
            {confirm.isPending ? <Loader2 className="animate-spin" /> : null}
            Confirm {label}
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}

/**
 * The photo-review queue: listing photos the vision check flagged as likely
 * gold references, waiting for the owner's confirm/discard. Scoped to the
 * viewer's own captures (D-V11) — you review what your hunts found.
 */
export function ReviewQueuePage() {
  const { data: instance } = useInstance()
  const [page, setPage] = useState(1)

  const queue = useQuery({
    queryKey: qk.visionQueue({ page }),
    queryFn: () => listReviewQueue({ page }),
    placeholderData: keepPreviousData,
  })

  const entries = queue.data?.data ?? []

  return (
    <div className="space-y-5">
      <div className="flex items-baseline gap-3">
        <h1 className="font-display text-[26px] leading-tight font-semibold tracking-[0.05em] text-ink uppercase">
          Review
        </h1>
        {queue.data ? (
          <span className="font-mono text-[11px] text-ink-3 tnum">
            {queue.data.meta.total} {queue.data.meta.total === 1 ? 'photo' : 'photos'} waiting
          </span>
        ) : null}
      </div>

      {instance && !instance.vision_enabled ? (
        <EmptyState
          title="Photo checks are off"
          description="Set VISION_SIDECAR_URL on the backend to enable image-based authenticity checks."
        />
      ) : queue.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
        </div>
      ) : entries.length === 0 ? (
        <EmptyState
          title="Queue clear"
          description="When a scan finds a listing photo that strongly matches an item's references, it lands here for your call. Confirming grows that item's library — the more it holds, the sharper future checks get."
        />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {entries.map((entry) => (
              <QueueCard key={entry.id} entry={entry} />
            ))}
          </div>
          {queue.data && queue.data.meta.total > queue.data.meta.per_page ? (
            <div className="flex justify-end">
              <Pagination meta={queue.data.meta} onPage={setPage} />
            </div>
          ) : null}
        </>
      )}
    </div>
  )
}
