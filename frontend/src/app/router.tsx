import { createBrowserRouter, Navigate } from 'react-router'

import { AgentDetailPage } from '@/features/agents/AgentDetailPage'
import { AgentListPage } from '@/features/agents/AgentListPage'
import { ComparePage } from '@/features/benchmarks/ComparePage'
import { SuiteEditorPage } from '@/features/benchmarks/SuiteEditorPage'
import { SuiteListPage } from '@/features/benchmarks/SuiteListPage'
import { SuiteRunPage } from '@/features/benchmarks/SuiteRunPage'
import { LoginPage } from '@/features/auth/LoginPage'
import { RunDetailPage } from '@/features/runs/RunDetailPage'
import { RunLauncherPage } from '@/features/runs/RunLauncherPage'
import { RunListPage } from '@/features/runs/RunListPage'
import { ScenarioDetailPage } from '@/features/scenarios/ScenarioDetailPage'
import { ScenarioListPage } from '@/features/scenarios/ScenarioListPage'
import { StatusPage } from '@/features/status/StatusPage'

import { RequireAuth, RequireOwner } from './auth/guards'
import { AgentEditorRoute, EditorRoute } from './EditorRoute'
import { AppShell } from './layout/AppShell'
import { NotFoundPage } from './NotFoundPage'

export const routes = [
  { path: '/login', element: <LoginPage /> },
  {
    path: '/',
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Navigate to="/scenarios" replace /> },
      { path: 'scenarios', element: <ScenarioListPage /> },
      { path: 'scenarios/new', element: <EditorRoute mode="create" /> },
      { path: 'scenarios/:id', element: <ScenarioDetailPage /> },
      { path: 'scenarios/:id/edit', element: <EditorRoute mode="edit" /> },
      { path: 'agents', element: <AgentListPage /> },
      { path: 'agents/new', element: <AgentEditorRoute mode="create" /> },
      { path: 'agents/:id', element: <AgentDetailPage /> },
      { path: 'agents/:id/edit', element: <AgentEditorRoute mode="edit" /> },
      { path: 'runs', element: <RunListPage /> },
      { path: 'runs/new', element: <RunLauncherPage /> },
      { path: 'runs/:id', element: <RunDetailPage /> },
      { path: 'suites', element: <SuiteListPage /> },
      { path: 'suites/new', element: <RequireOwner><SuiteEditorPage mode="create" /></RequireOwner> },
      { path: 'suites/:id/edit', element: <RequireOwner><SuiteEditorPage mode="edit" /></RequireOwner> },
      { path: 'suite-runs/:id', element: <SuiteRunPage /> },
      { path: 'compare', element: <ComparePage /> },
      { path: 'status', element: <StatusPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]

export const router = createBrowserRouter(routes)
