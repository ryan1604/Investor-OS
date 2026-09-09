// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { PortfolioChartSection } from './PortfolioChartSection'
afterEach(cleanup)
const rows = [{ month: '2026-01', amount_invested: 1000, updated_at: '' }]
const props = { account: 'DU1', rows, error: null, isLoading: false, isSaving: false, onSaveRows: vi.fn() }
it('keeps the monthly chart and saves only amount invested', async () => {
  const save = vi.fn(async values => values.map((row: object) => ({ ...row, updated_at: '' })))
  render(<PortfolioChartSection {...props} onSaveRows={save} />)
  expect(screen.queryByText('Monthly amount invested')).toBeNull()
  expect(screen.getByLabelText('Amount invested chart')).toBeTruthy()
  expect(screen.queryByText('Portfolio value')).toBeNull()
  expect(screen.queryByText('Advanced')).toBeNull()
  fireEvent.click(screen.getByText('Edit amount invested'))
  fireEvent.change(screen.getByLabelText('Amount invested 1'), { target: { value: '2500' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(save).toHaveBeenCalledWith([{ month: '2026-01', amount_invested: 2500 }]))
})
it('validates blank amounts and restores saved values on cancel', () => {
  render(<PortfolioChartSection {...props} />)
  fireEvent.click(screen.getByText('Edit amount invested'))
  fireEvent.change(screen.getByLabelText('Amount invested 1'), { target: { value: '' } })
  expect(screen.getByText('Row 1: Amount invested is required.')).toBeTruthy()
  expect((screen.getByRole('button', { name: 'Save' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByText('Cancel'))
  fireEvent.click(screen.getByText('Edit amount invested'))
  expect((screen.getByLabelText('Amount invested 1') as HTMLInputElement).value).toBe('1000')
})
it('shows save errors without discarding the editor', async () => {
  render(<PortfolioChartSection {...props} onSaveRows={vi.fn().mockRejectedValue(new Error('Save unavailable'))} />)
  fireEvent.click(screen.getByText('Edit amount invested'))
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByText('Save unavailable')).toBeTruthy()
  expect(screen.getByLabelText('Amount invested 1')).toBeTruthy()
})
