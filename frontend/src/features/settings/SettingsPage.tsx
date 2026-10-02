import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2, ScanSearch } from 'lucide-react'
import { useBlocker } from 'react-router-dom'
import { toast } from 'sonner'
import { changePassword, updateMe } from '@/api/endpoints'
import { ApiError } from '@/api/client'
import { qk } from '@/api/queries'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader, CardTitle } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { usePageTitle } from '@/lib/usePageTitle'
import { NewPasswordInput } from '@/features/auth/NewPasswordInput'
import { useInstance, useSession } from '@/features/auth/useSession'
import { ChannelsCard } from '@/features/settings/ChannelsCard'
import { SettingsTabs } from '@/features/settings/SettingsTabs'
import { percentToThreshold, thresholdToPercent } from '@/features/settings/thresholds'

/**
 * Account settings: profile, password, notification channels and, when vision
 * is on, the authenticity thresholds.
 */
export function SettingsPage() {
  usePageTitle('Settings')
  const { data: user } = useSession()
  const { data: instance } = useInstance()
  const queryClient = useQueryClient()

  const [email, setEmail] = useState(user?.email ?? '')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [rejectFake, setRejectFake] = useState(thresholdToPercent(user?.vision_auto_reject_fake ?? '0.85'))
  const [promoteReal, setPromoteReal] = useState(thresholdToPercent(user?.vision_auto_promote_real ?? '0.90'))
  const [promoteFake, setPromoteFake] = useState(thresholdToPercent(user?.vision_auto_promote_fake ?? '0.90'))

  const saveProfile = useMutation({
    mutationFn: () => updateMe({ email: email.trim() }),
    meta: { inlineError: true },
    onSuccess: (updated) => {
      queryClient.setQueryData(qk.session, updated)
      setEmail(updated.email)
      toast.success('Profile saved')
    },
  })

  const password = useMutation({
    mutationFn: () => changePassword({ current_password: currentPassword, new_password: newPassword }),
    meta: { inlineError: true },
    onSuccess: () => {
      setCurrentPassword('')
      setNewPassword('')
      toast.success('Password changed')
    },
  })

  const saveThresholds = useMutation({
    mutationFn: () =>
      updateMe({
        vision_auto_reject_fake: percentToThreshold(rejectFake),
        vision_auto_promote_real: percentToThreshold(promoteReal),
        vision_auto_promote_fake: percentToThreshold(promoteFake),
      }),
    meta: { inlineError: true },
    onSuccess: (updated) => {
      queryClient.setQueryData(qk.session, updated)
      setRejectFake(thresholdToPercent(updated.vision_auto_reject_fake))
      setPromoteReal(thresholdToPercent(updated.vision_auto_promote_real))
      setPromoteFake(thresholdToPercent(updated.vision_auto_promote_fake))
      toast.success('Photo-check thresholds saved')
    },
  })

  const profileError = saveProfile.error instanceof ApiError ? saveProfile.error.message : null
  const passwordError = password.error instanceof ApiError ? password.error.message : null
  const thresholdError = saveThresholds.error instanceof ApiError ? saveThresholds.error : null
  const thresholdFields = thresholdError?.fields ?? {}
  const thresholdsDirty =
    user != null &&
    (rejectFake !== thresholdToPercent(user.vision_auto_reject_fake) ||
      promoteReal !== thresholdToPercent(user.vision_auto_promote_real) ||
      promoteFake !== thresholdToPercent(user.vision_auto_promote_fake))
  const emailDirty = user != null && email.trim() !== user.email

  // Email and the thresholds wait for their Save button while the channel
  // switches apply at once, so leaving with typed changes unsaved asks first.
  // The password fields stay out: a password manager can fill them unprompted.
  const unsaved = emailDirty || thresholdsDirty
  const leaving = useBlocker(
    ({ currentLocation, nextLocation }) =>
      unsaved &&
      nextLocation.pathname !== currentLocation.pathname &&
      // signing out has already happened by the time it heads to /login
      nextLocation.pathname !== '/login',
  )
  useEffect(() => {
    if (!unsaved) return
    const warn = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [unsaved])

  return (
    <div className="max-w-2xl space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-[26px] leading-tight font-semibold tracking-[0.05em] text-ink uppercase">Settings</h1>
        <SettingsTabs />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Profile</CardTitle>
        </CardHeader>
        <CardBody className="space-y-3">
          <form
            onSubmit={(e) => {
              e.preventDefault()
              saveProfile.mutate()
            }}
          >
            <Label htmlFor="settings-email">Email</Label>
            <div className="flex gap-2">
              <Input id="settings-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
              <Button
                type="submit"
                variant="default"
                disabled={saveProfile.isPending || email.trim() === user?.email}
              >
                {saveProfile.isPending ? <Loader2 className="animate-spin" /> : null}
                Save
              </Button>
            </div>
            {profileError ? (
              <p role="alert" className="mt-1.5 text-xs text-rise">
                {profileError}
              </p>
            ) : null}
          </form>

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
                <NewPasswordInput id="new-password" value={newPassword} onChange={setNewPassword} />
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
          <CardBody>
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault()
                saveThresholds.mutate()
              }}
            >
              <p className="text-[14px] text-ink-2">
                Confidence thresholds for the image-based authenticity check, 50–100%. Auto-reject
                drops a listing before it's saved; auto-promote lets a strong suggestion join an
                item's library without review — it also needs three confirmed references of that
                label and Snagr's own read of the listing to agree.
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
                    <div className="flex items-center gap-2">
                      <Input
                        id={field}
                        type="number"
                        required
                        step="1"
                        min="50"
                        max="100"
                        className="w-20 font-mono tnum"
                        value={value}
                        onChange={(e) => setValue(e.target.value)}
                      />
                      <span className="text-xs text-ink-3">%</span>
                    </div>
                    {thresholdFields[field] ? (
                      <p className="mt-1 text-xs text-rise">{thresholdFields[field]}</p>
                    ) : null}
                  </div>
                ))}
              </div>
              {thresholdError && !thresholdError.fields ? (
                <p role="alert" className="text-xs text-rise">
                  {thresholdError.message}
                </p>
              ) : null}
              <Button type="submit" disabled={saveThresholds.isPending || !thresholdsDirty}>
                {saveThresholds.isPending ? <Loader2 className="animate-spin" /> : null}
                Save thresholds
              </Button>
            </form>
          </CardBody>
        </Card>
      ) : null}

      <ConfirmDialog
        open={leaving.state === 'blocked'}
        onOpenChange={(open) => {
          if (!open) leaving.reset?.()
        }}
        title="Leave without saving?"
        description="Changes you've typed here and not saved will be lost."
        confirmLabel="Leave"
        onConfirm={() => leaving.proceed?.()}
      />
    </div>
  )
}
