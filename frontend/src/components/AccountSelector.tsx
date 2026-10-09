import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

type AccountSelectorProps = {
  accounts: string[]
  activeAccount: string | undefined
  disabled?: boolean
  onAccountChange: (account: string) => void
}

export function AccountSelector({
  accounts,
  activeAccount,
  disabled = false,
  onAccountChange,
}: AccountSelectorProps) {
  return (
    <Select
      value={activeAccount}
      onValueChange={onAccountChange}
      disabled={!accounts.length || disabled}
    >
      <SelectTrigger className="w-44 cursor-pointer">
        <SelectValue placeholder="Select account" />
      </SelectTrigger>
      <SelectContent position="popper" align="start">
        {accounts.map((account) => (
          <SelectItem key={account} value={account} className="cursor-pointer">
            {account}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
