import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { BellRing, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { changePassword, sendTestNotification, updateMe } from '@/api/endpoints'
import { ApiError } from '@/api/client'
import { qk } from '@/api/queries'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useInstance, useSession } from '@/features/auth/useSession'

export function SettingsPage() {
  const { data: user } = useSession()
  const { data: instance } = useInstance()
  const queryClient = useQueryClient()

  const [email, setEmail] = useState(user?.email ?? '')
  const [topic, setTopic] = useState(user?.ntfy_topic ?? '')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')

  const saveProfile = useMutation({
    mutationFn: () => updateMe({ email: email.trim() }),
    onSuccess: (updated) => {
      queryClient.setQueryData(qk.session, updated)
      toast.success('Profile saved')
    },
  })

  const saveTopic = useMutation({
    mutationFn: () => updateMe({ ntfy_topic: topic.trim() || null }),
    onSuccess: (updated) => {
      queryClient.setQueryData(qk.session, updated)
      toast.success('Notification topic saved')
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

  const test = useMutation({
    mutationFn: sendTestNotification,
    onSuccess: () => toast.success('Test notification sent — check your ntfy app'),
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not send the test notification'),
  })

  const passwordError = password.error instanceof ApiError ? password.error.message : null
  const suggestedTopic = `snagr-${(user?.email.split('@')[0] ?? 'me').replace(/[^a-z0-9]/gi, '').toLowerCase()}-${String(user?.id ?? 0).padStart(2, '0')}${Math.abs((user?.email ?? '').split('').reduce((a, c) => a + c.charCodeAt(0), 0) % 97).toString(16)}`

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

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BellRing className="size-4 text-ink-3" /> Notifications
          </CardTitle>
        </CardHeader>
        <CardBody className="space-y-3">
          {instance?.ntfy_server_url == null ? (
            <p className="text-[13px] text-ink-2">
              Your admin hasn't configured a ntfy server yet. Set{' '}
              <code className="rounded-sm bg-well px-1 py-0.5 font-mono text-xs break-all">NTFY_SERVER_URL</code> on the
              backend to enable push notifications when a target price is hit.
            </p>
          ) : (
            <>
              <div>
                <Label>ntfy server</Label>
                <p className="font-mono text-[13px] text-ink-2">{instance.ntfy_server_url}</p>
              </div>
              <div>
                <Label htmlFor="ntfy-topic">Your topic</Label>
                <div className="flex gap-2">
                  <Input
                    id="ntfy-topic"
                    placeholder={suggestedTopic}
                    className="font-mono"
                    value={topic}
                    onChange={(e) => setTopic(e.target.value)}
                  />
                  <Button
                    disabled={saveTopic.isPending || topic.trim() === (user?.ntfy_topic ?? '')}
                    onClick={() => saveTopic.mutate()}
                  >
                    {saveTopic.isPending ? <Loader2 className="animate-spin" /> : null}
                    Save
                  </Button>
                </div>
                <p className="mt-1.5 text-xs text-ink-3">
                  Subscribe to{' '}
                  <code className="rounded-sm bg-well px-1 py-0.5 font-mono break-all">
                    {instance.ntfy_server_url}/{topic.trim() || suggestedTopic}
                  </code>{' '}
                  in the ntfy app. You'll get a push when an item you watch hits its target — toggle
                  "Notify at target" on each item.
                </p>
              </div>
              <Button variant="snag" size="sm" disabled={test.isPending || !user?.ntfy_topic} onClick={() => test.mutate()}>
                {test.isPending ? <Loader2 className="animate-spin" /> : <BellRing />}
                Send test notification
              </Button>
            </>
          )}
        </CardBody>
      </Card>
    </div>
  )
}
