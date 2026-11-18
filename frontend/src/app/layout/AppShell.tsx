import {
  Activity,
  Bot,
  FileBarChart,
  FlaskConical,
  LayoutDashboard,
  ListChecks,
  LogOut,
  Menu,
  PlayCircle,
  Settings,
  X,
  type LucideIcon,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router'

import { useAuth } from '@/app/auth/context'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import { BackendWakingBanner } from './BackendWakingBanner'

interface NavItem {
  label: string
  icon: LucideIcon
  to: string
}

const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard', icon: LayoutDashboard, to: '/dashboard' },
  { label: 'Scenarios', icon: ListChecks, to: '/scenarios' },
  { label: 'Agents', icon: Bot, to: '/agents' },
  { label: 'Runs', icon: PlayCircle, to: '/runs' },
  { label: 'Benchmarks', icon: FlaskConical, to: '/suites' },
  { label: 'Reports', icon: FileBarChart, to: '/reports' },
  { label: 'Settings', icon: Settings, to: '/settings' },
  { label: 'System status', icon: Activity, to: '/status' },
]

function Brand() {
  return (
    <div>
      <p className="text-base font-semibold leading-tight">AgentOps Logistics</p>
      <p className="text-xs text-muted-foreground">Agent reliability workbench</p>
    </div>
  )
}

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Main" className="flex flex-col gap-0.5 px-3">
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.label}
          to={item.to}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
              isActive ? 'bg-sidebar-accent font-medium text-sidebar-accent-foreground' : 'hover:bg-sidebar-accent/60',
            )
          }
        >
          <item.icon className="size-4" aria-hidden />
          {item.label}
        </NavLink>
      ))}
    </nav>
  )
}

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

/** Below the md breakpoint (768 px) the sidebar becomes a top bar with a slide-over menu. */
function MobileMenu() {
  // The menu is open only on the page it was opened on, so any navigation closes it.
  const { pathname } = useLocation()
  const [openOn, setOpenOn] = useState<string | null>(null)
  const open = openOn === pathname
  const setOpen = (value: boolean) => setOpenOn(value ? pathname : null)
  const panelRef = useRef<HTMLDivElement>(null)
  const toggleRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    panelRef.current?.querySelector<HTMLElement>('a, button')?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpenOn(null)
        toggleRef.current?.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  return (
    <>
      <header className="sticky top-0 z-30 flex items-center justify-between border-b bg-sidebar px-4 py-3 text-sidebar-foreground md:hidden">
        <Brand />
        <Button
          ref={toggleRef}
          variant="ghost"
          size="icon"
          aria-label={open ? 'Close menu' : 'Open menu'}
          aria-expanded={open}
          aria-controls="mobile-menu"
          onClick={() => setOpen(!open)}
        >
          {open ? <X aria-hidden /> : <Menu aria-hidden />}
        </Button>
      </header>
      {open ? (
        <div className="fixed inset-0 z-40 md:hidden">
          <button
            type="button"
            aria-label="Close menu"
            tabIndex={-1}
            className="absolute inset-0 bg-black/40"
            onClick={() => setOpen(false)}
          />
          <div
            id="mobile-menu"
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-label="Menu"
            className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col border-r bg-sidebar pt-4 text-sidebar-foreground shadow-lg"
          >
            <div className="flex items-center justify-between px-5 pb-4">
              <Brand />
              <Button variant="ghost" size="icon" aria-label="Close menu" onClick={() => setOpen(false)}>
                <X aria-hidden />
              </Button>
            </div>
            <NavLinks onNavigate={() => setOpen(false)} />
            <SessionPanel />
          </div>
        </div>
      ) : null}
    </>
  )
}

export function AppShell() {
  return (
    <div className="flex min-h-svh flex-col bg-background text-foreground md:flex-row">
      <aside className="hidden w-60 shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground md:flex">
        <div className="px-5 py-5">
          <Brand />
        </div>
        <NavLinks />
        <SessionPanel />
      </aside>
      <MobileMenu />
      <main className="min-w-0 flex-1 overflow-y-auto">
        <BackendWakingBanner />
        <div className="p-4 sm:p-6 md:p-8">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
