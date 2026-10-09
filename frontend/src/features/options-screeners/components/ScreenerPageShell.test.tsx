// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { OptionsScreenerScanJob } from '@/api/optionsScreeners'
import { Alert } from '@/components/ui/alert'
import { ScanActionButton } from '@/features/options-screeners/components/ScanActionButton'
import { ScreenerPageShell } from '@/features/options-screeners/components/ScreenerPageShell'
import { defaultSingleLegFilters } from '@/features/options-screeners/lib/screenerSettings'

afterEach(cleanup)

const activeJob: OptionsScreenerScanJob = {
  id: 'job-1', screener: 'csp', status: 'active', tickers: ['AAPL'],
  filters: defaultSingleLegFilters,
  total_tickers: 1, completed_tickers: 0, progress_message: '',
  successful_tickers: 0, no_match_tickers: 0, failed_tickers: 0,
  total_match_count: 0, excluded_contracts: 0, candidates: [], errors: [], warnings: [],
  started_at: '2026-07-01T16:00:00Z', finished_at: null, successful_completion_at: null,
}

describe('shared screener page controls', () => {
  it.each([ [0, 'Scan tickers'], [1, 'Scan 1 ticker'], [2, 'Scan 2 tickers'] ])(
    'preserves the scan label and disabled behavior for %i tickers',
    (tickerCount, label) => {
      const onStartScan = vi.fn(async () => {})
      const props = { activeJob: null, tickerCount, onStartScan, onCancelScan: vi.fn(async () => {}) }
      const view = render(<ScanActionButton {...props} disabled />)
      const button = screen.getByRole('button', { name: label }) as HTMLButtonElement
      expect(button.disabled).toBe(true)
      fireEvent.click(button)
      expect(onStartScan).not.toHaveBeenCalled()
      view.rerender(<ScanActionButton {...props} disabled={false} />)
      fireEvent.click(button)
      expect(onStartScan).toHaveBeenCalledOnce()
    },
  )

  it('keeps cancellation enabled for the active screener even when scanning is disabled', () => {
    const onStartScan = vi.fn(async () => {})
    const onCancelScan = vi.fn(async () => {})
    render(<ScanActionButton activeJob={activeJob} disabled tickerCount={1} onStartScan={onStartScan} onCancelScan={onCancelScan} />)
    const button = screen.getByRole('button', { name: 'Cancel scan' }) as HTMLButtonElement
    expect(button.disabled).toBe(false)
    fireEvent.click(button)
    expect(onCancelScan).toHaveBeenCalledOnce()
    expect(onStartScan).not.toHaveBeenCalled()
  })

  it('preserves alert order, the results heading id, and slot order', () => {
    render(
      <ScreenerPageShell
        title="Cash-Secured Put Screener"
        loadError="load error"
        scanActionError="scan error"
        tickerEditor={<Alert>ticker error</Alert>}
        filters={<Alert>filter error</Alert>}
        headingId="results-heading"
        activeJob={null}
        snapshot={null}
        visibleCount={0}
        ticketError="ticket error"
        isRefreshingTicket
        refreshMessage="Refreshing the selected contract and quote..."
        results={<div data-testid="results-table">results table</div>}
      >
        <div data-testid="strategy-ticket">strategy ticket</div>
      </ScreenerPageShell>,
    )
    expect(screen.getAllByRole('alert').map((alert) => alert.textContent)).toEqual([
      'load error', 'scan error', 'ticker error', 'filter error', 'ticket error',
      'Refreshing the selected contract and quote...',
    ])
    const heading = screen.getByRole('heading', { name: 'Results' })
    expect(heading.id).toBe('results-heading')
    expect(heading.closest('section')?.getAttribute('aria-labelledby')).toBe('results-heading')
    const table = screen.getByTestId('results-table')
    const ticket = screen.getByTestId('strategy-ticket')
    expect(table.compareDocumentPosition(ticket) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})
