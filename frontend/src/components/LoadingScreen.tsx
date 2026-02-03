import { useState, useEffect } from 'react'
import styles from './LoadingScreen.module.css'

interface LoadingScreenProps {
  message?: string
  subtitle?: string
  showProgress?: boolean
  showTip?: boolean
}

const tips = [
  "Vous pouvez exporter la liste des experts-comptables en format Excel",
  "Utilisez les filtres pour trouver rapidement un expert-comptable",
  "Le numéro d'ordre doit être unique pour chaque expert-comptable",
  "Vous pouvez importer plusieurs experts-comptables via un fichier Excel",
  "Les experts-comptables désactivés restent dans la base de données",
  "Utilisez la recherche pour filtrer par numéro, nom, email ou cabinet"
]

export default function LoadingScreen({
  message = "Chargement en cours",
  subtitle = "Veuillez patienter pendant que nous récupérons les données...",
  showProgress = true,
  showTip = true
}: LoadingScreenProps) {
  const [currentTip, setCurrentTip] = useState('')

  useEffect(() => {
    if (showTip) {
      const randomTip = tips[Math.floor(Math.random() * tips.length)]
      setCurrentTip(randomTip)
    }
  }, [showTip])

  return (
    <div className={styles.loadingOverlay}>
      <div className={styles.loadingContainer}>
        <div className={styles.spinner}></div>

        <h2 className={styles.title}>{message}</h2>
        <p className={styles.subtitle}>{subtitle}</p>

        {showProgress && (
          <div className={styles.progressBar}>
            <div className={styles.progressFill}></div>
          </div>
        )}

        {showTip && currentTip && (
          <div className={styles.tip}>
            <span className={styles.tipLabel}>Astuce</span>
            {currentTip}
          </div>
        )}
      </div>
    </div>
  )
}
