import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BellRing, Check, Copy, Loader2, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { createChannel, deleteChannel, listChannels, testChannel, updateChannel } from '@/api/endpoints'
import { ApiError } from '@/api/client'
import { qk } from '@/api/queries'
import type { ChannelKind, NotificationChannel, NotificationEvent } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader, CardTitle } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Segmented } from '@/components/ui/segmented'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { useInstance, useSession } from '@/features/auth/useSession'

const EVENT_LABELS: Record<NotificationEvent, string> = {
  'target.hit': 'target hits',
  'listing.new': 'new listings',
}

/** With two events every meaningful subset is "all", one, or the other — a
 *  segmented picker covers the whole space. Revisit when a third event lands. */
const EVENT_OPTIONS = [
  { value: 'all', label: 'All events' },
  { value: 'target.hit', label: 'Target hits' },
  { value: 'listing.new', label: 'New listings' },
] as const

function suggestedTopicFor(user: { email: string; id: number } | undefined): string {
  return `snagr-${(user?.email.split('@')[0] ?? 'me').replace(/[^a-z0-9]/gi, '').toLowerCase()}-${String(user?.id ?? 0).padStart(2, '0')}${Math.abs((user?.email ?? '').split('').reduce((a, c) => a + c.charCodeAt(0), 0) % 97).toString(16)}`
}

function NewChannelDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { data: user } = useSession()
  const { data: instance } = useInstance()
  const queryClient = useQueryClient()

  const [kind, setKind] = useState<ChannelKind>('discord')
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [topic, setTopic] = useState('')
  const [events, setEvents] = useState<(typeof EVENT_OPTIONS)[number]['value']>('all')
  const [secret, setSecret] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const ntfyAvailable = instance?.ntfy_server_url != null
  const kindOptions = [
    ...(ntfyAvailable ? [{ value: 'ntfy' as const, label: 'ntfy' }] : []),
    { value: 'discord' as const, label: 'Discord' },
    { value: 'webhook' as const, label: 'Webhook' },
  ]
  const suggestedTopic = suggestedTopicFor(user)

  const create = useMutation({
    mutationFn: () =>
      createChannel({
        kind,
        name: name.trim(),
        url: kind === 'ntfy' ? undefined : url.trim(),
        topic: kind === 'ntfy' ? topic.trim() || suggestedTopic : undefined,
        events: events === 'all' ? null : [events],
      }),
    onSuccess: (channel) => {
      void queryClient.invalidateQueries({ queryKey: qk.channels })
      if (channel.secret != null) {
        setSecret(channel.secret)
      } else {
        close(false)
        toast.success('Channel added')
      }
    },
  })

  const copy = async () => {
    if (secret == null) return
    await navigator.clipboard.writeText(secret)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const close = (o: boolean) => {
    onOpenChange(o)
    if (!o) {
      setKind('discord')
      setName('')
      setUrl('')
      setTopic('')
      setEvents('all')
      setSecret(null)
      setCopied(false)
      create.reset()
    }
  }

  const createError = create.error instanceof ApiError ? create.error : null
  const fieldError = (field: string) => createError?.fields?.[field] ?? null

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent>
        <DialogTitle>Add a channel</DialogTitle>
        <DialogDescription>
          Where Snagr should send a push when something happens on an item you watch.
        </DialogDescription>

        {secret != null ? (
          <div className="mt-4 space-y-3">
            <Label>Signing secret — shown once, store it now</Label>
            <div className="flex gap-2">
              <Input readOnly value={secret} className="font-mono text-xs" onFocus={(e) => e.target.select()} />
              <Button onClick={copy} aria-label="Copy signing secret">
                {copied ? <Check className="text-drop" /> : <Copy />}
                {copied ? 'Copied' : 'Copy'}
              </Button>
            </div>
            <p className="text-xs text-ink-3">
              Every delivery carries an <code className="rounded-sm bg-well px-1 py-0.5 font-mono">X-Snagr-Signature</code>{' '}
              header — an HMAC-SHA256 of the timestamp and body under this secret.
            </p>
            <DialogFooter>
              <Button variant="primary" onClick={() => close(false)}>
                Done
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <form
            className="mt-4 space-y-3"
            onSubmit={(e) => {
              e.preventDefault()
              create.mutate()
            }}
          >
            <div>
              <Label>Kind</Label>
              <Segmented options={kindOptions} value={kind} onChange={setKind} ariaLabel="Channel kind" />
              {!ntfyAvailable ? (
                <p className="mt-1.5 text-xs text-ink-3">
                  ntfy channels need{' '}
                  <code className="rounded-sm bg-well px-1 py-0.5 font-mono break-all">NTFY_SERVER_URL</code> configured
                  on the backend.
                </p>
              ) : null}
            </div>

            <div>
              <Label htmlFor="channel-name">Name</Label>
              <Input
                id="channel-name"
                placeholder={kind === 'ntfy' ? 'my phone' : kind === 'discord' ? 'deals channel' : 'automation'}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              {fieldError('name') ? <p className="mt-1 text-xs text-rise">{fieldError('name')}</p> : null}
            </div>

            {kind === 'ntfy' ? (
              <div>
                <Label htmlFor="channel-topic">Topic</Label>
                <Input
                  id="channel-topic"
                  placeholder={suggestedTopic}
                  className="font-mono"
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                />
                {fieldError('topic') ? <p className="mt-1 text-xs text-rise">{fieldError('topic')}</p> : null}
                <p className="mt-1.5 text-xs text-ink-3">
                  Subscribe to{' '}
                  <code className="rounded-sm bg-well px-1 py-0.5 font-mono break-all">
                    {instance?.ntfy_server_url}/{topic.trim() || suggestedTopic}
                  </code>{' '}
                  in the ntfy app.
                </p>
              </div>
            ) : (
              <div>
                <Label htmlFor="channel-url">{kind === 'discord' ? 'Discord webhook URL' : 'Webhook URL'}</Label>
                <Input
                  id="channel-url"
                  placeholder={
                    kind === 'discord' ? 'https://discord.com/api/webhooks/…' : 'https://example.com/hooks/snagr'
                  }
                  className="font-mono"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                />
                {fieldError('url') ? <p className="mt-1 text-xs text-rise">{fieldError('url')}</p> : null}
                <p className="mt-1.5 text-xs text-ink-3">
                  {kind === 'discord'
                    ? 'Server Settings → Integrations → Webhooks → New Webhook → Copy URL.'
                    : 'Snagr POSTs a signed JSON envelope here — the signing secret is shown once after creating.'}
                </p>
              </div>
            )}

            <div>
              <Label>Events</Label>
              <Segmented options={EVENT_OPTIONS} value={events} onChange={setEvents} ariaLabel="Events to receive" />
            </div>

            <DialogFooter>
              <Button variant="ghost" onClick={() => close(false)}>
                Cancel
              </Button>
              <Button type="submit" variant="primary" disabled={create.isPending}>
                {create.isPending ? <Loader2 className="animate-spin" /> : null}
                Add channel
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

export function ChannelsCard() {
  const [adding, setAdding] = useState(false)
  const [deleting, setDeleting] = useState<NotificationChannel | null>(null)
  const queryClient = useQueryClient()

  const channels = useQuery({ queryKey: qk.channels, queryFn: listChannels })

  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => updateChannel(id, { enabled }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: qk.channels }),
  })

  const test = useMutation({
    mutationFn: (id: number) => testChannel(id),
    onSuccess: () => toast.success('Test notification sent'),
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not send the test notification'),
  })

  const remove = useMutation({
    mutationFn: (id: number) => deleteChannel(id),
    onSuccess: () => {
      setDeleting(null)
      void queryClient.invalidateQueries({ queryKey: qk.channels })
    },
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <BellRing className="size-4 text-ink-3" /> Notifications
        </CardTitle>
        <Button variant="primary" size="sm" onClick={() => setAdding(true)}>
          <Plus /> Add channel
        </Button>
      </CardHeader>
      <CardBody className="space-y-3">
        <p className="text-[13px] text-ink-2">
          Channels this account's notifications go to — a target price hit, a new listing found. Toggle
          "Notify at target" on each item to control which watches fire.
        </p>

        {channels.isPending ? (
          <Skeleton className="h-16" />
        ) : (channels.data?.data.length ?? 0) === 0 ? (
          <p className="text-[13px] text-ink-3">No channels yet — notifications go nowhere until you add one.</p>
        ) : (
          <ul className="divide-y divide-hairline">
            {channels.data?.data.map((channel) => (
              <li key={channel.id} className="flex items-center gap-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm text-ink">{channel.name}</span>
                    <Badge variant="muted" className="font-mono">
                      {channel.kind}
                    </Badge>
                  </div>
                  <p className="truncate font-mono text-xs text-ink-3">
                    {channel.kind === 'ntfy' ? channel.topic : channel.url}
                    <span className="font-sans">
                      {' · '}
                      {channel.events == null
                        ? 'all events'
                        : channel.events.map((e) => EVENT_LABELS[e]).join(', ')}
                    </span>
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={test.isPending}
                  onClick={() => test.mutate(channel.id)}
                >
                  {test.isPending && test.variables === channel.id ? (
                    <Loader2 className="animate-spin" />
                  ) : (
                    <BellRing />
                  )}
                  Test
                </Button>
                <Switch
                  checked={channel.enabled}
                  disabled={toggle.isPending}
                  onCheckedChange={(enabled) => toggle.mutate({ id: channel.id, enabled })}
                  aria-label={`${channel.enabled ? 'Disable' : 'Enable'} ${channel.name}`}
                />
                <Button
                  variant="ghost"
                  size="iconSm"
                  aria-label={`Delete ${channel.name}`}
                  onClick={() => setDeleting(channel)}
                >
                  <Trash2 />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </CardBody>

      <NewChannelDialog open={adding} onOpenChange={setAdding} />
      <ConfirmDialog
        open={deleting != null}
        onOpenChange={(o) => (o ? null : setDeleting(null))}
        title={`Delete ${deleting?.name ?? 'channel'}?`}
        description="Notifications stop going here immediately. A webhook's signing secret cannot be recovered."
        pending={remove.isPending}
        onConfirm={() => (deleting ? remove.mutate(deleting.id) : null)}
      />
    </Card>
  )
}
