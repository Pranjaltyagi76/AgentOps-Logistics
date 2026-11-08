import {
  Activity,
  Bot,
  FileBarChart,
  FlaskConical,
  LayoutDashboard,
  ListChecks,
  PlayCircle,
  Settings,
  type LucideIcon,
} from 'lucide-react'
import { NavLink, Outlet } from 'react-router'

import { cn } from '@/lib/utils'

interface NavItem {
  label: string
  icon: LucideIcon
  to?: string
  /** Roadmap phase that delivers the page; shown until it exists. */
  phase?: number
}

const NAV_ITEMS: NavItem[] = [
  { label: 'Status', icon: Activity, to: '/' },
  { label: 'Dashboard', icon: LayoutDashboard, phase: 9 },
  { label: 'Scenarios', icon: ListChecks, phase: 1 },
  { label: 'Agents', icon: Bot, phase: 3 },
  { label: 'Runs', icon: PlayCircle, phase: 4 },
  { label: 'Benchmarks', icon: FlaskConical, phase: 8 },
  { label: 'Reports', icon: FileBarChart, phase: 9 },
  { label: 'Settings', icon: Settings, phase: 6 },
]

export function AppShell() {
  return (
    <div className="flex min-h-svh bg-background text-foreground">
      <aside className="flex w-60 shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground">
        <div className="px-5 py-5">
          <p className="text-base font-semibold leading-tight">AgentOps Logistics</p>
          <p className="text-xs text-muted-foreground">Agent reliability workbench</p>
        </div>
        <nav aria-label="Main" className="flex flex-col gap-0.5 px-3">
          {NAV_ITEMS.map((item) =>
            item.to ? (
              <NavLink
                key={item.label}
                to={item.to}
                end
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
                    isActive
                      ? 'bg-sidebar-accent font-medium text-sidebar-accent-foreground'
                      : 'hover:bg-sidebar-accent/60',
                  )
                }
              >
                <item.icon className="size-4" aria-hidden />
                {item.label}
              </NavLink>
            ) : (
              <span
                key={item.label}
                aria-disabled="true"
                title={`Coming in Phase ${item.phase}`}
                className="flex cursor-not-allowed items-center gap-3 rounded-md px-3 py-2 text-sm text-muted-foreground/70"
              >
                <item.icon className="size-4" aria-hidden />
                {item.label}
                <span className="ml-auto text-[10px] uppercase tracking-wide">P{item.phase}</span>
              </span>
            ),
          )}
        </nav>
      </aside>
      <main className="flex-1 overflow-y-auto p-8">
        <Outlet />
      </main>
    </div>
  )
}
