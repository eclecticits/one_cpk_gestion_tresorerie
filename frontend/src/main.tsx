import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'
import { reloadOnceForChunkError } from './utils/lazyWithRetry'

// Après un déploiement, les fichiers que Vite précharge pour une page ont
// changé de nom : on recharge une fois plutôt que de laisser la page en panne.
window.addEventListener('vite:preloadError', (event) => {
  if (reloadOnceForChunkError()) event.preventDefault()
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
