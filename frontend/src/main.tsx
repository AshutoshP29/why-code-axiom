import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { AppProviders, AppRoutes } from './App'
import { defaultApi } from './api/context'
import './index.css'

const root = document.getElementById('root')
if (!root) throw new Error('index.html is missing <div id="root">')

createRoot(root).render(
  <StrictMode>
    <BrowserRouter>
      <AppProviders api={defaultApi()}>
        <AppRoutes />
      </AppProviders>
    </BrowserRouter>
  </StrictMode>,
)
