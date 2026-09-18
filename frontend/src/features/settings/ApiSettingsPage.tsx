import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Copy, KeyRound, Loader2, Plug, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { createToken, listTokens, revokeToken } from '@/api/endpoints'
import { ApiError } from '@/api/client'
import { qk } from '@/api/queries'
import type { ApiToken, ApiTokenScope } from '@/api/types'
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
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/table'
import { formatDateTime, relativeTime } from '@/lib/time'
import { useInstance } from '@/features/auth/useSession'
import { SettingsTabs } from '@/features/settings/SettingsTabs'

const TOKEN_PLACEHOLDER = '<your-token>'

/** The API is same-origin, so the page's own origin is where agents connect too. */
function mcpUrl(): string {
  return `${window.location.origin}/api/mcp`
}

type ClientKind = 'claude' | 'json' | 'hermes' | 'openclaw' | 'curl'

const CLIENT_OPTIONS: readonly { value: ClientKind; label: string }[] = [
  { value: 'claude', label: 'Claude Code' },
  { value: 'json', label: 'JSON' },
  { value: 'hermes', label: 'Hermes' },
  { value: 'openclaw', label: 'OpenClaw' },
  { value: 'curl', label: 'curl' },
]

/**
 * Ready-to-paste config per client. Every one is the same thing underneath —
 * the MCP URL plus a bearer header — spelled the way that client's config
 * wants it. The formats come from each project's docs; keep them in sync.
 */
function snippetFor(kind: ClientKind, url: string, token: string): { code: string; hint: string } {
  const bearer = `Bearer ${token}`
  switch (kind) {
    case 'claude':
      return {
        code: `claude mcp add --transport http snagr ${url} --header "Authorization: ${bearer}"`,
        hint: 'Run in a terminal; Snagr then shows up under /mcp inside Claude Code.',
      }
    case 'json':
      return {
        code: JSON.stringify(
          { mcpServers: { snagr: { url, headers: { Authorization: bearer } } } },
          null,
          2,
        ),
        hint: 'The mcpServers shape most agents and editors read (Cursor, Claude Desktop-style configs).',
      }
    case 'hermes':
      return {
        code: `mcp_servers:\n  snagr:\n    url: "${url}"\n    headers:\n      Authorization: "${bearer}"`,
        hint: 'Add to ~/.hermes/config.yaml, then /reload-mcp in Hermes.',
      }
    case 'openclaw':
      return {
        code: JSON.stringify(
          {
            mcp: {
              servers: {
                snagr: { url, transport: 'streamable-http', headers: { Authorization: bearer } },
              },
            },
          },
          null,
          2,
        ),
        hint: 'Merge into ~/.openclaw/openclaw.json — spell out the transport, OpenClaw defaults to sse.',
      }
    case 'curl':
      return {
        code: [
          `curl -s ${url} \\`,
          `  -H "Authorization: ${bearer}" \\`,
          '  -H "Content-Type: application/json" \\',
          '  -H "Accept: application/json, text/event-stream" \\',
          `  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'`,
        ].join('\n'),
        hint: 'A smoke test — lists the tools this token can see.',
      }
  }
}

function CopyButton({ text, label, size = 'default' }: { text: string; label: string; size?: 'default' | 'sm' }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <Button size={size} aria-label={label} onClick={copy}>
      {copied ? <Check className="text-drop" /> : <Copy />}
      {copied ? 'Copied' : 'Copy'}
    </Button>
  )
}

/** The MCP URL and a per-client config block. With a real token (the create
 *  dialog, the one place it exists) the block is paste-ready; otherwise it
 *  carries a placeholder. */
function ConnectSnippets({ token, compact = false }: { token: string | null; compact?: boolean }) {
  const [kind, setKind] = useState<ClientKind>('claude')
  const url = mcpUrl()
  const { code, hint } = snippetFor(kind, url, token ?? TOKEN_PLACEHOLDER)

  return (
    <div className="space-y-3">
      {compact ? null : (
        <div>
          <Label htmlFor="mcp-url">MCP endpoint</Label>
          <div className="flex gap-2">
            <Input id="mcp-url" readOnly value={url} className="font-mono text-xs" onFocus={(e) => e.target.select()} />
            <CopyButton text={url} label="Copy MCP URL" />
          </div>
        </div>
      )}
      <div>
        <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
          <Label className="mb-0">Client config</Label>
          <Segmented options={CLIENT_OPTIONS} value={kind} onChange={setKind} ariaLabel="Client" />
        </div>
        <pre className="overflow-x-auto rounded-sm border border-hairline-strong bg-well px-3 py-2.5 font-mono text-xs leading-relaxed whitespace-pre text-ink">
          {code}
        </pre>
        <div className="mt-1.5 flex items-start justify-between gap-2">
          <p className="text-xs text-ink-3">{hint}</p>
          <CopyButton text={code} label="Copy config" size="sm" />
        </div>
      </div>
    </div>
  )
}

type Access = 'read' | 'write' | 'full'

/** Every useful combination is one of three presets — like the notification
 *  events picker, a segmented control covers the space. `runs` is its own
 *  scope because a run costs LLM money. */
const ACCESS_OPTIONS: readonly { value: Access; label: string }[] = [
  { value: 'read', label: 'Read only' },
  { value: 'write', label: 'Read & write' },
  { value: 'full', label: 'Full' },
]
const ACCESS_SCOPES: Record<Access, ApiTokenScope[]> = {
  read: ['read'],
  write: ['read', 'write'],
  full: ['read', 'write', 'runs'],
}
const ACCESS_HINT: Record<Access, string> = {
  read: 'Browse items, prices, runs and the review queue.',
  write: 'Also add and edit categories, sites, items, listings and photo reviews.',
  full: 'Also trigger and cancel agent runs.',
}

type Expiry = 'never' | '30' | '90' | '365'

const EXPIRY_OPTIONS: readonly { value: Expiry; label: string }[] = [
  { value: 'never', label: 'Never' },
  { value: '30', label: '30 days' },
  { value: '90', label: '90 days' },
  { value: '365', label: '1 year' },
]

function NewTokenDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [access, setAccess] = useState<Access>('read')
  const [expiry, setExpiry] = useState<Expiry>('never')
  const [created, setCreated] = useState<string | null>(null)

  const create = useMutation({
    mutationFn: () =>
      createToken({
        name: name.trim(),
        scopes: ACCESS_SCOPES[access],
        expires_in_days: expiry === 'never' ? null : Number(expiry),
      }),
    onSuccess: (token) => {
      void queryClient.invalidateQueries({ queryKey: qk.tokens })
      setCreated(token.token)
    },
  })

  const close = (o: boolean) => {
    onOpenChange(o)
    if (!o) {
      setName('')
      setAccess('read')
      setExpiry('never')
      setCreated(null)
      create.reset()
    }
  }

  const createError = create.error instanceof ApiError ? create.error : null
  const fieldError = (field: string) => createError?.fields?.[field] ?? null

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent>
        <DialogTitle>New API token</DialogTitle>
        <DialogDescription>
          A token lets an agent or script act as you — on your items and runs, never on your account.
        </DialogDescription>

        {created != null ? (
          <div className="mt-4 space-y-3">
            <div>
              <Label>Token — shown once, store it now</Label>
              <div className="flex gap-2">
                <Input readOnly value={created} className="font-mono text-xs" onFocus={(e) => e.target.select()} />
                <CopyButton text={created} label="Copy token" />
              </div>
            </div>
            <ConnectSnippets token={created} compact />
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
              <Label htmlFor="token-name">Name</Label>
              <Input
                id="token-name"
                placeholder="claude code (laptop)"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              {fieldError('name') ? <p className="mt-1 text-xs text-rise">{fieldError('name')}</p> : null}
            </div>

            <div>
              <Label>Access</Label>
              <Segmented options={ACCESS_OPTIONS} value={access} onChange={setAccess} ariaLabel="Token access" />
              <p className="mt-1.5 text-xs text-ink-3">{ACCESS_HINT[access]}</p>
              {fieldError('scopes') ? <p className="mt-1 text-xs text-rise">{fieldError('scopes')}</p> : null}
            </div>

            <div>
              <Label>Expires</Label>
              <Segmented options={EXPIRY_OPTIONS} value={expiry} onChange={setExpiry} ariaLabel="Token expiry" />
              {fieldError('expires_in_days') ? (
                <p className="mt-1 text-xs text-rise">{fieldError('expires_in_days')}</p>
              ) : null}
            </div>

            <DialogFooter>
              <Button variant="ghost" onClick={() => close(false)}>
                Cancel
              </Button>
              <Button type="submit" variant="primary" disabled={create.isPending || !name.trim()}>
                {create.isPending ? <Loader2 className="animate-spin" /> : null}
                Create token
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

function expiryCell(token: ApiToken) {
  if (token.expires_at == null) return 'never'
  if (new Date(token.expires_at).getTime() < Date.now()) return <Badge variant="rise">expired</Badge>
  return formatDateTime(token.expires_at)
}

export function ApiSettingsPage() {
  const { data: instance } = useInstance()
  const queryClient = useQueryClient()
  const [adding, setAdding] = useState(false)
  const [revoking, setRevoking] = useState<ApiToken | null>(null)

  const enabled = instance?.mcp_enabled === true
  const tokens = useQuery({ queryKey: qk.tokens, queryFn: listTokens, enabled })

  const remove = useMutation({
    mutationFn: (id: number) => revokeToken(id),
    onSuccess: () => {
      setRevoking(null)
      void queryClient.invalidateQueries({ queryKey: qk.tokens })
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : 'Could not revoke the token'),
  })

  return (
    <div className="max-w-2xl space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-[26px] leading-tight font-semibold tracking-[0.05em] text-ink uppercase">Settings</h1>
        <SettingsTabs />
      </div>

      {instance == null ? (
        <Skeleton className="h-40" />
      ) : !enabled ? (
        <Card>
          <CardBody className="pt-4">
            <p className="text-[13px] text-ink-2">
              Agent access is turned off on this instance — the operator set{' '}
              <code className="rounded-sm bg-well px-1 py-0.5 font-mono">MCP_ENABLED=false</code>. There is no
              MCP endpoint and API tokens are not accepted.
            </p>
          </CardBody>
        </Card>
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Plug className="size-4 text-ink-3" /> Connect an agent
              </CardTitle>
            </CardHeader>
            <CardBody className="space-y-3">
              <p className="text-[13px] text-ink-2">
                Snagr speaks the Model Context Protocol: point Claude Code, Hermes, OpenClaw or any MCP
                client at the endpoint below with a token, and it can browse your items and prices, add
                watches, and kick off runs — exactly what you can do here, nothing more.
              </p>
              <ConnectSnippets token={null} />
              <p className="text-xs text-ink-3">
                Replace <code className="rounded-sm bg-well px-1 py-0.5 font-mono">{TOKEN_PLACEHOLDER}</code>{' '}
                with a token from below — the create dialog fills these in for you. claude.ai and Claude
                Desktop connectors sign in with OAuth, which Snagr doesn't offer yet; use a client that sends
                a bearer header.
              </p>
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <KeyRound className="size-4 text-ink-3" /> API tokens
              </CardTitle>
              <Button variant="primary" size="sm" onClick={() => setAdding(true)}>
                <Plus /> New token
              </Button>
            </CardHeader>
            <CardBody className="px-0 py-1">
              {tokens.isPending ? (
                <div className="space-y-2 p-4">
                  <Skeleton className="h-6" />
                </div>
              ) : (tokens.data?.data.length ?? 0) === 0 ? (
                <p className="px-4 py-3 text-[13px] text-ink-3">
                  No tokens yet — create one to connect your first agent.
                </p>
              ) : (
                <Table>
                  <THead>
                    <TR>
                      <TH>Name</TH>
                      <TH>Access</TH>
                      <TH className="hidden sm:table-cell">Last used</TH>
                      <TH className="hidden sm:table-cell">Expires</TH>
                      <TH className="w-10" />
                    </TR>
                  </THead>
                  <TBody>
                    {tokens.data?.data.map((token) => (
                      <TR key={token.id}>
                        <TD className="font-medium text-ink">{token.name}</TD>
                        <TD>
                          <div className="flex gap-1">
                            {token.scopes.map((scope) => (
                              <Badge key={scope} variant="muted" className="font-mono">
                                {scope}
                              </Badge>
                            ))}
                          </div>
                        </TD>
                        <TD className="hidden text-ink-3 sm:table-cell">
                          {token.last_used_at ? relativeTime(token.last_used_at) : 'never'}
                        </TD>
                        <TD className="hidden text-ink-3 sm:table-cell">{expiryCell(token)}</TD>
                        <TD className="text-right">
                          <Button
                            variant="ghost"
                            size="iconSm"
                            aria-label={`Revoke ${token.name}`}
                            onClick={() => setRevoking(token)}
                          >
                            <Trash2 />
                          </Button>
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              )}
            </CardBody>
          </Card>
        </>
      )}

      <NewTokenDialog open={adding} onOpenChange={setAdding} />
      <ConfirmDialog
        open={revoking != null}
        onOpenChange={(o) => (o ? null : setRevoking(null))}
        title={`Revoke ${revoking?.name ?? 'token'}?`}
        description="Anything using this token stops working immediately. This can't be undone."
        confirmLabel="Revoke"
        pending={remove.isPending}
        onConfirm={() => (revoking ? remove.mutate(revoking.id) : null)}
      />
    </div>
  )
}
