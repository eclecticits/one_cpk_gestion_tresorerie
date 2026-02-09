import { useState, useEffect, useRef } from 'react'
import { format } from 'date-fns'
import { fr } from 'date-fns/locale'
import { getPrintSettings, PrintSettings } from '../api/settings'
import { numberToWords } from '../utils/numberToWords'
import { getOperationLabel, getTypeClientLabel } from '../utils/encaissementHelpers'
import { Money, TypeClient } from '../types'
import { toNumber } from '../utils/amount'
import { generateReceiptPDF } from '../utils/pdfGenerator'
import styles from './PrintReceipt.module.css'

interface Encaissement {
  id: string
  numero_recu: string
  type_client: TypeClient
  expert_comptable_id?: string
  client_nom?: string
  type_operation: string
  description?: string | null
  montant: Money
  montant_total: Money
  montant_paye: Money
  statut_paiement: 'non_paye' | 'partiel' | 'complet' | 'avance'
  mode_paiement: string
  reference?: string
  date_encaissement: string
  created_at: string
  expert_comptable?: {
    numero_ordre: string
    nom_denomination: string
  }
}

interface PrintReceiptProps {
  encaissement: Encaissement
  onClose: () => void
}

type PaperSize = 'A4' | 'A5'

export default function PrintReceipt({ encaissement, onClose }: PrintReceiptProps) {
  const [paperSize, setPaperSize] = useState<PaperSize>('A5')
  const [compactHeader, setCompactHeader] = useState(false)
  const [settings, setSettings] = useState<PrintSettings | null>(null)
  const [isDuplicate, setIsDuplicate] = useState(false)
  const [isPrinting, setIsPrinting] = useState(false)
  const [showDuplicateBtn, setShowDuplicateBtn] = useState(false)
  const [hasPrintedOriginal, setHasPrintedOriginal] = useState(false)
  const receiptRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    loadSettings()
  }, [])

  useEffect(() => {
    const countKey = `print_count:${encaissement.numero_recu}`
    const currentCount = Number(window.localStorage.getItem(countKey) || '0')
    setShowDuplicateBtn(currentCount >= 1)
    setHasPrintedOriginal(currentCount >= 1)
    setIsDuplicate(false)
  }, [encaissement.numero_recu])

  const loadSettings = async () => {
    try {
      const data = await getPrintSettings()
      setSettings(data)
      if (data?.paper_format === 'A4' || data?.paper_format === 'A5') {
        setPaperSize(data.paper_format as PaperSize)
      }
      setCompactHeader(!!data?.compact_header)
    } catch (error) {
      console.error('Error loading print settings:', error)
    }
  }

  const formatCurrency = (amount: Money) => {
    return new Intl.NumberFormat('fr-FR', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(toNumber(amount))
  }

  const safePrint = async (forceDuplicate: boolean, printFormat: PaperSize, _compact: boolean) => {
    if (isPrinting) return
    try {
      setIsPrinting(true)
      const countKey = `print_count:${encaissement.numero_recu}`
      const currentCount = Number(window.localStorage.getItem(countKey) || '0')
      const nextCount = currentCount + 1
      const duplicate = forceDuplicate ? true : currentCount >= 1
      const persistedCount = forceDuplicate ? Math.max(nextCount, 2) : nextCount
      setIsDuplicate(duplicate)
      window.localStorage.setItem(countKey, String(persistedCount))
      if (persistedCount >= 1) {
        setShowDuplicateBtn(true)
        setHasPrintedOriginal(true)
      }

      await generateReceiptPDF(encaissement, {
        format: printFormat === 'A4' ? 'a4' : 'a5',
        duplicate,
        compactHeader,
        settings,
      })
      setIsPrinting(false)
    } catch (error) {
      console.error('Print error:', error)
      setIsPrinting(false)
    }
  }

  const handlePrint = () => safePrint(false, paperSize, compactHeader)
  const handlePrintDuplicate = () => safePrint(true, paperSize, compactHeader)

  const clientName = encaissement.expert_comptable
    ? encaissement.expert_comptable.nom_denomination
    : encaissement.client_nom || 'N/A'

  const clientInfo = encaissement.expert_comptable
    ? `N° Ordre: ${encaissement.expert_comptable.numero_ordre}`
    : 'Autre client'

  const modesPaiement: Record<string, string> = {
    cash: 'Espèces',
    check: 'Chèque',
    bank_transfer: 'Virement bancaire',
    mobile_money: 'Mobile Money',
  }

  const statutsLabels: Record<string, string> = {
    non_paye: 'Non payé',
    partiel: 'Paiement partiel',
    complet: 'Payé en totalité',
    avance: 'Avance',
  }

  const totalMontant = toNumber(encaissement.montant_total)
  const montantPaye = toNumber(encaissement.montant_paye)
  const soldeRestant = totalMontant - montantPaye

  if (!settings) {
    return (
      <div className={styles.overlay}>
        <div className={styles.modal}>
          <div className={styles.toolbar}>
            <p>Chargement des paramètres...</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className={styles.overlay}>
      <div className={styles.modal}>
        <div className={`${styles.toolbar} ${styles.noPrint}`}>
          <h3>Aperçu avant impression</h3>

          <div className={styles.formatSelector}>
            <label>Format:</label>
            <select value={paperSize} onChange={(e) => setPaperSize(e.target.value as PaperSize)}>
              <option value="A4">A4 (210 × 297 mm)</option>
              <option value="A5">A5 (148 × 210 mm)</option>
            </select>
          </div>
          <div className={styles.formatSelector}>
            <label>En-tête compact:</label>
            <select value={compactHeader ? 'yes' : 'no'} onChange={(e) => setCompactHeader(e.target.value === 'yes')}>
              <option value="no">Non</option>
              <option value="yes">Oui</option>
            </select>
          </div>

          <div className={styles.actions}>
            <button onClick={handlePrint} className={styles.printBtn} disabled={hasPrintedOriginal}>
              Générer PDF
            </button>
            {showDuplicateBtn && (
              <button onClick={handlePrintDuplicate} className={styles.duplicateBtn}>
                Générer duplicata
              </button>
            )}
            <button onClick={onClose} className={styles.closeBtn}>
              Fermer
            </button>
          </div>
          {hasPrintedOriginal && (
            <div className={styles.printNotice}>
              L'original a déjà été généré. Utilisez "Générer duplicata".
            </div>
          )}
        </div>

        <div className={styles.preview}>
          <div
            id="receipt-root"
            data-duplicate={isDuplicate ? 'true' : 'false'}
            data-format={paperSize}
            ref={receiptRef}
            className={`${styles.receiptRoot} ${styles.receipt} ${paperSize === 'A4' ? styles.paperA4 : styles.paperA5} ${compactHeader ? styles.compactHeader : ''}`}
          >
            <div className={styles.watermark}>DUPLICATA</div>

            <div className={styles.headerSection}>
              <div className={styles.headerLeft}>
                {settings.show_header_logo && (
                  <img
                    src={settings.logo_url || '/imge_onec.png'}
                    alt="Logo"
                    className={styles.headerLogo}
                  />
                )}
              </div>
              <div className={styles.headerRight}>
                <h1 className={styles.orgName}>{settings.organization_name}</h1>
                <p className={styles.orgSubtitle}>Conseil Provincial de Kinshasa</p>
                <p className={styles.orgExtra}>{settings.organization_subtitle}</p>
                {settings.header_text && <p className={styles.orgExtra}>{settings.header_text}</p>}

                {(settings.address || settings.phone || settings.email) && (
                  <div className={styles.headerContact}>
                    {settings.address && <div>{settings.address}</div>}
                    {settings.phone && <div>Tél: {settings.phone}</div>}
                    {settings.email && <div>Email: {settings.email}</div>}
                  </div>
                )}
              </div>
            </div>

            <div className={styles.documentTitle}>
              <h2>REÇU DE PAIEMENT</h2>
              <div className={styles.receiptNumber}>N° {encaissement.numero_recu}</div>
            </div>

            <table className={styles.infoTable}>
              <tbody>
                <tr>
                  <td className={styles.labelCell}>Date d'encaissement</td>
                  <td className={styles.valueCell}>
                    {format(new Date(encaissement.date_encaissement), 'dd MMMM yyyy', { locale: fr })}
                  </td>
                </tr>
                <tr>
                  <td className={styles.labelCell}>Reçu de</td>
                  <td className={styles.valueCell}><strong>{clientName}</strong></td>
                </tr>
                <tr>
                  <td className={styles.labelCell}>Identification</td>
                  <td className={styles.valueCell}>{clientInfo}</td>
                </tr>
                <tr>
                  <td className={styles.labelCell}>Type de client</td>
                  <td className={styles.valueCell}>{getTypeClientLabel(encaissement.type_client)}</td>
                </tr>
                <tr>
                  <td className={styles.labelCell}>Type d'opération</td>
                  <td className={styles.valueCell}>{getOperationLabel(encaissement.type_operation as any)}</td>
                </tr>
                {encaissement.description && (
                  <tr>
                    <td className={styles.labelCell}>Description</td>
                    <td className={styles.valueCell}>{encaissement.description}</td>
                  </tr>
                )}
                <tr>
                  <td className={styles.labelCell}>Mode de paiement</td>
                  <td className={styles.valueCell}>{modesPaiement[encaissement.mode_paiement]}</td>
                </tr>
                {encaissement.reference && (
                  <tr>
                    <td className={styles.labelCell}>Référence</td>
                    <td className={styles.valueCell}>{encaissement.reference}</td>
                  </tr>
                )}
              </tbody>
            </table>

            <div className={styles.paymentDetails}>
              <table className={styles.amountTable}>
                <tbody>
                  <tr>
                    <td className={styles.amountLabel}>Montant dû</td>
                    <td className={styles.amountValue}>{formatCurrency(totalMontant)} USD</td>
                  </tr>
                  <tr>
                    <td colSpan={2} className={styles.amountWords}>
                      {numberToWords(totalMontant)}
                    </td>
                  </tr>
                  <tr className={styles.highlightRow}>
                    <td className={styles.amountLabel}>Montant payé</td>
                    <td className={styles.amountValue}><strong>{formatCurrency(montantPaye)} USD</strong></td>
                  </tr>
                  <tr>
                    <td colSpan={2} className={styles.amountWords}>
                      {numberToWords(montantPaye)}
                    </td>
                  </tr>
                  {soldeRestant > 0 && (
                    <>
                      <tr>
                        <td className={styles.amountLabel}>Solde restant</td>
                        <td className={styles.amountValue}>{formatCurrency(soldeRestant)} USD</td>
                      </tr>
                      <tr>
                        <td colSpan={2} className={styles.amountWords}>
                          {numberToWords(soldeRestant)}
                        </td>
                      </tr>
                    </>
                  )}
                  <tr>
                    <td className={styles.amountLabel}>Statut</td>
                    <td className={styles.amountValue}>
                      <span className={`${styles.statutBadge} ${styles[encaissement.statut_paiement]}`}>
                        {statutsLabels[encaissement.statut_paiement]}
                      </span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            {settings.show_footer_signature && (
              <div className={styles.signatureSection}>
                <div className={styles.signatureBox}>
                  {settings.stamp_url && (
                    <img src={settings.stamp_url} alt="Cachet" className={styles.stampImage} />
                  )}
                  <div className={styles.signatureMeta}>
                    <p>{settings.recu_label_signature || 'Cachet & signature'}</p>
                    {settings.recu_nom_signataire && <div className={styles.signatureName}>{settings.recu_nom_signataire}</div>}
                  </div>
                </div>
              </div>
            )}

            <div className={styles.footerSection}>
              <p>{settings.pied_de_page_legal}</p>
              <span className={styles.footerNote}>Document généré automatiquement</span>
            </div>

            <div className={`${styles.printFooter} ${styles.printFooterNoFixed}`}>
              <div className={styles.printFooterLeft}>
                {format(new Date(), 'dd/MM/yyyy HH:mm')}
              </div>
              <div className={styles.printFooterCenter}>
                Reçu de paiement - ONEC/CPK
              </div>
              <div className={styles.printFooterRight}>
                Page 1/1
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
