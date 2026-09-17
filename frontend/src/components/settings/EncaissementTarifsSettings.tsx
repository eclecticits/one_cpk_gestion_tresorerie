import { useCallback, useEffect, useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, Lock } from 'lucide-react'
import {
  createEncaissementTarif,
  deleteEncaissementTarif,
  listEncaissementTarifs,
  updateEncaissementTarif,
  type EncaissementTarif,
} from '../../api/encaissementTarifs'
import { getBudgetPostes } from '../../api/budget'
import { useNotification } from '../../contexts/NotificationContext'
import styles from './EncaissementTarifsSettings.module.css'

/** Ligne en cours d'édition. `id` absent = tarif jamais enregistré. */
interface Ligne {
  id?: number
  libelle: string
  montant: string
  devise: 'USD' | 'CDF'
  budget_poste_code: string
  is_active: boolean
  /** Poste auquel le code se résout aujourd'hui ; vide = code introuvable. */
  poste_resolu: string | null
}

interface PosteOption {
  code: string
  libelle: string
}

const versLigne = (tarif: EncaissementTarif): Ligne => ({
  id: tarif.id,
  libelle: tarif.libelle,
  montant: tarif.montant === null || tarif.montant === undefined ? '' : String(tarif.montant),
  devise: tarif.devise || 'USD',
  budget_poste_code: tarif.budget_poste_code || '',
  is_active: tarif.is_active,
  poste_resolu: tarif.budget_poste_id ? tarif.budget_poste_libelle : null,
})

const ligneVide = (): Ligne => ({
  libelle: '',
  montant: '',
  devise: 'USD',
  budget_poste_code: '',
  is_active: true,
  poste_resolu: null,
})

interface Props {
  canEdit: boolean
}

export default function EncaissementTarifsSettings({ canEdit }: Props) {
  const { showError, showSuccess } = useNotification()
  const [lignes, setLignes] = useState<Ligne[]>([])
  const [initiales, setInitiales] = useState<EncaissementTarif[]>([])
  const [postes, setPostes] = useState<PosteOption[]>([])
  const [chargement, setChargement] = useState(true)
  const [enregistrement, setEnregistrement] = useState(false)

  const charger = useCallback(async () => {
    setChargement(true)
    try {
      const [tarifs, budget] = await Promise.all([
        listEncaissementTarifs(),
        // Les postes de recette de l'exercice courant : un encaissement
        // alimente une recette, jamais une dépense.
        getBudgetPostes({ type: 'RECETTE', active: true }).catch(() => ({ postes: [] as any[] })),
      ])
      setInitiales(tarifs)
      setLignes(tarifs.map(versLigne))
      setPostes(
        ((budget as any)?.postes ?? [])
          .filter((p: any) => p?.code)
          .map((p: any) => ({ code: String(p.code), libelle: String(p.libelle || '') })),
      )
    } catch (e: any) {
      showError('Chargement impossible', e?.message || "Impossible de lire les tarifs d'encaissement.")
    } finally {
      setChargement(false)
    }
  }, [showError])

  useEffect(() => {
    charger()
  }, [charger])

  const modifier = (index: number, champ: keyof Ligne, valeur: any) => {
    if (!canEdit) return
    setLignes((prev) => prev.map((l, i) => (i === index ? { ...l, [champ]: valeur } : l)))
  }

  const deplacer = (index: number, sens: -1 | 1) => {
    if (!canEdit) return
    setLignes((prev) => {
      const cible = index + sens
      if (cible < 0 || cible >= prev.length) return prev
      const next = [...prev]
      const tmp = next[cible]
      next[cible] = next[index]
      next[index] = tmp
      return next
    })
  }

  /** Un code saisi qui ne figure pas parmi les postes de recette de l'exercice
   *  courant n'imputera rien : mieux vaut le dire ici que le découvrir à la
   *  caisse. */
  const codeInconnu = useCallback(
    (ligne: Ligne) =>
      !!ligne.budget_poste_code &&
      !postes.some((p) => p.code.toUpperCase() === ligne.budget_poste_code.toUpperCase()),
    [postes],
  )

  const alertes = useMemo(() => lignes.filter(codeInconnu).length, [lignes, codeInconnu])

  const enregistrer = async () => {
    const nettoyees = lignes
      .map((l) => ({ ...l, libelle: l.libelle.trim() }))
      .filter((l) => l.libelle.length > 0)

    const doublon = nettoyees.find(
      (l, i) =>
        nettoyees.findIndex(
          (autre) => autre.libelle.trim().toLowerCase() === l.libelle.trim().toLowerCase(),
        ) !== i,
    )
    if (doublon) {
      showError('Libellé en double', `« ${doublon.libelle} » figure deux fois : un libellé ne peut désigner qu'un tarif.`)
      return
    }

    setEnregistrement(true)
    try {
      const gardes = new Set(nettoyees.map((l) => l.id).filter(Boolean) as number[])
      for (const tarif of initiales) {
        if (!gardes.has(tarif.id)) await deleteEncaissementTarif(tarif.id)
      }
      for (const [index, ligne] of nettoyees.entries()) {
        const charge = {
          libelle: ligne.libelle,
          montant: ligne.montant.trim() === '' ? null : Number(ligne.montant),
          devise: ligne.devise,
          budget_poste_code: ligne.budget_poste_code.trim() || null,
          is_active: ligne.is_active,
          position: index,
        }
        if (ligne.id) await updateEncaissementTarif(ligne.id, charge)
        else await createEncaissementTarif(charge)
      }
      showSuccess('Tarifs enregistrés', "Ils s'appliqueront aux prochains encaissements.")
      await charger()
    } catch (e: any) {
      showError('Enregistrement impossible', e?.message || "Impossible d'enregistrer les tarifs.")
    } finally {
      setEnregistrement(false)
    }
  }

  if (chargement) return <div className={styles.chargement}>Chargement des tarifs…</div>

  return (
    <div className={styles.wrap}>
      <p className={styles.intro}>
        Un libellé peut porter un <strong>montant</strong>, un <strong>poste budgétaire</strong>, ou les
        deux. Ce qui est défini ici s'impose à l'encaissement ; ce qui reste vide demeure libre à la
        saisie. Le montant est un <strong>prix unitaire</strong> : la quantité reste toujours modifiable.
      </p>

      {alertes > 0 && (
        <div className={styles.alerte}>
          {alertes === 1 ? 'Un code de poste ne correspond' : `${alertes} codes de poste ne correspondent`} à
          aucune recette de l'exercice en cours. Ces tarifs n'imputeront rien tant que le code reste
          introuvable.
        </div>
      )}

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.colRang}>#</th>
              <th>Libellé</th>
              <th className={styles.colMontant}>Montant unitaire</th>
              <th className={styles.colDevise}>Devise</th>
              <th className={styles.colPoste}>Poste budgétaire (recette)</th>
              <th className={styles.colActif}>Actif</th>
              <th className={styles.colActions}>Ordre</th>
            </tr>
          </thead>
          <tbody>
            {lignes.map((ligne, index) => (
              <tr key={ligne.id ?? `nouveau-${index}`} className={ligne.is_active ? '' : styles.inactif}>
                <td className={styles.colRang}>{index + 1}</td>
                <td>
                  <input
                    type="text"
                    value={ligne.libelle}
                    onChange={(e) => modifier(index, 'libelle', e.target.value)}
                    placeholder="Ex : Cotisation annuelle - Stagiaire (SEC)"
                    maxLength={255}
                    disabled={!canEdit}
                  />
                </td>
                <td>
                  <div className={styles.montantCell}>
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={ligne.montant}
                      onChange={(e) => modifier(index, 'montant', e.target.value)}
                      placeholder="Libre"
                      disabled={!canEdit}
                    />
                    {ligne.montant.trim() !== '' && <Lock size={12} className={styles.cadenas} />}
                  </div>
                </td>
                <td>
                  <select
                    value={ligne.devise}
                    onChange={(e) => modifier(index, 'devise', e.target.value)}
                    disabled={!canEdit || ligne.montant.trim() === ''}
                  >
                    <option value="USD">USD</option>
                    <option value="CDF">CDF</option>
                  </select>
                </td>
                <td>
                  <select
                    value={ligne.budget_poste_code}
                    onChange={(e) => modifier(index, 'budget_poste_code', e.target.value)}
                    disabled={!canEdit}
                    className={codeInconnu(ligne) ? styles.champAlerte : ''}
                  >
                    <option value="">Libre (choisi à la saisie)</option>
                    {codeInconnu(ligne) && (
                      <option value={ligne.budget_poste_code}>
                        {ligne.budget_poste_code} — introuvable dans cet exercice
                      </option>
                    )}
                    {postes.map((poste) => (
                      <option key={poste.code} value={poste.code}>
                        {poste.code} - {poste.libelle}
                      </option>
                    ))}
                  </select>
                </td>
                <td className={styles.colActif}>
                  <input
                    type="checkbox"
                    checked={ligne.is_active}
                    onChange={(e) => modifier(index, 'is_active', e.target.checked)}
                    disabled={!canEdit}
                    title="Un tarif inactif n'est plus proposé, sans être perdu"
                  />
                </td>
                <td className={styles.colActions}>
                  <button
                    type="button"
                    className={styles.actionBtn}
                    onClick={() => deplacer(index, -1)}
                    disabled={!canEdit || index === 0}
                    title="Monter"
                  >
                    <ArrowUp size={14} />
                  </button>
                  <button
                    type="button"
                    className={styles.actionBtn}
                    onClick={() => deplacer(index, 1)}
                    disabled={!canEdit || index >= lignes.length - 1}
                    title="Descendre"
                  >
                    <ArrowDown size={14} />
                  </button>
                  <button
                    type="button"
                    className={styles.actionBtn}
                    onClick={() => setLignes((prev) => prev.filter((_, i) => i !== index))}
                    disabled={!canEdit}
                    title="Retirer"
                  >
                    Retirer
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {canEdit && (
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.secondaryBtn}
            onClick={() => setLignes((prev) => [...prev, ligneVide()])}
          >
            + Ajouter un tarif
          </button>
          <button type="button" className={styles.primaryBtn} onClick={enregistrer} disabled={enregistrement}>
            {enregistrement ? 'Enregistrement…' : 'Enregistrer les tarifs'}
          </button>
        </div>
      )}
    </div>
  )
}
