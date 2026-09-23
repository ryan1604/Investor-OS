import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

type StrategySelectCellProps = {
  id: string
  value: string
  strategies: string[]
  onChange: (value: string) => void
  onAddStrategy: () => void
  onOpenChange?: (open: boolean) => void
}

export function StrategySelectCell({
  id,
  value,
  strategies,
  onChange,
  onAddStrategy,
  onOpenChange,
}: StrategySelectCellProps) {
  return (
    <Select value={value} onValueChange={onChange} onOpenChange={onOpenChange}>
      <SelectTrigger
        aria-label={`Strategy row ${id}`}
        className="w-full justify-between"
      >
        <SelectValue placeholder="Strategy" />
      </SelectTrigger>
      <SelectContent className="min-w-44">
        {strategies.map((strategy) => (
          <SelectItem key={strategy} value={strategy}>
            {strategy}
          </SelectItem>
        ))}
        <SelectSeparator />
        <div className="p-1">
          <Button
            type="button"
            variant="ghost"
            className="w-full justify-start"
            onClick={onAddStrategy}
          >
            Add strategy
          </Button>
        </div>
      </SelectContent>
    </Select>
  )
}
