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

export async function requestJson<TResponse>(
  path: string,
  label: string,
  init?: RequestInit,
) {
  const response = await requestOk(path, label, init)

  return response.json() as Promise<TResponse>
}

export async function requestOk(path: string, label: string, init?: RequestInit) {
  const response =
    init === undefined ? await fetch(apiUrl(path)) : await fetch(apiUrl(path), init)

  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, label))
  }

  return response
}

export function jsonRequest<TResponse>(
  path: string,
  method: 'PATCH' | 'POST' | 'PUT',
  body: unknown,
  label: string,
  signal?: AbortSignal,
) {
  return requestJson<TResponse>(path, label, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
}

export function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}

export function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback
}
