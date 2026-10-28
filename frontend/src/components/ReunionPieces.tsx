import { useEffect, useRef, useState } from 'react'
import { format } from 'date-fns'
import { ArrowLeft, ArrowRight, Camera, Eye, FileUp, Trash2, X } from 'lucide-react'
import type { PieceReunion, PieceReunionKind } from '../api/remboursementsTransport'
import { useConfirm } from '../contexts/ConfirmContext'
import { openAuthenticatedFile } from '../utils/download'
import styles from './ReunionPieces.module.css'

const PIECES: { kind: PieceReunionKind; titre: string; aide: string; nomFichier: string }[] = [
  {
    kind: 'liste_presence',
    titre: 'Liste de présence signée',
    aide: 'Imprimée avant la séance, remplie et signée par les présents, puis scannée ou photographiée page par page.',
    nomFichier: 'liste-presence-signee',
  },
  {
    kind: 'pv',
    titre: 'Procès-verbal (facultatif)',
    aide: 'Le PV signé de la séance, s’il est déjà disponible.',
    nomFichier: 'proces-verbal',
  },
]

type Props = {
  pieces: Partial<Record<PieceReunionKind, Omit<PieceReunion, 'file_path'> | null>>
  // Envoie le document assemblé là où il doit aller (brouillon ou réquisition
  // d'un remboursement existant) ; false si le dépôt n'a pas pu avoir lieu.
  onDeposer: (kind: PieceReunionKind, file: Blob, filename: string) => Promise<boolean>
  // Chemin de consultation de la pièce déposée, s'il y en a un.
  voirPath?: (kind: PieceReunionKind) => string | null
  // Absent : une pièce déposée ne se retire pas, elle se remplace.
  onRetirer?: (kind: PieceReunionKind) => Promise<void>
  confirmationDepot?: string
  onMessage: (type: 'success' | 'error', message: string) => void
  disabled?: boolean
  canUpload?: boolean
}

type PageEnAttente = { file: File; url: string }
const MAX_PHOTO_PAGES = 20
const MAX_PHOTO_SOURCE_BYTES = 60 * 1024 * 1024

export default function ReunionPieces({
  pieces,
  onDeposer,
  voirPath,
  onRetirer,
  confirmationDepot = 'Elle sera jointe à la réquisition à la création du remboursement.',
  onMessage,
  disabled,
  canUpload = true,
}: Props) {
  // Photos prises une à une au téléphone : elles s'accumulent ici, dans
  // l'ordre des pages, avant d'être réunies en un seul PDF.
  const [attente, setAttente] = useState<Partial<Record<PieceReunionKind, PageEnAttente[]>>>({})
  const [enCours, setEnCours] = useState<PieceReunionKind | null>(null)
  const confirm = useConfirm()
  const photoInputs = useRef<Partial<Record<PieceReunionKind, HTMLInputElement | null>>>({})
  const fileInputs = useRef<Partial<Record<PieceReunionKind, HTMLInputElement | null>>>({})
  const attenteRef = useRef(attente)
  attenteRef.current = attente

  useEffect(
    () => () => {
      Object.values(attenteRef.current).forEach((pages) => pages?.forEach((p) => URL.revokeObjectURL(p.url)))
    },
    [],
  )

  const viderAttente = (kind: PieceReunionKind) => {
    attente[kind]?.forEach((p) => URL.revokeObjectURL(p.url))
    setAttente((prev) => ({ ...prev, [kind]: [] }))
  }

  const deposer = async (kind: PieceReunionKind, files: File[]) => {
    const def = PIECES.find((p) => p.kind === kind)!
    setEnCours(kind)
    try {
      const { preparerScan } = await import('../utils/scanToPdf')
      const scan = await preparerScan(files, def.nomFichier)
      if (!(await onDeposer(kind, scan.blob, scan.filename))) return
      viderAttente(kind)
      onMessage('success', `${def.titre} déposée${scan.pages > 1 ? ` (${scan.pages} pages)` : ''}. ${confirmationDepot}`)
    } catch (error: any) {
      onMessage('error', error?.message || 'Dépôt impossible.')
    } finally {
      setEnCours(null)
    }
  }

  const choisirFichiers = (kind: PieceReunionKind, list: FileList | null) => {
    const files = Array.from(list || [])
    if (!files.length) return
    // Un PDF part directement ; des photos rejoignent les pages en attente.
    if (files.some((f) => f.type === 'application/pdf')) {
      void deposer(kind, files)
      return
    }
    ajouterPages(kind, files)
  }

  const ajouterPages = (kind: PieceReunionKind, files: File[]) => {
    const existantes = attente[kind] || []
    if (existantes.length + files.length > MAX_PHOTO_PAGES) {
      onMessage('error', `Maximum ${MAX_PHOTO_PAGES} pages par document.`)
      return
    }
    const octets = [...existantes.map((p) => p.file), ...files].reduce((total, file) => total + file.size, 0)
    if (octets > MAX_PHOTO_SOURCE_BYTES) {
      onMessage('error', 'Les photos sélectionnées sont trop volumineuses. Réduisez leur nombre ou leur résolution.')
      return
    }
    const pages = files.map((file) => ({ file, url: URL.createObjectURL(file) }))
    setAttente((prev) => ({ ...prev, [kind]: [...(prev[kind] || []), ...pages] }))
  }

  const deplacerPage = (kind: PieceReunionKind, index: number, delta: number) => {
    setAttente((prev) => {
      const pages = [...(prev[kind] || [])]
      const cible = index + delta
      if (cible < 0 || cible >= pages.length) return prev
      ;[pages[index], pages[cible]] = [pages[cible], pages[index]]
      return { ...prev, [kind]: pages }
    })
  }

  const retirerPage = (kind: PieceReunionKind, index: number) => {
    setAttente((prev) => {
      const pages = [...(prev[kind] || [])]
      const [page] = pages.splice(index, 1)
      if (page) URL.revokeObjectURL(page.url)
      return { ...prev, [kind]: pages }
    })
  }

  const retirer = async (kind: PieceReunionKind) => {
    if (!onRetirer) return
    const def = PIECES.find((piece) => piece.kind === kind)!
    const ok = await confirm({
      title: 'Retirer cette pièce ?',
      description: `${def.titre} sera supprimée du brouillon et du stockage.`,
      confirmText: 'Retirer',
      variant: 'danger',
    })
    if (!ok) return
    setEnCours(kind)
    try {
      await onRetirer(kind)
    } catch (error: any) {
      onMessage('error', error?.message || 'Retrait impossible.')
    } finally {
      setEnCours(null)
    }
  }

  return (
    <div className={styles.grid}>
      {PIECES.map((def) => {
        const piece = pieces[def.kind]
        const pages = attente[def.kind] || []
        const occupe = disabled || enCours !== null
        const titreId = `piece-${def.kind}-titre`
        return (
          <section key={def.kind} className={styles.card} aria-labelledby={titreId}>
            <div className={styles.head}>
              <h4 id={titreId}>{def.titre}</h4>
              {piece ? (
                <span className={`${styles.badge} ${styles.badgeOk}`}>
                  {piece.version ? `Version ${piece.version} courante` : 'Déposée'}
                </span>
              ) : def.kind === 'liste_presence' ? (
                <span className={`${styles.badge} ${styles.badgeWarn}`}>À déposer</span>
              ) : null}
            </div>

            {piece ? (
              <p className={styles.meta}>
                {piece.deposee_le ? format(new Date(piece.deposee_le), "dd/MM/yyyy 'à' HH:mm") : 'Déposée'}
                {piece.deposee_par ? ` par ${piece.deposee_par}` : ''} · {Math.max(1, Math.round(piece.file_size / 1024))} Ko
                {piece.version ? ` · version ${piece.version}` : ''}
              </p>
            ) : (
              <p className={styles.aide}>{def.aide}</p>
            )}

            {pages.length > 0 && (
              <div className={styles.tray}>
                <ol className={styles.thumbs} aria-label="Pages en attente">
                  {pages.map((p, i) => (
                    <li key={p.url} className={styles.thumb}>
                      <img src={p.url} alt={`Page ${i + 1}`} />
                      <span className={styles.pageNo}>{i + 1}</span>
                      <div className={styles.thumbActions}>
                        <button type="button" onClick={() => deplacerPage(def.kind, i, -1)} disabled={i === 0 || occupe} aria-label={`Avancer la page ${i + 1}`}>
                          <ArrowLeft size={13} aria-hidden="true" />
                        </button>
                        <button type="button" onClick={() => retirerPage(def.kind, i)} disabled={occupe} aria-label={`Retirer la page ${i + 1}`}>
                          <X size={13} aria-hidden="true" />
                        </button>
                        <button type="button" onClick={() => deplacerPage(def.kind, i, 1)} disabled={i === pages.length - 1 || occupe} aria-label={`Reculer la page ${i + 1}`}>
                          <ArrowRight size={13} aria-hidden="true" />
                        </button>
                      </div>
                    </li>
                  ))}
                </ol>
                <div className={styles.actions}>
                  <button type="button" className={styles.primary} onClick={() => deposer(def.kind, pages.map((p) => p.file))} disabled={occupe}>
                    {enCours === def.kind ? 'Assemblage…' : `Assembler et déposer (${pages.length} page${pages.length > 1 ? 's' : ''})`}
                  </button>
                  <button type="button" className={styles.ghost} onClick={() => viderAttente(def.kind)} disabled={occupe}>
                    Annuler
                  </button>
                </div>
              </div>
            )}

            <div className={styles.actions}>
              {canUpload && (
                <>
                  <button type="button" className={styles.secondary} onClick={() => photoInputs.current[def.kind]?.click()} disabled={occupe}>
                    <Camera size={15} aria-hidden="true" /> {pages.length ? 'Page suivante' : 'Photographier'}
                  </button>
                  <button type="button" className={styles.secondary} onClick={() => fileInputs.current[def.kind]?.click()} disabled={occupe}>
                    <FileUp size={15} aria-hidden="true" /> {piece ? 'Ajouter une version' : 'Importer un scan'}
                  </button>
                </>
              )}
              {piece && voirPath?.(def.kind) && (
                <button
                  type="button"
                  className={styles.ghost}
                  onClick={() => openAuthenticatedFile(voirPath(def.kind)!).catch(() => onMessage('error', 'Ouverture impossible.'))}
                >
                  <Eye size={15} aria-hidden="true" /> Voir
                </button>
              )}
              {piece && onRetirer && (
                <button type="button" className={styles.ghost} onClick={() => retirer(def.kind)} disabled={occupe}>
                  <Trash2 size={15} aria-hidden="true" /> Retirer
                </button>
              )}
              {enCours === def.kind && !pages.length && <span className={styles.meta} role="status">Dépôt en cours…</span>}
            </div>

            <input
              ref={(el) => { photoInputs.current[def.kind] = el }}
              type="file"
              accept="image/*"
              capture="environment"
              hidden
              onChange={(e) => { ajouterPages(def.kind, Array.from(e.target.files || [])); e.target.value = '' }}
            />
            <input
              ref={(el) => { fileInputs.current[def.kind] = el }}
              type="file"
              accept="application/pdf,image/jpeg,image/png"
              multiple
              hidden
              onChange={(e) => { choisirFichiers(def.kind, e.target.files); e.target.value = '' }}
            />
          </section>
        )
      })}
    </div>
  )
}
