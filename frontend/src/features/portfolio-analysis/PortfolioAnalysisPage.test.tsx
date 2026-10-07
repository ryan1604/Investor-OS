// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { PortfolioAnalysisResponse, RiskLimit, RiskLimitKey } from '@/api/portfolioAnalysis'
import { PortfolioAnalysisPage } from '@/features/portfolio-analysis/PortfolioAnalysisPage'
import { analysisResponse, riskHistory } from '@/features/portfolio-analysis/testFixtures'

class FakeWebSocket {
  static OPEN = 1
  static sockets: FakeWebSocket[] = []

  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onclose: (() => void) | null = null
  readyState = 1
  sent: unknown[] = []
  closed = false
  url: string

  constructor(url: string) {
    this.url = url
    FakeWebSocket.sockets.push(this)
  }

  send(data: string) {
    this.sent.push(JSON.parse(data))
  }

  close() {
    this.closed = true
    this.onclose?.()
  }

  receive(analysis: PortfolioAnalysisResponse) {
    act(() => {
      this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(analysis) }))
    })
  }
}

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderPage() {
  return render(
    <PortfolioAnalysisPage
      accounts={['DU1', 'DU2']}
      selectedAccount="DU1"
      onSelectedAccountChange={vi.fn()}
    />,
  )
}

const LIMITS_URL = 'http://127.0.0.1:8000/portfolio/analysis/limits/DU1'
const HISTORY_URL = 'http://127.0.0.1:8000/portfolio/analysis/history?account=DU1'
const HISTORY = { account: 'DU1', snapshots: riskHistory() }

describe('PortfolioAnalysisPage', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  let savedLimits: RiskLimit[]

  beforeEach(() => {
    FakeWebSocket.sockets = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
    savedLimits = []
    // Risk limits and history are routed by URL; other requests (beta overrides) return a list.
    fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === HISTORY_URL) {
        return Promise.resolve(jsonResponse(HISTORY))
      }
      if (url === LIMITS_URL) {
        if (init?.method === 'PUT') {
          const body = JSON.parse(String(init.body)) as { limits: Record<string, number> }
          savedLimits = Object.entries(body.limits).map(([key, value]) => ({
            key: key as RiskLimitKey,
            value,
            updated_at: '2026-09-26T00:00:00Z',
          }))
        }
        return Promise.resolve(jsonResponse({ account: 'DU1', limits: savedLimits }))
      }
      return Promise.resolve(jsonResponse([]))
    })
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('renders summary cards, coverage, and fallback indicators from live data', () => {
    renderPage()
    const base = analysisResponse()
    FakeWebSocket.sockets[0].receive({
      ...base,
      summary: { ...base.summary, maintenance_margin: null, margin_utilisation_percent: null },
    })

    expect(screen.getByRole('heading', { name: 'Portfolio Analysis' })).toBeTruthy()
    expect(screen.getByText('$100,000')).toBeTruthy()
    expect(screen.getByText('0.45x')).toBeTruthy()
    expect(screen.getByText('$85')).toBeTruthy()
    expect(screen.getByText('34.00%')).toBeTruthy()
    const marginLabel = screen.getByText('Margin Used')
    expect(marginLabel.parentElement?.textContent).toBe('Margin Used-')

    const banner = screen.getByText(/Coverage:/).closest('[role="alert"]') as HTMLElement
    expect(banner.textContent).toContain('1 position used fallback Greeks')
    expect(banner.textContent).toContain('1 position used a fallback beta of 1.0')
    expect(banner.textContent).toContain('ESZ6 (FUT, 1): Unsupported instrument (FUT).')

    expect(
      screen.getByRole('img', { name: 'Beta 1.0 fallback: no daily history against SPY yet.' }),
    ).toBeTruthy()
    expect(screen.getByText('(set)')).toBeTruthy()
    expect(screen.getByText('Unlimited')).toBeTruthy()
    expect(screen.getByText('Stress Test (Estimates)')).toBeTruthy()
    expect(screen.getByText('21.4%')).toBeTruthy()
  })

  it('omits the stress sections when the response has no grid', () => {
    renderPage()
    FakeWebSocket.sockets[0].receive(analysisResponse({ stress: null }))

    expect(screen.getByText('Portfolio Analysis')).toBeTruthy()
    expect(screen.queryByText('Stress Test (Estimates)')).toBeNull()
    expect(screen.queryByText('Distance to Margin Call (Est.)')).toBeNull()
  })

  it('expands underlyings into strategy groups and legs', () => {
    renderPage()
    FakeWebSocket.sockets[0].receive(analysisResponse())

    expect(screen.queryByText(/Cash-Secured/)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Expand HIMS strategies' }))
    expect(screen.getByText('Cash-Secured / Naked Put x 2')).toBeTruthy()
    const nakedCallRow = screen.getByText('Naked Call x 1').closest('tr') as HTMLElement
    expect(within(nakedCallRow).getByText('Unlimited')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Expand HIMS Cash-Secured / Naked Put legs' }))
    expect(screen.getByText('-2 x 2026-10-16 25P')).toBeTruthy()
    expect(
      screen.getByRole('img', { name: "Missing IB Greeks filled from Black-Scholes at IB's IV." }),
    ).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Expand HIMS Naked Call legs' }))
    const missingLeg = screen.getByText('-1 x 2026-10-16 35C').closest('tr') as HTMLElement
    expect(
      Array.from(missingLeg.querySelectorAll('td'))
        .slice(1)
        .map((cell) => cell.textContent),
    ).toEqual(['-', '-', '-', '-', '-', '-', '-'])
    expect(within(missingLeg).getByRole('img').getAttribute('aria-label')).toContain('No Greeks')
  })

  it('explains Greeks solved from the IB mark', () => {
    renderPage()
    const base = analysisResponse()
    const [aapl, hims] = base.underlyings
    const [shortPut, nakedCall] = hims.groups
    const markLeg = {
      ...shortPut.legs[0],
      greeks_source: 'solved_iv' as const,
      flags: ['solved_iv', 'mark_price'],
    }
    FakeWebSocket.sockets[0].receive({
      ...base,
      underlyings: [aapl, { ...hims, groups: [{ ...shortPut, legs: [markLeg] }, nakedCall] }],
    })

    fireEvent.click(screen.getByRole('button', { name: 'Expand HIMS strategies' }))
    fireEvent.click(screen.getByRole('button', { name: 'Expand HIMS Cash-Secured / Naked Put legs' }))
    expect(
      screen.getByRole('img', {
        name: "Greeks from Black-Scholes at an IV solved from the option price. No quote from IB, so the IV was solved from IB's position mark.",
      }),
    ).toBeTruthy()
  })

  it('shows the connection message when no account has loaded', () => {
    renderPage()
    FakeWebSocket.sockets[0].receive(
      analysisResponse({
        status: { connected: false, host: '127.0.0.1', port: 7496, client_id: 1 },
        account: null,
        accounts: [],
        underlyings: [],
        message: 'Interactive Brokers is not connected.',
      }),
    )

    expect(screen.getByText('Interactive Brokers is not connected.')).toBeTruthy()
    expect(screen.getByText('Disconnected')).toBeTruthy()
    expect(screen.queryByText('Underlying')).toBeNull()
  })

  it('closes the analysis socket when the page unmounts', () => {
    const { unmount } = renderPage()
    unmount()

    expect(FakeWebSocket.sockets[0].closed).toBe(true)
    expect(FakeWebSocket.sockets).toHaveLength(1)
  })

  it('saves a beta override and asks for a fresh analysis', async () => {
    const saved = { ticker: 'HIMS', beta: 1.8, updated_at: '2026-09-26T00:00:00Z' }
    fetchMock.mockImplementation((url: string, init?: RequestInit) =>
      Promise.resolve(
        jsonResponse(
          url === LIMITS_URL
            ? { account: 'DU1', limits: [] }
            : url === HISTORY_URL
              ? HISTORY
              : init?.method === 'PUT'
                ? saved
                : [],
        ),
      ),
    )
    renderPage()
    const [socket] = FakeWebSocket.sockets
    socket.receive(analysisResponse())

    fireEvent.change(screen.getByLabelText('Override ticker'), { target: { value: 'hims' } })
    fireEvent.change(screen.getByLabelText('Override beta'), { target: { value: '1.8' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save override' }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Remove HIMS override' })).toBeTruthy())
    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/portfolio/analysis/beta-overrides/HIMS',
      expect.objectContaining({ method: 'PUT', body: JSON.stringify({ beta: 1.8 }) }),
    )
    expect(socket.sent.at(-1)).toEqual({ account: 'DU1' })

    const base = analysisResponse()
    socket.receive({
      ...base,
      underlyings: base.underlyings.map((underlying) =>
        underlying.symbol === 'HIMS'
          ? { ...underlying, beta: 1.8, beta_source: 'override' as const }
          : underlying,
      ),
    })
    expect(screen.getByText('1.80', { selector: 'td span' })).toBeTruthy()
    expect(screen.getAllByText('(set)')).toHaveLength(2)
  })

  it('shows realised risk and the risk history for the account', async () => {
    renderPage()
    FakeWebSocket.sockets[0].receive(analysisResponse())

    expect(screen.getByText('Realised Risk')).toBeTruthy()
    expect(screen.getByText('18.40%')).toBeTruthy()
    const bwd = await screen.findByLabelText('Beta-Wtd Delta / NLV history')
    expect(bwd.querySelectorAll('circle[data-kind="intraday"]')).toHaveLength(1)
    expect(fetchMock).toHaveBeenCalledWith(HISTORY_URL, expect.anything())
  })

  it('rejects an out-of-range beta without calling the API', () => {
    renderPage()
    fireEvent.change(screen.getByLabelText('Override ticker'), { target: { value: 'HIMS' } })
    fireEvent.change(screen.getByLabelText('Override beta'), { target: { value: '12' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save override' }))

    expect(screen.getByText('Enter a beta between -10 and 10.')).toBeTruthy()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('shows no limit status until limits are saved, then colours metrics by band', async () => {
    renderPage()
    FakeWebSocket.sockets[0].receive(analysisResponse())

    // Suggested values pre-fill the editor but apply only once saved.
    const marginInput = await screen.findByLabelText('Margin Used limit')
    expect((marginInput as HTMLInputElement).value).toBe('30')
    expect(screen.queryByRole('list', { name: 'Risk limit status' })).toBeNull()

    fireEvent.change(marginInput, { target: { value: '22' } })
    fireEvent.change(screen.getByLabelText('Largest Underlying limit'), { target: { value: '30' } })
    fireEvent.change(screen.getByLabelText('Margin Call Distance limit'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save limits' }))

    const strip = await screen.findByRole('list', { name: 'Risk limit status' })
    expect(fetchMock).toHaveBeenCalledWith(
      LIMITS_URL,
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({
          limits: {
            beta_weighted_delta_multiple: 1,
            margin_utilisation_percent: 22,
            assignment_exposure_percent: 50,
            largest_underlying_percent: 30,
            realistic_path_loss_percent: 25,
          },
        }),
      }),
    )
    const chips = within(strip).getAllByRole('listitem')
    expect(chips.map((chip) => chip.dataset.band)).toEqual(['green', 'amber', 'green', 'red', 'red'])
    // Margin used 20% against 22% is amber; largest underlying 34% against 30% is red.
    expect(within(strip).getByText('20.0%').className).toContain('text-amber-500')
    const largest = screen.getByText('Largest Underlying', { selector: 'div' }).parentElement!
    expect(largest.querySelector('span.text-xl')?.parentElement?.className).toContain('text-red-500')
    expect(screen.getByLabelText('Margin Call Distance limit')).toHaveProperty('value', '')

    fireEvent.click(screen.getByRole('button', { name: 'Clear limits' }))
    await waitFor(() => expect(screen.queryByRole('list', { name: 'Risk limit status' })).toBeNull())
  })

  it('rejects an invalid limit without calling the API', async () => {
    renderPage()
    FakeWebSocket.sockets[0].receive(analysisResponse())
    fireEvent.change(await screen.findByLabelText('Assignment / NLV limit'), {
      target: { value: '-5' },
    })
    const calls = fetchMock.mock.calls.length
    fireEvent.click(screen.getByRole('button', { name: 'Save limits' }))

    expect(
      screen.getByText('Enter a number of at least 0 for Assignment / NLV, or leave it blank.'),
    ).toBeTruthy()
    expect(fetchMock.mock.calls.length).toBe(calls)
  })
})
