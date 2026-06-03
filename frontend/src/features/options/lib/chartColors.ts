export type ChartColors = {
  background: string
  foreground: string
  mutedForeground: string
  border: string
}

export function chartColors(): ChartColors {
  const styles = getComputedStyle(document.documentElement)

  return {
    background: canvasSafeColor(styles.getPropertyValue('--card'), '#0a0a0a'),
    foreground: canvasSafeColor(styles.getPropertyValue('--foreground'), '#fafafa'),
    mutedForeground: canvasSafeColor(
      styles.getPropertyValue('--muted-foreground'),
      '#a1a1aa',
    ),
    border: canvasSafeColor(styles.getPropertyValue('--border'), '#27272a'),
  }
}

function canvasSafeColor(value: string, fallback: string) {
  const color = value.trim()
  if (!color) {
    return fallback
  }

  const context = document.createElement('canvas').getContext('2d')
  if (!context) {
    return fallback
  }

  context.fillStyle = fallback
  context.fillStyle = color
  const parsedColor = context.fillStyle

  if (isLightweightChartsColor(parsedColor)) {
    return parsedColor
  }

  return fallback
}

function isLightweightChartsColor(value: string) {
  return (
    value.startsWith('#') ||
    value.startsWith('rgb(') ||
    value.startsWith('rgba(')
  )
}
