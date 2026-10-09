import { pages as navigationItems, type AppPage } from '@/lib/pages'

type AppSidebarProps = {
  activePage: AppPage
  onPageChange: (page: AppPage) => void
}

export function AppSidebar({ activePage, onPageChange }: AppSidebarProps) {
  return (
    <aside className="flex min-h-svh w-64 shrink-0 flex-col bg-sidebar text-sidebar-foreground">
      <header className="flex flex-col gap-2 px-4 py-6 text-lg font-semibold">
        Investor OS
      </header>
      <nav
        aria-label="Primary"
        className="no-scrollbar flex min-h-0 flex-1 flex-col gap-0 overflow-auto p-2 text-sm"
      >
        <ul className="flex w-full min-w-0 flex-col gap-0">
          {navigationItems.map((item) => {
            const Icon = item.icon

            return (
              <li key={item.id}>
                <button
                  type="button"
                  aria-current={activePage === item.id ? 'page' : undefined}
                  className="flex h-8 w-full cursor-pointer items-center gap-2 overflow-hidden rounded-md p-2 text-left text-sm ring-sidebar-ring outline-hidden hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 active:cursor-pointer active:bg-sidebar-accent active:text-sidebar-accent-foreground aria-[current=page]:bg-sidebar-accent aria-[current=page]:font-medium aria-[current=page]:text-sidebar-accent-foreground [&_svg]:size-4 [&_svg]:shrink-0 [&>span:last-child]:truncate"
                  onClick={() => onPageChange(item.id)}
                >
                  <Icon />
                  <span>{item.label}</span>
                </button>
              </li>
            )
          })}
        </ul>
      </nav>
    </aside>
  )
}
