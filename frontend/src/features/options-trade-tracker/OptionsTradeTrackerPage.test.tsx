// @vitest-environment jsdom

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createOptionsTradeTracker,
  deleteOptionsTradeTracker,
  fetchOptionsTradeStrategyOptions,
  fetchOptionsTradeTracker,
  fetchOptionsTradeTrackers,
  renameOptionsTradeTracker,
  replaceOptionsTradeStrategyOptions,
  replaceOptionsTradeTrackerTrades,
  updateOptionsTradeTrackerNotes,
} from '@/api/optionsTradeTrackers'
import { OptionsTradeTrackerPage } from '@/features/options-trade-tracker/OptionsTradeTrackerPage'

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

beforeAll(() => {
  Element.prototype.hasPointerCapture ??= vi.fn(() => false)
  Element.prototype.setPointerCapture ??= vi.fn()
  Element.prototype.releasePointerCapture ??= vi.fn()
  Element.prototype.scrollIntoView ??= vi.fn()
})

const incomeTracker = {
  id: 'income',
  name: 'Income',
  created_at: '2026-06-06T01:02:03+00:00',
  updated_at: '2026-06-06T01:02:03+00:00',
}

const growthTracker = {
  id: 'growth',
  name: 'Growth',
  created_at: '2026-06-06T01:02:03+00:00',
  updated_at: '2026-06-06T01:02:03+00:00',
}

beforeEach(() => {
  vi.mocked(fetchOptionsTradeTrackers).mockResolvedValue({
    trackers: [incomeTracker, growthTracker],
  })
  vi.mocked(fetchOptionsTradeStrategyOptions).mockResolvedValue({
    strategies: ['WHEEL', 'SPREAD'],
  })
  vi.mocked(fetchOptionsTradeTracker).mockImplementation(async (trackerId) => ({
    tracker: trackerId === 'growth' ? growthTracker : incomeTracker,
    trades:
      trackerId === 'growth'
        ? [
            {
              id: 'growth-row-1',
              display_order: 1,
              status: 'In Progress',
              strategy: 'SPREAD',
              ticker: 'MSFT',
              month: 'feb',
              size: null,
              strike_price: null,
              credit_debit: null,
              exit: null,
              created_at: '',
              updated_at: '',
            },
          ]
        : [],
    notes: trackerId === 'growth' ? 'Growth notes' : '',
    strategy_options: ['WHEEL', 'SPREAD'],
  }))
  vi.mocked(replaceOptionsTradeStrategyOptions).mockResolvedValue({
    strategies: ['WHEEL', 'SPREAD', 'IRON CONDOR'],
  })
  vi.mocked(replaceOptionsTradeTrackerTrades).mockImplementation(
    async (_trackerId, request) => ({
      tracker: incomeTracker,
      trades: request.trades.map((trade, index) => ({
        id: trade.id ?? `saved-row-${index + 1}`,
        display_order: trade.display_order,
        status: trade.status ?? 'In Progress',
        strategy: trade.strategy ?? null,
        ticker: trade.ticker ?? null,
        month: trade.month ?? null,
        size: trade.size ?? null,
        strike_price: trade.strike_price ?? null,
        credit_debit: trade.credit_debit ?? null,
        exit: trade.exit ?? null,
        created_at: '',
        updated_at: '',
      })),
      notes: '',
      strategy_options: ['WHEEL', 'SPREAD', 'IRON CONDOR'],
    }),
  )
  vi.mocked(updateOptionsTradeTrackerNotes).mockImplementation(
    async (_trackerId, request) => ({
      tracker: incomeTracker,
      trades: [],
      notes: request.notes,
      strategy_options: ['WHEEL', 'SPREAD'],
    }),
  )
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('OptionsTradeTrackerPage', () => {
  it('shows an empty first-visit state without creating a default tracker', async () => {
    vi.mocked(fetchOptionsTradeTrackers).mockResolvedValueOnce({ trackers: [] })

    render(<OptionsTradeTrackerPage />)

    expect(await screen.findByText('No trackers yet')).toBeTruthy()
    expect(fetchOptionsTradeTrackers).toHaveBeenCalledTimes(1)
    expect(fetchOptionsTradeStrategyOptions).toHaveBeenCalledTimes(1)
    expect(createOptionsTradeTracker).not.toHaveBeenCalled()
  })

  it('creates a tracker and selects the returned workspace', async () => {
    const createdTracker = { ...incomeTracker, id: 'new-tracker', name: 'June' }
    vi.mocked(fetchOptionsTradeTrackers).mockResolvedValueOnce({ trackers: [] })
    vi.mocked(createOptionsTradeTracker).mockResolvedValueOnce({
      tracker: createdTracker,
      trades: [],
      notes: '',
      strategy_options: ['Wheel'],
    })

    render(<OptionsTradeTrackerPage />)

    fireEvent.click(await screen.findByText('Create tracker'))
    fireEvent.change(screen.getByLabelText('Tracker name'), {
      target: { value: ' June ' },
    })
    fireEvent.click(screen.getByText('Create'))

    await waitFor(() => {
      expect(createOptionsTradeTracker).toHaveBeenCalledWith({ name: 'June' })
    })
    expect(await screen.findByText('June')).toBeTruthy()
  })

  it('loads tracker summaries and global strategy options independently', async () => {
    render(<OptionsTradeTrackerPage />)

    expect(await screen.findByText('Income')).toBeTruthy()
    expect(fetchOptionsTradeTrackers).toHaveBeenCalledTimes(1)
    expect(fetchOptionsTradeStrategyOptions).toHaveBeenCalledTimes(1)
    expect(fetchOptionsTradeTracker).toHaveBeenCalledWith(
      'income',
      expect.any(AbortSignal),
    )
    expect(screen.queryByText('2 global strategies loaded')).toBeNull()
  })

  it('keeps the selected tracker stable while switching tabs', async () => {
    render(<OptionsTradeTrackerPage />)

    expect(await screen.findByText('Income')).toBeTruthy()

    fireEvent.click(screen.getByRole('tab', { name: 'Stats' }))
    await waitFor(() => {
      expect(screen.getByText('Summary')).toBeTruthy()
    })
    expect(screen.getAllByText('Income').length).toBeGreaterThan(0)

    fireEvent.click(screen.getByRole('tab', { name: 'Trades' }))
    expect(await screen.findByRole('button', { name: 'Add row' })).toBeTruthy()
    expect(screen.getAllByText('Income').length).toBeGreaterThan(0)
  })

  it('renames the selected tracker from the actions menu', async () => {
    vi.mocked(renameOptionsTradeTracker).mockResolvedValueOnce({
      tracker: { ...incomeTracker, name: 'Renamed income' },
      trades: [],
      notes: '',
      strategy_options: ['Wheel'],
    })

    render(<OptionsTradeTrackerPage />)

    expect(await screen.findByText('Income')).toBeTruthy()
    fireEvent.pointerDown(screen.getByLabelText('Tracker actions'))
    fireEvent.click(await screen.findByText('Rename'))
    fireEvent.change(screen.getByLabelText('Tracker name'), {
      target: { value: ' Renamed income ' },
    })
    fireEvent.click(screen.getByText('Rename'))

    await waitFor(() => {
      expect(renameOptionsTradeTracker).toHaveBeenCalledWith(
        'income',
        { name: 'Renamed income' },
        expect.any(AbortSignal),
      )
    })
    await waitFor(() => {
      expect(screen.getAllByText('Renamed income').length).toBeGreaterThan(0)
    })
  })

  it('confirms deletion and clears the active selected tracker', async () => {
    vi.mocked(deleteOptionsTradeTracker).mockResolvedValueOnce(undefined)

    render(<OptionsTradeTrackerPage />)

    expect(await screen.findByText('Income')).toBeTruthy()
    fireEvent.pointerDown(screen.getByLabelText('Tracker actions'))
    fireEvent.click(await screen.findByText('Delete'))

    expect(await screen.findByText('Delete tracker?')).toBeTruthy()
    fireEvent.click(screen.getByText('Delete tracker'))

    await waitFor(() => {
      expect(deleteOptionsTradeTracker).toHaveBeenCalledWith(
        'income',
        expect.any(AbortSignal),
      )
    })
    expect(
      await screen.findByText((text) =>
        text.includes('1 tracker available. Select one'),
      ),
    ).toBeTruthy()
  })

  it('closes the delete confirmation when clicking outside', async () => {
    render(<OptionsTradeTrackerPage />)

    expect(await screen.findByText('Income')).toBeTruthy()
    fireEvent.pointerDown(screen.getByLabelText('Tracker actions'))
    fireEvent.click(await screen.findByText('Delete'))

    expect(await screen.findByText('Delete tracker?')).toBeTruthy()
    const overlay = document.querySelector('[data-slot="alert-dialog-overlay"]')
    expect(overlay).toBeTruthy()

    fireEvent.pointerDown(overlay as Element)

    await waitFor(() => {
      expect(screen.queryByText('Delete tracker?')).toBeNull()
    })
  })

  it('keeps loaded data visible when a save fails', async () => {
    vi.mocked(renameOptionsTradeTracker).mockRejectedValueOnce(
      new Error('Tracker name already exists.'),
    )

    render(<OptionsTradeTrackerPage />)

    expect(await screen.findByText('Income')).toBeTruthy()
    fireEvent.pointerDown(screen.getByLabelText('Tracker actions'))
    fireEvent.click(await screen.findByText('Rename'))
    fireEvent.change(screen.getByLabelText('Tracker name'), {
      target: { value: 'Growth' },
    })
    fireEvent.click(screen.getByText('Rename'))

    await waitFor(() => {
      expect(screen.getAllByText('Tracker name already exists.').length).toBe(2)
    })
    expect(screen.getAllByText('Income').length).toBeGreaterThan(0)
  })

  it('adds, edits, reorders, deletes, and saves trade rows', async () => {
    render(<OptionsTradeTrackerPage />)

    await screen.findByText('Income')
    fireEvent.click(await screen.findByRole('button', { name: 'Add row' }))

    setFirstStrategy('WHEEL')
    fireEvent.change(screen.getByLabelText(/Ticker row/), {
      target: { value: 'aapl' },
    })
    fireEvent.change(screen.getByLabelText(/Size row/), {
      target: { value: '-1' },
    })
    fireEvent.change(screen.getByLabelText(/Strike price row/), {
      target: { value: '190' },
    })
    fireEvent.change(screen.getByLabelText(/Credit debit row/), {
      target: { value: '1.5' },
    })
    fireEvent.click(await screen.findByRole('button', { name: 'Add row' }))

    expect((screen.getAllByLabelText(/Ticker row/)[0] as HTMLInputElement).value).toBe(
      'AAPL',
    )

    dragRow(
      screen.getAllByLabelText(/Drag row/)[0],
      screen.getAllByLabelText(/Drag row/)[1],
    )
    fireEvent.click(screen.getAllByLabelText(/Delete row/)[0])
    fireEvent.click(screen.getByRole('button', { name: 'Save trades' }))

    await waitFor(() => {
      expect(replaceOptionsTradeTrackerTrades).toHaveBeenCalledWith(
        'income',
        {
          trades: [
            expect.objectContaining({
              display_order: 1,
              status: 'In Progress',
            }),
          ],
        },
        expect.any(AbortSignal),
      )
    })
  })

  it('creates global strategy options from strategy cells', async () => {
    let globalStrategies = ['WHEEL', 'SPREAD']
    vi.mocked(replaceOptionsTradeStrategyOptions).mockImplementationOnce(
      async (request) => {
        globalStrategies = request.strategies
        return { strategies: globalStrategies }
      },
    )
    vi.mocked(fetchOptionsTradeTracker).mockImplementation(async (trackerId) => ({
      tracker: trackerId === 'growth' ? growthTracker : incomeTracker,
      trades: [],
      notes: trackerId === 'growth' ? 'Growth notes' : '',
      strategy_options: globalStrategies,
    }))

    render(<OptionsTradeTrackerPage />)

    await screen.findByText('Income')
    fireEvent.click(await screen.findByRole('button', { name: 'Add row' }))
    openSelect(/Strategy row/)
    fireEvent.click(await screen.findByText('Add strategy'))
    fireEvent.change(screen.getByLabelText('Strategy name'), {
      target: { value: 'iron   condor' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Add strategy' }))

    await waitFor(() => {
      expect(replaceOptionsTradeStrategyOptions).toHaveBeenCalledWith({
        strategies: ['WHEEL', 'SPREAD', 'IRON CONDOR'],
      }, expect.any(AbortSignal))
    })
    expect(screen.queryByText('3 global strategies loaded')).toBeNull()

    openSelect('Select tracker')
    fireEvent.click(await screen.findByText('Growth'))
    await waitFor(() => {
      expect(fetchOptionsTradeTracker).toHaveBeenCalledWith(
        'growth',
        expect.any(AbortSignal),
      )
    })
    expect(screen.queryByText('3 global strategies loaded')).toBeNull()
  })

  it('computes completed trade P&L and footer totals', async () => {
    render(<OptionsTradeTrackerPage />)

    await screen.findByText('Income')
    fireEvent.click(await screen.findByRole('button', { name: 'Add row' }))
    setFirstStrategy('WHEEL')
    fireEvent.change(screen.getByLabelText(/Ticker row/), {
      target: { value: 'aapl' },
    })
    fireEvent.change(screen.getByLabelText(/Size row/), {
      target: { value: '-2' },
    })
    fireEvent.change(screen.getByLabelText(/Strike price row/), {
      target: { value: '190' },
    })
    fireEvent.change(screen.getByLabelText(/Credit debit row/), {
      target: { value: '1.5' },
    })

    expect(screen.queryByText('$296.00')).toBeNull()
    setFirstStatus('Completed')

    expect(await screen.findAllByText('$296.00')).toHaveLength(2)
  })

  it('shows inline validation for invalid completed rows before saving', async () => {
    render(<OptionsTradeTrackerPage />)

    await screen.findByText('Income')
    fireEvent.click(await screen.findByRole('button', { name: 'Add row' }))
    setFirstStatus('Completed')
    fireEvent.click(screen.getByRole('button', { name: 'Save trades' }))

    expect(
      await screen.findByText(/Completed rows require strategy/),
    ).toBeTruthy()
    expect(replaceOptionsTradeTrackerTrades).not.toHaveBeenCalled()
  })

  it('rejects zero-size completed rows before saving', async () => {
    render(<OptionsTradeTrackerPage />)

    await screen.findByText('Income')
    fireEvent.click(await screen.findByRole('button', { name: 'Add row' }))
    setFirstStrategy('WHEEL')
    fireEvent.change(screen.getByLabelText(/Ticker row/), {
      target: { value: 'AAPL' },
    })
    fireEvent.change(screen.getByLabelText(/Size row/), {
      target: { value: '0' },
    })
    fireEvent.change(screen.getByLabelText(/Strike price row/), {
      target: { value: '190' },
    })
    fireEvent.change(screen.getByLabelText(/Credit debit row/), {
      target: { value: '1.5' },
    })
    setFirstStatus('Completed')
    fireEvent.click(screen.getByRole('button', { name: 'Save trades' }))

    expect(
      await screen.findByText(/Completed rows require strategy/),
    ).toBeTruthy()
    expect(replaceOptionsTradeTrackerTrades).not.toHaveBeenCalled()
    expect(screen.queryByText('$-2.00')).toBeNull()
  })

  it('edits and saves tracker notes', async () => {
    render(<OptionsTradeTrackerPage />)

    await screen.findByText('Income')
    fireEvent.change(screen.getByLabelText('Tracker notes'), {
      target: { value: 'Plan the exit before earnings.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save notes' }))

    await waitFor(() => {
      expect(updateOptionsTradeTrackerNotes).toHaveBeenCalledWith(
        'income',
        { notes: 'Plan the exit before earnings.' },
        expect.any(AbortSignal),
      )
    })
  })

  it('preserves unsaved trade edits when notes save', async () => {
    const notesSave = deferred<
      Awaited<ReturnType<typeof updateOptionsTradeTrackerNotes>>
    >()
    vi.mocked(updateOptionsTradeTrackerNotes).mockReturnValueOnce(notesSave.promise)

    render(<OptionsTradeTrackerPage />)

    await screen.findByText('Income')
    fireEvent.click(await screen.findByRole('button', { name: 'Add row' }))
    fireEvent.change(screen.getByLabelText(/Ticker row/), {
      target: { value: 'aapl' },
    })
    fireEvent.change(screen.getByLabelText('Tracker notes'), {
      target: { value: 'Saved notes' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save notes' }))

    notesSave.resolve(trackerDetail(incomeTracker, 'Saved notes', 'STALE'))
    await act(async () => {
      await notesSave.promise
    })

    expect(screen.getByDisplayValue('AAPL')).toBeTruthy()
    expect(screen.queryByDisplayValue('STALE')).toBeNull()
    expect(screen.getByDisplayValue('Saved notes')).toBeTruthy()
  })

  it('preserves unsaved notes when trades save', async () => {
    const tradesSave = deferred<
      Awaited<ReturnType<typeof replaceOptionsTradeTrackerTrades>>
    >()
    vi.mocked(replaceOptionsTradeTrackerTrades).mockReturnValueOnce(
      tradesSave.promise,
    )

    render(<OptionsTradeTrackerPage />)

    await screen.findByText('Income')
    fireEvent.click(await screen.findByRole('button', { name: 'Add row' }))
    fireEvent.change(screen.getByLabelText(/Ticker row/), {
      target: { value: 'aapl' },
    })
    fireEvent.change(screen.getByLabelText('Tracker notes'), {
      target: { value: 'Unsaved notes' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save trades' }))

    tradesSave.resolve(trackerDetail(incomeTracker, 'STALE NOTES', 'AAPL'))
    await act(async () => {
      await tradesSave.promise
    })

    expect(screen.getByDisplayValue('AAPL')).toBeTruthy()
    expect(screen.getByDisplayValue('Unsaved notes')).toBeTruthy()
    expect(screen.queryByDisplayValue('STALE NOTES')).toBeNull()
  })

  it('keeps simultaneous trade and notes saves independent out of order', async () => {
    const tradesSave = deferred<
      Awaited<ReturnType<typeof replaceOptionsTradeTrackerTrades>>
    >()
    const notesSave = deferred<
      Awaited<ReturnType<typeof updateOptionsTradeTrackerNotes>>
    >()
    vi.mocked(replaceOptionsTradeTrackerTrades).mockReturnValueOnce(
      tradesSave.promise,
    )
    vi.mocked(updateOptionsTradeTrackerNotes).mockReturnValueOnce(notesSave.promise)

    render(<OptionsTradeTrackerPage />)

    await screen.findByText('Income')
    fireEvent.click(await screen.findByRole('button', { name: 'Add row' }))
    fireEvent.change(screen.getByLabelText(/Ticker row/), {
      target: { value: 'aapl' },
    })
    fireEvent.change(screen.getByLabelText('Tracker notes'), {
      target: { value: 'Independent notes' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save trades' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save notes' }))

    await waitFor(() => {
      expect(replaceOptionsTradeTrackerTrades).toHaveBeenCalledTimes(1)
      expect(updateOptionsTradeTrackerNotes).toHaveBeenCalledTimes(1)
    })
    expect(
      vi.mocked(replaceOptionsTradeTrackerTrades).mock.calls[0][2]?.aborted,
    ).toBe(false)
    expect(
      vi.mocked(updateOptionsTradeTrackerNotes).mock.calls[0][2]?.aborted,
    ).toBe(false)

    notesSave.resolve(trackerDetail(incomeTracker, 'Independent notes', 'STALE'))
    await act(async () => {
      await notesSave.promise
    })
    expect(screen.getByDisplayValue('AAPL')).toBeTruthy()

    tradesSave.resolve(trackerDetail(incomeTracker, 'STALE NOTES', 'AAPL'))
    await act(async () => {
      await tradesSave.promise
    })

    expect(screen.getByDisplayValue('AAPL')).toBeTruthy()
    expect(screen.getByDisplayValue('Independent notes')).toBeTruthy()
    expect(screen.queryByDisplayValue('STALE')).toBeNull()
    expect(screen.queryByDisplayValue('STALE NOTES')).toBeNull()
  })

  it('switching trackers loads that tracker trades and notes', async () => {
    render(<OptionsTradeTrackerPage />)

    await screen.findByText('Income')
    openSelect('Select tracker')
    fireEvent.click(await screen.findByText('Growth'))

    expect(await screen.findByDisplayValue('MSFT')).toBeTruthy()
    expect(screen.getByDisplayValue('Growth notes')).toBeTruthy()
  })

  it('does not render a previous tracker while the next detail is loading', async () => {
    const incomeLoad = deferred<Awaited<ReturnType<typeof fetchOptionsTradeTracker>>>()
    const growthLoad = deferred<Awaited<ReturnType<typeof fetchOptionsTradeTracker>>>()
    vi.mocked(fetchOptionsTradeTracker)
      .mockReturnValueOnce(incomeLoad.promise)
      .mockReturnValueOnce(growthLoad.promise)

    render(<OptionsTradeTrackerPage />)

    await waitFor(() => {
      expect(fetchOptionsTradeTracker).toHaveBeenCalledWith(
        'income',
        expect.any(AbortSignal),
      )
    })
    openSelect('Select tracker')
    fireEvent.click(await screen.findByText('Growth'))

    expect(screen.getByText('Loading selected tracker...')).toBeTruthy()
    expect(screen.queryByLabelText('Tracker notes')).toBeNull()
    expect(
      vi.mocked(fetchOptionsTradeTracker).mock.calls[0][1]?.aborted,
    ).toBe(true)

    incomeLoad.resolve(trackerDetail(incomeTracker, 'Income notes', 'AAPL'))
    await act(async () => {
      await incomeLoad.promise
    })
    expect(screen.queryByDisplayValue('Income notes')).toBeNull()
    expect(screen.queryByDisplayValue('AAPL')).toBeNull()

    growthLoad.resolve(trackerDetail(growthTracker, 'Growth notes', 'MSFT'))
    expect(await screen.findByDisplayValue('Growth notes')).toBeTruthy()
    expect(screen.getByDisplayValue('MSFT')).toBeTruthy()
  })

  it('discards unsaved drafts when switching trackers', async () => {
    render(<OptionsTradeTrackerPage />)

    await screen.findByText('Income')
    fireEvent.click(await screen.findByRole('button', { name: 'Add row' }))
    fireEvent.change(screen.getByLabelText(/Ticker row/), {
      target: { value: 'aapl' },
    })
    fireEvent.change(screen.getByLabelText('Tracker notes'), {
      target: { value: 'Unsaved income notes' },
    })

    openSelect('Select tracker')
    fireEvent.click(await screen.findByText('Growth'))

    expect(screen.queryByDisplayValue('AAPL')).toBeNull()
    expect(screen.queryByDisplayValue('Unsaved income notes')).toBeNull()
    expect(await screen.findByDisplayValue('Growth notes')).toBeTruthy()
  })

  it('ignores a late notes save after switching trackers', async () => {
    const notesSave = deferred<
      Awaited<ReturnType<typeof updateOptionsTradeTrackerNotes>>
    >()
    vi.mocked(updateOptionsTradeTrackerNotes).mockReturnValueOnce(notesSave.promise)

    render(<OptionsTradeTrackerPage />)

    await screen.findByText('Income')
    fireEvent.change(screen.getByLabelText('Tracker notes'), {
      target: { value: 'Saved too late' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save notes' }))
    await waitFor(() => {
      expect(updateOptionsTradeTrackerNotes).toHaveBeenCalledWith(
        'income',
        { notes: 'Saved too late' },
        expect.any(AbortSignal),
      )
    })

    openSelect('Select tracker')
    fireEvent.click(await screen.findByText('Growth'))
    expect(await screen.findByDisplayValue('Growth notes')).toBeTruthy()
    await waitFor(() => {
      expect(
        vi.mocked(updateOptionsTradeTrackerNotes).mock.calls[0][2]?.aborted,
      ).toBe(true)
    })

    notesSave.resolve(trackerDetail(incomeTracker, 'Saved too late', 'AAPL'))
    await act(async () => {
      await notesSave.promise
    })

    expect(screen.getByDisplayValue('Growth notes')).toBeTruthy()
    expect(screen.queryByDisplayValue('Saved too late')).toBeNull()
    expect(screen.queryByDisplayValue('AAPL')).toBeNull()
  })

  it('ignores a late trade save after switching trackers', async () => {
    const tradesSave = deferred<
      Awaited<ReturnType<typeof replaceOptionsTradeTrackerTrades>>
    >()
    vi.mocked(replaceOptionsTradeTrackerTrades).mockReturnValueOnce(
      tradesSave.promise,
    )

    render(<OptionsTradeTrackerPage />)

    await screen.findByText('Income')
    fireEvent.click(await screen.findByRole('button', { name: 'Add row' }))
    fireEvent.change(screen.getByLabelText(/Ticker row/), {
      target: { value: 'aapl' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save trades' }))

    openSelect('Select tracker')
    fireEvent.click(await screen.findByText('Growth'))
    expect(await screen.findByDisplayValue('MSFT')).toBeTruthy()
    expect(
      vi.mocked(replaceOptionsTradeTrackerTrades).mock.calls[0][2]?.aborted,
    ).toBe(true)

    tradesSave.resolve(trackerDetail(incomeTracker, 'Income notes', 'AAPL'))
    await act(async () => {
      await tradesSave.promise
    })

    expect(screen.getByDisplayValue('MSFT')).toBeTruthy()
    expect(screen.queryByDisplayValue('AAPL')).toBeNull()
  })

  it('renders stats table and charts from completed valid trades', async () => {
    vi.mocked(fetchOptionsTradeStrategyOptions).mockResolvedValueOnce({
      strategies: ['WHEEL', 'SPREAD', 'IRON CONDOR'],
    })
    vi.mocked(fetchOptionsTradeTracker).mockResolvedValueOnce({
      tracker: incomeTracker,
      trades: [
        completedTrade({
          id: 'wheel-jan',
          strategy: 'WHEEL',
          month: 'jan',
          size: -2,
          credit_debit: 1.5,
          exit: null,
        }),
        completedTrade({
          id: 'spread-feb',
          strategy: 'SPREAD',
          month: 'feb',
          size: 1,
          credit_debit: 2,
          exit: 0.5,
        }),
        completedTrade({
          id: 'ignored-progress',
          status: 'In Progress',
          strategy: 'WHEEL',
          month: 'mar',
          size: -4,
          credit_debit: 10,
          exit: null,
        }),
        completedTrade({
          id: 'ignored-invalid',
          strategy: null,
          month: 'apr',
          size: -1,
          credit_debit: 10,
          exit: null,
        }),
      ],
      notes: '',
      strategy_options: ['WHEEL', 'SPREAD', 'IRON CONDOR'],
    })

    render(<OptionsTradeTrackerPage />)

    expect(await screen.findByText('Income')).toBeTruthy()
    fireEvent.click(screen.getByRole('tab', { name: 'Stats' }))

    expect(await screen.findByText('Summary')).toBeTruthy()
    expect(screen.getAllByText('Jan').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Dec').length).toBeGreaterThan(0)
    expect(screen.getAllByText('WHEEL').length).toBeGreaterThan(0)
    expect(screen.getAllByText('SPREAD').length).toBeGreaterThan(0)
    expect(screen.getByText('IRON CONDOR')).toBeTruthy()
    expect(screen.getAllByText('IRON CONDOR')).toHaveLength(1)
    expect(screen.getAllByText('$296.00').length).toBeGreaterThan(0)
    expect(screen.getAllByText('-$148.00').length).toBeGreaterThan(0)
    expect(screen.getAllByText('$49.33').length).toBeGreaterThan(0)
    expect(screen.getAllByText('-').length).toBeGreaterThan(0)
    expect(screen.getByText('Monthly performance')).toBeTruthy()
    expect(screen.getByText('Strategy execution')).toBeTruthy()
    expect(
      screen.getByRole('radio', { name: 'By strategy' }).getAttribute(
        'aria-checked',
      ),
    ).toBe('true')

    fireEvent.click(screen.getByRole('radio', { name: 'Net' }))
    expect(
      screen.getByRole('radio', { name: 'Net' }).getAttribute('aria-checked'),
    ).toBe('true')
  })
})

function completedTrade(
  overrides: Partial<Parameters<typeof baseCompletedTrade>[0]> & {
    id: string
  },
) {
  return baseCompletedTrade(overrides)
}

function baseCompletedTrade({
  id,
  status = 'Completed',
  strategy = 'WHEEL',
  ticker = 'AAPL',
  month = 'jan',
  size = -1,
  strike_price = 190,
  credit_debit = 1,
  exit = null,
}: {
  id: string
  status?: 'Completed' | 'In Progress'
  strategy?: string | null
  ticker?: string | null
  month?: 'jan' | 'feb' | 'mar' | 'apr'
  size?: number | null
  strike_price?: number | null
  credit_debit?: number | null
  exit?: number | null
}) {
  return {
    id,
    display_order: 1,
    status,
    strategy,
    ticker,
    month,
    size,
    strike_price,
    credit_debit,
    exit,
    created_at: '',
    updated_at: '',
  }
}

function openSelect(label: string | RegExp) {
  fireEvent.pointerDown(screen.getByLabelText(label), {
    button: 0,
    ctrlKey: false,
    pointerId: 1,
    pointerType: 'mouse',
  })
}

function setFirstStatus(status: string) {
  openSelect(/Status row/)
  fireEvent.click(screen.getByText(status))
}

function setFirstStrategy(strategy: string) {
  openSelect(/Strategy row/)
  fireEvent.click(screen.getByText(strategy))
}

function dragRow(source: HTMLElement, target: HTMLElement) {
  const data = new Map<string, string>()
  const dataTransfer = {
    dropEffect: 'move',
    effectAllowed: 'move',
    getData: (format: string) => data.get(format) ?? '',
    setData: (format: string, value: string) => data.set(format, value),
  }

  fireEvent.dragStart(source, { dataTransfer })
  fireEvent.dragOver(target, { dataTransfer })
  fireEvent.drop(target, { dataTransfer })
  fireEvent.dragEnd(source, { dataTransfer })
}

function trackerDetail(
  tracker: typeof incomeTracker,
  notes: string,
  ticker: string,
) {
  return {
    tracker,
    trades: [
      {
        id: `${tracker.id}-row`,
        display_order: 1,
        status: 'In Progress' as const,
        strategy: 'WHEEL',
        ticker,
        month: 'jan' as const,
        size: null,
        strike_price: null,
        credit_debit: null,
        exit: null,
        created_at: '',
        updated_at: '',
      },
    ],
    notes,
    strategy_options: ['WHEEL', 'SPREAD'],
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}
