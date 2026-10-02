import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Copy, KeyRound, Loader2, Plus, Shield, ShieldOff, Trash2, UserX, UserCheck } from 'lucide-react'
import { toast } from 'sonner'
import { ApiError } from '@/api/client'
import {
  createInvite,
  createPasswordReset,
  deleteUser,
  listInvites,
  listUsers,
  revokeInvite,
  updateUser,
} from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { AdminUser, AdminUserUpdateRequest, Invite, PasswordReset } from '@/api/types'
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuMoreTrigger,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { ErrorState } from '@/components/ui/error-state'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/table'
import { RelativeTime } from '@/components/ui/relative-time'
import { copyText } from '@/lib/clipboard'
import { formatDate, formatDateTime } from '@/lib/time'
import { usePageTitle } from '@/lib/usePageTitle'
import { useSession } from '@/features/auth/useSession'
import { SettingsTabs } from '@/features/settings/SettingsTabs'
import { accountStatusReceipt } from '@/features/settings/accountStatus'

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
    if (!(await copyText(inviteUrl(created)))) {
      toast.error("Couldn't copy — select the link and copy it yourself")
      return
    }
    toast.success('Invite link copied')
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
        <DialogHeader>
          <DialogTitle>Invite a user</DialogTitle>
          <DialogDescription>
            Share the invite link — it lets someone create their own account on this instance.
          </DialogDescription>
        </DialogHeader>

        {created ? (
          <>
            <DialogBody className="space-y-3">
              <Label>Invite link (expires {formatDate(created.expires_at)})</Label>
              <div className="flex gap-2">
                <Input readOnly value={inviteUrl(created)} className="font-mono sm:text-xs" onFocus={(e) => e.target.select()} />
                <Button onClick={copy} aria-label="Copy invite link">
                  {copied ? <Check className="text-drop" /> : <Copy />}
                  {copied ? 'Copied' : 'Copy'}
                </Button>
              </div>
            </DialogBody>
            <DialogFooter>
              <Button variant="primary" onClick={() => close(false)}>
                Done
              </Button>
            </DialogFooter>
          </>
        ) : (
          <form
            className="contents"
            onSubmit={(e) => {
              e.preventDefault()
              create.mutate()
            }}
          >
            <DialogBody className="space-y-3">
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
            </DialogBody>
            <DialogFooter>
              <Button variant="ghost" onClick={() => close(false)}>
                Cancel
              </Button>
              <Button type="submit" variant="primary" className="max-sm:flex-[2]" disabled={create.isPending}>
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

function resetUrl(reset: PasswordReset): string {
  return `${window.location.origin}/reset/${reset.token}`
}

/**
 * Issues a password-reset link for one user and shows it, once: only its hash
 * is kept, so closing the dialog loses it (issuing another replaces it).
 */
function ResetPasswordDialog({ user, onOpenChange }: { user: AdminUser | null; onOpenChange: (o: boolean) => void }) {
  const [created, setCreated] = useState<PasswordReset | null>(null)
  const [copied, setCopied] = useState(false)

  const create = useMutation({
    mutationFn: (id: number) => createPasswordReset(id),
    onSuccess: setCreated,
  })

  const copy = async () => {
    if (!created) return
    if (!(await copyText(resetUrl(created)))) {
      toast.error("Couldn't copy — select the link and copy it yourself")
      return
    }
    toast.success('Reset link copied')
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const close = (o: boolean) => {
    onOpenChange(o)
    if (!o) {
      setCreated(null)
      create.reset()
    }
  }

  return (
    <Dialog open={user != null} onOpenChange={close}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reset password</DialogTitle>
          <DialogDescription>
            {created
              ? 'Send this link to them yourself — Snagr emails nothing. It works once, and this is the only time it is shown.'
              : `Create a link ${user?.email ?? ''} can use to choose a new password. Using it signs them out everywhere. Their current password keeps working until then.`}
          </DialogDescription>
        </DialogHeader>

        {created ? (
          <>
            <DialogBody className="space-y-3">
              <Label>Reset link (expires {formatDateTime(created.expires_at)})</Label>
              <div className="flex gap-2">
                <Input readOnly value={resetUrl(created)} className="font-mono sm:text-xs" onFocus={(e) => e.target.select()} />
                <Button onClick={copy} aria-label="Copy reset link">
                  {copied ? <Check className="text-drop" /> : <Copy />}
                  {copied ? 'Copied' : 'Copy'}
                </Button>
              </div>
            </DialogBody>
            <DialogFooter>
              <Button variant="primary" onClick={() => close(false)}>
                Done
              </Button>
            </DialogFooter>
          </>
        ) : (
          <DialogFooter>
            <Button variant="ghost" onClick={() => close(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              className="max-sm:flex-[2]"
              disabled={create.isPending}
              onClick={() => {
                if (user) create.mutate(user.id)
              }}
            >
              {create.isPending ? <Loader2 className="animate-spin" /> : null}
              Create reset link
            </Button>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  )
}

/**
 * Admin-only user management: activate, deactivate or delete users, change
 * their role, issue password-reset links, and create or revoke invites.
 */
export function AdminUsersPage() {
  usePageTitle('Users · Settings')
  const [inviteOpen, setInviteOpen] = useState(false)
  const [deactivating, setDeactivating] = useState<AdminUser | null>(null)
  const [deleting, setDeleting] = useState<AdminUser | null>(null)
  const [resetting, setResetting] = useState<AdminUser | null>(null)
  const [revoking, setRevoking] = useState<Invite | null>(null)
  const queryClient = useQueryClient()
  const { data: me } = useSession()

  const users = useQuery({ queryKey: qk.adminUsers, queryFn: listUsers })
  const invites = useQuery({ queryKey: qk.adminInvites, queryFn: listInvites })

  const onStatusChanged = (user: AdminUser) => {
    void queryClient.invalidateQueries({ queryKey: qk.adminUsers })
    toast.success(accountStatusReceipt(user.email, user.is_active))
  }

  const deactivate = useMutation({
    mutationFn: (id: number) => updateUser(id, { is_active: false }),
    meta: { inlineError: true },
    onSuccess: (user) => {
      onStatusChanged(user)
      setDeactivating(null)
    },
  })

  const reactivate = useMutation({
    mutationFn: (id: number) => updateUser(id, { is_active: true }),
    onSuccess: onStatusChanged,
  })

  const patchUser = useMutation({
    mutationFn: ({ id, ...body }: AdminUserUpdateRequest & { id: number }) => updateUser(id, body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: qk.adminUsers }),
  })

  const removeUser = useMutation({
    mutationFn: (id: number) => deleteUser(id),
    meta: { inlineError: true },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.adminUsers })
      setDeleting(null)
    },
  })

  const revoke = useMutation({
    mutationFn: (id: number) => revokeInvite(id),
    meta: { inlineError: true },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.adminInvites })
      setRevoking(null)
    },
  })

  return (
    <div className="max-w-3xl space-y-5">
      <div className="flex flex-col items-start gap-3">
        <h1 className="font-display text-[26px] leading-tight font-semibold tracking-[0.05em] text-ink uppercase">Settings</h1>
        <SettingsTabs />
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
                    <TD className="hidden text-xs whitespace-nowrap text-ink-3 sm:table-cell"><RelativeTime iso={user.created_at} /></TD>
                    <TD>
                      {user.id !== me?.id ? (
                        <DropdownMenu>
                          <DropdownMenuMoreTrigger label={`Actions for ${user.email}`} />
                          <DropdownMenuContent align="end" className="w-60">
                            <DropdownMenuLabel>
                              <span className="truncate text-[14px] text-ink">{user.email}</span>
                              <span className="font-mono text-[12px] text-ink-3 tnum">
                                {user.role} ·{' '}
                                {user.is_active ? 'active' : <span className="text-warn">deactivated</span>} ·{' '}
                                {user.item_count} {user.item_count === 1 ? 'item' : 'items'}
                              </span>
                            </DropdownMenuLabel>
                            <DropdownMenuItem
                              onSelect={() => (user.is_active ? setDeactivating(user) : reactivate.mutate(user.id))}
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
                            <DropdownMenuItem
                              onSelect={() =>
                                patchUser.mutate({ id: user.id, role: user.role === 'admin' ? 'user' : 'admin' })
                              }
                            >
                              {user.role === 'admin' ? (
                                <>
                                  <ShieldOff /> Remove admin
                                </>
                              ) : (
                                <>
                                  <Shield /> Make admin
                                </>
                              )}
                            </DropdownMenuItem>
                            <DropdownMenuItem onSelect={() => setResetting(user)}>
                              <KeyRound /> Reset password
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem tone="danger" onSelect={() => setDeleting(user)}>
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
          <Button variant="primary" size="sm" onClick={() => setInviteOpen(true)}>
            <Plus /> Invite user
          </Button>
        </CardHeader>
        <CardBody className="px-0 py-1">
          {invites.isPending ? (
            <div className="space-y-2 p-4">
              <Skeleton className="h-6" />
            </div>
          ) : invites.isError ? (
            <ErrorState
              className="m-4 border-0 py-6"
              title="Couldn't load invites"
              error={invites.error}
              onRetry={() => void invites.refetch()}
              retrying={invites.isFetching}
            />
          ) : invites.data.data.length === 0 ? (
            <p className="px-4 pb-3 text-[14px] text-ink-3">No pending invites.</p>
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
                {invites.data.data.map((invite) => (
                  <TR key={invite.id}>
                    <TD className="text-ink-2">{invite.email ?? <span className="text-ink-3">anyone with the link</span>}</TD>
                    <TD className="text-xs whitespace-nowrap text-ink-3">
                      {formatDate(invite.expires_at)}
                    </TD>
                    <TD>
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={async () => {
                            if (await copyText(inviteUrl(invite))) toast.success('Invite link copied')
                            else toast.error(`Couldn't copy — the link is ${inviteUrl(invite)}`)
                          }}
                        >
                          <Copy /> Copy link
                        </Button>
                        <Button variant="ghost" size="sm" className="text-rise" onClick={() => setRevoking(invite)}>
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
      <ResetPasswordDialog
        user={resetting}
        onOpenChange={(open) => {
          if (!open) setResetting(null)
        }}
      />
      <ConfirmDialog
        open={deactivating != null}
        onOpenChange={(open) => {
          if (open) return
          setDeactivating(null)
          deactivate.reset()
        }}
        title="Deactivate user"
        description={
          deactivating
            ? `This signs ${deactivating.email} out everywhere and stops them signing back in until you reactivate the account. Their items are kept.`
            : ''
        }
        confirmLabel="Deactivate"
        pending={deactivate.isPending}
        error={deactivate.error instanceof ApiError ? deactivate.error.message : null}
        onConfirm={() => {
          if (deactivating) deactivate.mutate(deactivating.id)
        }}
      />
      <ConfirmDialog
        open={deleting != null}
        onOpenChange={(open) => {
          if (open) return
          setDeleting(null)
          removeUser.reset()
        }}
        title="Delete user"
        description={
          deleting
            ? `This permanently deletes ${deleting.email}'s account and ${deleting.item_count} ${deleting.item_count === 1 ? 'item' : 'items'}, with the listings and price history Snagr found for them. Anyone else watching the same items keeps theirs. To lock the account but keep its data, deactivate it instead.`
            : ''
        }
        confirmLabel="Delete user"
        pending={removeUser.isPending}
        error={removeUser.error instanceof ApiError ? removeUser.error.message : null}
        onConfirm={() => {
          if (deleting) removeUser.mutate(deleting.id)
        }}
      />
      <ConfirmDialog
        open={revoking != null}
        onOpenChange={(open) => {
          if (open) return
          setRevoking(null)
          revoke.reset()
        }}
        title="Revoke invite"
        description={`${revoking?.email ? `The invite for ${revoking.email}` : 'This invite link'} stops working immediately. This can't be undone.`}
        confirmLabel="Revoke"
        pending={revoke.isPending}
        error={revoke.error instanceof ApiError ? revoke.error.message : null}
        onConfirm={() => {
          if (revoking) revoke.mutate(revoking.id)
        }}
      />
    </div>
  )
}
