import { errorMessage } from '@/api/client'

export function parsePositiveNumber(value: string) {
  if (!value.trim()) {
    return null
  }
  const parsedValue = Number(value)
  return Number.isFinite(parsedValue) && parsedValue > 0 ? parsedValue : null
}

export function parsePositiveInteger(value: string) {
  const parsedValue = Number(value)
  return Number.isInteger(parsedValue) && parsedValue > 0 ? parsedValue : null
}

export function parseSignedNumber(value: string) {
  if (!value.trim()) {
    return null
  }
  const parsedValue = Number(value)
  return Number.isFinite(parsedValue) ? parsedValue : null
}

export function orderErrorMessage(error: unknown) {
  return errorMessage(error, 'Order request failed.')
}
