import { describe, expect, it } from 'vitest'
import { maskWebhookUrl } from './webhookUrl'

describe('maskWebhookUrl', () => {
  it('keeps the host of a Discord webhook and hides its id and token', () => {
    expect(maskWebhookUrl('https://discord.com/api/webhooks/1234567890/AbC-dEf_123')).toBe(
      'https://discord.com/••••',
    )
  })

  it('hides a token that sits before a suffix', () => {
    expect(maskWebhookUrl('https://discordapp.com/api/webhooks/1234567890/AbC-dEf_123/slack')).toBe(
      'https://discordapp.com/••••',
    )
  })

  it('hides a token carried in the query or the fragment', () => {
    expect(maskWebhookUrl('https://example.com/?token=s3cret')).toBe('https://example.com/••••')
    expect(maskWebhookUrl('https://example.com/#s3cret')).toBe('https://example.com/••••')
  })

  it('hides credentials in the userinfo', () => {
    expect(maskWebhookUrl('http://user:s3cret@hooks.example.com/')).toBe('http://hooks.example.com/••••')
  })

  it('keeps the port, which is part of where alerts go', () => {
    expect(maskWebhookUrl('http://203.0.113.7:8123/api/webhook/s3cret')).toBe('http://203.0.113.7:8123/••••')
  })

  it('has nothing to hide on a bare host', () => {
    expect(maskWebhookUrl('https://hooks.example.com')).toBe('https://hooks.example.com')
    expect(maskWebhookUrl('https://hooks.example.com/')).toBe('https://hooks.example.com')
  })

  it('masks the whole of something that does not parse', () => {
    expect(maskWebhookUrl('not a url/s3cret')).toBe('••••')
  })
})
