import { afterEach, expect, it, vi } from 'vitest'

import { createLocalId, draftNumberText } from '@/lib/drafts'

afterEach(() => vi.restoreAllMocks())

it('keeps nullable number drafts blank while retaining zero and number text', () => {
  expect(draftNumberText(null)).toBe('')
  expect(draftNumberText(0)).toBe('0')
  expect(draftNumberText(-12.5)).toBe('-12.5')
})

it('keeps the timestamp/random row id shape with the caller prefix', () => {
  vi.spyOn(Date, 'now').mockReturnValue(1712)
  vi.spyOn(Math, 'random').mockReturnValue(0.5)
  expect(createLocalId('draft')).toBe('draft-1712-i')
  expect(createLocalId('other')).toBe('other-1712-i')
})
