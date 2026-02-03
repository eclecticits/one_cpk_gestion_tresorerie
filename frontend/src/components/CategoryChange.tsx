import { useState } from 'react'
import { findExpertByNumeroOrdre, changeCategory, CategoryType, ExpertComptable } from '../api/experts'
import styles from './CategoryChange.module.css'

interface CategoryChangeProps {
  onClose: () => void
  onSuccess: () => void
}

export default function CategoryChange({ onClose, onSuccess }: CategoryChangeProps) {
  const [step, setStep] = useState<'search' | 'confirm' | 'update'>('search')
  const [numeroOrdre, setNumeroOrdre] = useState('')
  const [expert, setExpert] = useState<ExpertComptable | null>(null)
  const [newCategory, setNewCategory] = useState<CategoryType | ''>('')
  const [reason, setReason] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const [nif, setNif] = useState('')
  const [cabinetAttache, setCabinetAttache] = useState('')
  const [nomEmployeur, setNomEmployeur] = useState('')
  const [raisonSociale, setRaisonSociale] = useState('')
  const [associeGerant, setAssocieGerant] = useState('')

  const categoryLabels: Record<CategoryType, string> = {
    sec: 'SEC - Société d\'Expertise Comptable',
    en_cabinet: 'Expert-comptable en Cabinet',
    independant: 'Expert-comptable Indépendant',
    salarie: 'Expert-comptable Salarié'
  }

  const getCurrentCategory = (expert: ExpertComptable): CategoryType | null => {
    if (expert.type_ec === 'SEC') return 'sec'
    if (expert.statut_professionnel === 'En Cabinet') return 'en_cabinet'
    if (expert.statut_professionnel === 'Indépendant') return 'independant'
    if (expert.statut_professionnel === 'Salarié') return 'salarie'
    return null
  }

  const searchExpert = async () => {
    if (!numeroOrdre.trim()) {
      setError('Veuillez saisir un N° d\'ordre')
      return
    }

    setLoading(true)
    setError('')

    try {
      const data = await findExpertByNumeroOrdre(numeroOrdre.trim())

      if (!data) {
        setError('Aucun expert-comptable trouvé avec ce N° d\'ordre')
        return
      }

      setExpert(data)
      setStep('confirm')
    } catch (err: any) {
      setError(err.message || 'Erreur lors de la recherche')
    } finally {
      setLoading(false)
    }
  }

  const confirmChange = () => {
    if (!newCategory) {
      setError('Veuillez sélectionner une nouvelle catégorie')
      return
    }

    const currentCat = getCurrentCategory(expert!)
    if (currentCat === newCategory) {
      setError('La nouvelle catégorie doit être différente de l\'actuelle')
      return
    }

    setStep('update')
    setError('')

    if (expert) {
      setNif(expert.nif || '')
      setCabinetAttache(expert.cabinet_attache || '')
      setNomEmployeur(expert.nom_employeur || '')
      setRaisonSociale(expert.raison_sociale || '')
      setAssocieGerant(expert.associe_gerant || '')
    }
  }

  const validateAndSave = async () => {
    if (!expert || !newCategory) return

    if (newCategory === 'independant' && !nif.trim()) {
      setError('Le NIF est obligatoire pour un expert-comptable indépendant')
      return
    }

    if (newCategory === 'en_cabinet' && !cabinetAttache.trim()) {
      setError('Le cabinet d\'attache est obligatoire')
      return
    }

    if (newCategory === 'salarie' && !nomEmployeur.trim()) {
      setError('Le nom de l\'employeur est obligatoire')
      return
    }

    if (newCategory === 'sec' && (!raisonSociale.trim() || !associeGerant.trim())) {
      setError('La raison sociale et l\'associé gérant sont obligatoires pour une SEC')
      return
    }

    setLoading(true)
    setError('')

    try {
      await changeCategory({
        expert_id: expert.id,
        new_category: newCategory,
        reason: reason.trim() || undefined,
        nif: newCategory === 'independant' ? nif : undefined,
        cabinet_attache: newCategory === 'en_cabinet' ? cabinetAttache : undefined,
        nom_employeur: newCategory === 'salarie' ? nomEmployeur : undefined,
        raison_sociale: newCategory === 'sec' ? raisonSociale : undefined,
        associe_gerant: newCategory === 'sec' ? associeGerant : undefined,
      })

      setLoading(false)
      onClose()
      onSuccess()
    } catch (err: any) {
      console.error('Erreur lors du changement:', err)
      setLoading(false)
      setError(err.message || 'Erreur lors du changement de catégorie')
    }
  }

  return (
    <div className={styles.modal}>
      <div className={styles.modalContent}>
        <div className={styles.modalHeader}>
          <h2>Changement de Catégorie</h2>
          <button onClick={onClose} className={styles.closeBtn}>×</button>
        </div>

        {error && (
          <div className={styles.error}>
            {error}
          </div>
        )}

        {step === 'search' && (
          <div className={styles.searchStep}>
            <label>N° d'ordre de l'expert-comptable</label>
            <input
              type="text"
              value={numeroOrdre}
              onChange={(e) => setNumeroOrdre(e.target.value)}
              placeholder="Ex: SEC/18.00001"
              className={styles.input}
              autoFocus
            />
            <div className={styles.actions}>
              <button onClick={searchExpert} disabled={loading} className={styles.btnPrimary}>
                {loading ? 'Recherche...' : 'Rechercher'}
              </button>
              <button onClick={onClose} className={styles.btnSecondary}>
                Annuler
              </button>
            </div>
          </div>
        )}

        {step === 'confirm' && expert && (
          <div className={styles.confirmStep}>
            <div className={styles.expertInfo}>
              <h3>Expert-comptable trouvé</h3>
              <p><strong>N° d'ordre :</strong> {expert.numero_ordre}</p>
              <p><strong>Nom :</strong> {expert.nom_denomination}</p>
              <p><strong>Catégorie actuelle :</strong> {categoryLabels[getCurrentCategory(expert)!]}</p>
            </div>

            <label>Nouvelle catégorie</label>
            <select
              value={newCategory}
              onChange={(e) => setNewCategory(e.target.value as CategoryType)}
              className={styles.select}
            >
              <option value="">-- Sélectionner --</option>
              {Object.entries(categoryLabels)
                .filter(([key]) => key !== getCurrentCategory(expert))
                .map(([key, label]) => (
                  <option key={key} value={key}>{label}</option>
                ))}
            </select>

            <label>Motif du changement (optionnel)</label>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Ex: Changement de statut professionnel, mise à jour administrative..."
              className={styles.textarea}
              rows={3}
            />

            <div className={styles.actions}>
              <button onClick={confirmChange} className={styles.btnPrimary}>
                Continuer
              </button>
              <button onClick={() => setStep('search')} className={styles.btnSecondary}>
                Retour
              </button>
            </div>
          </div>
        )}

        {step === 'update' && expert && (
          <div className={styles.updateStep}>
            <h3>Compléter les informations</h3>
            <p className={styles.infoText}>
              Les informations communes (nom, téléphone, email) sont conservées.
            </p>

            {newCategory === 'independant' && (
              <div className={styles.formGroup}>
                <label>NIF (obligatoire)</label>
                <input
                  type="text"
                  value={nif}
                  onChange={(e) => setNif(e.target.value)}
                  className={styles.input}
                  autoFocus
                />
              </div>
            )}

            {newCategory === 'en_cabinet' && (
              <div className={styles.formGroup}>
                <label>Cabinet d'attache (obligatoire)</label>
                <input
                  type="text"
                  value={cabinetAttache}
                  onChange={(e) => setCabinetAttache(e.target.value)}
                  className={styles.input}
                  autoFocus
                />
              </div>
            )}

            {newCategory === 'salarie' && (
              <div className={styles.formGroup}>
                <label>Nom de l'employeur (obligatoire)</label>
                <input
                  type="text"
                  value={nomEmployeur}
                  onChange={(e) => setNomEmployeur(e.target.value)}
                  className={styles.input}
                  autoFocus
                />
              </div>
            )}

            {newCategory === 'sec' && (
              <>
                <div className={styles.formGroup}>
                  <label>Raison sociale (obligatoire)</label>
                  <input
                    type="text"
                    value={raisonSociale}
                    onChange={(e) => setRaisonSociale(e.target.value)}
                    className={styles.input}
                    autoFocus
                  />
                </div>
                <div className={styles.formGroup}>
                  <label>Associé gérant (obligatoire)</label>
                  <input
                    type="text"
                    value={associeGerant}
                    onChange={(e) => setAssocieGerant(e.target.value)}
                    className={styles.input}
                  />
                </div>
              </>
            )}

            <div className={styles.actions}>
              <button onClick={validateAndSave} disabled={loading} className={styles.btnPrimary}>
                {loading ? 'Enregistrement...' : 'Enregistrer le changement'}
              </button>
              <button onClick={() => setStep('confirm')} className={styles.btnSecondary}>
                Retour
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
