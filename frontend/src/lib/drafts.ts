export function draftNumberText(value: number | null) {
  return value === null ? '' : String(value)
}

export function createLocalId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}
