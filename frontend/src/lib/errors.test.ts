import { expect, it } from 'vitest'

import { errorMessage } from '@/lib/errors'

it('preserves Error text, including blank text, and the exact caller fallback', () => {
  expect(errorMessage(new Error('IB unavailable.'), 'fallback')).toBe('IB unavailable.')
  expect(errorMessage(new Error(''), 'fallback')).toBe('')
  for (const value of [null, undefined, 'failure', { message: 'failure' }]) {
    expect(errorMessage(value, 'Options request failed.')).toBe('Options request failed.')
    expect(errorMessage(value, 'Portfolio request failed')).toBe('Portfolio request failed')
  }
})
