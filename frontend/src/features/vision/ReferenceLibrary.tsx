import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { listReferences, revokeAutoReferences, revokeReference } from '@/api/endpoints'
import { ApiError } from '@/api/client'
import { qk } from '@/api/queries'
import type { ReferenceImage } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader, CardTitle } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/cn'
import { relativeTime } from '@/lib/time'
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
          {relativeTime(reference.created_at)}
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
 * the capturer and admins see a reference's source listing (D-V11).
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
    onSuccess: () => setRevokeTarget(null),
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not revoke the reference'),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: qk.itemReferences(itemId) }),
  })

  const revokeAuto = useMutation({
    mutationFn: () => revokeAutoReferences(itemId),
    onSuccess: ({ revoked }) => {
      setRevokeAutoOpen(false)
      toast.success(`Revoked ${revoked} auto-promoted ${revoked === 1 ? 'reference' : 'references'}`)
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not revoke the references'),
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
        <CardTitle>Library</CardTitle>
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
            description="Photo checks stay inconclusive until this library holds known-real or known-fake photos. Confirm suggestions from your Review queue as hunts capture them, or upload photos of a unit you know first-hand."
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
          if (!open) setRevokeTarget(null)
        }}
        title="Revoke reference"
        description={`This ${revokeTarget?.label ?? ''} reference stops counting toward the item's photo checks. There is no un-revoke.`}
        confirmLabel="Revoke"
        pending={revoke.isPending}
        onConfirm={() => revokeTarget && revoke.mutate(revokeTarget.id)}
      />

      <ConfirmDialog
        open={revokeAutoOpen}
        onOpenChange={setRevokeAutoOpen}
        title="Revoke auto-promoted references"
        description={`${autoCount} auto-promoted ${autoCount === 1 ? 'reference' : 'references'} will stop counting toward this item's photo checks. Human-confirmed and uploaded references are untouched.`}
        confirmLabel={`Revoke ${autoCount}`}
        pending={revokeAuto.isPending}
        onConfirm={() => revokeAuto.mutate()}
      />

      <UploadReferenceDialog itemId={itemId} open={uploadOpen} onOpenChange={setUploadOpen} />
    </Card>
  )
}
