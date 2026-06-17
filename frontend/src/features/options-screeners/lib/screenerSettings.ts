import type {
  CreditSpreadScreenerFilters,
  CreditSpreadStrategy,
  CreditSpreadWidth,
  OptionsScreenerFilters,
} from '@/api/optionsScreeners'

export const defaultCspFilters: OptionsScreenerFilters = {
  version: 1,
  minimum_dte: 7,
  maximum_dte: 45,
  minimum_absolute_delta: 0.15,
  maximum_absolute_delta: 0.3,
  minimum_annualized_return: 10,
}

export const creditSpreadStrategies: {
  value: CreditSpreadStrategy
  label: string
}[] = [
  { value: 'put_credit_spread', label: 'Put credit spread' },
  { value: 'call_credit_spread', label: 'Call credit spread' },
]

export const creditSpreadWidths: {
  value: CreditSpreadWidth
  label: string
}[] = [
  { value: 1, label: '$1' },
  { value: 2, label: '$2' },
  { value: 2.5, label: '$2.50' },
  { value: 5, label: '$5' },
  { value: 10, label: '$10' },
]

export const defaultCsFilters: CreditSpreadScreenerFilters = {
  ...defaultCspFilters,
  strategy_types: ['put_credit_spread', 'call_credit_spread'],
  spread_widths: [5],
}

export type ScreenerFilterDraft = {
  minimum_dte: string
  maximum_dte: string
  minimum_absolute_delta: string
  maximum_absolute_delta: string
  minimum_annualized_return: string
}

export type CreditSpreadFilterDraft = ScreenerFilterDraft & {
  strategy_types: CreditSpreadStrategy[]
  spread_widths: CreditSpreadWidth[]
}

export function filterDraftFromSettings(
  filters: OptionsScreenerFilters,
): ScreenerFilterDraft {
  return {
    minimum_dte: String(filters.minimum_dte),
    maximum_dte: String(filters.maximum_dte),
    minimum_absolute_delta: String(filters.minimum_absolute_delta),
    maximum_absolute_delta: String(filters.maximum_absolute_delta),
    minimum_annualized_return: String(filters.minimum_annualized_return),
  }
}

export function creditSpreadFilterDraftFromSettings(
  filters: CreditSpreadScreenerFilters,
): CreditSpreadFilterDraft {
  return {
    ...filterDraftFromSettings(filters),
    strategy_types: [...filters.strategy_types],
    spread_widths: [...filters.spread_widths],
  }
}

export function validateFilterDraft(draft: ScreenerFilterDraft) {
  const draftValues = [
    draft.minimum_dte,
    draft.maximum_dte,
    draft.minimum_absolute_delta,
    draft.maximum_absolute_delta,
    draft.minimum_annualized_return,
  ]
  if (draftValues.some((value) => !value.trim())) {
    return { filters: null, error: 'Enter a number in every filter field.' }
  }
  const parsed = {
    minimum_dte: Number(draft.minimum_dte),
    maximum_dte: Number(draft.maximum_dte),
    minimum_absolute_delta: Number(draft.minimum_absolute_delta),
    maximum_absolute_delta: Number(draft.maximum_absolute_delta),
    minimum_annualized_return: Number(draft.minimum_annualized_return),
  }
  const values = Object.values(parsed)
  if (values.some((value) => !Number.isFinite(value))) {
    return { filters: null, error: 'Enter a number in every filter field.' }
  }
  if (
    !Number.isInteger(parsed.minimum_dte) ||
    !Number.isInteger(parsed.maximum_dte) ||
    parsed.minimum_dte < 1 ||
    parsed.minimum_dte > parsed.maximum_dte
  ) {
    return {
      filters: null,
      error: 'DTE must use whole days with 1 ≤ minimum ≤ maximum.',
    }
  }
  if (
    parsed.minimum_absolute_delta < 0 ||
    parsed.minimum_absolute_delta > parsed.maximum_absolute_delta ||
    parsed.maximum_absolute_delta > 1
  ) {
    return {
      filters: null,
      error: 'Absolute delta must satisfy 0 ≤ minimum ≤ maximum ≤ 1.',
    }
  }
  if (parsed.minimum_annualized_return < 0) {
    return {
      filters: null,
      error: 'Minimum annualized return must be zero or greater.',
    }
  }
  return {
    filters: { version: 1, ...parsed } satisfies OptionsScreenerFilters,
    error: null,
  }
}

export function validateCreditSpreadFilterDraft(
  draft: CreditSpreadFilterDraft,
) {
  const baseValidation = validateFilterDraft(draft)
  if (!baseValidation.filters) {
    return baseValidation
  }
  if (!draft.strategy_types.length) {
    return {
      filters: null,
      error: 'Select at least one credit spread strategy.',
    }
  }
  if (!draft.spread_widths.length) {
    return {
      filters: null,
      error: 'Select at least one spread width.',
    }
  }
  return {
    filters: {
      ...baseValidation.filters,
      strategy_types: [...draft.strategy_types],
      spread_widths: [...draft.spread_widths],
    } satisfies CreditSpreadScreenerFilters,
    error: null,
  }
}

export function parseTickerInput(value: string) {
  const seen = new Set<string>()
  return value
    .split(/[\s,]+/)
    .map((ticker) => ticker.trim().toUpperCase())
    .filter((ticker) => {
      if (!ticker || seen.has(ticker)) {
        return false
      }
      seen.add(ticker)
      return true
    })
}
