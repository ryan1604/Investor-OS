// @vitest-environment jsdom

import { Profiler, type ProfilerOnRenderCallback } from 'react'
import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { OptionsAnalysisResponse } from '@/api/options'
import { OptionChainTable } from '@/features/options/components/OptionChainTable'
import { mergeLiveChainRows } from '@/features/options/lib/chainRows'
import { makeLargeOptionChainFixture } from '@/performance/fixtures'

const FRAME_BUDGET_MS = 16.7
const STRIKE_COUNTS = [25, 100, 250]
const UPDATE_RATES = [1, 5, 10]

const analysis: OptionsAnalysisResponse = {
  ticker: 'AAPL',
  underlying_price: 192.5,
  candles: [],
  bollinger_bands: [],
  rsi: [],
  message: null,
}

afterEach(() => {
  cleanup()
})

describe('option-chain render profile', () => {
  it('records commit duration and dropped-frame risk for documented workloads', () => {
    const profiles = STRIKE_COUNTS.flatMap((strikeCount) =>
      UPDATE_RATES.map((updatesPerSecond) =>
        profileOptionChainCommit(strikeCount, updatesPerSecond),
      ),
    )

    expect(profiles).toHaveLength(9)
    expect(profiles).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          strikeCount: 25,
          updatesPerSecond: 1,
        }),
        expect.objectContaining({
          strikeCount: 250,
          updatesPerSecond: 10,
        }),
      ]),
    )
    for (const profile of profiles) {
      expect(profile.updateCommitMs).toBeGreaterThanOrEqual(0)
      expect(profile.droppedFrameRisk).toBe(
        profile.updateCommitMs > FRAME_BUDGET_MS,
      )
    }

    if (import.meta.env.VITE_PRINT_OPTION_CHAIN_PROFILE === '1') {
      console.table(profiles)
    }
  })
})

function profileOptionChainCommit(
  strikeCount: number,
  updatesPerSecond: number,
) {
  const chain = makeLargeOptionChainFixture(strikeCount)
  const updatedRows = chain.rows.slice(0, updatesPerSecond).map((row, index) => ({
    ...row,
    call: row.call
      ? {
          ...row.call,
          bid: (row.call.bid ?? 0) + index + 0.01,
        }
      : null,
  }))
  const updatedChain = mergeLiveChainRows(
    chain,
    chain.ticker,
    chain.expiration,
    updatedRows,
    null,
  )
  const commitDurations: number[] = []
  const onRender: ProfilerOnRenderCallback = (
    _id,
    phase,
    actualDuration,
  ) => {
    if (phase === 'update') {
      commitDurations.push(actualDuration)
    }
  }
  const { rerender } = render(
    <Profiler id={`${strikeCount}-${updatesPerSecond}`} onRender={onRender}>
      <OptionChainTable
        analysis={analysis}
        chain={chain}
        error={null}
        isLoading={false}
        selectedExpiration={chain.expiration}
      />
    </Profiler>,
  )

  rerender(
    <Profiler id={`${strikeCount}-${updatesPerSecond}`} onRender={onRender}>
      <OptionChainTable
        analysis={analysis}
        chain={updatedChain}
        error={null}
        isLoading={false}
        selectedExpiration={chain.expiration}
      />
    </Profiler>,
  )

  const updateCommitMs = commitDurations.at(-1) ?? 0

  return {
    strikeCount,
    updatesPerSecond,
    updateCommitMs,
    droppedFrameRisk: updateCommitMs > FRAME_BUDGET_MS,
  }
}
