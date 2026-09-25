import { useId, useRef, useState, type KeyboardEvent } from 'react'
import { flushSync } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, X } from 'lucide-react'
import { createSite, listSites } from '@/api/endpoints'
import { ApiError } from '@/api/client'
import { qk } from '@/api/queries'
import type { Site } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/cn'
import { defaultSiteName, findDuplicate, hostOf, isPlausibleUrl, normalizeBaseUrl } from './siteUrl'

type Notice = { kind: 'invalid' | 'duplicate'; text: string }

/**
 * Checklist of the instance's sites, with a last row that adds a site in place
 * and picks it. Used wherever a category's sites are chosen.
 */
export function SitePicker({ selected, onChange }: { selected: number[]; onChange: (ids: number[]) => void }) {
  const queryClient = useQueryClient()
  const sites = useQuery({ queryKey: qk.sites, queryFn: listSites })
  // "paused" is judged once, when the picker opens, rather than on every render
  const [openedAt] = useState(Date.now)

  const [adding, setAdding] = useState(false)
  const [url, setUrl] = useState('')
  const [name, setName] = useState('')
  const [nameTouched, setNameTouched] = useState(false)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [addedIds, setAddedIds] = useState<number[]>([])
  const [announcement, setAnnouncement] = useState('')

  const formId = useId()
  const urlId = useId()
  const nameId = useId()
  const urlRef = useRef<HTMLInputElement>(null)
  const addRowRef = useRef<HTMLButtonElement>(null)
  // a site just added is focused as soon as its row mounts
  const focusOnMount = useRef<number | null>(null)
  // Opened before the sites loaded, focus lands on the add row, the only control
  // there is; move it to the first site when the list arrives, unless the user
  // has since moved it themselves.
  const firstRowSeen = useRef(false)

  const create = useMutation({
    mutationFn: createSite,
    onSuccess: (site) => {
      // show the row now rather than after the refetch, so it can take focus
      queryClient.setQueryData<{ data: Site[] }>(qk.sites, (old) =>
        old ? { data: [...old.data.filter((s) => s.id !== site.id), site] } : old,
      )
      void queryClient.invalidateQueries({ queryKey: ['sites'] })
      setAddedIds((ids) => [...ids, site.id])
      focusOnMount.current = site.id
      onChange([...selected, site.id])
      closeForm()
      setAnnouncement(`${site.name} added and picked.`)
    },
  })

  const toggle = (id: number) => {
    onChange(selected.includes(id) ? selected.filter((s) => s !== id) : [...selected, id])
  }

  const openForm = () => {
    flushSync(() => setAdding(true))
    urlRef.current?.focus({ preventScroll: true })
  }

  function closeForm() {
    setAdding(false)
    setUrl('')
    setName('')
    setNameTouched(false)
    setNotice(null)
    create.reset()
  }

  const submit = () => {
    if (create.isPending) return
    setNotice(null)
    if (!isPlausibleUrl(url)) {
      setNotice({ kind: 'invalid', text: "⚠ That doesn't look like a URL." })
      urlRef.current?.focus()
      return
    }
    const duplicate = findDuplicate(url, sites.data?.data ?? [])
    if (duplicate) {
      if (!selected.includes(duplicate.id)) onChange([...selected, duplicate.id])
      setNotice({ kind: 'duplicate', text: `⚠ ${duplicate.name} is already listed. Picked it for you.` })
      return
    }
    create.mutate({ name: name.trim() || defaultSiteName(url), base_url: normalizeBaseUrl(url) })
  }

  // Enter submits the add-a-site form, never the dialog's form around it
  const submitOnEnter = (e: KeyboardEvent) => {
    if (e.key !== 'Enter') return
    e.preventDefault()
    submit()
  }

  const apiError =
    create.error instanceof ApiError
      ? (create.error.fields?.base_url ?? create.error.fields?.name ?? create.error.message)
      : null

  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between font-mono text-[10px] font-medium tracking-[0.14em] text-ink-3 uppercase">
        <span>Sites</span>
        <span className="text-ink-2 tnum">{selected.length} picked</span>
      </div>

      <div role="group" aria-label="Sites" className="overflow-hidden rounded-md border border-hairline-strong bg-well">
        {sites.isLoading ? (
          <div className="space-y-2 p-3">
            <Skeleton className="h-5" />
            <Skeleton className="h-5" />
          </div>
        ) : sites.isError ? (
          <p role="alert" className="px-3 py-2.5 text-xs text-rise">
            {sites.error.message}
          </p>
        ) : (
          <div className="divide-y divide-hairline">
            {sites.data?.data.map((site, i) => {
              const picked = selected.includes(site.id)
              const paused = site.paused_until != null && new Date(site.paused_until).getTime() > openedAt
              const added = addedIds.includes(site.id)
              return (
                <button
                  key={site.id}
                  ref={(el) => {
                    if (!el) return
                    if (i === 0 && !firstRowSeen.current) {
                      firstRowSeen.current = true
                      if (document.activeElement === addRowRef.current) el.focus({ preventScroll: true })
                    }
                    if (focusOnMount.current === site.id) {
                      focusOnMount.current = null
                      el.focus()
                    }
                  }}
                  type="button"
                  role="checkbox"
                  aria-checked={picked}
                  onClick={() => toggle(site.id)}
                  className={cn(
                    'relative grid h-10 w-full grid-cols-[16px_20px_auto_minmax(0,1fr)_auto] items-center gap-2.5 px-3 text-left transition-colors',
                    'hover:bg-[rgb(193_255_208/0.03)] focus-visible:-outline-offset-2',
                    'max-sm:grid-cols-[16px_20px_minmax(0,1fr)_auto]',
                    // the picked edge: a lume bar that grows from the middle, no row fill
                    'before:absolute before:inset-y-0 before:left-0 before:w-0.5 before:scale-y-0 before:bg-lume before:transition-transform before:duration-150 before:ease-shelf aria-checked:before:scale-y-100',
                    added && 'animate-pick-new',
                  )}
                >
                  <span
                    className={cn(
                      'grid size-4 place-items-center rounded-[3px] border transition-colors',
                      picked ? 'border-lume bg-lume' : 'border-hairline-strong',
                    )}
                  >
                    <svg
                      viewBox="0 0 10 10"
                      aria-hidden
                      className={cn('size-2.5 transition-opacity', picked ? 'opacity-100' : 'opacity-0')}
                    >
                      <path
                        d="M2 5.2 4.1 7.3 8 2.9"
                        fill="none"
                        stroke="#1a1208"
                        strokeWidth="1.8"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </span>
                  <span
                    aria-hidden
                    className="grid size-5 place-items-center rounded-[3px] border border-hairline bg-raised font-mono text-[9.5px] font-medium text-ink-2 uppercase"
                  >
                    {site.name.slice(0, 2)}
                  </span>
                  <span className="truncate text-[13px] text-ink">{site.name}</span>
                  <span className="truncate font-mono text-[11px] text-ink-3 max-sm:hidden">
                    {hostOf(site.base_url) ?? site.base_url}
                  </span>
                  {paused ? (
                    <span className="font-mono text-[11px] whitespace-nowrap text-warn">⚠ paused</span>
                  ) : added ? (
                    <span className="font-mono text-[11px] text-lume">new</span>
                  ) : (
                    <span className="font-mono text-[11px] whitespace-nowrap text-ink-3 tnum">
                      {site.listing_count} tracked
                    </span>
                  )}
                </button>
              )
            })}
          </div>
        )}

        <button
          ref={addRowRef}
          type="button"
          aria-expanded={adding}
          aria-controls={formId}
          hidden={adding}
          onClick={openForm}
          className="flex h-10 w-full items-center gap-2.5 border-t border-hairline px-3 text-[13px] text-ink-3 transition-colors hover:text-lume focus-visible:-outline-offset-2"
        >
          <span aria-hidden className="w-4 text-center font-mono">
            ＋
          </span>
          Add a site that isn't listed
        </button>

        <div
          id={formId}
          className={cn(
            'grid transition-[grid-template-rows] duration-[180ms] ease-shelf',
            adding ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]',
          )}
        >
          <div className="min-h-0 overflow-hidden" inert={!adding}>
            <div className="grid gap-2 border-t border-hairline px-3 pt-2.5 pb-3">
              <div className="grid grid-cols-[1.4fr_1fr_auto_auto] items-end gap-1.5 max-sm:grid-cols-2">
                <div>
                  <Label htmlFor={urlId}>Site URL</Label>
                  <Input
                    ref={urlRef}
                    id={urlId}
                    autoComplete="off"
                    placeholder="facebook.com/marketplace"
                    aria-invalid={notice?.kind === 'invalid' || undefined}
                    className="h-[30px] font-mono text-[12.5px] aria-invalid:border-rise/60"
                    value={url}
                    onChange={(e) => {
                      setUrl(e.target.value)
                      setNotice(null)
                      if (!nameTouched) setName(defaultSiteName(e.target.value))
                    }}
                    onKeyDown={submitOnEnter}
                  />
                </div>
                <div>
                  <Label htmlFor={nameId}>Name</Label>
                  <Input
                    id={nameId}
                    autoComplete="off"
                    className="h-[30px] text-[12.5px]"
                    value={name}
                    onChange={(e) => {
                      setName(e.target.value)
                      setNameTouched(true)
                    }}
                    onKeyDown={submitOnEnter}
                  />
                </div>
                <Button className="h-[30px]" disabled={create.isPending} onClick={submit}>
                  {create.isPending ? <Loader2 className="animate-spin" /> : null}
                  Add
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-[30px]"
                  aria-label="Cancel adding a site"
                  onClick={() => {
                    flushSync(closeForm)
                    addRowRef.current?.focus({ preventScroll: true })
                  }}
                >
                  <X />
                </Button>
              </div>
              {notice ? (
                <p
                  role={notice.kind === 'invalid' ? 'alert' : 'status'}
                  className={cn('text-xs', notice.kind === 'invalid' ? 'text-rise' : 'text-warn')}
                >
                  {notice.text}
                </p>
              ) : null}
              {apiError ? (
                <p role="alert" className="text-xs text-rise">
                  {apiError}
                </p>
              ) : null}
              <p className="text-xs text-ink-3">Added sites are shared with everyone on this instance.</p>
            </div>
          </div>
        </div>
      </div>

      <p aria-live="polite" className="sr-only">
        {announcement}
      </p>
    </div>
  )
}
