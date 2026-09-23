// @vitest-environment jsdom

import { useState, type ComponentProps } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  fetchOptionsTradeStrategyOptions,
  fetchOptionsTradeTracker,
  fetchOptionsTradeTrackers,
  replaceOptionsTradeTrackerTrades,
  type OptionsTradeRow,
} from '@/api/optionsTradeTrackers'
import { OptionsTradeTrackerPage } from '@/features/options-trade-tracker/OptionsTradeTrackerPage'
import { deriveStrategyStats } from '@/features/options-trade-tracker/lib/tradeTracker'
import { mockTableLayout, scrollPage } from '@/features/options-trade-tracker/mockTableLayout.test-support'

const { inputRender, selectRender } = vi.hoisted(() => ({
  inputRender: vi.fn(),
  selectRender: vi.fn(),
}))

vi.mock('@/api/optionsTradeTrackers', () => ({
  createOptionsTradeTracker: vi.fn(),
  deleteOptionsTradeTracker: vi.fn(),
  fetchOptionsTradeStrategyOptions: vi.fn(),
  fetchOptionsTradeTracker: vi.fn(),
  fetchOptionsTradeTrackers: vi.fn(),
  renameOptionsTradeTracker: vi.fn(),
  replaceOptionsTradeStrategyOptions: vi.fn(),
  replaceOptionsTradeTrackerTrades: vi.fn(),
  updateOptionsTradeTrackerNotes: vi.fn(),
}))

// Count real control renders, keeping their input, focus, and Select behavior.
vi.mock('@/components/ui/input', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/components/ui/input')>()
  return {
    ...original,
    Input: (props: ComponentProps<typeof original.Input>) => {
      inputRender(props['aria-label'])
      return <original.Input {...props} />
    },
  }
})

vi.mock('@/components/ui/select', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/components/ui/select')>()
  return {
    ...original,
    SelectTrigger: (props: ComponentProps<typeof original.SelectTrigger>) => {
      selectRender(props['aria-label'])
      return <original.SelectTrigger {...props} />
    },
  }
})

vi.mock('@/features/options-trade-tracker/lib/tradeTracker', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/features/options-trade-tracker/lib/tradeTracker')>()
  return { ...original, deriveStrategyStats: vi.fn(original.deriveStrategyStats) }
})

const tracker = { id: 'income', name: 'Income', created_at: '', updated_at: '' }
const strategies = ['CC', 'CSP']
const trades: OptionsTradeRow[] = Array.from({ length: 3 }, (_, index) => ({
  id: `row-${index}`,
  display_order: index + 1,
  status: 'Completed',
  strategy: 'CC',
  ticker: 'SYN',
  month: 'may',
  expiry_date: null,
  size: -1,
  strike_price: 100,
  credit_debit: 5 + index,
  exit: 2,
  created_at: '',
  updated_at: '',
}))

beforeAll(() => {
  mockTableLayout()
  Element.prototype.hasPointerCapture ??= vi.fn(() => false)
  Element.prototype.setPointerCapture ??= vi.fn()
  Element.prototype.releasePointerCapture ??= vi.fn()
  Element.prototype.scrollIntoView ??= vi.fn()
})

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(fetchOptionsTradeTrackers).mockResolvedValue({ trackers: [tracker] })
  vi.mocked(fetchOptionsTradeStrategyOptions).mockResolvedValue({ strategies })
  vi.mocked(fetchOptionsTradeTracker).mockResolvedValue({
    tracker, trades, notes: '', strategy_options: strategies,
  })
  vi.mocked(replaceOptionsTradeTrackerTrades).mockImplementation(async (_id, request) => ({
    tracker,
    trades: request.trades.map((row, index) => ({ ...trades[index], ...row, id: row.id ?? `saved-${index}` })),
    notes: '',
    strategy_options: strategies,
  }))
})

afterEach(() => {
  cleanup()
  scrollPage(0)
})

function clearRenders() {
  inputRender.mockClear()
  selectRender.mockClear()
}

function renderedRowControls() {
  return [...inputRender.mock.calls, ...selectRender.mock.calls]
    .map(([label]) => String(label))
    .filter((label) => label.includes(' row row-'))
}

function change(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } })
}

describe('tracker edit isolation', () => {
  it('renders only the edited row and isolates notes, dialogs, and parent updates', async () => {
    function Shell() {
      const [snapshot, setSnapshot] = useState(0)
      return <><button onClick={() => setSnapshot(snapshot + 1)}>Portfolio update {snapshot}</button><OptionsTradeTrackerPage /></>
    }
    render(<Shell />)
    await screen.findByLabelText('Ticker row row-0')
    clearRenders()

    change('Ticker row row-0', 'aapl')
    expect(screen.getByDisplayValue('AAPL')).toBeTruthy()
    expect(renderedRowControls()).toContain('Ticker row row-0')
    expect(renderedRowControls().every((label) => label.endsWith('row-0'))).toBe(true)
    expect(deriveStrategyStats).not.toHaveBeenCalled()

    clearRenders()
    change('Tracker notes', 'Keep this draft')
    fireEvent.click(screen.getByRole('button', { name: 'New tracker' }))
    change('Tracker name', 'New workspace')
    fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
    fireEvent.click(screen.getByRole('button', { name: 'Portfolio update 0' }))
    expect(renderedRowControls()).toEqual([])
    expect(screen.getByDisplayValue('Keep this draft')).toBeTruthy()
  })

  it('keeps raw numeric drafts and current P&L, and saves the latest edit immediately', async () => {
    render(<OptionsTradeTrackerPage />)
    const size = await screen.findByLabelText('Size row row-0') as HTMLInputElement
    size.focus()
    for (const value of ['-', '', '-2']) {
      change('Size row row-0', value)
      expect(size.value).toBe(value)
      expect(document.activeElement).toBe(size)
    }

    const credit = screen.getByLabelText('Credit debit row row-0') as HTMLInputElement
    fireEvent.focus(credit)
    change('Credit debit row row-0', '5.')
    expect(credit.value).toBe('5.')
    fireEvent.blur(credit)
    expect(credit.value).toBe('$5.00')
    expect(screen.getByText('$596.00')).toBeTruthy()
    expect(screen.getByText('$1,492.00')).toBeTruthy()

    fireEvent.focus(credit)
    change('Credit debit row row-0', '5.25')
    fireEvent.click(screen.getByRole('button', { name: 'Save trades' }))
    await waitFor(() => expect(replaceOptionsTradeTrackerTrades).toHaveBeenCalledWith(
      'income',
      { trades: [expect.objectContaining({ id: 'row-0', size: -2, credit_debit: 5.25 }), expect.anything(), expect.anything()] },
      expect.any(AbortSignal),
    ))
  })

  it('keeps per-row validation isolated and derives Stats from unsaved drafts on entry', async () => {
    render(<OptionsTradeTrackerPage />)
    await screen.findByLabelText('Ticker row row-0')
    change('Credit debit row row-0', '-1')
    change('Strike price row row-1', '-1')
    fireEvent.click(screen.getByRole('button', { name: 'Save trades' }))
    expect(await screen.findByText('Credit/debit must be a positive currency value.')).toBeTruthy()
    expect(screen.getByText('Strike price must be a positive currency value.')).toBeTruthy()
    expect(replaceOptionsTradeTrackerTrades).not.toHaveBeenCalled()

    clearRenders()
    change('Credit debit row row-0', '6')
    expect(renderedRowControls().every((label) => label.endsWith('row-0'))).toBe(true)
    expect(screen.getByText('Strike price must be a positive currency value.')).toBeTruthy()
    change('Strike price row row-1', '100')
    expect(deriveStrategyStats).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('tab', { name: 'Stats' }))
    expect(await screen.findByText('Summary')).toBeTruthy()
    expect(deriveStrategyStats).toHaveBeenCalled()
    expect(screen.getAllByText('$1,294.00').length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('tab', { name: 'Trades' }))
    expect((screen.getByLabelText('Credit debit row row-0') as HTMLInputElement).value).toBe('$6.00')
  })

  it('mounts a bounded window while offscreen trades contribute to totals, Stats, and saves', async () => {
    const largeTrades = Array.from({ length: 300 }, (_, index) => ({ ...trades[0], id: `row-${index}`, display_order: index + 1 }))
    vi.mocked(fetchOptionsTradeTracker).mockResolvedValue({ tracker, trades: largeTrades, notes: '', strategy_options: strategies })
    render(<OptionsTradeTrackerPage />)
    await screen.findByLabelText('Ticker row row-0')
    expect(screen.queryByLabelText('Ticker row row-299')).toBeNull()
    expect(screen.getAllByLabelText(/^Ticker row /).length).toBeLessThan(25)
    expect(screen.getByText('$89,400.00')).toBeTruthy()
    expect(screen.getByRole('table', { name: 'Trades' }).getAttribute('aria-rowcount')).toBe('302')

    act(() => scrollPage(16250))
    const last = await screen.findByLabelText('Ticker row row-299')
    expect(last.closest('tr')!.cells[0].textContent).toBe('300')
    for (const spacer of screen.getByRole('table', { name: 'Trades' }).querySelectorAll('tr[aria-hidden="true"] td')) {
      expect(spacer.getAttribute('colspan')).toBe('11')
    }
    fireEvent.change(last, { target: { value: 'LAST' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save trades' }))
    await waitFor(() => expect(replaceOptionsTradeTrackerTrades).toHaveBeenCalled())
    const saved = vi.mocked(replaceOptionsTradeTrackerTrades).mock.calls[0][1].trades
    expect(saved).toHaveLength(300)
    expect(saved[0].ticker).toBe('SYN')
    expect(saved[299].ticker).toBe('LAST')
    fireEvent.click(screen.getByRole('tab', { name: 'Stats' }))
    expect(await screen.findByText('Summary')).toBeTruthy()
    expect(screen.getAllByText('$89,400.00').length).toBeGreaterThan(0)
  })

  it('reveals invalid offscreen trades and blocks saving the complete draft', async () => {
    const largeTrades = Array.from({ length: 300 }, (_, index) => ({ ...trades[0], id: `row-${index}`, display_order: index + 1, strike_price: index === 250 ? -1 : 100 }))
    vi.mocked(fetchOptionsTradeTracker).mockResolvedValue({ tracker, trades: largeTrades, notes: '', strategy_options: strategies })
    render(<OptionsTradeTrackerPage />)
    await screen.findByLabelText('Ticker row row-0')
    expect(screen.queryByLabelText('Strike price row row-250')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Save trades' }))
    expect(await screen.findByLabelText('Strike price row row-250')).toBeTruthy()
    expect(screen.getByText('Strike price must be a positive currency value.')).toBeTruthy()
    expect(replaceOptionsTradeTrackerTrades).not.toHaveBeenCalled()
    expect(screen.getAllByLabelText(/^Ticker row /).length).toBeLessThan(25)
  })

  it('retains the focused partial draft across scrolls and focuses a newly appended row', async () => {
    const largeTrades = Array.from({ length: 300 }, (_, index) => ({ ...trades[0], id: `row-${index}`, display_order: index + 1 }))
    vi.mocked(fetchOptionsTradeTracker).mockResolvedValue({ tracker, trades: largeTrades, notes: '', strategy_options: strategies })
    render(<OptionsTradeTrackerPage />)
    const credit = await screen.findByLabelText('Credit debit row row-0') as HTMLInputElement
    act(() => credit.focus())
    fireEvent.change(credit, { target: { value: '5.' } })
    act(() => scrollPage(10000))
    await screen.findByLabelText('Ticker row row-190')
    expect(document.activeElement).toBe(credit)
    expect(credit.value).toBe('5.')
    expect(screen.getAllByLabelText(/^Ticker row /).length).toBeLessThan(28)
    fireEvent.click(screen.getByRole('button', { name: 'Add row' }))
    await waitFor(() => expect(document.activeElement?.getAttribute('aria-label')).toMatch(/^Strategy row draft-/))
    expect(screen.getByRole('table', { name: 'Trades' }).getAttribute('aria-rowcount')).toBe('303')
    expect(document.activeElement!.closest('tr')!.cells[0].textContent).toBe('301')
  })
})
