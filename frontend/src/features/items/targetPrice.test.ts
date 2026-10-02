import { describe, expect, it } from 'vitest'
import { parseTargetPrice } from './targetPrice'

describe('parseTargetPrice', () => {
  it('reads an empty field as no target', () => {
    expect(parseTargetPrice('')).toEqual({ price: null })
    expect(parseTargetPrice('   ')).toEqual({ price: null })
  })

  it('takes whole and decimal amounts as the API writes them', () => {
    expect(parseTargetPrice('549')).toEqual({ price: '549.00' })
    expect(parseTargetPrice('549.9')).toEqual({ price: '549.90' })
    expect(parseTargetPrice(' 549.99 ')).toEqual({ price: '549.99' })
    expect(parseTargetPrice('0.01')).toEqual({ price: '0.01' })
  })

  it("ignores the currency's sign and spaces", () => {
    expect(parseTargetPrice('$549')).toEqual({ price: '549.00' })
    expect(parseTargetPrice('$ 549.99')).toEqual({ price: '549.99' })
    expect(parseTargetPrice('549 $')).toEqual({ price: '549.00' })
    expect(parseTargetPrice('549 €', 'EUR')).toEqual({ price: '549.00' })
    expect(parseTargetPrice('CA$549', 'CAD')).toEqual({ price: '549.00' })
  })

  it('reads a decimal comma, and the other separator as thousands', () => {
    expect(parseTargetPrice('549,99')).toEqual({ price: '549.99' })
    expect(parseTargetPrice('549,9')).toEqual({ price: '549.90' })
    expect(parseTargetPrice('1,299.00')).toEqual({ price: '1299.00' })
    expect(parseTargetPrice('$1,299.00')).toEqual({ price: '1299.00' })
    expect(parseTargetPrice('1.299,00')).toEqual({ price: '1299.00' })
    expect(parseTargetPrice('1 299,00 €', 'EUR')).toEqual({ price: '1299.00' })
    expect(parseTargetPrice('1,299')).toEqual({ price: '1299.00' })
    expect(parseTargetPrice('1,234,567.89')).toEqual({ price: '1234567.89' })
  })

  it('refuses zero and negatives, pointing at leaving it empty', () => {
    const aboveZero = { error: 'Enter an amount above zero, or leave it empty for no target.' }
    expect(parseTargetPrice('0')).toEqual(aboveZero)
    expect(parseTargetPrice('$0.00')).toEqual(aboveZero)
    expect(parseTargetPrice('0,00')).toEqual(aboveZero)
    expect(parseTargetPrice('-5')).toEqual(aboveZero)
    expect(parseTargetPrice('-$5')).toEqual(aboveZero)
    expect(parseTargetPrice('$-5')).toEqual(aboveZero)
    expect(parseTargetPrice('−5')).toEqual(aboveZero)
  })

  it('refuses fractions of a cent rather than rounding them away', () => {
    const cents = { error: 'Use at most two decimals, like 120.99.' }
    expect(parseTargetPrice('1.001')).toEqual(cents)
    expect(parseTargetPrice('1.299')).toEqual(cents)
    expect(parseTargetPrice('1,2345')).toEqual(cents)
  })

  it('refuses more than the API can store', () => {
    expect(parseTargetPrice('99999999.99')).toEqual({ price: '99999999.99' })
    expect(parseTargetPrice('100000000')).toEqual({ error: 'Enter at most $99,999,999.99.' })
    expect(parseTargetPrice('100000000', 'EUR')).toEqual({ error: 'Enter at most €99,999,999.99.' })
  })

  it('refuses text that is not one amount', () => {
    const notAnAmount = { error: 'Enter an amount, like 120 or 120.00.' }
    for (const text of ['abc', '$', '1e3', 'NaN', 'Infinity', '12,34,56', '1,29.00', '1.2.3', '549.', '$10 to $20']) {
      expect(parseTargetPrice(text), text).toEqual(notAnAmount)
    }
  })
})
