import {
  Activity,
  Bot,
  FileBarChart,
  FlaskConical,
  LayoutDashboard,
  ListChecks,
  LogOut,
  PlayCircle,
  Settings,
  type LucideIcon,
} from 'lucide-react'
import { NavLink, Outlet, useNavigate } from 'react-router'

import { useAuth } from '@/app/auth/context'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface NavItem {
  label: string
  icon: LucideIcon
  to?: string
  /** Roadmap phase that delivers the page; shown until it exists. */
  phase?: number
}

const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard', icon: LayoutDashboard, phase: 9 },
  { label: 'Scenarios', icon: ListChecks, to: '/scenarios' },
  { label: 'Agents', icon: Bot, to: '/agents' },
  { label: 'Runs', icon: PlayCircle, phase: 4 },
  { label: 'Benchmarks', icon: FlaskConical, phase: 8 },
  { label: 'Reports', icon: FileBarChart, phase: 9 },
  { label: 'Settings', icon: Settings, phase: 6 },
  { label: 'System status', icon: Activity, to: '/status' },
]

function SessionPanel() {
  const { session, logout } = useAuth()
  const navigate = useNavigate()
  if (!session) return null
  return (
    <div className="mt-auto flex flex-col gap-2 border-t px-5 py-4 text-sm">
      <div className="flex items-center gap-2">
        <Badge variant={session.role === 'owner' ? 'default' : 'secondary'}>
          {session.role === 'owner' ? 'Owner' : 'Demo viewer'}
        </Badge>
      </div>
      {session.email ? <p className="truncate text-xs text-muted-foreground">{session.email}</p> : null}
      <Button
        variant="ghost"
        size="sm"
        className="justify-start px-2"
        onClick={() => {
          logout()
          navigate('/login', { replace: true })
        }}
      >
        <LogOut aria-hidden /> Sign out
      </Button>
    </div>
  )
}

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
        <SessionPanel />
      </aside>
      <main className="flex-1 overflow-y-auto p-8">
        <Outlet />
      </main>
    </div>
  )
}
