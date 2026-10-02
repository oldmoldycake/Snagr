import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BellRing, Check, Copy, Eye, EyeOff, Loader2, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { createChannel, deleteChannel, listChannels, testChannel, testNewChannel, updateChannel } from '@/api/endpoints'
import { ApiError } from '@/api/client'
import { qk } from '@/api/queries'
import type { ChannelKind, NotificationChannel, NotificationEvent } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader, CardTitle } from '@/components/ui/card'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Segmented } from '@/components/ui/segmented'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { copyText } from '@/lib/clipboard'
import { cn } from '@/lib/cn'
import { useInstance, useSession } from '@/features/auth/useSession'
import { maskWebhookUrl } from './webhookUrl'

const EVENT_LABELS: Record<NotificationEvent, string> = {
  'target.hit': 'at target',
  'listing.new': 'new listings',
}

/** With two events every meaningful subset is "all", one, or the other — a
 *  segmented picker covers the whole space. Revisit when a third event lands. */
const EVENT_OPTIONS = [
  { value: 'all', label: 'Everything' },
  { value: 'target.hit', label: 'At target' },
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

  // shared by the test and the save, so a test goes exactly where the channel would
  const destination = () => ({
    kind,
    url: kind === 'ntfy' ? undefined : url.trim(),
    topic: kind === 'ntfy' ? topic.trim() || suggestedTopic : undefined,
  })

  const test = useMutation({
    mutationFn: () => testNewChannel(destination()),
    meta: { inlineError: true },
    onSuccess: () => toast.success('Test notification sent'),
  })

  const create = useMutation({
    mutationFn: () =>
      createChannel({
        ...destination(),
        name: name.trim(),
        events: events === 'all' ? null : [events],
      }),
    meta: { inlineError: true },
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
    if (!(await copyText(secret))) {
      toast.error("Couldn't copy — select the secret and copy it yourself")
      return
    }
    toast.success('Signing secret copied')
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
      test.reset()
      create.reset()
    }
  }

  // each request clears the other's error, so the form only ever shows the latest
  const failed = create.error ?? test.error
  const formError = failed instanceof ApiError ? failed : null
  const fieldError = (field: string) => formError?.fields?.[field] ?? null

  const sendTest = (
    <Button
      disabled={test.isPending || create.isPending}
      onClick={() => {
        create.reset()
        test.mutate()
      }}
    >
      {test.isPending ? <Loader2 className="animate-spin" /> : <BellRing />}
      Send test
    </Button>
  )

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent dismissible={secret == null}>
        <DialogHeader>
          <DialogTitle>Add a channel</DialogTitle>
          <DialogDescription>
            Where Snagr should send a push when something happens on an item you watch.
          </DialogDescription>
        </DialogHeader>

        {secret != null ? (
          <>
            <DialogBody className="space-y-3">
              <Label>Signing secret — shown once, store it now</Label>
              <div className="flex gap-2">
                <Input readOnly value={secret} className="font-mono sm:text-xs" onFocus={(e) => e.target.select()} />
                <Button onClick={copy} aria-label="Copy signing secret">
                  {copied ? <Check className="text-drop" /> : <Copy />}
                  {copied ? 'Copied' : 'Copy'}
                </Button>
              </div>
              <p className="text-xs text-ink-3">
                Every delivery carries an <code className="rounded-sm bg-well px-1 py-0.5 font-mono">X-Snagr-Signature</code>{' '}
                header — an HMAC-SHA256 of the timestamp and body under this secret.
              </p>
            </DialogBody>
            <DialogFooter>
              <Button variant="primary" onClick={() => close(false)}>
                I've saved it
              </Button>
            </DialogFooter>
          </>
        ) : (
          <form
            className="contents"
            onSubmit={(e) => {
              e.preventDefault()
              test.reset()
              create.mutate()
            }}
          >
            <DialogBody className="space-y-3">
              {formError && !formError.fields ? (
                <p role="alert" className="text-xs text-rise">
                  {formError.message}
                </p>
              ) : null}
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
                  <div className="flex gap-2">
                    <Input
                      id="channel-topic"
                      placeholder={suggestedTopic}
                      className="font-mono"
                      value={topic}
                      onChange={(e) => setTopic(e.target.value)}
                    />
                    {sendTest}
                  </div>
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
                  <div className="flex gap-2">
                    <Input
                      id="channel-url"
                      placeholder={
                        kind === 'discord' ? 'https://discord.com/api/webhooks/…' : 'https://example.com/hooks/snagr'
                      }
                      className="font-mono"
                      value={url}
                      onChange={(e) => setUrl(e.target.value)}
                    />
                    {sendTest}
                  </div>
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

            </DialogBody>

            <DialogFooter>
              <Button variant="ghost" onClick={() => close(false)}>
                Cancel
              </Button>
              <Button type="submit" variant="primary" className="max-sm:flex-[2]" disabled={create.isPending}>
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

/** Settings card for notification channels: add, enable/disable, test and delete them. */
export function ChannelsCard() {
  const [adding, setAdding] = useState(false)
  const [deleting, setDeleting] = useState<NotificationChannel | null>(null)
  const [revealed, setRevealed] = useState<Set<number>>(new Set())
  const queryClient = useQueryClient()

  const channels = useQuery({ queryKey: qk.channels, queryFn: listChannels })

  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => updateChannel(id, { enabled }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: qk.channels }),
  })

  const test = useMutation({
    mutationFn: (id: number) => testChannel(id),
    onSuccess: () => toast.success('Test notification sent'),
  })

  const remove = useMutation({
    mutationFn: (id: number) => deleteChannel(id),
    meta: { inlineError: true },
    onSuccess: () => {
      setDeleting(null)
      void queryClient.invalidateQueries({ queryKey: qk.channels })
    },
  })

  const toggleReveal = (id: number) => {
    setRevealed((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

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
        <p className="text-[14px] text-ink-2">
          Where your alerts go when an item reaches its target or Snagr finds a new listing. To silence one
          item, turn off Notify at target on its page.
        </p>

        {channels.isPending ? (
          <Skeleton className="h-16" />
        ) : (channels.data?.data.length ?? 0) === 0 ? (
          <p className="text-[14px] text-ink-3">No channels yet — notifications go nowhere until you add one.</p>
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
                  <div className="flex items-start gap-1">
                    <p
                      className={cn(
                        'min-w-0 font-mono text-xs text-ink-3',
                        revealed.has(channel.id) ? 'wrap-anywhere' : 'truncate',
                      )}
                    >
                      {channel.url == null
                        ? channel.topic
                        : revealed.has(channel.id)
                          ? channel.url
                          : maskWebhookUrl(channel.url)}
                      <span className="font-sans">
                        {' · '}
                        {channel.events == null
                          ? 'everything'
                          : channel.events.map((e) => EVENT_LABELS[e]).join(', ')}
                      </span>
                    </p>
                    {channel.url != null ? (
                      <button
                        type="button"
                        aria-label={`Show the full URL of ${channel.name}`}
                        aria-pressed={revealed.has(channel.id)}
                        className="tap-target relative -my-0.5 flex size-5 shrink-0 items-center justify-center rounded-sm text-ink-3 hover:bg-raised hover:text-ink"
                        onClick={() => toggleReveal(channel.id)}
                      >
                        {revealed.has(channel.id) ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
                      </button>
                    ) : null}
                  </div>
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
        onOpenChange={(o) => {
          if (o) return
          setDeleting(null)
          remove.reset()
        }}
        title={`Delete ${deleting?.name ?? 'channel'}?`}
        description="Notifications stop going here immediately. A webhook's signing secret cannot be recovered."
        pending={remove.isPending}
        error={remove.error instanceof ApiError ? remove.error.message : null}
        onConfirm={() => (deleting ? remove.mutate(deleting.id) : null)}
      />
    </Card>
  )
}
