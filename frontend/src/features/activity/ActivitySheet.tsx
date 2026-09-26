import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowDown, ExternalLink } from 'lucide-react'
import { getJobsSummary } from '@/api/endpoints'
import { qk } from '@/api/queries'
import { Radar } from '@/components/ui/radar'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { TerminalLog } from '@/components/ui/terminal-log'
import { cn } from '@/lib/cn'
import { checkLine } from './lines'
import { LiveHunts } from './LiveHunts'
import { useJobs } from './JobsProvider'

/**
 * The slide-over the masthead pill opens: the live work, without leaving the
 * page you were on. It is the same two beats as the Activity page's middle —
 * hunts with a voice, checks with a pulse — and links to the rest.
 */
export function ActivitySheet() {
  const { live, checks, connection, panelOpen, setPanelOpen } = useJobs()
  const logRef = useRef<HTMLDivElement>(null)
  const [following, setFollowing] = useState(true)
  const summary = useQuery({
    queryKey: qk.jobsSummary,
    queryFn: getJobsSummary,
    enabled: panelOpen,
  })

  useEffect(() => {
    if (following && logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [checks, following])

  const onScroll = () => {
    const el = logRef.current
    if (!el) return
    setFollowing(el.scrollHeight - el.scrollTop - el.clientHeight < 40)
  }

  const checksRunning = summary.data?.checks_running ?? 0

  return (
    <Sheet open={panelOpen} onOpenChange={setPanelOpen}>
      <SheetContent aria-describedby={undefined}>
        <div className="border-b border-hairline px-4 py-3">
          <div className="flex items-center gap-2.5 pr-8">
            <Radar size={22} animate={live.length + checksRunning > 0} />
            <SheetTitle className="min-w-0 truncate font-display text-[15px] font-semibold tracking-[0.06em] text-ink uppercase">
              {live.length + checksRunning > 0
                ? `Running: ${live.length} ${live.length === 1 ? 'hunt' : 'hunts'}, ${checksRunning} ${checksRunning === 1 ? 'price check' : 'price checks'}`
                : 'Nothing running'}
            </SheetTitle>
          </div>
          <SheetDescription className="mt-1 flex flex-wrap items-center gap-3 text-xs text-ink-3">
            <span className="flex items-center gap-1.5">
              <span
                aria-hidden
                className={cn(
                  'size-1.5 rounded-full',
                  connection === 'live' ? 'bg-drop' : 'animate-pulse bg-warn',
                )}
              />
              {connection === 'live' ? 'live' : 'reconnecting…'}
            </span>
            <Link
              to="/activity"
              onClick={() => setPanelOpen(false)}
              className="flex items-center gap-1 text-ink-3 hover:text-ink"
            >
              Open the activity page <ExternalLink className="size-3" />
            </Link>
          </SheetDescription>
        </div>

        <div className="flex-1 overflow-y-auto">
          <div className="p-4">
            <LiveHunts onOpen={() => setPanelOpen(false)} />
          </div>
          <div ref={logRef} onScroll={onScroll} className="relative bg-well px-4 py-3">
            {checks.length === 0 ? (
              <p className="font-mono text-xs text-ink-3">
                Nothing checked while this page has been open.
              </p>
            ) : (
              <TerminalLog lines={checks.map(checkLine)} />
            )}
          </div>
        </div>

        {!following ? (
          <button
            type="button"
            onClick={() => {
              setFollowing(true)
              logRef.current?.scrollTo({ top: logRef.current.scrollHeight })
            }}
            className="absolute right-4 bottom-[max(1rem,env(safe-area-inset-bottom))] flex items-center gap-1 rounded-full border border-hairline bg-overlay px-2.5 py-2 text-xs text-ink-2 shadow-lg hover:text-ink"
          >
            <ArrowDown className="size-3" /> Follow
          </button>
        ) : null}
      </SheetContent>
    </Sheet>
  )
}
