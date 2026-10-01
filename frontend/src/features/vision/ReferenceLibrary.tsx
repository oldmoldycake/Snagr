import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError } from '@/api/client'
import { listReferences, revokeAutoReferences, revokeReference } from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { ReferenceImage } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader, CardTitle } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import { RelativeTime } from '@/components/ui/relative-time'
import { cn } from '@/lib/cn'
import { UploadReferenceDialog } from './UploadReferenceDialog'

function ReferenceTile({ reference, onRevoke }: { reference: ReferenceImage; onRevoke: () => void }) {
  const fake = reference.label === 'fake'
  return (
    <div className={cn('overflow-hidden rounded-md border border-hairline', reference.revoked && 'opacity-45')}>
      <img
        src={reference.image_url}
        alt={`${reference.label} reference photo`}
        loading="lazy"
        className="aspect-[4/3] w-full border-b border-hairline bg-well object-cover"
      />
      <div className="space-y-1.5 p-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant={fake ? 'rise' : 'snagged'} className="font-mono text-[10px]">
            {fake ? '✗ fake' : '✓ real'}
          </Badge>
          <Badge variant="muted" className="font-mono text-[10px]">
            {reference.provenance}
          </Badge>
          {reference.revoked ? (
            <Badge variant="muted" className="font-mono text-[10px]">
              revoked
            </Badge>
          ) : (
            <button
              type="button"
              onClick={onRevoke}
              className="ml-auto font-mono text-[10px] tracking-[0.06em] text-ink-3 uppercase hover:text-rise"
            >
              Revoke
            </button>
          )}
        </div>
        {reference.variant_tag ? (
          <p className="truncate text-[11px] text-ink-2 italic">“{reference.variant_tag}”</p>
        ) : null}
        <p className="truncate font-mono text-[10px] text-ink-3">
          <RelativeTime iso={reference.created_at} />
          {reference.source_listing_url ? (
            <>
              {' · '}
              <a
                href={reference.source_listing_url}
                target="_blank"
                rel="noreferrer"
                className="hover:text-lume"
              >
                source ↗
              </a>
            </>
          ) : null}
        </p>
      </div>
    </div>
  )
}

/**
 * The item's gold-reference library — the photos its authenticity checks
 * score against. Communal per item (every watcher shares one library); only
 * the capturer and admins see a reference's source listing.
 */
export function ReferenceLibrary({ itemId }: { itemId: number }) {
  const queryClient = useQueryClient()
  const [uploadOpen, setUploadOpen] = useState(false)
  const [revokeTarget, setRevokeTarget] = useState<ReferenceImage | null>(null)
  const [revokeAutoOpen, setRevokeAutoOpen] = useState(false)

  const references = useQuery({
    queryKey: qk.itemReferences(itemId),
    queryFn: () => listReferences(itemId),
  })

  const revoke = useMutation({
    mutationFn: (id: number) => revokeReference(id),
    meta: { inlineError: true },
    onSuccess: () => setRevokeTarget(null),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: qk.itemReferences(itemId) }),
  })

  const revokeAuto = useMutation({
    mutationFn: () => revokeAutoReferences(itemId),
    meta: { inlineError: true },
    onSuccess: ({ revoked }) => {
      setRevokeAutoOpen(false)
      toast.success(`Revoked ${revoked} auto-promoted ${revoked === 1 ? 'reference' : 'references'}`)
    },
    onSettled: () => void queryClient.invalidateQueries({ queryKey: qk.itemReferences(itemId) }),
  })

  const rows = references.data?.data ?? []
  const live = rows.filter((r) => !r.revoked)
  const autoCount = live.filter((r) => r.provenance === 'auto').length
  const realCount = live.filter((r) => r.label === 'real').length
  const fakeCount = live.filter((r) => r.label === 'fake').length

  return (
    <Card>
      <CardHeader>
        <CardTitle>Reference photos</CardTitle>
        <div className="flex items-center gap-3">
          {rows.length > 0 ? (
            <span className="font-mono text-[11px] text-ink-3 tnum">
              {realCount} real · {fakeCount} fake
            </span>
          ) : null}
          {autoCount > 0 ? (
            <Button variant="ghost" size="sm" onClick={() => setRevokeAutoOpen(true)}>
              Revoke auto ×{autoCount}
            </Button>
          ) : null}
          <Button size="sm" onClick={() => setUploadOpen(true)}>
            Add photo
          </Button>
        </div>
      </CardHeader>
      <CardBody>
        {references.isLoading ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
            <Skeleton className="h-40" />
            <Skeleton className="h-40" />
            <Skeleton className="h-40" />
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            className="border-0 py-8"
            title="No reference photos yet"
            description="Photo checks can't reach a verdict until this item has photos of known-real or known-fake copies. Confirm photos on the Photo review page, or upload your own."
            action={
              <Button size="sm" onClick={() => setUploadOpen(true)}>
                Add photo
              </Button>
            }
          />
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
            {rows.map((reference) => (
              <ReferenceTile
                key={reference.id}
                reference={reference}
                onRevoke={() => setRevokeTarget(reference)}
              />
            ))}
          </div>
        )}
      </CardBody>

      <ConfirmDialog
        open={revokeTarget != null}
        onOpenChange={(open) => {
          if (open) return
          setRevokeTarget(null)
          revoke.reset()
        }}
        title="Revoke reference"
        description={`This ${revokeTarget?.label ?? ''} reference stops counting toward the item's photo checks. There is no un-revoke.`}
        confirmLabel="Revoke"
        pending={revoke.isPending}
        error={revoke.error instanceof ApiError ? revoke.error.message : null}
        onConfirm={() => revokeTarget && revoke.mutate(revokeTarget.id)}
      />

      <ConfirmDialog
        open={revokeAutoOpen}
        onOpenChange={(open) => {
          setRevokeAutoOpen(open)
          if (!open) revokeAuto.reset()
        }}
        title="Revoke auto-promoted references"
        description={`${autoCount} auto-promoted ${autoCount === 1 ? 'reference' : 'references'} will stop counting toward this item's photo checks. Human-confirmed and uploaded references are untouched.`}
        confirmLabel={`Revoke ${autoCount}`}
        pending={revokeAuto.isPending}
        error={revokeAuto.error instanceof ApiError ? revokeAuto.error.message : null}
        onConfirm={() => revokeAuto.mutate()}
      />

      <UploadReferenceDialog itemId={itemId} open={uploadOpen} onOpenChange={setUploadOpen} />
    </Card>
  )
}
