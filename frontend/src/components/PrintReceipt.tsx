import { useState, useEffect, useRef } from 'react'
import { format } from 'date-fns'
import { fr } from 'date-fns/locale'
import { getPrintSettings, PrintSettings } from '../api/settings'
import { numberToWords } from '../utils/numberToWords'
import { getTypeClientLabel } from '../utils/encaissementHelpers'
import { Money, TypeClient } from '../types'
import { toNumber } from '../utils/amount'
import styles from './PrintReceipt.module.css'

interface Encaissement {
  id: string
  numero_recu?: string | null
  numero_proforma?: string | null
  est_proforma?: boolean
  type_client: TypeClient
  expert_comptable_id?: string
  client_nom?: string
  libelle?: string | null
  description?: string | null
  montant: Money
  montant_total: Money
  montant_paye: Money
  budget_poste_code?: string | null
  budget_poste_libelle?: string | null
  montant_percu?: Money
  devise_perception?: 'USD' | 'CDF'
  taux_change_applique?: Money
  statut_paiement: 'non_paye' | 'partiel' | 'complet' | 'avance'
  mode_paiement: string
  reference?: string
  date_encaissement: string
  date_paiement?: string | null
  created_at: string
  expert_comptable?: {
    numero_ordre: string
    nom_denomination: string
  }
  articles?: Array<{
    libelle: string
    quantite?: Money
    prix_unitaire?: Money
    montant: Money
  }>
}

interface PrintReceiptProps {
  encaissement: Encaissement
  onClose: () => void
  autoPrint?: boolean
}

type PaperSize = 'A4' | 'A5'

export default function PrintReceipt({ encaissement, onClose, autoPrint = false }: PrintReceiptProps) {
  const [paperSize, setPaperSize] = useState<PaperSize>('A5')
  const [compactHeader, setCompactHeader] = useState(false)
  const [settings, setSettings] = useState<PrintSettings | null>(null)
  const [isDuplicate, setIsDuplicate] = useState(false)
  const [isPrinting, setIsPrinting] = useState(false)
  const [showDuplicateBtn, setShowDuplicateBtn] = useState(false)
  const [hasPrintedOriginal, setHasPrintedOriginal] = useState(false)
  const [autoPrinted, setAutoPrinted] = useState(false)
  const receiptRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    loadSettings()
  }, [])

  useEffect(() => {
    if (!autoPrint || !settings || autoPrinted || isPrinting) return
    setAutoPrinted(true)
    handlePrint()
  }, [autoPrint, settings, autoPrinted, isPrinting])

  useEffect(() => {
    const root = document.documentElement
    root.classList.remove('printing', 'print-a4', 'print-a5', 'print-duplicate', 'print-compact-header')
    const styleEl = document.getElementById('print-page-size')
    if (styleEl?.parentNode) {
      styleEl.parentNode.removeChild(styleEl)
    }
    return () => {
      root.classList.remove('printing', 'print-a4', 'print-a5', 'print-duplicate', 'print-compact-header')
      const styleOnUnmount = document.getElementById('print-page-size')
      if (styleOnUnmount?.parentNode) {
        styleOnUnmount.parentNode.removeChild(styleOnUnmount)
      }
    }
  }, [])

  useEffect(() => {
    const docKey = encaissement.est_proforma
      ? encaissement.numero_proforma || encaissement.id
      : encaissement.numero_recu || encaissement.id
    const countKey = `print_count:${docKey}`
    const currentCount = Number(window.localStorage.getItem(countKey) || '0')
    setShowDuplicateBtn(currentCount >= 1)
    setHasPrintedOriginal(currentCount >= 1)
    setIsDuplicate(false)
  }, [encaissement.numero_recu, encaissement.numero_proforma, encaissement.id, encaissement.est_proforma])

  const loadSettings = async () => {
    try {
      const data = await getPrintSettings()
      setSettings(data)
      setPaperSize('A5')
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
      const docKey = encaissement.est_proforma
        ? encaissement.numero_proforma || encaissement.id
        : encaissement.numero_recu || encaissement.id
      const countKey = `print_count:${docKey}`
      const currentCount = Number(window.localStorage.getItem(countKey) || '0')
      const nextCount = currentCount + 1
      const duplicate = forceDuplicate ? true : false
      const persistedCount = nextCount
      setIsDuplicate(duplicate)
      window.localStorage.setItem(countKey, String(persistedCount))
      if (persistedCount >= 1) {
        setShowDuplicateBtn(true)
        setHasPrintedOriginal(true)
      }
      const root = document.documentElement
      const styleId = 'print-page-size'
      let styleEl = document.getElementById(styleId) as HTMLStyleElement | null
      if (!styleEl) {
        styleEl = document.createElement('style')
        styleEl.id = styleId
        document.head.appendChild(styleEl)
      }
      styleEl.textContent = `@page { size: ${printFormat}; margin: 5mm; }`
      let fallbackTimer: number | null = null
      const mediaQuery = window.matchMedia ? window.matchMedia('print') : null
      const cleanup = () => {
        root.classList.remove('printing', 'print-a4', 'print-a5', 'print-duplicate', 'print-compact-header')
        if (styleEl?.parentNode) {
          styleEl.parentNode.removeChild(styleEl)
        }
        if (fallbackTimer) {
          window.clearTimeout(fallbackTimer)
        }
        if (mediaQuery) {
          mediaQuery.removeEventListener('change', onPrintChange)
        }
        window.removeEventListener('afterprint', cleanup)
        setIsPrinting(false)
        onClose()
      }
      const onPrintChange = (event: MediaQueryListEvent) => {
        if (!event.matches) cleanup()
      }

      root.classList.add('printing')
      root.classList.add(printFormat === 'A4' ? 'print-a4' : 'print-a5')
      if (duplicate) root.classList.add('print-duplicate')
      if (compactHeader) root.classList.add('print-compact-header')

      window.addEventListener('afterprint', cleanup)
      if (mediaQuery) {
        mediaQuery.addEventListener('change', onPrintChange)
      }
      fallbackTimer = window.setTimeout(cleanup, 30000)
      setTimeout(() => {
        window.print()
      }, 50)
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
    bank_transfer: 'Opération bancaire',
    mobile_money: 'Mobile Money',
    card: 'Carte (Visa)',
    virement: 'Opération bancaire',
  }

  const statutsLabels: Record<string, string> = {
    non_paye: 'Non payé',
    partiel: 'Paiement partiel',
    complet: 'Payé en totalité',
    avance: 'Avance',
  }

  const isProforma = !!encaissement.est_proforma
  const totalMontant = toNumber(encaissement.montant_total)
  const montantPaye = toNumber(encaissement.montant_paye)
  const soldeRestant = totalMontant - montantPaye
  const montantPercu = toNumber(encaissement.montant_percu || 0)
  const articles = Array.isArray(encaissement.articles) && encaissement.articles.length > 0
    ? encaissement.articles
    : [{ libelle: encaissement.libelle || 'Encaissement', quantite: 1, prix_unitaire: totalMontant, montant: totalMontant }]
  const devisePercu = (encaissement.devise_perception || 'USD').toUpperCase()
  const docNumero = isProforma ? encaissement.numero_proforma : encaissement.numero_recu
  const datePaiement = encaissement.date_paiement || encaissement.date_encaissement
  const dateLabel = isProforma ? "Date d'émission" : 'Date de paiement'
  const infoLeft: [string, string][] = [
    [dateLabel, format(new Date(datePaiement), 'dd MMMM yyyy', { locale: fr })],
    ['Reçu de', clientName],
    ['Identification', clientInfo],
    ['Type de client', getTypeClientLabel(encaissement.type_client)],
  ]
  const infoRight: [string, string][] = [
    [
      'Poste budgétaire',
      encaissement.budget_poste_code
        ? `${encaissement.budget_poste_code} ${encaissement.budget_poste_libelle ? `- ${encaissement.budget_poste_libelle}` : ''}`.trim()
        : '—',
    ],
    ['Libellé', encaissement.libelle || '—'],
    ['Mode de paiement', modesPaiement[encaissement.mode_paiement] || encaissement.mode_paiement],
  ]
  if (encaissement.description) {
    infoRight.push(['Description', encaissement.description])
  }
  if (encaissement.reference) {
    infoRight.push(['Référence', encaissement.reference])
  }
  if (devisePercu === 'CDF') {
    infoRight.push(['Devise perçue', `${montantPercu.toFixed(0)} CDF`])
  }
  const maxInfoRows = Math.max(infoLeft.length, infoRight.length)
  const infoRows = Array.from({ length: maxInfoRows }).map((_, idx) => {
    const left = infoLeft[idx] || ['', '']
    const right = infoRight[idx] || ['', '']
    return [left[0], left[1], right[0], right[1]]
  })

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
            <div className={styles.formatHint}>
              Le format sélectionné sera appliqué à l'impression.
            </div>
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
              Imprimer / Enregistrer PDF
            </button>
            {showDuplicateBtn && (
              <button onClick={handlePrintDuplicate} className={styles.duplicateBtn}>
                Imprimer duplicata
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
          <div id="print-root">
            {Array.from({ length: isProforma ? 1 : 3 }).map((_, copyIndex) => (
            <div
              key={`receipt-copy-${copyIndex}`}
              id={copyIndex === 0 ? 'receipt-root' : undefined}
              data-duplicate={isDuplicate ? 'true' : 'false'}
              data-format={paperSize}
              ref={copyIndex === 0 ? receiptRef : undefined}
              className={`${styles.printCopy} ${styles.receiptRoot} ${styles.receipt} ${paperSize === 'A4' ? styles.paperA4 : styles.paperA5} ${compactHeader ? styles.compactHeader : ''}`}
            >
              <div className={styles.watermark}>DUPLICATA</div>
              {isProforma && <div className={styles.proformaWatermark}>PROFORMA</div>}

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
                <h1 className={styles.orgName}>ORDRE NATIONAL DES EXPERTS-COMPTABLES</h1>
                <p className={styles.orgSubtitle}>
                  {settings.organization_name || 'Conseil Provincial de Kinshasa'}
                </p>
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
              <h2>{isProforma ? 'FACTURE PROFORMA' : 'REÇU DE PAIEMENT'}</h2>
              <div className={styles.receiptNumber}>N° {docNumero || '—'}</div>
              {isProforma && <div className={styles.proformaHint}>Document non comptable</div>}
            </div>

            <table className={styles.infoTable}>
              <tbody>
                {infoRows.map((row, idx) => (
                  <tr key={`info-${idx}`}>
                    <td className={styles.labelCell}>{row[0]}</td>
                    <td className={styles.valueCell}>{row[1]}</td>
                    <td className={styles.labelCell}>{row[2]}</td>
                    <td className={styles.valueCell}>{row[3]}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <table className={styles.infoTable}>
              <thead>
                <tr>
                  <td className={styles.labelCell}>Article</td>
                  <td className={styles.labelCell}>Qté</td>
                  <td className={styles.labelCell}>Prix unitaire</td>
                  <td className={styles.labelCell}>Montant</td>
                </tr>
              </thead>
              <tbody>
                {articles.map((article, idx) => (
                  <tr key={`article-${idx}`}>
                    <td className={styles.valueCell}>{article.libelle}</td>
                    <td className={styles.valueCell}>{toNumber(article.quantite || 1).toLocaleString()}</td>
                    <td className={styles.valueCell}>{formatCurrency(article.prix_unitaire || article.montant)} USD</td>
                    <td className={styles.valueCell}>{formatCurrency(article.montant)} USD</td>
                  </tr>
                ))}
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
                    <td className={styles.amountLabel}>{isProforma ? 'Montant à payer' : 'Montant payé'}</td>
                    <td className={styles.amountValue}><strong>{formatCurrency(isProforma ? totalMontant : montantPaye)} USD</strong></td>
                  </tr>
                  {devisePercu === 'CDF' && (
                    <>
                      <tr>
                        <td className={styles.amountLabel}>Montant perçu (CDF)</td>
                        <td className={styles.amountValue}>{formatCurrency(montantPercu)} CDF</td>
                      </tr>
                      <tr>
                        <td className={styles.amountLabel}>Équivalent USD</td>
                        <td className={styles.amountValue}>{formatCurrency(totalMontant)} USD</td>
                      </tr>
                    </>
                  )}
                  <tr>
                    <td colSpan={2} className={styles.amountWords}>
                      {numberToWords(isProforma ? totalMontant : montantPaye)}
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
              <span className={styles.footerNote}>Document généré automatiquement par l’application développée par ck (kidikala@gmail.com)</span>
            </div>

            <div className={`${styles.printFooter} ${styles.printFooterNoFixed}`}>
              <div className={styles.printFooterLeft}>
                {format(new Date(), 'dd/MM/yyyy HH:mm')}
              </div>
              <div className={styles.printFooterCenter}>
                {isProforma ? 'Proforma - ONEC/CPK' : 'Reçu de paiement - ONEC/CPK'}
              </div>
              <div className={styles.printFooterRight}>
                Page 1/1
              </div>
            </div>
            </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
