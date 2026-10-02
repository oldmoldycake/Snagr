import { useState } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { Input } from '@/components/ui/input'

// the backend's rule for a new password (MIN_PASSWORD_LENGTH in
// core/security.py); the mock handlers hold the same line
const MIN_PASSWORD_LENGTH = 8

/**
 * Input for choosing a password (sign-up, invite, password change): states the
 * length rule under the field and can show what was typed, since a typo here
 * locks the account out.
 */
export function NewPasswordInput({
  id,
  value,
  onChange,
}: {
  id: string
  value: string
  onChange: (value: string) => void
}) {
  const [shown, setShown] = useState(false)

  return (
    <>
      <div className="relative">
        <Input
          id={id}
          type={shown ? 'text' : 'password'}
          autoComplete="new-password"
          required
          minLength={MIN_PASSWORD_LENGTH}
          aria-describedby={`${id}-rule`}
          className="pr-8"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
        <button
          type="button"
          aria-label="Show password"
          aria-pressed={shown}
          className="tap-target absolute top-1/2 right-1.5 flex size-5 -translate-y-1/2 items-center justify-center rounded-sm text-ink-3 hover:bg-raised hover:text-ink"
          onClick={() => setShown((s) => !s)}
        >
          {shown ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
        </button>
      </div>
      <p id={`${id}-rule`} className="mt-1.5 text-xs text-ink-3">
        At least {MIN_PASSWORD_LENGTH} characters.
      </p>
    </>
  )
}
