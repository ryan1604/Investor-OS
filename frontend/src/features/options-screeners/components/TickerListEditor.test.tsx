// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { TickerListEditor } from '@/features/options-screeners/components/TickerListEditor'

afterEach(cleanup)

describe('TickerListEditor', () => {
  it('submits normalized pasted tickers and clears the input', async () => {
    const onAdd = vi.fn().mockResolvedValue(undefined)
    renderEditor({ onAdd })

    fireEvent.change(screen.getByLabelText('Add ticker symbols'), {
      target: { value: ' aapl, MSFT\nnvda aapl ' },
    })
    fireEvent.click(screen.getByRole('button', { name: /add/i }))

    await waitFor(() => {
      expect(onAdd).toHaveBeenCalledWith(['AAPL', 'MSFT', 'NVDA'])
    })
    expect(
      (screen.getByLabelText('Add ticker symbols') as HTMLTextAreaElement).value,
    ).toBe('')
  })

  it('supports enter submission, removal, and confirmed clear', async () => {
    const onAdd = vi.fn().mockResolvedValue(undefined)
    const onRemove = vi.fn().mockResolvedValue(undefined)
    const onClear = vi.fn().mockResolvedValue(undefined)
    renderEditor({ onAdd, onRemove, onClear })

    fireEvent.change(screen.getByLabelText('Add ticker symbols'), {
      target: { value: 'NVDA' },
    })
    fireEvent.keyDown(screen.getByLabelText('Add ticker symbols'), {
      key: 'Enter',
    })
    await waitFor(() => expect(onAdd).toHaveBeenCalledWith(['NVDA']))

    fireEvent.click(screen.getByRole('button', { name: 'Remove AAPL' }))
    expect(onRemove).toHaveBeenCalledWith('AAPL')

    fireEvent.click(screen.getByRole('button', { name: 'Clear all' }))
    fireEvent.click(
      await screen.findByRole('button', { name: 'Clear shared list' }),
    )
    expect(onClear).toHaveBeenCalled()
  })
})

function renderEditor({
  onAdd = vi.fn().mockResolvedValue(undefined),
  onClear = vi.fn().mockResolvedValue(undefined),
  onRemove = vi.fn().mockResolvedValue(undefined),
}: {
  onAdd?: (tickers: string[]) => Promise<void>
  onClear?: () => Promise<void>
  onRemove?: (ticker: string) => Promise<void>
} = {}) {
  return render(
    <TickerListEditor
      tickers={['AAPL', 'MSFT']}
      error={null}
      isPending={false}
      onAdd={onAdd}
      onClear={onClear}
      onRemove={onRemove}
    />,
  )
}
