// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { PortfolioChartValue } from '@/api/portfolioChartValues'
import { PortfolioChartSection } from '@/features/portfolio/components/PortfolioChartSection'

const rows: PortfolioChartValue[] = [
  {
    month: '2024-12',
    portfolio_value: 90_000,
    amount_invested: 75_000,
    updated_at: '2026-06-06T00:00:00+00:00',
  },
  {
    month: '2025-01',
    portfolio_value: 92_000,
    amount_invested: null,
    updated_at: '2026-06-06T00:00:00+00:00',
  },
  {
    month: '2025-12',
    portfolio_value: 125_000,
    amount_invested: 100_000,
    updated_at: '2026-06-06T00:00:00+00:00',
  },
]

afterEach(() => {
  cleanup()
})

describe('PortfolioChartSection', () => {
  it('defaults to advanced mode with separate monthly charts', () => {
    render(
      <PortfolioChartSection
        account="DU1234567"
        currency="USD"
        error={null}
        isLoading={false}
        isSaving={false}
        onSaveRows={vi.fn()}
        rows={rows}
      />,
    )

    expect(screen.getByText('Portfolio history')).toBeTruthy()
    expect(screen.getByText('DU1234567')).toBeTruthy()
    expect(
      screen.getByRole('radio', { name: 'Advanced' }).getAttribute('data-state'),
    ).toBe('on')
    expect(screen.getByRole('heading', { name: 'Portfolio value' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Amount invested' })).toBeTruthy()
    expect(screen.getAllByText('Jan 25').length).toBeGreaterThan(0)
  })

  it('switches to simple mode and renders December yearly values', () => {
    render(
      <PortfolioChartSection
        account="DU1234567"
        currency="USD"
        error={null}
        isLoading={false}
        isSaving={false}
        onSaveRows={vi.fn()}
        rows={rows}
      />,
    )

    fireEvent.click(screen.getByRole('radio', { name: 'Simple' }))

    expect(
      screen.getByRole('radio', { name: 'Simple' }).getAttribute('data-state'),
    ).toBe('on')
    expect(screen.getByRole('heading', { name: 'End-of-year values' })).toBeTruthy()
    expect(screen.getAllByText('Dec 2024').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Dec 2025').length).toBeGreaterThan(0)
    expect(screen.queryByText('Jan 25')).toBeNull()
  })

  it('shows an empty state while keeping Edit values available', () => {
    render(
      <PortfolioChartSection
        account="DU1234567"
        currency="USD"
        error={null}
        isLoading={false}
        isSaving={false}
        onSaveRows={vi.fn()}
        rows={[]}
      />,
    )

    expect(screen.getByText('No saved portfolio history yet.')).toBeTruthy()
    expect(screen.getByRole('button', { name: /Edit values/ })).toBeTruthy()
  })

  it('shows a simple-view empty state when no December rows are saved', () => {
    render(
      <PortfolioChartSection
        account="DU1234567"
        currency="USD"
        error={null}
        isLoading={false}
        isSaving={false}
        onSaveRows={vi.fn()}
        rows={[
          {
            month: '2025-11',
            portfolio_value: 110_000,
            amount_invested: 100_000,
            updated_at: '2026-06-06T00:00:00+00:00',
          },
        ]}
      />,
    )

    fireEvent.click(screen.getByRole('radio', { name: 'Simple' }))

    expect(screen.getByText('No December values saved yet.')).toBeTruthy()
  })

  it('uses distinct chart colors for the two metrics', () => {
    const { container } = render(
      <PortfolioChartSection
        account="DU1234567"
        currency="USD"
        error={null}
        isLoading={false}
        isSaving={false}
        onSaveRows={vi.fn()}
        rows={rows}
      />,
    )

    const styleText = Array.from(container.querySelectorAll('style'))
      .map((style) => style.textContent)
      .join('\n')
    expect(styleText).toContain('--color-portfolio_value')
    expect(styleText).toContain('--color-amount_invested')
  })

  it('keeps the editor hidden until Edit values is clicked', () => {
    render(
      <PortfolioChartSection
        account="DU1234567"
        currency="USD"
        error={null}
        isLoading={false}
        isSaving={false}
        onSaveRows={vi.fn()}
        rows={rows}
      />,
    )

    expect(screen.queryByTestId('portfolio-chart-values-editor')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: /Edit values/ }))

    expect(screen.getByTestId('portfolio-chart-values-editor')).toBeTruthy()
    expect(screen.getByDisplayValue('2024-12')).toBeTruthy()
  })

  it('adds, edits, deletes, and saves a full replacement set', async () => {
    const onSaveRows = vi.fn().mockResolvedValue([
      {
        month: '2025-01',
        portfolio_value: 91_000,
        amount_invested: null,
        updated_at: '2026-06-06T00:00:00+00:00',
      },
      {
        month: '2026-01',
        portfolio_value: 130_000.5,
        amount_invested: 110_000.25,
        updated_at: '2026-06-06T00:00:00+00:00',
      },
    ])

    render(
      <PortfolioChartSection
        account="DU1234567"
        currency="USD"
        error={null}
        isLoading={false}
        isSaving={false}
        onSaveRows={onSaveRows}
        rows={[rows[1]]}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Edit values/ }))
    fireEvent.change(screen.getByLabelText('Portfolio value 1'), {
      target: { value: '91000' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Add month/ }))
    fireEvent.change(screen.getByLabelText('Month 2'), {
      target: { value: '2026-01' },
    })
    fireEvent.change(screen.getByLabelText('Portfolio value 2'), {
      target: { value: '130000.5' },
    })
    fireEvent.change(screen.getByLabelText('Amount invested 2'), {
      target: { value: '110000.25' },
    })
    fireEvent.click(screen.getByLabelText('Delete row 1'))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => {
      expect(onSaveRows).toHaveBeenCalledWith([
        {
          month: '2026-01',
          portfolio_value: 130_000.5,
          amount_invested: 110_000.25,
        },
      ])
    })
    await waitFor(() => {
      expect(screen.queryByTestId('portfolio-chart-values-editor')).toBeNull()
    })
  })

  it('cancels local edits without saving', () => {
    const onSaveRows = vi.fn()

    render(
      <PortfolioChartSection
        account="DU1234567"
        currency="USD"
        error={null}
        isLoading={false}
        isSaving={false}
        onSaveRows={onSaveRows}
        rows={[rows[1]]}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Edit values/ }))
    fireEvent.change(screen.getByLabelText('Month 1'), {
      target: { value: '2026-06' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    fireEvent.click(screen.getByRole('button', { name: /Edit values/ }))

    expect(onSaveRows).not.toHaveBeenCalled()
    expect(screen.getByDisplayValue('2025-01')).toBeTruthy()
  })

  it('blocks save for invalid editor rows', () => {
    const onSaveRows = vi.fn()

    render(
      <PortfolioChartSection
        account="DU1234567"
        currency="USD"
        error={null}
        isLoading={false}
        isSaving={false}
        onSaveRows={onSaveRows}
        rows={[]}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Edit values/ }))
    fireEvent.click(screen.getByRole('button', { name: /Add month/ }))
    fireEvent.change(screen.getByLabelText('Month 1'), {
      target: { value: '2026-13' },
    })
    fireEvent.change(screen.getByLabelText('Portfolio value 1'), {
      target: { value: '$125000' },
    })

    expect(screen.getByText('Row 1: Month must use YYYY-MM format.')).toBeTruthy()
    expect(
      screen.getByText('Row 1: Portfolio value must be a valid number.'),
    ).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Save' }).hasAttribute('disabled'))
      .toBe(true)
    expect(onSaveRows).not.toHaveBeenCalled()
  })

  it('previews valid local edits in charts while the editor is open', () => {
    render(
      <PortfolioChartSection
        account="DU1234567"
        currency="USD"
        error={null}
        isLoading={false}
        isSaving={false}
        onSaveRows={vi.fn()}
        rows={[]}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Edit values/ }))
    fireEvent.click(screen.getByRole('button', { name: /Add month/ }))
    fireEvent.change(screen.getByLabelText('Month 1'), {
      target: { value: '2026-04' },
    })
    fireEvent.change(screen.getByLabelText('Portfolio value 1'), {
      target: { value: '140000' },
    })

    expect(screen.getAllByText('Apr 26').length).toBeGreaterThan(0)
    expect(screen.queryByText('No saved portfolio history yet.')).toBeNull()
  })

  it('discards unsaved local edits when the active account changes', async () => {
    const onSaveRows = vi.fn()
    const { rerender } = render(
      <PortfolioChartSection
        account="DU1234567"
        currency="USD"
        error={null}
        isLoading={false}
        isSaving={false}
        onSaveRows={onSaveRows}
        rows={[rows[1]]}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Edit values/ }))
    fireEvent.change(screen.getByLabelText('Month 1'), {
      target: { value: '2026-06' },
    })
    expect(screen.getAllByText('Jun 26').length).toBeGreaterThan(0)

    rerender(
      <PortfolioChartSection
        account="DU7654321"
        currency="USD"
        error={null}
        isLoading={false}
        isSaving={false}
        onSaveRows={onSaveRows}
        rows={[
          {
            month: '2024-12',
            portfolio_value: 80_000,
            amount_invested: 70_000,
            updated_at: '2026-06-06T00:00:00+00:00',
          },
        ]}
      />,
    )

    await waitFor(() => {
      expect(screen.queryByTestId('portfolio-chart-values-editor')).toBeNull()
    })
    expect(screen.getByText('DU7654321')).toBeTruthy()
    expect(screen.getAllByText('Dec 24').length).toBeGreaterThan(0)
    expect(screen.queryByText('Jun 26')).toBeNull()
    expect(onSaveRows).not.toHaveBeenCalled()
  })

  it('ignores a late editor save after the active account changes', async () => {
    const save = deferred<PortfolioChartValue[]>()
    const onSaveRows = vi.fn().mockReturnValue(save.promise)
    const { rerender } = render(
      <PortfolioChartSection
        account="ACCOUNT-A"
        error={null}
        isLoading={false}
        isSaving={false}
        onSaveRows={onSaveRows}
        rows={[rows[1]]}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Edit values/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    rerender(
      <PortfolioChartSection
        account="ACCOUNT-B"
        error={null}
        isLoading={false}
        isSaving={false}
        onSaveRows={onSaveRows}
        rows={[rows[0]]}
      />,
    )
    await waitFor(() => {
      expect(screen.queryByTestId('portfolio-chart-values-editor')).toBeNull()
    })

    save.resolve([rows[1]])
    await waitFor(() => {
      expect(screen.getByText('ACCOUNT-B')).toBeTruthy()
    })

    expect(screen.getAllByText('Dec 24').length).toBeGreaterThan(0)
    expect(screen.queryByText('Jan 25')).toBeNull()
  })
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}
