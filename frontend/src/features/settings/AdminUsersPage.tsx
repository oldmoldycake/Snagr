import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Check, Copy, Loader2, MoreHorizontal, Plus, Trash2, UserX, UserCheck } from 'lucide-react'
import { toast } from 'sonner'
import { createInvite, deleteUser, listInvites, listUsers, revokeInvite, updateUser } from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { AdminUser, Invite } from '@/api/types'
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/table'
import { relativeTime } from '@/lib/time'
import { useSession } from '@/features/auth/useSession'

function inviteUrl(invite: Invite): string {
  return `${window.location.origin}/invite/${invite.token}`
}

function InviteDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const [email, setEmail] = useState('')
  const [created, setCreated] = useState<Invite | null>(null)
  const [copied, setCopied] = useState(false)
  const queryClient = useQueryClient()

  const create = useMutation({
    mutationFn: () => createInvite(email.trim() ? { email: email.trim() } : {}),
    onSuccess: (invite) => {
      setCreated(invite)
      void queryClient.invalidateQueries({ queryKey: qk.adminInvites })
    },
  })

  const copy = async () => {
    if (!created) return
    await navigator.clipboard.writeText(inviteUrl(created))
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const close = (o: boolean) => {
    onOpenChange(o)
    if (!o) {
      setEmail('')
      setCreated(null)
      create.reset()
    }
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent>
        <DialogTitle>Invite a user</DialogTitle>
        <DialogDescription>
          Share the invite link — it lets someone create their own account on this instance.
        </DialogDescription>

        {created ? (
          <div className="mt-4 space-y-3">
            <Label>Invite link (expires {relativeTime(created.expires_at).replace(' ago', '')})</Label>
            <div className="flex gap-2">
              <Input readOnly value={inviteUrl(created)} className="font-mono text-xs" onFocus={(e) => e.target.select()} />
              <Button onClick={copy} aria-label="Copy invite link">
                {copied ? <Check className="text-drop" /> : <Copy />}
                {copied ? 'Copied' : 'Copy'}
              </Button>
            </div>
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
              <Label htmlFor="invite-email-input">Email (optional)</Label>
              <Input
                id="invite-email-input"
                type="email"
                placeholder="teammate@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
              <p className="mt-1.5 text-xs text-ink-3">
                If set, the invite is locked to this address; otherwise anyone with the link can join.
              </p>
            </div>
            <DialogFooter>
              <Button variant="ghost" onClick={() => close(false)}>
                Cancel
              </Button>
              <Button type="submit" variant="primary" disabled={create.isPending}>
                {create.isPending ? <Loader2 className="animate-spin" /> : null}
                Create invite
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

export function AdminUsersPage() {
  const [inviteOpen, setInviteOpen] = useState(false)
  const [deleting, setDeleting] = useState<AdminUser | null>(null)
  const queryClient = useQueryClient()
  const { data: me } = useSession()

  const users = useQuery({ queryKey: qk.adminUsers, queryFn: listUsers })
  const invites = useQuery({ queryKey: qk.adminInvites, queryFn: listInvites })

  const patchUser = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) => updateUser(id, { is_active }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: qk.adminUsers }),
  })

  const removeUser = useMutation({
    mutationFn: (id: number) => deleteUser(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.adminUsers })
      setDeleting(null)
    },
  })

  const revoke = useMutation({
    mutationFn: (id: number) => revokeInvite(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: qk.adminInvites }),
  })

  return (
    <div className="max-w-3xl space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-[26px] leading-tight font-semibold tracking-[0.05em] text-ink uppercase">Users & invites</h1>
          <p className="mt-0.5 text-xs text-ink-3">
            <Link to="/settings" className="hover:text-ink-2 hover:underline">
              ← Back to settings
            </Link>
          </p>
        </div>
        <Button variant="primary" size="sm" onClick={() => setInviteOpen(true)}>
          <Plus /> Invite user
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Users</CardTitle>
        </CardHeader>
        <CardBody className="px-0 py-1">
          {users.isLoading ? (
            <div className="space-y-2 p-4">
              <Skeleton className="h-6" />
            </div>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Email</TH>
                  <TH>Role</TH>
                  <TH>Status</TH>
                  <TH className="hidden text-right sm:table-cell">Items</TH>
                  <TH className="hidden sm:table-cell">Joined</TH>
                  <TH className="w-10" />
                </TR>
              </THead>
              <TBody>
                {(users.data?.data ?? []).map((user) => (
                  <TR key={user.id}>
                    <TD className="font-medium text-ink">
                      {user.email}
                      {user.id === me?.id ? <span className="ml-1.5 text-xs text-ink-3">(you)</span> : null}
                    </TD>
                    <TD>
                      <Badge variant={user.role === 'admin' ? 'lume' : 'muted'}>{user.role}</Badge>
                    </TD>
                    <TD>
                      {user.is_active ? (
                        <span className="text-xs text-ink-2">Active</span>
                      ) : (
                        <span className="text-xs text-warn">Deactivated</span>
                      )}
                    </TD>
                    <TD className="hidden text-right font-mono text-ink-2 tnum sm:table-cell">{user.item_count}</TD>
                    <TD className="hidden text-xs whitespace-nowrap text-ink-3 sm:table-cell">{relativeTime(user.created_at)}</TD>
                    <TD>
                      {user.id !== me?.id ? (
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="iconSm" aria-label={`Actions for ${user.email}`}>
                              <MoreHorizontal />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem
                              onSelect={() => patchUser.mutate({ id: user.id, is_active: !user.is_active })}
                            >
                              {user.is_active ? (
                                <>
                                  <UserX /> Deactivate
                                </>
                              ) : (
                                <>
                                  <UserCheck /> Reactivate
                                </>
                              )}
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem className="text-rise" onSelect={() => setDeleting(user)}>
                              <Trash2 /> Delete user
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      ) : null}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Pending invites</CardTitle>
        </CardHeader>
        <CardBody className="px-0 py-1">
          {(invites.data?.data.length ?? 0) === 0 ? (
            <p className="px-4 pb-3 text-[13px] text-ink-3">No pending invites.</p>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Email</TH>
                  <TH>Expires</TH>
                  <TH className="w-40" />
                </TR>
              </THead>
              <TBody>
                {invites.data!.data.map((invite) => (
                  <TR key={invite.id}>
                    <TD className="text-ink-2">{invite.email ?? <span className="text-ink-3">anyone with the link</span>}</TD>
                    <TD className="text-xs whitespace-nowrap text-ink-3">
                      {new Date(invite.expires_at).toLocaleDateString()}
                    </TD>
                    <TD>
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={async () => {
                            await navigator.clipboard.writeText(inviteUrl(invite))
                            toast.success('Invite link copied')
                          }}
                        >
                          <Copy /> Copy link
                        </Button>
                        <Button variant="ghost" size="sm" className="text-rise" onClick={() => revoke.mutate(invite.id)}>
                          Revoke
                        </Button>
                      </div>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardBody>
      </Card>

      <InviteDialog open={inviteOpen} onOpenChange={setInviteOpen} />
      <ConfirmDialog
        open={deleting != null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null)
        }}
        title="Delete user"
        description={
          deleting
            ? `${deleting.email}'s account, categories, items, and price history are removed permanently.`
            : ''
        }
        confirmLabel="Delete user"
        pending={removeUser.isPending}
        onConfirm={() => {
          if (deleting) removeUser.mutate(deleting.id)
        }}
      />
    </div>
  )
}
