/**
 * Logo de l'éditeur.
 *
 * Le fichier vit sur disque côté serveur ; seul son descripteur est rangé
 * dans `platform_settings.billing_config`. Il s'imprime en tête des factures
 * SaaS et signe cette console.
 */

import { useEffect, useRef, useState } from 'react'
import { Image as ImageIcon, Loader2, RotateCcw, Trash2, Upload } from 'lucide-react'
import {
  deleteEditorLogo,
  getEditorLogo,
  updateEditorAccent,
  uploadEditorLogo,
  type EditorLogo,
} from '../../api/superAdmin'
import { fetchAuthenticatedObjectUrl } from '../../utils/download'
import { useNotification } from '../../contexts/NotificationContext'
import { useConfirm } from '../../contexts/ConfirmContext'
import styles from './Reglages.module.css'

const formatTaille = (octets: number) => {
  if (!octets) return ''
  if (octets < 1024) return `${octets} o`
  if (octets < 1024 * 1024) return `${(octets / 1024).toFixed(0)} Ko`
  return `${(octets / (1024 * 1024)).toFixed(1)} Mo`
}

export default function BrandingEditor({ onChange }: { onChange?: () => void }) {
  const { showSuccess, showError } = useNotification()
  const confirm = useConfirm()
  const inputRef = useRef<HTMLInputElement>(null)
  const [logo, setLogo] = useState<EditorLogo | null>(null)
  const [apercu, setApercu] = useState<string>('')
  const [chargement, setChargement] = useState(true)
  const [occupe, setOccupe] = useState(false)
  // Couleur en cours d'édition. Le serveur la tire du logo au dépôt ; on peut
  // la corriger quand l'extraction s'est laissé prendre par un détail coloré.
  const [accent, setAccent] = useState('')

  const relire = async () => {
    const descripteur = await getEditorLogo()
    setLogo(descripteur)
    setAccent(descripteur.accent || '')
    if (!descripteur.present) {
      setApercu((ancien) => {
        if (ancien) URL.revokeObjectURL(ancien)
        return ''
      })
      return
    }
    // Une <img> ne peut pas porter d'en-tête Authorization : on passe par un
    // blob. L'URL est révoquée dès qu'elle est remplacée ou au démontage.
    const url = await fetchAuthenticatedObjectUrl('/super-admin/branding/logo/file')
    setApercu((ancien) => {
      if (ancien) URL.revokeObjectURL(ancien)
      return url
    })
  }

  /** Après une écriture : relire le descripteur et prévenir la console, qui
   *  affiche le logo dans son en-tête. */
  const relireApres = async () => {
    await relire()
    onChange?.()
  }

  useEffect(() => {
    let actif = true
    const charger = async () => {
      try {
        await relire()
      } catch (err: any) {
        if (actif) showError('Chargement impossible', err?.message || 'Logo illisible.')
      } finally {
        if (actif) setChargement(false)
      }
    }
    charger()
    return () => { actif = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Révocation de la dernière URL au démontage : sans cela le blob reste en
  // mémoire tant que l'onglet vit.
  useEffect(() => () => { if (apercu) URL.revokeObjectURL(apercu) }, [apercu])

  const deposer = async (fichier: File) => {
    setOccupe(true)
    try {
      await uploadEditorLogo(fichier)
      await relireApres()
      showSuccess('Logo enregistré', 'Il apparaîtra en tête des prochaines factures.')
    } catch (err: any) {
      showError('Envoi impossible', err?.message || "Le logo n'a pas pu être enregistré.")
    } finally {
      setOccupe(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  const enregistrerAccent = async (valeur: string) => {
    setOccupe(true)
    try {
      await updateEditorAccent(valeur)
      await relireApres()
      showSuccess(
        'Couleur enregistrée',
        'Les factures régénérées à partir de maintenant la reprendront.',
      )
    } catch (err: any) {
      showError('Enregistrement impossible', err?.message || 'La couleur n’a pas changé.')
    } finally {
      setOccupe(false)
    }
  }

  const supprimer = async () => {
    const ok = await confirm({
      title: 'Retirer le logo',
      description: 'Les prochaines factures repartiront sans logo, avec la seule raison sociale.',
      confirmText: 'Retirer',
      variant: 'danger',
    })
    if (!ok) return
    setOccupe(true)
    try {
      await deleteEditorLogo()
      await relireApres()
      showSuccess('Logo retiré', 'Aucun logo n’est plus enregistré.')
    } catch (err: any) {
      showError('Suppression impossible', err?.message || 'Le logo est toujours en place.')
    } finally {
      setOccupe(false)
    }
  }

  if (chargement) {
    return <div className={styles.state}>Chargement du logo…</div>
  }

  return (
    <section className={styles.panel}>
      <div className={styles.panelHead}>
        <div>
          <h3 className={styles.panelTitle}>Logo de l’éditeur</h3>
          <p className={styles.panelHint}>
            Imprimé en tête des factures SaaS, à gauche de la raison sociale, et affiché dans
            cette console. PNG ou JPEG, 2 Mo au maximum. Un logo modifié vaut pour les rendus
            suivants : les factures déjà émises gardent celui de leur émission tant qu’on ne les
            régénère pas.
          </p>
        </div>
        <div className={styles.actions}>
          <input
            ref={inputRef}
            type="file"
            accept="image/png,image/jpeg"
            className={styles.hiddenInput}
            onChange={(event) => {
              const fichier = event.target.files?.[0]
              if (fichier) deposer(fichier)
            }}
          />
          <button
            type="button"
            className={styles.primaryBtn}
            onClick={() => inputRef.current?.click()}
            disabled={occupe}
          >
            {occupe ? <Loader2 size={15} className="spin" /> : <Upload size={15} />}
            {logo?.present ? 'Remplacer' : 'Choisir un fichier'}
          </button>
          {logo?.present && (
            <button type="button" className={styles.dangerBtn} onClick={supprimer} disabled={occupe}>
              <Trash2 size={15} />
              Retirer
            </button>
          )}
        </div>
      </div>

      <div className={styles.logoRow}>
        <div className={styles.logoFrame}>
          {apercu ? (
            <img src={apercu} alt="Logo de l’éditeur" className={styles.logoImg} />
          ) : (
            <span className={styles.logoEmpty}>
              <ImageIcon size={18} aria-hidden="true" />
              <br />
              Aucun logo
            </span>
          )}
        </div>
        {logo?.present && (
          <div className={styles.logoMeta}>
            <span className={styles.logoName}>{logo.filename}</span>
            <span>{logo.content_type} · {formatTaille(logo.size)}</span>
            {logo.uploaded_at && (
              <span>Déposé le {new Date(logo.uploaded_at).toLocaleString('fr-FR')}</span>
            )}
          </div>
        )}
      </div>

      {logo?.present && (
        <div className={styles.accentBloc}>
          <div>
            <h4 className={styles.accentTitre}>Couleur de la facture</h4>
            <p className={styles.panelHint}>
              {logo.accent_detecte
                ? 'Tirée du logo au dépôt : elle habille le bandeau de tête, le numéro de facture et les intitulés. Ajustez-la si l’image a livré une teinte de détail plutôt que celle de la marque.'
                : 'Ce logo ne porte pas de couleur franche — un logo gris ou noir n’en donne pas. La facture garde sa teinte par défaut, sauf si vous en choisissez une ici.'}
              {' '}Sur les factures déjà émises, elle n’apparaît qu’à la régénération du PDF.
            </p>
          </div>
          <div className={styles.accentLigne}>
            <input
              type="color"
              className={styles.accentPicker}
              value={accent || '#0F766E'}
              onChange={(event) => setAccent(event.target.value.toUpperCase())}
              disabled={occupe}
              aria-label="Couleur de la facture"
            />
            <code className={styles.accentHex}>{accent || 'par défaut'}</code>
            {accent !== (logo.accent || '') && (
              <button
                type="button"
                className={styles.primaryBtn}
                onClick={() => enregistrerAccent(accent)}
                disabled={occupe}
              >
                {occupe ? <Loader2 size={15} className="spin" /> : null}
                Enregistrer la couleur
              </button>
            )}
            {logo.accent_detecte && logo.accent !== logo.accent_detecte && (
              <button
                type="button"
                className={styles.ghostBtn}
                onClick={() => enregistrerAccent('')}
                disabled={occupe}
                title={`Revenir à ${logo.accent_detecte}`}
              >
                <RotateCcw size={15} />
                Couleur du logo
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
