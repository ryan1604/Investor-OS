// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { FieldIssue, NumberCell } from '@/components/EditableTableCells'

afterEach(cleanup)

it('keeps plain drafts unformatted with the caller input styling and change handler', () => {
  const onChange = vi.fn()
  render(<NumberCell label="Buy row 1" value="12.50"
    className="text-right tabular-nums" onChange={onChange} />)
  const input = screen.getByRole('textbox', { name: 'Buy row 1' }) as HTMLInputElement
  expect(input.value).toBe('12.50')
  expect(input.getAttribute('inputmode')).toBe('decimal')
  expect(input.classList.contains('text-right')).toBe(true)
  fireEvent.focus(input)
  fireEvent.change(input, { target: { value: '13.25' } })
  expect(onChange).toHaveBeenCalledExactlyOnceWith('13.25')
})

it('shows formatted currency while blurred and the raw draft while focused', () => {
  const onChange = vi.fn()
  render(<NumberCell label="Strike price" value="12.5" onChange={onChange}
    formatValue={(value) => `$${Number(value).toFixed(2)}`} />)
  const input = screen.getByRole('textbox', { name: 'Strike price' }) as HTMLInputElement
  expect(input.value).toBe('$12.50')
  expect(input.classList.contains('w-full')).toBe(true)
  fireEvent.focus(input)
  expect(input.value).toBe('12.5')
  fireEvent.blur(input)
  expect(input.value).toBe('$12.50')
})

it('matches only the row/field issue and keeps each tracker issue layout', () => {
  const issues = [
    { localId: 'other', field: 'size', message: 'Other row' },
    { localId: 'draft', field: 'fee', message: 'Other field' },
    { localId: 'draft', field: 'size', message: 'Invalid size' },
  ]
  const { rerender } = render(<FieldIssue issues={issues} localId="draft" field="size" />)
  expect(screen.getByText('Invalid size').className)
    .toBe('mt-1 max-w-44 whitespace-normal text-xs text-destructive')
  expect(screen.queryByText('Other row')).toBeNull()
  expect(screen.queryByText('Other field')).toBeNull()
  rerender(<FieldIssue issues={issues} localId="draft" field="size"
    className="mt-1 text-left text-xs text-destructive" />)
  expect(screen.getByText('Invalid size').className)
    .toBe('mt-1 text-left text-xs text-destructive')
  rerender(<FieldIssue issues={issues} localId="draft" field="missing" />)
  expect(screen.queryByText('Invalid size')).toBeNull()
})
