import { describe, expect, it } from 'vitest'

import { mergeLiveChainRow } from '@/features/options/lib/chainRows'
import {
  CHART_STREAM_UPDATE_COUNT,
  LARGE_OPTION_CHAIN_ROW_COUNT,
  LARGE_PORTFOLIO_POSITION_COUNT,
  makeChartStreamFixture,
  makeLargeOptionChainFixture,
  makeLargePortfolioFixture,
  makeOptionChainStreamFixture,
  makeOrderStreamFixture,
  makePortfolioStreamFixture,
} from '@/performance/fixtures'

describe('performance profiling fixtures', () => {
  it('creates a large portfolio fixture with repeatable account and position data', () => {
    const fixture = makeLargePortfolioFixture()

    expect(fixture.accounts).toHaveLength(1)
    expect(fixture.positions).toHaveLength(LARGE_PORTFOLIO_POSITION_COUNT)
    expect(fixture.positions.some((position) => position.sec_type === 'OPT')).toBe(
      true,
    )
    expect(fixture.positions.some((position) => position.sec_type === 'STK')).toBe(
      true,
    )
  })

  it('creates option-chain and stream fixtures that can exercise merge cost', () => {
    const chain = makeLargeOptionChainFixture()
    const stream = makeOptionChainStreamFixture(5)
    const update = stream.find((message) => message.type === 'update')

    expect(chain.rows).toHaveLength(LARGE_OPTION_CHAIN_ROW_COUNT)
    expect(stream).toHaveLength(6)
    expect(update?.type).toBe('update')
    if (update?.type === 'update') {
      const nextChain = mergeLiveChainRow(
        chain,
        update.ticker,
        update.expiration,
        update.row,
        null,
      )

      expect(nextChain.rows).toHaveLength(chain.rows.length)
    }
  })

  it('creates chart, portfolio, and order stream updates', () => {
    expect(makeChartStreamFixture()).toHaveLength(CHART_STREAM_UPDATE_COUNT)
    expect(makePortfolioStreamFixture(3)).toHaveLength(3)
    expect(makeOrderStreamFixture(4)).toHaveLength(4)
  })
})
