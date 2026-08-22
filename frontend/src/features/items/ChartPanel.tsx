import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { getPriceHistory, getPriceSummary } from '@/api/endpoints'
import { qk } from '@/api/queries'
import { RangeSelector } from '@/components/charts/RangeSelector'
import { Card, CardBody, CardHeader, CardTitle } from '@/components/ui/card'
import { Segmented } from '@/components/ui/segmented'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/cn'
import type { TimeRange } from '@/lib/time'
import { AvgBestChart } from './AvgBestChart'
import { PriceHistoryChart } from './PriceHistoryChart'

type ChartTab = 'listings' | 'summary'

const TABS = [
  { value: 'listings', label: 'Per listing' },
  { value: 'summary', label: 'Avg vs best' },
] as const

/** One chart surface with two views — per-listing steps or the avg/best summary. */
export function ChartPanel({
  itemId,
  range,
  onRangeChange,
}: {
  itemId: number
  range: TimeRange
  onRangeChange: (range: TimeRange) => void
}) {
  const [tab, setTab] = useState<ChartTab>('listings')

  const history = useQuery({
    queryKey: qk.itemHistory(itemId, range),
    queryFn: () => getPriceHistory(itemId, range),
    placeholderData: keepPreviousData,
    enabled: tab === 'listings',
  })
  const summary = useQuery({
    queryKey: qk.itemSummary(itemId, range),
    queryFn: () => getPriceSummary(itemId, range),
    placeholderData: keepPreviousData,
    enabled: tab === 'summary',
  })

  const active = tab === 'listings' ? history : summary

  return (
    <Card className={cn(active.isFetching && 'opacity-60')}>
      <CardHeader className="border-b border-hairline pb-3">
        <div className="flex items-center gap-4">
          <CardTitle>Price history</CardTitle>
          <Segmented options={TABS} value={tab} onChange={setTab} ariaLabel="Chart view" />
        </div>
        <RangeSelector value={range} onChange={onRangeChange} />
      </CardHeader>
      <CardBody className="px-2 pt-3">
        {active.isLoading ? (
          <Skeleton className="m-2 h-56" />
        ) : tab === 'listings' && history.data ? (
          <PriceHistoryChart data={history.data} range={range} />
        ) : tab === 'summary' && summary.data ? (
          <AvgBestChart data={summary.data} range={range} />
        ) : null}
      </CardBody>
    </Card>
  )
}
