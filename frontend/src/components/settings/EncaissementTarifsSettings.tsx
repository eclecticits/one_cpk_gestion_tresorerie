import { useCallback, useEffect, useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, Lock, Search } from 'lucide-react'
import {
  createEncaissementTarif,
  deleteEncaissementTarif,
  listEncaissementTarifs,
  updateEncaissementTarif,
  type EncaissementTarif,
} from '../../api/encaissementTarifs'
import { getBudgetPostes } from '../../api/budget'
import { useConfirm } from '../../contexts/ConfirmContext'
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
  /** Lignes d'encaissement déjà passées sous cette version. Au-delà de zéro,
   *  la modifier ouvre une version neuve et la retirer la clôt : l'archive ne
   *  bouge pas, seules les saisies à venir suivent le nouveau réglage. */
  utilisations: number
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
  utilisations: tarif.utilisations || 0,
})

const ligneVide = (): Ligne => ({
  libelle: '',
  montant: '',
  devise: 'USD',
  budget_poste_code: '',
  is_active: true,
  poste_resolu: null,
  utilisations: 0,
})

/** Ce qui, dans une ligne, mérite d'être enregistré. Sert à reconnaître un
 *  brouillon : l'écran peut alors dire qu'il reste des modifications en attente
 *  plutôt que de laisser quitter la page sans un mot. */
const empreinte = (lignes: Ligne[]) =>
  JSON.stringify(
    lignes.map((l) => [l.id ?? 0, l.libelle.trim(), l.montant.trim(), l.devise, l.budget_poste_code, l.is_active]),
  )

const pluriel = (nombre: number, singulier: string, pluriel_: string) => (nombre > 1 ? pluriel_ : singulier)

interface Props {
  canEdit: boolean
}

export default function EncaissementTarifsSettings({ canEdit }: Props) {
  const { showError, showSuccess } = useNotification()
  const confirm = useConfirm()
  const [lignes, setLignes] = useState<Ligne[]>([])
  const [initiales, setInitiales] = useState<EncaissementTarif[]>([])
  const [postes, setPostes] = useState<PosteOption[]>([])
  // Les versions closes ne s'éditent pas : elles se relisent. Les tenir hors
  // des lignes éditables évite qu'un enregistrement ne tente de les réécrire.
  const [closes, setCloses] = useState<EncaissementTarif[]>([])
  const [voirCloses, setVoirCloses] = useState(false)
  const [chargement, setChargement] = useState(true)
  const [enregistrement, setEnregistrement] = useState(false)
  const [recherche, setRecherche] = useState('')

  const charger = useCallback(async () => {
    setChargement(true)
    try {
      const [tarifs, budget, histoire] = await Promise.all([
        listEncaissementTarifs(),
        // Les postes de recette de l'exercice courant : un encaissement
        // alimente une recette, jamais une dépense.
        getBudgetPostes({ type: 'RECETTE', active: true }).catch(() => ({ postes: [] as any[] })),
        listEncaissementTarifs(undefined, true).catch(() => [] as EncaissementTarif[]),
      ])
      setInitiales(tarifs)
      setLignes(tarifs.map(versLigne))
      setCloses(histoire.filter((t) => t.effet_au !== null))
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

  const parId = useMemo(() => new Map(initiales.map((t) => [t.id, t])), [initiales])

  /** La ligne touche-t-elle à ce qui engage un reçu — libellé, prix, devise,
   *  imputation — alors qu'elle a déjà tarifé quelque chose ? Le serveur ouvre
   *  alors une version neuve et referme l'actuelle. L'ordre et le commutateur
   *  « Actif » n'engagent rien : ils règlent ce que la caisse se voit proposer,
   *  et se corrigent sur place. */
  const ouvriraUneVersion = useCallback(
    (ligne: Ligne) => {
      if (!ligne.id || ligne.utilisations === 0) return false
      const avant = parId.get(ligne.id)
      if (!avant) return false
      const prixAvant = avant.montant === null || avant.montant === undefined ? '' : String(avant.montant)
      const memePrix =
        prixAvant.trim() === ''
          ? ligne.montant.trim() === ''
          : ligne.montant.trim() !== '' && Number(prixAvant) === Number(ligne.montant)
      return (
        avant.libelle.trim() !== ligne.libelle.trim() ||
        !memePrix ||
        (avant.devise || 'USD') !== ligne.devise ||
        (avant.budget_poste_code || '') !== ligne.budget_poste_code
      )
    },
    [parId],
  )

  /** Retirer un tarif qui a servi ne l'efface pas : il se clôt. Le dire avant
   *  vaut mieux que de le laisser découvrir — l'administrateur croirait sinon
   *  avoir supprimé ce qui demeure. */
  const retirer = async (index: number) => {
    const ligne = lignes[index]
    if (ligne.utilisations > 0) {
      const alle = await confirm({
        title: `Retirer « ${ligne.libelle} » ?`,
        description:
          `Ce tarif a déjà été appliqué à ${ligne.utilisations} ` +
          `${pluriel(ligne.utilisations, "ligne d'encaissement", "lignes d'encaissement")}. ` +
          `Il sera clos, non effacé : les encaissements passés gardent leur montant et ` +
          `continuent de le désigner. Seules les saisies à venir cesseront d'y être soumises.`,
        confirmText: 'Clore le tarif',
        cancelText: 'Annuler',
        variant: 'danger',
      })
      if (!alle) return
    }
    setLignes((prev) => prev.filter((_, i) => i !== index))
  }

  const alertes = useMemo(() => lignes.filter(codeInconnu).length, [lignes, codeInconnu])

  const compte = useMemo(
    () => ({
      total: lignes.length,
      actifs: lignes.filter((l) => l.is_active).length,
      prixFixe: lignes.filter((l) => l.montant.trim() !== '').length,
      imputes: lignes.filter((l) => l.budget_poste_code.trim() !== '').length,
    }),
    [lignes],
  )

  const modifiee = useMemo(
    () => empreinte(lignes) !== empreinte(initiales.map(versLigne)),
    [lignes, initiales],
  )

  /** Le filtre ne retire rien : il masque. Chaque ligne garde son rang réel,
   *  sans quoi une modification tomberait sur la voisine. */
  const filtre = recherche.trim().toLowerCase()
  const visibles = useMemo(
    () =>
      lignes
        .map((ligne, index) => ({ ligne, index }))
        .filter(({ ligne }) =>
          !filtre
            ? true
            : ligne.libelle.toLowerCase().includes(filtre) ||
              ligne.budget_poste_code.toLowerCase().includes(filtre) ||
              (ligne.poste_resolu || '').toLowerCase().includes(filtre),
        ),
    [lignes, filtre],
  )

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

  const ajouter = () => {
    // Une ligne ajoutée alors qu'un filtre masque la table serait invisible :
    // on rend d'abord la table entière, puis on ajoute.
    setRecherche('')
    setLignes((prev) => [...prev, ligneVide()])
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

      <div className={styles.toolbar}>
        <div className={styles.compteurs}>
          <span className={styles.compteurFort}>
            {compte.total} {pluriel(compte.total, 'tarif', 'tarifs')}
          </span>
          <span className={styles.compteurDetail}>
            {compte.actifs} {pluriel(compte.actifs, 'actif', 'actifs')} · {compte.prixFixe} à prix fixé ·{' '}
            {compte.imputes} {pluriel(compte.imputes, 'imputé', 'imputés')}
          </span>
        </div>
        <div className={styles.outils}>
          {modifiee && <span className={styles.brouillon}>Modifications non enregistrées</span>}
          {closes.length > 0 && (
            <button
              type="button"
              className={styles.lienHistoire}
              onClick={() => setVoirCloses((v) => !v)}
            >
              {voirCloses ? 'Masquer' : 'Voir'} les {closes.length}{' '}
              {pluriel(closes.length, 'version close', 'versions closes')}
            </button>
          )}
          <div className={styles.rechercheWrap}>
            <Search size={14} className={styles.rechercheIcone} />
            <input
              type="search"
              className={styles.recherche}
              value={recherche}
              onChange={(e) => setRecherche(e.target.value)}
              placeholder="Filtrer par libellé ou poste"
            />
          </div>
        </div>
      </div>

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.colRang}>#</th>
              <th className={styles.colLibelle}>Libellé</th>
              <th className={styles.colMontant}>Montant unitaire</th>
              <th className={styles.colDevise}>Devise</th>
              <th className={styles.colPoste}>Poste budgétaire (recette)</th>
              <th className={styles.colActif}>Actif</th>
              <th className={styles.colActions}>Ordre</th>
            </tr>
          </thead>
          <tbody>
            {visibles.length === 0 && (
              <tr>
                <td colSpan={7} className={styles.vide}>
                  {lignes.length === 0
                    ? "Aucun tarif : tous les libellés restent libres à la caisse."
                    : `Aucun tarif ne correspond à « ${recherche.trim()} ».`}
                </td>
              </tr>
            )}
            {visibles.map(({ ligne, index }) => (
              <tr key={ligne.id ?? `nouveau-${index}`} className={ligne.is_active ? '' : styles.inactif}>
                <td className={styles.colRang}>{index + 1}</td>
                <td className={styles.colLibelle}>
                  <input
                    type="text"
                    className={styles.champLibelle}
                    value={ligne.libelle}
                    onChange={(e) => modifier(index, 'libelle', e.target.value)}
                    placeholder="Ex : Cotisation annuelle - Stagiaire (SEC)"
                    title={ligne.libelle}
                    maxLength={255}
                    disabled={!canEdit}
                  />
                  {ligne.utilisations > 0 && (
                    <span className={styles.usage}>
                      Appliqué à {ligne.utilisations}{' '}
                      {pluriel(ligne.utilisations, 'encaissement', 'encaissements')}
                    </span>
                  )}
                  {ouvriraUneVersion(ligne) && (
                    <span className={styles.version}>
                      Une nouvelle version sera créée — les encaissements passés ne changent pas
                    </span>
                  )}
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
                    disabled={!canEdit || index === 0 || !!filtre}
                    title={filtre ? "Retirez le filtre pour réordonner" : 'Monter'}
                  >
                    <ArrowUp size={14} />
                  </button>
                  <button
                    type="button"
                    className={styles.actionBtn}
                    onClick={() => deplacer(index, 1)}
                    disabled={!canEdit || index >= lignes.length - 1 || !!filtre}
                    title={filtre ? "Retirez le filtre pour réordonner" : 'Descendre'}
                  >
                    <ArrowDown size={14} />
                  </button>
                  <button
                    type="button"
                    className={styles.actionBtn}
                    onClick={() => retirer(index)}
                    disabled={!canEdit}
                    title={ligne.utilisations > 0 ? 'Clore ce tarif (les reçus passés ne changent pas)' : 'Retirer'}
                  >
                    Retirer
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {voirCloses && closes.length > 0 && (
        <div className={styles.histoire}>
          <h4 className={styles.histoireTitre}>Versions closes</h4>
          <p className={styles.histoireIntro}>
            Elles ne s'appliquent plus à une saisie d'aujourd'hui, mais valent encore pour les
            encaissements qu'elles couvraient : c'est ce qui permet de relire un ancien reçu au prix
            réglé de l'époque.
          </p>
          <ul className={styles.histoireListe}>
            {closes.map((version) => (
              <li key={version.id}>
                <strong>{version.libelle}</strong>
                {version.montant !== null && version.montant !== undefined && (
                  <> — {String(version.montant)} {version.devise}</>
                )}
                {version.budget_poste_code && <> · {version.budget_poste_code}</>}
                <span className={styles.histoireDates}>
                  du {version.effet_du} au {version.effet_au}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {canEdit && (
        <div className={styles.actions}>
          <button type="button" className={styles.secondaryBtn} onClick={ajouter}>
            + Ajouter un tarif
          </button>
          <span className={styles.actionsEspace} />
          {modifiee && <span className={styles.brouillonPied}>Modifications non enregistrées</span>}
          <button type="button" className={styles.primaryBtn} onClick={enregistrer} disabled={enregistrement}>
            {enregistrement ? 'Enregistrement…' : 'Enregistrer les tarifs'}
          </button>
        </div>
      )}
    </div>
  )
}
