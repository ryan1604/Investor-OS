import { CircleDot, RefreshCw } from 'lucide-react'

import type { IbStatus } from '@/api/portfolio'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { AccountSelector } from '@/features/portfolio/components/AccountSelector'

type PortfolioHeaderProps = {
  accounts: string[]
  activeAccount: string | undefined
  isLoading: boolean
  status: IbStatus | null
  onAccountChange: (account: string) => void
  onRefresh: () => void
}

export function PortfolioHeader({
  accounts,
  activeAccount,
  isLoading,
  status,
  onAccountChange,
  onRefresh,
}: PortfolioHeaderProps) {
  const isConnected = status?.connected ?? false

  return (
    <header className="flex items-center justify-between gap-4">
      <div className="flex items-center gap-3">
        <h1 className="text-3xl font-semibold tracking-tight">Account</h1>
        <AccountSelector
          accounts={accounts}
          activeAccount={activeAccount}
          disabled={isLoading}
          onAccountChange={onAccountChange}
        />
      </div>
      <div className="flex items-center gap-2">
        <Badge
          variant={isConnected ? 'secondary' : 'outline'}
          className={
            isConnected
              ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
              : undefined
          }
        >
          <CircleDot
            data-icon="inline-start"
            className={
              isConnected ? 'fill-emerald-400 text-emerald-400' : undefined
            }
          />
          {isConnected ? 'Connected' : 'Disconnected'}
        </Badge>
        <Button
          type="button"
          variant="outline"
          onClick={onRefresh}
          disabled={isLoading}
          className="cursor-pointer active:cursor-pointer disabled:cursor-not-allowed"
        >
          <RefreshCw className={isLoading ? 'animate-spin' : undefined} />
          Refresh
        </Button>
      </div>
    </header>
  )
}
