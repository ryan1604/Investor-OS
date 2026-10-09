import { Radar, Square } from 'lucide-react'

import type { OptionsScreenerScanJob } from '@/api/optionsScreeners'
import { Button } from '@/components/ui/button'

export function ScanActionButton({
  activeJob,
  disabled,
  tickerCount,
  onStartScan,
  onCancelScan,
}: {
  activeJob: OptionsScreenerScanJob | null
  disabled: boolean
  tickerCount: number
  onStartScan: () => Promise<void>
  onCancelScan: () => Promise<void>
}) {
  return activeJob ? (
    <Button
      variant="destructive"
      className="cursor-pointer"
      onClick={() => void onCancelScan()}
    >
      <Square className="fill-current" />
      Cancel scan
    </Button>
  ) : (
    <Button
      className="cursor-pointer disabled:cursor-not-allowed"
      disabled={disabled}
      onClick={() => void onStartScan()}
    >
      <Radar />
      Scan {tickerCount || ''} ticker
      {tickerCount === 1 ? '' : 's'}
    </Button>
  )
}
