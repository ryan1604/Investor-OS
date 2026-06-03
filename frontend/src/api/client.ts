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

export async function responseErrorMessage(response: Response, label: string) {
  try {
    const payload = (await response.json()) as { detail?: unknown }

    if (typeof payload.detail === 'string' && payload.detail) {
      return payload.detail
    }
  } catch {
    // Fall back to the status code below.
  }

  return `${label} request failed: ${response.status}`
}
