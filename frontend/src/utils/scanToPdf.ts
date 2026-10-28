import jsPDF from 'jspdf'

// Les annexes de réquisition partent en pièces jointes des e-mails du Bureau :
// même plafond côté serveur.
export const MAX_PIECE_BYTES = 3 * 1024 * 1024
export const MAX_SCAN_PAGES = 20
export const MAX_SCAN_SOURCE_BYTES = 60 * 1024 * 1024

const IMAGE_TYPES = ['image/jpeg', 'image/jpg', 'image/png']

export type ScanAssemble = { blob: Blob; filename: string; pages: number }

async function chargerImage(file: File): Promise<HTMLImageElement> {
  const url = URL.createObjectURL(file)
  try {
    const img = new Image()
    img.src = url
    await img.decode()
    return img
  } finally {
    // L'image décodée garde ses pixels ; l'URL n'est plus utile.
    setTimeout(() => URL.revokeObjectURL(url), 0)
  }
}

function versJpeg(img: HTMLImageElement, coteMax: number, qualite: number): { data: string; w: number; h: number } {
  const ratio = Math.min(1, coteMax / Math.max(img.naturalWidth, img.naturalHeight))
  const w = Math.max(1, Math.round(img.naturalWidth * ratio))
  const h = Math.max(1, Math.round(img.naturalHeight * ratio))
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Navigateur incapable de traiter l’image.')
  // Fond blanc : un PNG transparent deviendrait noir en JPEG.
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, w, h)
  ctx.drawImage(img, 0, 0, w, h)
  return { data: canvas.toDataURL('image/jpeg', qualite), w, h }
}

function assembler(images: HTMLImageElement[], coteMax: number, qualite: number): Blob {
  const doc = new jsPDF({ unit: 'mm', format: 'a4', compress: true })
  const pageW = doc.internal.pageSize.getWidth()
  const pageH = doc.internal.pageSize.getHeight()
  const marge = 5
  images.forEach((img, i) => {
    const { data, w, h } = versJpeg(img, coteMax, qualite)
    const paysage = w > h
    if (i > 0) doc.addPage('a4', paysage ? 'landscape' : 'portrait')
    else if (paysage) {
      doc.deletePage(1)
      doc.addPage('a4', 'landscape')
    }
    const pw = paysage ? pageH : pageW
    const ph = paysage ? pageW : pageH
    const echelle = Math.min((pw - 2 * marge) / w, (ph - 2 * marge) / h)
    const dw = w * echelle
    const dh = h * echelle
    doc.addImage(data, 'JPEG', (pw - dw) / 2, (ph - dh) / 2, dw, dh)
  })
  return doc.output('blob')
}

/**
 * Prépare le scan d'une pièce signée pour le dépôt.
 *
 * - un PDF (sortie de scanner) passe tel quel ;
 * - une ou plusieurs photos (téléphone) sont réduites et réunies en un seul
 *   PDF, une page par photo, dans l'ordre choisi ; on resserre la qualité
 *   jusqu'à tenir sous le plafond.
 */
export async function preparerScan(files: File[], nomBase: string): Promise<ScanAssemble> {
  if (!files.length) throw new Error('Aucun fichier choisi.')
  if (files.length > MAX_SCAN_PAGES) throw new Error(`Maximum ${MAX_SCAN_PAGES} pages par document.`)
  if (files.reduce((total, file) => total + file.size, 0) > MAX_SCAN_SOURCE_BYTES) {
    throw new Error('Les fichiers source sont trop volumineux. Réduisez leur nombre ou leur résolution.')
  }
  const pdfs = files.filter((f) => f.type === 'application/pdf')
  if (pdfs.length) {
    if (files.length > 1) {
      throw new Error('Choisissez soit un PDF, soit des photos : pas les deux, ni plusieurs PDF.')
    }
    if (pdfs[0].size > MAX_PIECE_BYTES) {
      throw new Error('PDF trop volumineux (max 3 Mo). Rescannez en 150 ou 200 ppp, ou en niveaux de gris.')
    }
    return { blob: pdfs[0], filename: `${nomBase}.pdf`, pages: 0 }
  }
  if (files.some((f) => !IMAGE_TYPES.includes(f.type))) {
    throw new Error('Formats acceptés : PDF, JPG ou PNG.')
  }
  const images = await Promise.all(files.map(chargerImage))
  for (const [coteMax, qualite] of [[1800, 0.72], [1500, 0.62], [1200, 0.55], [1000, 0.5]] as const) {
    const blob = assembler(images, coteMax, qualite)
    if (blob.size <= MAX_PIECE_BYTES) return { blob, filename: `${nomBase}.pdf`, pages: images.length }
  }
  throw new Error('Trop de pages pour tenir sous 3 Mo : réduisez le nombre de photos ou scannez la liste en PDF.')
}
