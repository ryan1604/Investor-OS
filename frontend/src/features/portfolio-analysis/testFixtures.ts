import type {
  AnalysisLeg,
  AnalysisRealisedStats,
  AnalysisRiskSnapshot,
  AnalysisStressCell,
  AnalysisStressGrid,
  PortfolioAnalysisResponse,
} from '@/api/portfolioAnalysis'

const zeroExposure = { dollar_delta: 0, beta_weighted_delta: 0, gamma: 0, theta: 0, vega: 0 }

export function analysisLeg(overrides: Partial<AnalysisLeg> = {}): AnalysisLeg {
  return {
    ...zeroExposure,
    con_id: 11,
    symbol: 'HIMS',
    sec_type: 'OPT',
    local_symbol: null,
    right: 'P',
    strike: 25,
    expiry: '20261016',
    currency: 'USD',
    quantity: -2,
    price: 0.9,
    underlying_price: 28,
    implied_volatility: 0.6,
    delta: -0.2,
    greeks_source: 'ib',
    fx_rate: 1,
    flags: [],
    ...overrides,
  }
}

const SPY_MOVES = [-30, -20, -15, -10, -5, 0, 5, 10]
const IV_SHOCKS = [0, 25, 50, 100]

function stressCell(spyMove: number, ivShock: number, realisticPath = false): AnalysisStressCell {
  // $1,000 per 1% SPY move and $100 per 1% IV; margin call below -20% SPY.
  const pnl = spyMove * 1_000 - ivShock * 100
  return {
    spy_move_percent: spyMove,
    iv_shock_percent: ivShock,
    pnl,
    pnl_percent: pnl / 1_000,
    excess_liquidity: 80_000 + pnl - (spyMove < -20 ? 60_000 : 0),
    realistic_path: realisticPath,
  }
}

export function stressGrid(overrides: Partial<AnalysisStressGrid> = {}): AnalysisStressGrid {
  return {
    spy_moves_percent: SPY_MOVES,
    iv_shocks_percent: IV_SHOCKS,
    cells: SPY_MOVES.flatMap((move) =>
      IV_SHOCKS.map((shock) => stressCell(move, shock, move === -30 && shock === 100)),
    ),
    realistic_path: [
      stressCell(-5, 15, true),
      stressCell(-10, 40, true),
      stressCell(-20, 80, true),
      stressCell(-30, 100, true),
    ],
    legs: 3,
    excluded_legs: 1,
    margin: {
      model_margin: 16_000,
      ib_maintenance_margin: 20_000,
      calibration_factor: 1.25,
      excluded_groups: 1,
      distance_to_margin_call_percent: 21.4,
      margin_call_beyond_path: false,
    },
    ...overrides,
  }
}

export function analysisResponse(
  overrides: Partial<PortfolioAnalysisResponse> = {},
): PortfolioAnalysisResponse {
  return {
    status: { connected: true, host: '127.0.0.1', port: 7496, client_id: 1 },
    account: 'DU1',
    accounts: ['DU1', 'DU2'],
    as_of: '2026-09-28T14:00:00Z',
    summary: {
      net_liquidation: 100_000,
      gross_dollar_delta: 40_000,
      net_dollar_delta: 30_000,
      beta_weighted_delta: 45_000,
      beta_weighted_delta_multiple: 0.45,
      net_gamma: -120,
      net_theta: 85,
      net_vega: -310,
      assignment_exposure: 5_000,
      assignment_exposure_percent: 5,
      maintenance_margin: 20_000,
      margin_utilisation_percent: 20,
      excess_liquidity: 80_000,
      largest_underlying: 'AAPL',
      largest_underlying_percent: 34,
      coverage: {
        positions: 4,
        fallback_greeks: 1,
        fallback_beta: 1,
        unsupported: 1,
        fx_converted: 0,
        missing_price: 0,
      },
    },
    underlyings: [
      {
        ...zeroExposure,
        dollar_delta: 34_000,
        beta_weighted_delta: 40_800,
        theta: 4,
        symbol: 'AAPL',
        beta: 1.2,
        beta_source: 'override',
        beta_observations: null,
        underlying_price: 200,
        net_liquidation_percent: 34,
        max_loss: 14_700,
        max_loss_unlimited: false,
        assignment_exposure: 0,
        groups: [],
      },
      {
        ...zeroExposure,
        dollar_delta: -4_000,
        beta_weighted_delta: -4_000,
        symbol: 'HIMS',
        beta: 1,
        beta_source: 'fallback',
        beta_observations: 0,
        underlying_price: 28,
        net_liquidation_percent: 4,
        max_loss: null,
        max_loss_unlimited: true,
        assignment_exposure: 5_000,
        groups: [
          {
            ...zeroExposure,
            dollar_delta: -4_000,
            kind: 'short_put',
            label: 'Cash-Secured / Naked Put',
            quantity: 2,
            premium_type: 'credit',
            net_premium: 160,
            max_loss: 4_840,
            assignment_exposure: 5_000,
            legs: [
              analysisLeg({ dollar_delta: -4_000, greeks_source: 'fallback', flags: ['fallback_greeks'] }),
            ],
          },
          {
            ...zeroExposure,
            kind: 'naked_call',
            label: 'Naked Call',
            quantity: 1,
            premium_type: 'credit',
            net_premium: 50,
            max_loss: null,
            assignment_exposure: 0,
            legs: [
              analysisLeg({
                con_id: 12,
                right: 'C',
                strike: 35,
                quantity: -1,
                price: null,
                implied_volatility: null,
                delta: null,
                greeks_source: 'missing',
                flags: ['missing_greeks'],
              }),
            ],
          },
        ],
      },
    ],
    unsupported: [
      {
        con_id: 99,
        symbol: 'ES',
        sec_type: 'FUT',
        local_symbol: 'ESZ6',
        currency: 'USD',
        quantity: 1,
        reason: 'Unsupported instrument (FUT).',
      },
    ],
    stress: stressGrid(),
    realised: realisedStats(),
    message: 'Analysed 4 position(s).',
    ...overrides,
  }
}

export function realisedStats(
  overrides: Partial<AnalysisRealisedStats> = {},
): AnalysisRealisedStats {
  return {
    currency: 'USD',
    start_date: '2025-06-02',
    end_date: '2026-09-25',
    nav_observations: 340,
    volatility_20d_percent: { value: 18.4, observations: 20, reason: null },
    volatility_60d_percent: { value: 22.1, observations: 60, reason: null },
    max_drawdown_percent: { value: -12.5, observations: 340, reason: null },
    current_drawdown_percent: { value: -3.2, observations: 340, reason: null },
    beta: {
      value: null,
      observations: 0,
      reason: 'SPY daily bars are not available yet.',
    },
    ...overrides,
  }
}

export function riskSnapshot(
  sessionDate: string,
  overrides: Partial<AnalysisRiskSnapshot> = {},
): AnalysisRiskSnapshot {
  return {
    session_date: sessionDate,
    kind: 'post_close',
    captured_at: `${sessionDate}T21:00:00Z`,
    net_liquidation: 100_000,
    beta_weighted_delta: 45_000,
    beta_weighted_delta_multiple: 0.45,
    net_gamma: -120,
    net_theta: 85,
    net_vega: -310,
    assignment_exposure: 5_000,
    assignment_exposure_percent: 5,
    maintenance_margin: 20_000,
    margin_utilisation_percent: 20,
    excess_liquidity: 80_000,
    largest_underlying: 'AAPL',
    largest_underlying_percent: 34,
    realistic_down_20_pnl: -28_000,
    realistic_down_20_pnl_percent: -28,
    model_margin: 16_000,
    calibration_factor: 1.25,
    distance_to_margin_call_percent: 21.4,
    margin_call_beyond_path: false,
    ...overrides,
  }
}

// Monday to Friday with Wednesday missing; Friday is intraday.
export function riskHistory(): AnalysisRiskSnapshot[] {
  return [
    riskSnapshot('2026-09-21', { beta_weighted_delta_multiple: 0.4, net_theta: 70 }),
    riskSnapshot('2026-09-22', { beta_weighted_delta_multiple: 0.5, net_theta: 90 }),
    riskSnapshot('2026-09-24', { beta_weighted_delta_multiple: -0.2, net_theta: -15 }),
    riskSnapshot('2026-09-25', {
      kind: 'intraday',
      captured_at: '2026-09-25T15:00:00Z',
      beta_weighted_delta_multiple: 0.6,
      margin_utilisation_percent: null,
    }),
  ]
}
