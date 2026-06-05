import { useCallback, useRef, type WheelEvent } from 'react'

import type { OptionExpiration } from '@/api/options'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

export function ExpirationTabs({
  expirations,
  selectedExpiration,
  onSelectedExpirationChange,
}: {
  expirations: OptionExpiration[]
  selectedExpiration: string
  onSelectedExpirationChange: (expiration: string) => void
}) {
  const expirationsListRef = useRef<HTMLDivElement | null>(null)
  const handleExpirationWheel = useCallback(
    (event: WheelEvent<HTMLDivElement>) => {
      const expirationsList = expirationsListRef.current

      if (!expirationsList) {
        return
      }

      const maxScrollLeft =
        expirationsList.scrollWidth - expirationsList.clientWidth

      if (maxScrollLeft <= 0) {
        return
      }

      event.preventDefault()
      expirationsList.scrollLeft += event.deltaY || event.deltaX
    },
    [],
  )

  return (
    <Tabs
      value={selectedExpiration}
      onValueChange={onSelectedExpirationChange}
      className="min-w-0"
    >
      <TabsList
        ref={expirationsListRef}
        className="no-scrollbar max-w-full justify-start overflow-x-auto overscroll-x-contain"
        onWheel={handleExpirationWheel}
      >
        {expirations.map((expiration) => (
          <TabsTrigger
            key={expiration.date}
            value={expiration.date}
            className="cursor-pointer active:cursor-pointer"
          >
            {expiration.date}
            {expiration.days_to_expiration !== null
              ? ` (${expiration.days_to_expiration}D)`
              : ''}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  )
}
