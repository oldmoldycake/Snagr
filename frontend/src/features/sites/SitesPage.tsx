import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Pencil, Plus, Trash2 } from 'lucide-react'
import { createSite, deleteSite, listCategories, listSites, updateSite } from '@/api/endpoints'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/table'
import { relativeTime } from '@/lib/time'
import { HuntButton } from '@/features/activity/HuntButton'

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
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['sites'] })
      onOpenChange(false)
    },
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{site ? 'Edit site' : 'Add site'}</DialogTitle>
          <DialogDescription>
            The agent browses this site when it's linked to a category.
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

/** The site list: add, edit and delete the stores the hunter searches. */
export function SitesPage() {
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<Site | null>(null)
  // Bumped on every open so the dialog's form starts fresh, while staying
  // mounted after close long enough to play its exit animation.
  const [dialogSession, setDialogSession] = useState(0)
  const [deleting, setDeleting] = useState<Site | null>(null)
  const queryClient = useQueryClient()

  const sites = useQuery({ queryKey: qk.sites, queryFn: listSites })
  const categories = useQuery({ queryKey: qk.categories, queryFn: listCategories })

  const remove = useMutation({
    mutationFn: (site: Site) => deleteSite(site.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['sites'] })
      void queryClient.invalidateQueries({ queryKey: ['items'] })
      void queryClient.invalidateQueries({ queryKey: ['categories'] })
      setDeleting(null)
    },
  })

  const categoryName = (id: number) => categories.data?.data.find((c) => c.id === id)?.name ?? '…'
  const rows = sites.data?.data ?? []

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <h1 className="font-display text-[26px] leading-tight font-semibold tracking-[0.05em] text-ink uppercase">Sites</h1>
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
      </div>

      <Card>
        <CardBody className="px-0 py-1">
          {sites.isLoading ? (
            <div className="space-y-2 p-4">
              <Skeleton className="h-6" />
              <Skeleton className="h-6" />
            </div>
          ) : rows.length === 0 ? (
            <EmptyState
              className="m-4 border-0"
              title="No sites yet"
              description="Add the stores you want the agent to search, then link them to categories."
            />
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Site</TH>
                  <TH>Base URL</TH>
                  <TH className="hidden md:table-cell">Used by</TH>
                  <TH className="text-right">Listings</TH>
                  <TH className="hidden md:table-cell">Last check</TH>
                  <TH className="w-24" />
                </TR>
              </THead>
              <TBody>
                {rows.map((site) => (
                  <TR key={site.id}>
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
                    <TD className="hidden md:table-cell">
                      <span className="flex flex-wrap gap-1">
                        {site.category_ids.length === 0 ? (
                          <span className="text-xs text-ink-3">not linked</span>
                        ) : (
                          site.category_ids.map((cid) => (
                            <Badge key={cid} variant="muted">
                              {categoryName(cid)}
                            </Badge>
                          ))
                        )}
                      </span>
                    </TD>
                    <TD className="text-right font-mono text-ink-2 tnum">{site.listing_count}</TD>
                    <TD className="hidden text-xs whitespace-nowrap text-ink-3 md:table-cell">{relativeTime(site.last_checked_at)}</TD>
                    <TD>
                      <div className="flex items-center justify-end gap-1">
                        <HuntButton scope="site" scopeId={site.id} label="Hunt this site" variant="ghost" size="sm" />
                        <DropdownMenu>
                          <DropdownMenuMoreTrigger label={`Actions for ${site.name}`} />
                          <DropdownMenuContent align="end" className="w-60">
                            <DropdownMenuLabel
                              title={site.name}
                              meta={
                                <span className="font-mono text-[10.5px] whitespace-nowrap text-ink-3 tnum">
                                  {site.listing_count} {site.listing_count === 1 ? 'listing' : 'listings'}
                                </span>
                              }
                            >
                              {site.category_ids.length === 0 ? (
                                <span className="font-mono text-[10.5px] text-ink-3">not linked to a category</span>
                              ) : (
                                <span className="flex flex-wrap gap-1 font-mono text-[10.5px] text-ink-2">
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
                            <DropdownMenuItem
                              onSelect={() => {
                                setEditing(site)
                                setDialogSession((n) => n + 1)
                                setDialogOpen(true)
                              }}
                            >
                              <Pencil /> Edit
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem tone="danger" onSelect={() => setDeleting(site)}>
                              <Trash2 /> Delete
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
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
            ? deleting.listing_count > 0
              ? `${deleting.name} will be removed and its ${deleting.listing_count} listing${deleting.listing_count === 1 ? '' : 's'} deactivated.`
              : `${deleting.name} will be removed.`
            : ''
        }
        confirmLabel="Delete site"
        pending={remove.isPending}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting)
        }}
      />
    </div>
  )
}
