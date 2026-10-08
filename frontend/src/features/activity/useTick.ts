import { useEffect, useState } from 'react'

/** Re-renders once a second while `active`, so elapsed times and countdowns keep moving. */
export function useTick(active: boolean) {
  const [, setTick] = useState(0)
  useEffect(() => {
    if (!active) return
    const id = setInterval(() => setTick((n) => n + 1), 1000)
    return () => clearInterval(id)
  }, [active])
}
