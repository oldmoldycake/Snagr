import { Fragment, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Loader2, Pencil, Plus, Trash2 } from 'lucide-react'
import { createSite, deleteSite, listCategories, listSites, updateSite } from '@/api/endpoints'
import { ApiError } from '@/api/client'
import { qk } from '@/api/queries'
import type { Site } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuMoreTrigger,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { EmptyState } from '@/components/ui/empty-state'
import { ErrorState } from '@/components/ui/error-state'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/table'
import { RelativeTime } from '@/components/ui/relative-time'
import { cn } from '@/lib/cn'
import { clockTime } from '@/lib/time'
import { usePageTitle } from '@/lib/usePageTitle'
import { HuntButton } from '@/features/activity/HuntButton'
import { useTick } from '@/features/activity/useTick'
import { useSession } from '@/features/auth/useSession'
import { isPaused } from './sitePause'

function SiteDialog({
  site,
  open,
  onOpenChange,
}: {
  site: Site | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [name, setName] = useState(site?.name ?? '')
  const [baseUrl, setBaseUrl] = useState(site?.base_url ?? '')
  const queryClient = useQueryClient()

  const save = useMutation({
    mutationFn: () =>
      site
        ? updateSite(site.id, { name: name.trim(), base_url: baseUrl.trim() })
        : createSite({ name: name.trim(), base_url: baseUrl.trim() }),
    meta: { inlineError: true },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['sites'] })
      if (site) {
        // a rename reaches every row that carries the site's name
        void queryClient.invalidateQueries({ queryKey: ['items'] })
        void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
        void queryClient.invalidateQueries({ queryKey: ['jobs'] })
      }
      onOpenChange(false)
    },
  })

  const errorMessage =
    save.error instanceof ApiError
      ? (save.error.fields?.name ?? save.error.fields?.base_url ?? save.error.message)
      : null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{site ? 'Edit site' : 'Add site'}</DialogTitle>
          <DialogDescription>
            Snagr searches this site for items in the categories it's linked to.
          </DialogDescription>
        </DialogHeader>
        <form
          className="contents"
          onSubmit={(e) => {
            e.preventDefault()
            save.mutate()
          }}
        >
          <DialogBody className="space-y-3">
            {errorMessage ? (
              <p role="alert" className="text-xs text-rise">
                {errorMessage}
              </p>
            ) : null}
            <div>
              <Label htmlFor="site-name">Name</Label>
              <Input
                id="site-name"
                required
                placeholder="newegg.com"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="site-url">Base URL</Label>
              <Input
                id="site-url"
                type="url"
                required
                placeholder="https://www.newegg.com"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
              />
            </div>
          </DialogBody>
          <DialogFooter>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" className="max-sm:flex-[2]" disabled={save.isPending || !name.trim() || !baseUrl.trim()}>
              {save.isPending ? <Loader2 className="animate-spin" /> : null}
              {site ? 'Save changes' : 'Add site'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/**
 * A paused site, said on its row: the circuit breaker stopped reading it after
 * it kept failing, and nothing on it is checked or hunted until the pause
 * lifts. Sites are shared, so only an admin can lift the pause early.
 */
function SitePause({ site, isAdmin, className }: { site: Site; isAdmin: boolean; className?: string }) {
  const queryClient = useQueryClient()
  const resume = useMutation({
    mutationFn: () => updateSite(site.id, { paused_until: null }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['jobs'] })
      void queryClient.invalidateQueries({ queryKey: ['sites'] })
    },
  })

  return (
    <div className={cn('flex flex-wrap items-center gap-x-3 gap-y-1.5', className)}>
      <Badge variant="warn" className="font-mono whitespace-nowrap">
        <span aria-hidden>⚠</span> paused until {clockTime(site.paused_until)}
      </Badge>
      <p className="min-w-0 flex-1 basis-48 text-xs leading-relaxed text-ink-2">
        {site.paused_reason ? `${site.paused_reason}. ` : null}Its checks and hunts wait until then.
      </p>
      {isAdmin ? (
        <Button variant="warn" size="sm" disabled={resume.isPending} onClick={() => resume.mutate()}>
          Resume now
        </Button>
      ) : null}
    </div>
  )
}

/** A site's row actions: hunt it, and for an admin, the edit/delete menu. */
function SiteActions({
  site,
  categoryName,
  isAdmin,
  onEdit,
  onDelete,
}: {
  site: Site
  categoryName: (id: number) => string
  isAdmin: boolean
  onEdit: () => void
  onDelete: () => void
}) {
  return (
    <div className="flex items-center justify-end gap-1">
      <HuntButton
        scope="site"
        scopeId={site.id}
        label="Hunt"
        unavailable={isPaused(site) ? `${site.name} is paused until ${clockTime(site.paused_until)}` : undefined}
        variant="ghost"
        size="sm"
      />
      {isAdmin ? (
        <DropdownMenu>
          <DropdownMenuMoreTrigger label={`Actions for ${site.name}`} />
          <DropdownMenuContent align="end" className="w-60">
            <DropdownMenuLabel
              title={site.name}
              meta={
                <span className="font-mono text-[12px] whitespace-nowrap text-ink-3 tnum">
                  {site.listing_count} {site.listing_count === 1 ? 'listing' : 'listings'}
                </span>
              }
            >
              {site.category_ids.length === 0 ? (
                <span className="font-mono text-[12px] text-ink-3">not linked to a category</span>
              ) : (
                <span className="flex flex-wrap gap-1 font-mono text-[12px] text-ink-2">
                  {site.category_ids.map((cid) => (
                    <span
                      key={cid}
                      className="inline-flex h-[17px] items-center rounded-[3px] border border-hairline bg-raised px-[5px]"
                    >
                      {categoryName(cid)}
                    </span>
                  ))}
                </span>
              )}
            </DropdownMenuLabel>
            <DropdownMenuItem onSelect={onEdit}>
              <Pencil /> Edit
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem tone="danger" onSelect={onDelete}>
              <Trash2 /> Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
    </div>
  )
}

/** The site list: the stores the hunter searches. Sites are shared, so only an admin adds, edits or deletes one. */
export function SitesPage() {
  usePageTitle('Sites')
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<Site | null>(null)
  // Bumped on every open so the dialog's form starts fresh, while staying
  // mounted after close long enough to play its exit animation.
  const [dialogSession, setDialogSession] = useState(0)
  const [deleting, setDeleting] = useState<Site | null>(null)
  const queryClient = useQueryClient()
  const isAdmin = useSession().data?.role === 'admin'

  const sites = useQuery({ queryKey: qk.sites, queryFn: listSites })
  const categories = useQuery({ queryKey: qk.categories, queryFn: listCategories })

  const remove = useMutation({
    mutationFn: (site: Site) => deleteSite(site.id),
    meta: { inlineError: true },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['sites'] })
      void queryClient.invalidateQueries({ queryKey: ['items'] })
      void queryClient.invalidateQueries({ queryKey: ['categories'] })
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      setDeleting(null)
    },
  })

  const removeError = remove.error instanceof ApiError ? remove.error.message : null
  const categoryById = (id: number) => categories.data?.data.find((c) => c.id === id)
  const categoryName = (id: number) => categoryById(id)?.name ?? '…'
  const rows = sites.data?.data ?? []
  // a pause lifts on its own, and the row should stop saying paused when it does
  useTick(rows.some((site) => isPaused(site)))
  const openEdit = (site: Site) => {
    setEditing(site)
    setDialogSession((n) => n + 1)
    setDialogOpen(true)
  }
  const openDelete = (site: Site) => {
    remove.reset()
    setDeleting(site)
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <h1 className="font-display text-[26px] leading-tight font-semibold tracking-[0.05em] text-ink uppercase">Sites</h1>
        {isAdmin ? (
          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              setEditing(null)
              setDialogSession((n) => n + 1)
              setDialogOpen(true)
            }}
          >
            <Plus /> Add site
          </Button>
        ) : null}
      </div>

      <Card>
        <CardBody className="px-0 py-1">
          {sites.isLoading ? (
            <div className="space-y-2 p-4">
              <Skeleton className="h-6" />
              <Skeleton className="h-6" />
            </div>
          ) : sites.isError ? (
            <ErrorState
              className="m-4 border-0"
              title="Couldn't load the sites"
              error={sites.error}
              onRetry={() => void sites.refetch()}
              retrying={sites.isFetching}
            />
          ) : rows.length === 0 ? (
            <EmptyState
              className="m-4 border-0"
              title="No sites yet"
              description={
                isAdmin
                  ? 'Add the sites you want Snagr to search, then link them to categories.'
                  : 'An admin adds the sites Snagr searches and links them to categories.'
              }
            />
          ) : (
            <>
              {/* under md the table won't fit, so each site stacks into a card
                  with its actions in reach instead of behind a sideways scroll */}
              <ul className="md:hidden">
                {rows.map((site) => (
                  <li key={site.id} className="flex items-center gap-2 border-b border-hairline px-3 py-2.5 last:border-0">
                    <div className="min-w-0 flex-1">
                      <p className="font-medium wrap-anywhere text-ink">{site.name}</p>
                      <a
                        href={site.base_url}
                        target="_blank"
                        rel="noreferrer"
                        title={site.base_url}
                        className="block truncate text-xs text-lume hover:underline"
                      >
                        {site.base_url}
                      </a>
                      <p className="mt-0.5 font-mono text-[12px] text-ink-3 tnum">
                        {site.listing_count} {site.listing_count === 1 ? 'listing' : 'listings'} ·{' '}
                        {site.last_checked_at ? (
                          <>
                            checked <RelativeTime iso={site.last_checked_at} />
                          </>
                        ) : (
                          'never checked'
                        )}
                      </p>
                      {isPaused(site) ? <SitePause site={site} isAdmin={isAdmin} className="mt-1.5" /> : null}
                    </div>
                    <SiteActions
                      site={site}
                      categoryName={categoryName}
                      isAdmin={isAdmin}
                      onEdit={() => openEdit(site)}
                      onDelete={() => openDelete(site)}
                    />
                  </li>
                ))}
              </ul>
              <Table className="max-md:hidden">
                <THead>
                  <TR>
                    <TH>Site</TH>
                    <TH>Base URL</TH>
                    <TH>Used by</TH>
                    <TH className="text-right">Listings</TH>
                    <TH>Last check</TH>
                    <TH className="w-24" />
                  </TR>
                </THead>
                <TBody>
                  {rows.map((site) => (
                    <Fragment key={site.id}>
                      <TR className={cn(isPaused(site) && 'border-b-0')}>
                        <TD className="font-medium text-ink">{site.name}</TD>
                        <TD>
                          <a
                            href={site.base_url}
                            target="_blank"
                            rel="noreferrer"
                            title={site.base_url}
                            className="inline-block max-w-[40vw] truncate align-middle text-xs text-lume hover:underline"
                          >
                            {site.base_url}
                          </a>
                        </TD>
                        <TD>
                          <span className="flex flex-wrap gap-1">
                            {site.category_ids.length === 0 ? (
                              <span className="text-xs text-ink-3">not linked</span>
                            ) : (
                              site.category_ids.map((cid) => {
                                const category = categoryById(cid)
                                return category ? (
                                  <Link key={cid} to={`/categories/${category.slug}`} className="rounded-sm">
                                    <Badge variant="muted" className="transition-colors hover:border-lume/40 hover:text-lume">
                                      {category.name}
                                    </Badge>
                                  </Link>
                                ) : (
                                  <Badge key={cid} variant="muted">
                                    …
                                  </Badge>
                                )
                              })
                            )}
                          </span>
                        </TD>
                        <TD className="text-right font-mono text-ink-2 tnum">{site.listing_count}</TD>
                        <TD className="text-xs whitespace-nowrap text-ink-3"><RelativeTime iso={site.last_checked_at} /></TD>
                        <TD>
                          <SiteActions
                            site={site}
                            categoryName={categoryName}
                            isAdmin={isAdmin}
                            onEdit={() => openEdit(site)}
                            onDelete={() => openDelete(site)}
                          />
                        </TD>
                      </TR>
                      {isPaused(site) ? (
                        <TR>
                          <TD colSpan={6} className="pt-0 pb-2.5">
                            <SitePause site={site} isAdmin={isAdmin} />
                          </TD>
                        </TR>
                      ) : null}
                    </Fragment>
                  ))}
                </TBody>
              </Table>
            </>
          )}
        </CardBody>
      </Card>

      <SiteDialog key={`site-${dialogSession}`} site={editing} open={dialogOpen} onOpenChange={setDialogOpen} />
      <ConfirmDialog
        open={deleting != null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null)
        }}
        title="Delete site"
        description={
          deleting
            ? `${deleting.name} will be removed from every category and item. Every listing found on it${
                deleting.listing_count > 0 ? `, including the ${deleting.listing_count} being tracked,` : ''
              } is deleted with its price history, for every user. This can't be undone.`
            : ''
        }
        confirmLabel="Delete site"
        pending={remove.isPending}
        error={removeError}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting)
        }}
      />
    </div>
  )
}
