import { CircleDot } from 'lucide-react'

import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { AccountSelector } from '@/components/AccountSelector'
import { AnalysisSummaryCards } from '@/features/portfolio-analysis/components/AnalysisSummaryCards'
import { BetaOverrideEditor } from '@/features/portfolio-analysis/components/BetaOverrideEditor'
import { CoverageBanner } from '@/features/portfolio-analysis/components/CoverageBanner'
import { ExposureTable } from '@/features/portfolio-analysis/components/ExposureTable'
import { LimitStatusStrip } from '@/features/portfolio-analysis/components/LimitStatusStrip'
import { RealisedStats } from '@/features/portfolio-analysis/components/RealisedStats'
import { RiskHistory } from '@/features/portfolio-analysis/components/RiskHistory'
import { RiskLimitsEditor } from '@/features/portfolio-analysis/components/RiskLimitsEditor'
import {
  StressGridTable,
  StressSummaryCards,
} from '@/features/portfolio-analysis/components/StressTest'
import { useBetaOverrides } from '@/features/portfolio-analysis/hooks/useBetaOverrides'
import { usePortfolioAnalysis } from '@/features/portfolio-analysis/hooks/usePortfolioAnalysis'
import { useRiskHistory } from '@/features/portfolio-analysis/hooks/useRiskHistory'
import { useRiskLimits } from '@/features/portfolio-analysis/hooks/useRiskLimits'
import { limitBandsByKey, limitStatuses } from '@/features/portfolio-analysis/lib/limits'

type PortfolioAnalysisPageProps = {
  accounts: string[]
  selectedAccount: string | null
  onSelectedAccountChange: (account: string) => void
}

export function PortfolioAnalysisPage({
  accounts,
  selectedAccount,
  onSelectedAccountChange,
}: PortfolioAnalysisPageProps) {
  const { analysis, isLoading, error, refresh } = usePortfolioAnalysis(selectedAccount)
  const betaOverrides = useBetaOverrides(refresh)
  const isConnected = analysis?.status.connected ?? false
  const hasAccount = Boolean(analysis?.account)
  const account = analysis?.account || null
  const riskLimits = useRiskLimits(account)
  const riskHistory = useRiskHistory(account)
  const statuses = hasAccount ? limitStatuses(riskLimits.limits, analysis) : []
  const bands = limitBandsByKey(statuses)

  return (
    <>
      <header className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <h1 className="text-3xl font-semibold tracking-tight">Portfolio Analysis</h1>
          <AccountSelector
            accounts={accounts}
            activeAccount={selectedAccount ?? undefined}
            onAccountChange={onSelectedAccountChange}
          />
        </div>
        <Badge
          variant={isConnected ? 'secondary' : 'outline'}
          className={
            isConnected ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400' : undefined
          }
        >
          <CircleDot
            data-icon="inline-start"
            className={isConnected ? 'fill-emerald-400 text-emerald-400' : undefined}
          />
          {isConnected ? 'Connected' : 'Disconnected'}
        </Badge>
      </header>
      <LimitStatusStrip statuses={statuses} />

      {error ? (
        <Alert variant="destructive" className="mt-6">
          {error}
        </Alert>
      ) : null}
      {analysis && !hasAccount ? (
        <Alert variant="muted" className="mt-6">
          {analysis.message ?? 'Portfolio data has not loaded yet.'}
        </Alert>
      ) : null}

      <AnalysisSummaryCards
        isLoading={isLoading}
        summary={hasAccount ? analysis?.summary ?? null : null}
        bands={bands}
      />
      {analysis && hasAccount ? (
        <>
          <CoverageBanner
            coverage={analysis.summary.coverage}
            unsupported={analysis.unsupported}
          />
          {analysis.stress ? <StressSummaryCards stress={analysis.stress} bands={bands} /> : null}
          <ExposureTable underlyings={analysis.underlyings} />
          {analysis.stress ? <StressGridTable stress={analysis.stress} /> : null}
          {analysis.realised ? <RealisedStats realised={analysis.realised} /> : null}
          <RiskHistory
            snapshots={riskHistory.snapshots}
            limits={riskLimits.limits}
            isLoaded={riskHistory.isLoaded}
            error={riskHistory.error}
          />
        </>
      ) : null}
      {account && riskLimits.isLoaded ? (
        <RiskLimitsEditor
          key={`${account}:${JSON.stringify(riskLimits.limits)}`}
          limits={riskLimits.limits}
          isSaving={riskLimits.isSaving}
          error={riskLimits.error}
          onSave={riskLimits.save}
        />
      ) : account && riskLimits.error ? (
        <Alert variant="destructive" className="mt-6">
          {riskLimits.error}
        </Alert>
      ) : null}
      <BetaOverrideEditor
        overrides={betaOverrides.overrides}
        tickers={analysis?.underlyings.map((underlying) => underlying.symbol) ?? []}
        isSaving={betaOverrides.isSaving}
        error={betaOverrides.error}
        onSave={betaOverrides.save}
        onRemove={betaOverrides.remove}
      />
    </>
  )
}
