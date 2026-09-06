/**
 * Identité de l'éditeur imprimée sur les factures.
 *
 * Aucune de ces valeurs n'est codée en dur côté serveur, à l'exception du nom
 * commercial : les mentions légales et bancaires engagent l'entreprise sur des
 * pièces envoyées à de vrais clients, elles se saisissent donc ici. Ce qui est
 * enregistré au moment de l'émission est figé sur la facture : modifier une
 * adresse plus tard ne réécrit pas les pièces déjà émises.
 */

import { useEffect, useState } from 'react'
import { Building2, Loader2, Save } from 'lucide-react'
import { getInvoiceIssuer, updateInvoiceIssuer, type InvoiceIssuer } from '../../api/superAdmin'
import { useNotification } from '../../contexts/NotificationContext'
import styles from './Invoicing.module.css'

const EMPTY: InvoiceIssuer = {
  name: 'Eclectic IT Services',
  tagline: '',
  address: '',
  city: '',
  country: '',
  email: '',
  phone: '',
  website: '',
  rccm: '',
  id_nat: '',
  tax_id: '',
  bank_name: '',
  bank_account: '',
  bank_swift: '',
  mobile_money: '',
  payment_terms_days: 15,
  online_payment_enabled: true,
  manual_payment_enabled: true,
  invoice_prefix: 'EIS',
  footer_note: '',
}

type TextKey = Exclude<keyof InvoiceIssuer, 'payment_terms_days' | 'online_payment_enabled' | 'manual_payment_enabled'>

export default function InvoiceIssuerEditor() {
  const { showSuccess, showError } = useNotification()
  const [issuer, setIssuer] = useState<InvoiceIssuer>(EMPTY)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const res = await getInvoiceIssuer()
        if (active) {
          setIssuer({ ...EMPTY, ...res })
          setDirty(false)
        }
      } catch (err: any) {
        if (active) showError('Chargement impossible', err?.message || 'Identité émetteur illisible.')
      } finally {
        if (active) setLoading(false)
      }
    }
    void load()
    return () => {
      active = false
    }
  }, [showError])

  const patch = (values: Partial<InvoiceIssuer>) => {
    setIssuer((prev) => ({ ...prev, ...values }))
    setDirty(true)
  }

  const text = (key: TextKey, label: string, placeholder = '') => (
    <label className={styles.field}>
      {label}
      <input
        value={issuer[key] ?? ''}
        placeholder={placeholder}
        onChange={(e) => patch({ [key]: e.target.value } as Partial<InvoiceIssuer>)}
      />
    </label>
  )

  const save = async () => {
    if (!issuer.name.trim()) {
      showError('Nom manquant', 'La raison sociale figure sur chaque facture, elle ne peut pas être vide.')
      return
    }
    setSaving(true)
    try {
      const res = await updateInvoiceIssuer(issuer)
      setIssuer({ ...EMPTY, ...res })
      setDirty(false)
      showSuccess('Identité enregistrée', 'Les prochaines factures porteront ces mentions.')
    } catch (err: any) {
      showError('Enregistrement impossible', err?.payload?.detail || err?.message || 'Échec de la sauvegarde.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <div className={styles.empty}>Chargement de l’identité émetteur…</div>
  }

  return (
    <div className={styles.wrap}>
      <div className={styles.section}>
        <div className={styles.sectionHead}>
          <div>
            <h3 className={styles.sectionName}>
              <Building2 size={15} className={styles.sectionIcon} />
              Émetteur des factures
            </h3>
            <p className={styles.sectionHint}>
              Ces mentions s’impriment en tête de chaque facture émise aux tenants.
            </p>
          </div>
          <button
            className={`${styles.iconBtn} ${styles.iconBtnPrimary}`}
            onClick={() => void save()}
            disabled={saving || !dirty}
          >
            {saving ? <Loader2 size={14} className={styles.spin} /> : <Save size={14} />}
            Enregistrer
          </button>
        </div>

        <div className={styles.fieldsetTitle}>Raison sociale</div>
        <div className={styles.grid2}>
          {text('name', 'Nom commercial *', 'Eclectic IT Services')}
          {text('tagline', 'Accroche', 'Édition et hébergement de solutions de gestion')}
          {text('address', 'Adresse', '12, avenue …')}
          {text('city', 'Ville', 'Kinshasa / Gombe')}
          {text('country', 'Pays', 'RD Congo')}
          {text('website', 'Site web', 'https://…')}
          {text('email', 'Email de facturation', 'facturation@…')}
          {text('phone', 'Téléphone', '+243 …')}
        </div>

        <div className={styles.fieldsetTitle}>Mentions légales</div>
        <div className={styles.grid3}>
          {text('rccm', 'RCCM')}
          {text('id_nat', 'Identification nationale')}
          {text('tax_id', 'NIF / Numéro impôt')}
        </div>
        <div className={styles.notice}>
          <span>
            Laissés vides, ces champs n’apparaissent tout simplement pas sur la facture. Aucune valeur
            n’est inventée par la plateforme : renseignez-les avec vos identifiants réels.
          </span>
        </div>

        <div className={styles.fieldsetTitle}>Coordonnées de règlement</div>
        <div className={styles.grid2}>
          {text('bank_name', 'Banque', 'Rawbank')}
          {text('bank_account', 'Numéro de compte / IBAN')}
          {text('bank_swift', 'SWIFT / BIC')}
          {text('mobile_money', 'Mobile money', '+243 … (Airtel Money)')}
        </div>

        <div className={styles.fieldsetTitle}>Voies de règlement annoncées sur la facture</div>
        <div className={styles.grid2}>
          <label className={`${styles.field} ${styles.fieldCheckbox}`}>
            <input
              type="checkbox"
              checked={issuer.online_payment_enabled}
              onChange={(e) => patch({ online_payment_enabled: e.target.checked })}
            />
            Paiement en ligne
          </label>
          <label className={`${styles.field} ${styles.fieldCheckbox}`}>
            <input
              type="checkbox"
              checked={issuer.manual_payment_enabled}
              onChange={(e) => patch({ manual_payment_enabled: e.target.checked })}
            />
            Paiement manuel (virement, mobile money, espèces)
          </label>
        </div>
        <div className={styles.notice}>
          <span>
            Rien n’est imposé : cochez ce que la facture doit annoncer. Les deux — le client choisit.
            Une seule — seule celle-ci apparaît. Aucune — la facture reste muette sur le règlement,
            ce qui se défend quand les modalités vivent dans un contrat signé.{' '}
            <strong>
              Décocher le paiement manuel n’empêche pas de constater un règlement reçu par virement :
              c’est un choix d’affichage, pas une restriction.
            </strong>
          </span>
        </div>

        <div className={styles.fieldsetTitle}>Numérotation et mentions de pied</div>
        <div className={styles.grid3}>
          <label className={styles.field}>
            Préfixe de numéro
            <input
              value={issuer.invoice_prefix}
              maxLength={10}
              onChange={(e) => patch({ invoice_prefix: e.target.value.toUpperCase() })}
            />
          </label>
          <label className={styles.field}>
            Délai de paiement (jours)
            <input
              type="number"
              min={0}
              max={365}
              value={issuer.payment_terms_days}
              onChange={(e) => patch({ payment_terms_days: Number(e.target.value) || 0 })}
            />
          </label>
          {text('footer_note', 'Note de pied de page')}
        </div>
        <div className={styles.notice}>
          <span>
            Les numéros suivent le format <strong>{issuer.invoice_prefix || 'EIS'}-{new Date().getFullYear()}-0001</strong>,
            séquentiels et continus sur l’année civile. Changer le préfixe redémarre une série : les
            factures déjà émises gardent leur numéro.
          </span>
        </div>
      </div>
    </div>
  )
}
