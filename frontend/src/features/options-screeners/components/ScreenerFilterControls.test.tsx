// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ScreenerFilterControls } from '@/features/options-screeners/components/ScreenerFilterControls'
import {
  defaultCspFilters,
  filterDraftFromSettings,
} from '@/features/options-screeners/lib/screenerSettings'

afterEach(cleanup)

describe('ScreenerFilterControls', () => {
  it('emits field edits and resets filters', () => {
    const onChange = vi.fn()
    const onReset = vi.fn()
    render(
      <ScreenerFilterControls
        action={<button type="button">Scan tickers</button>}
        draft={filterDraftFromSettings(defaultCspFilters)}
        error={null}
        saveStatus="saved"
        onChange={onChange}
        onReset={onReset}
      />,
    )

    fireEvent.change(screen.getByLabelText('Minimum annualized %'), {
      target: { value: '18.5' },
    })
    expect(onChange).toHaveBeenCalledWith(
      'minimum_annualized_return',
      '18.5',
    )
    expect(screen.getByRole('button', { name: 'Scan tickers' })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /reset filters/i }))
    expect(onReset).toHaveBeenCalled()
  })
})
