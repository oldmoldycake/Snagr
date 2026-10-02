import { currencySign, formatMoney, fromCents } from '@/lib/money'

/** The largest target watches.target_price (numeric(10, 2)) can hold, in cents. */
const MAX_TARGET_CENTS = 9_999_999_999

/**
 * A dot or a comma marks the cents and the other groups thousands. Tried in
 * this order, so "1,299" is 1299 and "1.299" is not a whole number of cents —
 * the way the agent reads prices off a page.
 */
const AMOUNT_FORMATS = [
  /^(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?$/, // 1,299.00
  /^(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?$/, // 1.299,00
]

const ABOVE_ZERO = 'Enter an amount above zero, or leave it empty for no target.'

/**
 * A target-price field's text as the API's decimal string (null when it is
 * empty: no target), or the message to show under the field instead. Takes a
 * price as people type or paste one ("$549", "549,99", "1,299.00"), so
 * currency signs and spaces are ignored, and refuses what the API would:
 * zero, negatives, fractions of a cent and anything the column can't hold.
 */
export function parseTargetPrice(text: string, currency = 'USD'): { price: string | null } | { error: string } {
  if (!text.trim()) return { price: null }
  const amount = text.replaceAll(currencySign(currency), '').replace(/[\p{Sc}\s]/gu, '')
  if (/^[-−]/.test(amount)) return { error: ABOVE_ZERO }
  const match = AMOUNT_FORMATS.map((format) => format.exec(amount)).find((m) => m != null)
  if (!match) return { error: 'Enter an amount, like 120 or 120.00.' }
  const [, whole, fraction = ''] = match
  if (fraction.length > 2) return { error: 'Use at most two decimals, like 120.99.' }
  const cents = Number(whole.replace(/\D/g, '')) * 100 + Number(fraction.padEnd(2, '0'))
  if (cents < 1) return { error: ABOVE_ZERO }
  if (cents > MAX_TARGET_CENTS) {
    return { error: `Enter at most ${formatMoney(fromCents(MAX_TARGET_CENTS), currency)}.` }
  }
  return { price: fromCents(cents) }
}
