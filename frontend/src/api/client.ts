export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'

export function apiUrl(path: string) {
  return `${API_BASE_URL}${path}`
}

export function apiWebSocketUrl(path: string) {
  return `${API_BASE_URL.replace(/^http/, 'ws')}${path}`
}

export function encodePathSegment(value: string, emptyMessage: string) {
  const normalizedValue = value.trim()

  if (!normalizedValue) {
    throw new Error(emptyMessage)
  }

  return encodeURIComponent(normalizedValue)
}

export function tickerPathSegment(ticker: string) {
  return encodePathSegment(ticker.trim().toUpperCase(), 'Ticker is required.')
}

export async function responseErrorMessage(response: Response, label: string) {
  try {
    const payload = (await response.json()) as { detail?: unknown }

    if (typeof payload.detail === 'string' && payload.detail) {
      return payload.detail
    }
    if (
      payload.detail &&
      typeof payload.detail === 'object' &&
      'message' in payload.detail &&
      typeof payload.detail.message === 'string'
    ) {
      return payload.detail.message
    }
  } catch {
    // Fall back to the status code below.
  }

  return `${label} request failed: ${response.status}`
}

export function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}
