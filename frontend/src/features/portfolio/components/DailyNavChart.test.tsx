// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import type { NavHistory } from '@/api/portfolioNav'
import { DailyNavChart } from './DailyNavChart'
const mocks = vi.hoisted(() => ({ data: null as NavHistory | null, error: null as string | null, isLoading: false }))
vi.mock('../hooks/useNavHistory', () => ({ useNavHistory: () => mocks }))
afterEach(() => { cleanup(); mocks.data = null; mocks.error = null })
it('shows empty history without substituting live or manual values', () => {
  render(<DailyNavChart account="DU1" />)
  expect(screen.getByText('No daily NAV history yet.')).toBeTruthy()
})
it('shows compact status, currency, range controls and saved data on failure', () => {
  mocks.data = { account: 'DU1', latest_report_date: '2026-09-07', currencies: ['SGD'], currency_changed: false,
    rows: [{ account:'DU1', report_date:'2026-09-07', currency:'SGD', nav:'1234.50', source:'flex', updated_at:'' }],
    sync: { configured:true, state:'failed', error:'IBKR unavailable', last_successful_sync:null } }
  render(<DailyNavChart account="DU1" />)
  fireEvent.click(screen.getByRole('radio', { name:'All' }))
  expect(screen.queryByText(/Close ·/)).toBeNull()
  expect(screen.queryByText(/Daily closing NAV/)).toBeNull()
  fireEvent.click(screen.getByRole('radio', { name: 'Percentage' }))
  expect(screen.queryByText(/NAV change from/)).toBeNull()
  expect(screen.getByRole('alert').textContent).toBe('IBKR unavailable')
  expect(screen.getByLabelText('Daily NAV in SGD')).toBeTruthy()
  expect(screen.getAllByRole('radio')).toHaveLength(7)
})
