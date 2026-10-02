import { useState } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Loader2, ZoomIn } from 'lucide-react'
import { toast } from 'sonner'
import { confirmReviewEntry, discardReviewEntry, listReviewQueue } from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { LlmAuthenticityRead, ReferenceLabel, ReviewQueueEntry } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { ErrorState } from '@/components/ui/error-state'
import { Input } from '@/components/ui/input'
import { Pagination } from '@/components/ui/pagination'
import { Skeleton } from '@/components/ui/skeleton'
import { RelativeTime } from '@/components/ui/relative-time'
import { usePageTitle } from '@/lib/usePageTitle'
import { useInstance } from '@/features/auth/useSession'
import { PhotoCompareDialog } from './PhotoCompareDialog'
import { pageInRange } from './queue'

const LLM_READ_LABELS: Record<LlmAuthenticityRead, string> = {
  looks_authentic: 'looks authentic',
  suspect: 'suspect',
  unsure: 'unsure',
}

const LABELS: readonly ReferenceLabel[] = ['real', 'fake']

function QueueCard({ entry }: { entry: ReviewQueueEntry }) {
  const queryClient = useQueryClient()
  const [variantTag, setVariantTag] = useState('')
  const [compareOpen, setCompareOpen] = useState(false)

  const confirm = useMutation({
    mutationFn: (label: ReferenceLabel) =>
      confirmReviewEntry(entry.id, { label, variant_tag: variantTag.trim() || null }),
    onSuccess: (_, label) => {
      toast.success(`Added to ${entry.item_name}'s ${label} references`)
      void queryClient.invalidateQueries({ queryKey: ['items'] })
    },
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ['vision'] }),
  })

  const discard = useMutation({
    mutationFn: () => discardReviewEntry(entry.id),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ['vision'] }),
  })

  const pending = confirm.isPending || discard.isPending

  return (
    <Card className="flex flex-col">
      <button
        type="button"
        onClick={() => setCompareOpen(true)}
        aria-label={`Look closer at the photo of ${entry.item_name}`}
        className="group relative block cursor-zoom-in"
      >
        <img
          src={entry.image_url}
          alt={`Captured listing photo of ${entry.item_name}`}
          loading="lazy"
          className="aspect-[4/3] w-full border-b border-hairline bg-well object-cover"
        />
        <span
          aria-hidden
          className="absolute right-2 bottom-2 grid size-7 place-items-center rounded-sm bg-black/60 text-ink-2 group-hover:text-lume"
        >
          <ZoomIn className="size-4" />
        </span>
      </button>
      <PhotoCompareDialog entry={entry} open={compareOpen} onOpenChange={setCompareOpen} />
      <CardBody className="flex flex-1 flex-col gap-2.5 pt-3">
        <div className="flex items-center justify-between gap-2">
          <Link
            to={`/items/${entry.item_id}`}
            className="min-w-0 truncate text-[14px] font-medium text-ink hover:text-lume hover:underline"
          >
            {entry.item_name}
          </Link>
          <Badge
            variant={entry.suggested_label === 'fake' ? 'rise' : 'snagged'}
            className="shrink-0 font-mono text-[12px] tnum"
          >
            suggested {entry.suggested_label} {entry.confidence}
          </Badge>
        </div>
        <p className="font-mono text-[12px] text-ink-3">
          {entry.llm_authenticity_read
            ? `Snagr's read: ${LLM_READ_LABELS[entry.llm_authenticity_read]} · `
            : ''}
          captured <RelativeTime iso={entry.created_at} /> ·{' '}
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
          className="h-7 sm:text-xs"
          aria-label="Variant tag"
        />
        {/* Neither answer is preset or styled as the default: the suggestion
            above is a hint, and a reference filed under the wrong label
            skews every later photo check for this item. */}
        <div className="mt-auto flex items-center gap-2">
          <Button variant="ghost" size="sm" disabled={pending} onClick={() => discard.mutate()}>
            {discard.isPending ? <Loader2 className="animate-spin" /> : null}
            Discard
          </Button>
          <span className="flex-1" />
          {LABELS.map((label) => (
            <Button key={label} size="sm" disabled={pending} onClick={() => confirm.mutate(label)}>
              {confirm.isPending && confirm.variables === label ? (
                <Loader2 className="animate-spin" />
              ) : null}
              It's {label}
            </Button>
          ))}
        </div>
      </CardBody>
    </Card>
  )
}

/**
 * The photo-review queue: listing photos the vision check flagged as likely
 * gold references, waiting for the owner's confirm/discard. Scoped to the
 * viewer's own captures, admins included — you review what your hunts found.
 */
export function ReviewQueuePage() {
  usePageTitle('Photo review')
  const { data: instance } = useInstance()
  const [page, setPage] = useState(1)

  const queue = useQuery({
    queryKey: qk.visionQueue({ page }),
    queryFn: () => listReviewQueue({ page }),
    placeholderData: keepPreviousData,
  })

  const entries = queue.data?.data ?? []
  const meta = queue.data?.meta
  // An emptied later page steps back rather than reading as an empty queue,
  // which is why "Nothing to review" below keys off the total.
  if (meta && pageInRange(page, meta) !== page) setPage(pageInRange(page, meta))

  return (
    <div className="space-y-5">
      <div className="flex items-baseline gap-3">
        <h1 className="font-display text-[26px] leading-tight font-semibold tracking-[0.05em] text-ink uppercase">
          Photo review
        </h1>
        {queue.data ? (
          <span className="font-mono text-[12px] text-ink-3 tnum">
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
      ) : queue.isError ? (
        <ErrorState
          title="Couldn't load the review queue"
          error={queue.error}
          onRetry={() => void queue.refetch()}
          retrying={queue.isFetching}
        />
      ) : meta?.total === 0 ? (
        <EmptyState
          title="Nothing to review"
          description="When Snagr finds a listing photo that closely matches an item's reference photos, it shows up here for you to confirm. Each one you confirm makes future photo checks more accurate."
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
