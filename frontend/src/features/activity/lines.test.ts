import { describe, expect, it } from 'vitest'
import type { Job, JobEvent } from '@/api/types'
import { checkReceipt, failureDetail, huntReceipt, resultText, runningWork } from './lines'

function job(kind: Job['kind'], status: Job['status'] = 'running'): Job {
  return { kind, status } as Job
}

function hunt(itemId: number, siteId: number, status: Job['status'] = 'pending'): Job {
  return {
    kind: 'hunt',
    status,
    item_id: itemId,
    site_id: siteId,
    label: `Item ${itemId} × Site ${siteId}`,
  } as Job
}

describe('runningWork', () => {
  it('counts market-price refreshes apart from hunts', () => {
    expect(runningWork([job('hunt'), job('ground')])).toBe('1 hunt, 1 market price')
  })

  it('names only the kinds that are running', () => {
    expect(runningWork([job('hunt'), job('hunt')])).toBe('2 hunts')
    expect(runningWork([job('ground')])).toBe('1 market price')
    expect(runningWork([], 3)).toBe('3 price checks')
    expect(runningWork([])).toBe('')
  })

  it('adds the price checks it is given', () => {
    expect(runningWork([job('hunt'), job('ground'), job('ground')], 1)).toBe(
      '1 hunt, 2 market prices, 1 price check',
    )
  })
})

describe('huntReceipt', () => {
  it('says an item fans out into a hunt per site', () => {
    expect(huntReceipt([hunt(1, 10), hunt(1, 11), hunt(1, 12), hunt(1, 13)])).toBe(
      'Queued 4 hunts, one per site',
    )
  })

  it('says a site fans out into a hunt per item', () => {
    expect(huntReceipt([hunt(1, 10), hunt(2, 10)])).toBe('Queued 2 hunts, one per item')
  })

  it('counts the items a wider scope covers', () => {
    expect(huntReceipt([hunt(1, 10), hunt(1, 11), hunt(2, 10)])).toBe('Queued 3 hunts across 2 items')
  })

  it('names a single hunt', () => {
    expect(huntReceipt([hunt(1, 10)])).toBe('Queued a hunt for Item 1 × Site 10')
  })

  it('says which of them were already running', () => {
    expect(huntReceipt([hunt(1, 10, 'running'), hunt(1, 11)])).toBe(
      'Queued 2 hunts, one per site (1 already running)',
    )
    expect(huntReceipt([hunt(1, 10, 'running')])).toBe('Already running a hunt for Item 1 × Site 10')
  })

  it('says when there was nowhere to search', () => {
    expect(huntReceipt([])).toBe('No sites to search, so nothing was queued')
  })
})

function event(seq: number, event_type: JobEvent['event_type'], payload: JobEvent['payload'] = null): JobEvent {
  return { job_id: 1, seq, ts: '', level: 'error', event_type, message: '', payload }
}

describe('failureDetail', () => {
  it('reads the raw error of the last failed attempt', () => {
    const events = [
      event(1, 'job_started'),
      event(2, 'error', { detail: 'unit exceeded the 900s budget' }),
      event(3, 'job_started'),
      event(4, 'error', { detail: 'Error code: 401 - invalid x-api-key' }),
      event(5, 'site_paused', { detail: 'not an error' }),
    ]
    expect(failureDetail(events)).toBe('Error code: 401 - invalid x-api-key')
  })

  it('skips error lines that carry no detail, like a deferred search', () => {
    expect(failureDetail([event(1, 'error', { detail: 'page.goto: net::ERR' }), event(2, 'error')])).toBe(
      'page.goto: net::ERR',
    )
  })

  it('is null when nothing was kept', () => {
    expect(failureDetail([])).toBeNull()
    expect(failureDetail([event(1, 'error')])).toBeNull()
  })
})

function finished(stats: Partial<NonNullable<Job['stats']>>, status: Job['status'] = 'done'): Job {
  return { kind: 'hunt', status, stats } as Job
}

describe('resultText', () => {
  // the job page's "Listings looked at" tile counts the same thing, so the row
  // and the page it opens say it in the same words
  it('says what the count of candidates is', () => {
    expect(resultText(finished({ new_listings: 1, listings_checked: 3 })).text).toBe(
      '✚ 1 new · 3 looked at',
    )
    expect(resultText(finished({ new_listings: 0, listings_checked: 3 })).text).toBe(
      'nothing new · 3 looked at',
    )
    expect(resultText(finished({ listings_checked: 2 }, 'cancelled')).text).toBe(
      'cancelled · 2 looked at',
    )
  })
})

describe('checkReceipt', () => {
  it('counts the checks it queued', () => {
    expect(checkReceipt(3)).toBe('Queued 3')
  })

  it('says when there was nothing to check rather than queuing none', () => {
    expect(checkReceipt(0)).toBe('Nothing to check')
  })
})
