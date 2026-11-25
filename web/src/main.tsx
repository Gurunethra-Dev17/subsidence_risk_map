import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import Dashboard from './pages/Dashboard'
import './styles.css'
import './operations.css'
import './command.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Dashboard />
  </StrictMode>,
)
