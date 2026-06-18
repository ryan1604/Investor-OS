export function daysToExpiration(expiration: string) {
  const expirationTime = Date.parse(`${expiration}T00:00:00Z`)
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date())
  const datePart = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? ''
  const currentTime = Date.parse(
    `${datePart('year')}-${datePart('month')}-${datePart('day')}T00:00:00Z`,
  )
  return Math.round((expirationTime - currentTime) / 86_400_000)
}
