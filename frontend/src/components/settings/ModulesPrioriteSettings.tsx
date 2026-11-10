import { useEffect, useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, LogIn, RotateCcw, Save } from 'lucide-react'
import { updateOrganisationSettings } from '../../api/organisation'
import { APP_DEFINITIONS, MODULES_ORDRE_DEFAUT } from '../../contexts/AppContext'
import { useOrganisationSettings } from '../../contexts/OrganisationSettingsContext'
import { useNotification } from '../../contexts/NotificationContext'
import styles from './ModulesPrioriteSettings.module.css'

const LIBELLES: Record<string, string> = Object.fromEntries(
  APP_DEFINITIONS.filter((app) => app.moduleKey).map((app) => [app.moduleKey as string, app.label]),
)

/** Ordre complet : les modules absents de l'ordre reçu suivent, dans l'ordre par défaut. */
function completer(ordre: string[] | undefined): string[] {
  const connus = (ordre ?? []).filter((cle, index, liste) => MODULES_ORDRE_DEFAUT.includes(cle) && liste.indexOf(cle) === index)
  return [...connus, ...MODULES_ORDRE_DEFAUT.filter((cle) => !connus.includes(cle))]
}

/**
 * Ordre dans lequel on essaie les modules à la connexion. Une personne arrive
 * dans le premier module dont elle a le tableau de bord ; à défaut, dans le
 * premier où une page lui est ouverte. Le module d'accueil réglé sur la fiche
 * d'un utilisateur passe avant cet ordre.
 */
export default function ModulesPrioriteSettings() {
  const { settings, reload } = useOrganisationSettings()
  const { showSuccess, showError } = useNotification()
  const enregistre = useMemo(() => completer(settings?.modules_priorite), [settings?.modules_priorite])
  const [ordre, setOrdre] = useState<string[]>(enregistre)
  const [saving, setSaving] = useState(false)

  useEffect(() => setOrdre(enregistre), [enregistre])

  const modulesConfig = settings?.modules_config
  // Même règle que la barre des modules : une fois modules_config posé, un
  // module absent ou désactivé n'est proposé à personne (super admin excepté).
  const estActive = (cle: string) => !modulesConfig || (Boolean(modulesConfig[cle]) && modulesConfig[cle]?.enabled !== false)
  const modifie = ordre.join() !== enregistre.join()

  const deplacer = (index: number, sens: -1 | 1) => {
    const cible = index + sens
    if (cible < 0 || cible >= ordre.length) return
    const suivant = [...ordre]
    ;[suivant[index], suivant[cible]] = [suivant[cible], suivant[index]]
    setOrdre(suivant)
  }

  const enregistrer = async () => {
    setSaving(true)
    try {
      await updateOrganisationSettings({ modules_priorite: ordre })
      await reload()
      showSuccess('Ordre enregistré', 'Les prochaines connexions suivent ce nouvel ordre.')
    } catch (error) {
      showError('Enregistrement impossible', error instanceof Error ? error.message : "L'ordre des modules n'a pas pu être enregistré.")
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className={styles.card} aria-labelledby="modules-priorite-titre">
      <div className={styles.header}>
        <span className={styles.icon} aria-hidden="true"><LogIn size={18} /></span>
        <div>
          <h3 id="modules-priorite-titre">Module d'arrivée à la connexion</h3>
          <p>
            Chacun arrive dans le premier module de cette liste dont il a le tableau de bord, sinon dans le premier
            où une page lui est ouverte. Le module d'accueil choisi sur la fiche d'un utilisateur passe avant cet ordre.
          </p>
        </div>
      </div>

      <ol className={styles.liste}>
        {ordre.map((cle, index) => (
          <li key={cle} className={styles.ligne}>
            <span className={styles.rang}>{index + 1}</span>
            <span className={styles.libelle}>{LIBELLES[cle] ?? cle}</span>
            {!estActive(cle) && <span className={styles.inactif}>Module non activé</span>}
            <span className={styles.actions}>
              <button type="button" onClick={() => deplacer(index, -1)} disabled={index === 0 || saving} aria-label={`Monter ${LIBELLES[cle] ?? cle}`} title="Monter">
                <ArrowUp size={15} />
              </button>
              <button type="button" onClick={() => deplacer(index, 1)} disabled={index === ordre.length - 1 || saving} aria-label={`Descendre ${LIBELLES[cle] ?? cle}`} title="Descendre">
                <ArrowDown size={15} />
              </button>
            </span>
          </li>
        ))}
      </ol>

      <div className={styles.footer}>
        <button type="button" className={styles.secondaryButton} onClick={() => setOrdre(enregistre)} disabled={!modifie || saving}>
          <RotateCcw size={14} /> Annuler
        </button>
        <button type="button" className={styles.primaryButton} onClick={enregistrer} disabled={!modifie || saving}>
          <Save size={14} /> {saving ? 'Enregistrement…' : "Enregistrer l'ordre"}
        </button>
      </div>
    </section>
  )
}
