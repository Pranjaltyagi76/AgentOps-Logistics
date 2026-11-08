import { createBrowserRouter } from 'react-router'

import { StatusPage } from '@/features/status/StatusPage'

import { AppShell } from './layout/AppShell'
import { NotFoundPage } from './NotFoundPage'

export const routes = [
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <StatusPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]

export const router = createBrowserRouter(routes)
