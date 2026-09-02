import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Loader2, ScanSearch } from 'lucide-react'
import { toast } from 'sonner'
import { changePassword, updateMe } from '@/api/endpoints'
import { ApiError } from '@/api/client'
import { qk } from '@/api/queries'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useInstance, useSession } from '@/features/auth/useSession'
import { ChannelsCard } from '@/features/settings/ChannelsCard'

export function SettingsPage() {
  const { data: user } = useSession()
  const { data: instance } = useInstance()
  const queryClient = useQueryClient()

  const [email, setEmail] = useState(user?.email ?? '')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [rejectFake, setRejectFake] = useState(user?.vision_auto_reject_fake ?? '0.85')
  const [promoteReal, setPromoteReal] = useState(user?.vision_auto_promote_real ?? '0.90')
  const [promoteFake, setPromoteFake] = useState(user?.vision_auto_promote_fake ?? '0.90')

  const saveProfile = useMutation({
    mutationFn: () => updateMe({ email: email.trim() }),
    onSuccess: (updated) => {
      queryClient.setQueryData(qk.session, updated)
      toast.success('Profile saved')
    },
  })

  const password = useMutation({
    mutationFn: () => changePassword({ current_password: currentPassword, new_password: newPassword }),
    onSuccess: () => {
      setCurrentPassword('')
      setNewPassword('')
      toast.success('Password changed')
    },
  })

  const saveThresholds = useMutation({
    mutationFn: () =>
      updateMe({
        vision_auto_reject_fake: Number(rejectFake).toFixed(2),
        vision_auto_promote_real: Number(promoteReal).toFixed(2),
        vision_auto_promote_fake: Number(promoteFake).toFixed(2),
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(qk.session, updated)
      setRejectFake(updated.vision_auto_reject_fake)
      setPromoteReal(updated.vision_auto_promote_real)
      setPromoteFake(updated.vision_auto_promote_fake)
      toast.success('Photo-check thresholds saved')
    },
  })

  const passwordError = password.error instanceof ApiError ? password.error.message : null
  const thresholdFields =
    saveThresholds.error instanceof ApiError ? (saveThresholds.error.fields ?? {}) : {}
  const thresholdsDirty =
    rejectFake !== user?.vision_auto_reject_fake ||
    promoteReal !== user?.vision_auto_promote_real ||
    promoteFake !== user?.vision_auto_promote_fake

  return (
    <div className="max-w-2xl space-y-5">
      <div className="flex items-center justify-between gap-3">
        <h1 className="font-display text-[26px] leading-tight font-semibold tracking-[0.05em] text-ink uppercase">Settings</h1>
        {user?.role === 'admin' ? (
          <Link to="/settings/users" className="text-xs text-lume hover:underline">
            Manage users & invites →
          </Link>
        ) : null}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Profile</CardTitle>
        </CardHeader>
        <CardBody className="space-y-3">
          <div>
            <Label htmlFor="settings-email">Email</Label>
            <div className="flex gap-2">
              <Input id="settings-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
              <Button
                variant="default"
                disabled={saveProfile.isPending || email.trim() === user?.email}
                onClick={() => saveProfile.mutate()}
              >
                {saveProfile.isPending ? <Loader2 className="animate-spin" /> : null}
                Save
              </Button>
            </div>
          </div>

          <form
            className="space-y-3 border-t border-hairline pt-3"
            onSubmit={(e) => {
              e.preventDefault()
              password.mutate()
            }}
          >
            <p className="text-xs font-medium text-ink-2">Change password</p>
            {passwordError ? <p className="text-xs text-rise">{passwordError}</p> : null}
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <Label htmlFor="current-password">Current password</Label>
                <Input
                  id="current-password"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                />
              </div>
              <div>
                <Label htmlFor="new-password">New password</Label>
                <Input
                  id="new-password"
                  type="password"
                  autoComplete="new-password"
                  required
                  minLength={8}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                />
              </div>
            </div>
            <Button type="submit" disabled={password.isPending || !currentPassword || !newPassword}>
              {password.isPending ? <Loader2 className="animate-spin" /> : null}
              Change password
            </Button>
          </form>
        </CardBody>
      </Card>

      <ChannelsCard />

      {instance?.vision_enabled ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ScanSearch className="size-4 text-ink-3" /> Photo checks
            </CardTitle>
          </CardHeader>
          <CardBody className="space-y-3">
            <p className="text-[13px] text-ink-2">
              Confidence thresholds for the image-based authenticity check, 0.50–1.00. Auto-reject
              drops a listing before it's saved; auto-promote lets a strong suggestion join an
              item's library without review — it also needs three confirmed references of that
              label and the agent's own read to agree.
            </p>
            <div className="grid gap-3 sm:grid-cols-3">
              {(
                [
                  ['vision_auto_reject_fake', 'Auto-reject fake', rejectFake, setRejectFake],
                  ['vision_auto_promote_real', 'Auto-promote real', promoteReal, setPromoteReal],
                  ['vision_auto_promote_fake', 'Auto-promote fake', promoteFake, setPromoteFake],
                ] as const
              ).map(([field, label, value, setValue]) => (
                <div key={field}>
                  <Label htmlFor={field}>{label}</Label>
                  <Input
                    id={field}
                    type="number"
                    step="0.01"
                    min="0.5"
                    max="1"
                    className="font-mono tnum"
                    value={value}
                    onChange={(e) => setValue(e.target.value)}
                  />
                  {thresholdFields[field] ? (
                    <p className="mt-1 text-xs text-rise">{thresholdFields[field]}</p>
                  ) : null}
                </div>
              ))}
            </div>
            <Button
              disabled={saveThresholds.isPending || !thresholdsDirty}
              onClick={() => saveThresholds.mutate()}
            >
              {saveThresholds.isPending ? <Loader2 className="animate-spin" /> : null}
              Save thresholds
            </Button>
          </CardBody>
        </Card>
      ) : null}
    </div>
  )
}
