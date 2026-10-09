export function isoDate(date: Date) {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

export function newYorkDateParts(date = new Date()) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(date)
  return Object.fromEntries(parts.map((part) => [part.type, part.value]))
}

export function daysToExpiration(expiration: string) {
  const expirationTime = Date.parse(`${expiration}T00:00:00Z`)
  const parts = newYorkDateParts()
  const currentTime = Date.parse(`${parts.year}-${parts.month}-${parts.day}T00:00:00Z`)
  return Math.round((expirationTime - currentTime) / 86_400_000)
}
