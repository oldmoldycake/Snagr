import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, MoreHorizontal, Pencil, Plus, Trash2 } from 'lucide-react'
import { createSite, deleteSite, listCategories, listSites, updateSite } from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { Site } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/table'
import { relativeTime } from '@/lib/time'
import { RunButton } from '@/features/runs/RunButton'

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
        <DialogTitle>{site ? 'Edit site' : 'Add site'}</DialogTitle>
        <DialogDescription>
          The agent browses this site when it's linked to a category.
        </DialogDescription>
        <form
          className="mt-4 space-y-3"
          onSubmit={(e) => {
            e.preventDefault()
            save.mutate()
          }}
        >
          <div>
            <Label htmlFor="site-name">Name</Label>
            <Input
              id="site-name"
              required
              autoFocus
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
          <DialogFooter>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={save.isPending || !name.trim() || !baseUrl.trim()}>
              {save.isPending ? <Loader2 className="animate-spin" /> : null}
              {site ? 'Save changes' : 'Add site'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function SitesPage() {
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<Site | null>(null)
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
                        <RunButton scope="site" scopeId={site.id} label="Run" variant="ghost" size="sm" />
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="iconSm" aria-label={`Actions for ${site.name}`}>
                              <MoreHorizontal />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem
                              onSelect={() => {
                                setEditing(site)
                                setDialogOpen(true)
                              }}
                            >
                              <Pencil /> Edit
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem className="text-rise" onSelect={() => setDeleting(site)}>
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

      {dialogOpen ? (
        <SiteDialog
          key={editing?.id ?? 'new'}
          site={editing}
          open={dialogOpen}
          onOpenChange={setDialogOpen}
        />
      ) : null}
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
