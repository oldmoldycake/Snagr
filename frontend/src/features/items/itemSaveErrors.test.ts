import { describe, expect, it } from 'vitest'
import { ApiError } from '@/api/client'
import { itemSaveErrors } from './itemSaveErrors'

const refused = (code: string, message: string, fields?: Record<string, string>) =>
  new ApiError(422, { error: { code, message, fields } })

describe('itemSaveErrors', () => {
  it('says nothing before a save fails, or for one that never reached Snagr', () => {
    expect(itemSaveErrors(null)).toEqual({ fields: {}, message: null })
    expect(itemSaveErrors(new TypeError('Failed to fetch'))).toEqual({ fields: {}, message: null })
  })

  it('puts a refusal of a field the dialogs show beside it, not on top', () => {
    const taken = 'You already track an item with this name'
    expect(itemSaveErrors(refused('duplicate', taken, { name: taken }))).toEqual({
      fields: { name: taken },
      message: null,
    })
    const floor = refused('validation_error', 'Check interval must be between 5 and 1440 minutes', {
      recheck_interval_minutes: 'Must be between 5 and 1440 minutes',
    })
    expect(itemSaveErrors(floor).message).toBeNull()
    expect(itemSaveErrors(floor).fields.recheck_interval_minutes).toBe('Must be between 5 and 1440 minutes')
  })

  it('keeps the message on top when a field it names has no place in the dialogs', () => {
    const sites = refused('validation_error', "site_ids must be a subset of the category's sites", {
      site_ids: "Must be a subset of the category's linked sites",
    })
    expect(itemSaveErrors(sites).message).toBe("site_ids must be a subset of the category's sites")
  })

  it('keeps the message on top when it names no field', () => {
    const down = new ApiError(503, { error: { code: 'db_unavailable', message: 'Could not reach the database' } })
    expect(itemSaveErrors(down)).toEqual({ fields: {}, message: 'Could not reach the database' })
  })
})
