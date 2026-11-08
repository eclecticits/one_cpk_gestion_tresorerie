import type { CSSProperties } from 'react'

/** Coquille et éléments communs aux fenêtres d'envoi des relevés de situation. */

export const fondModale: CSSProperties = {
  position: 'fixed', inset: 0, zIndex: 80, background: 'rgba(17, 24, 39, 0.45)', display: 'grid', placeItems: 'center', padding: '16px',
}
export const fenetreModale: CSSProperties = {
  width: 'min(640px, 100%)', maxHeight: '90vh', overflowY: 'auto', background: '#fff', borderRadius: '8px', border: '1px solid #d8dadd', boxShadow: '0 20px 50px rgba(0,0,0,.22)',
}
export const enteteModale: CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px', padding: '16px 16px 0' }
export const titreModale: CSSProperties = { margin: 0, fontSize: '17px' }
export const sousTitreModale: CSSProperties = { margin: '4px 0 0', fontSize: '13px', color: '#6b7280' }
export const piedModale: CSSProperties = { display: 'flex', justifyContent: 'flex-end', gap: '8px', padding: '0 16px 16px' }

export const bouton: CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '8px 12px',
  border: '1px solid #c9ccd2', borderRadius: '5px', background: '#fff', cursor: 'pointer', fontSize: '13px',
}
export const boutonPrincipal: CSSProperties = { ...bouton, background: '#0f7b62', borderColor: '#0f7b62', color: '#fff', fontWeight: 600 }

export const cadreCanaux: CSSProperties = { border: '1px solid #e5e7eb', borderRadius: '6px', padding: '10px 12px', margin: 0, display: 'grid', gap: '8px' }
export const legendeCanaux: CSSProperties = { fontSize: '12px', fontWeight: 600, padding: '0 4px' }

/** Le texte du relevé tel qu'il partira. */
export const texteReleve: CSSProperties = {
  margin: 0, padding: '12px', whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: '13px', lineHeight: 1.55, background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: '6px',
}

export const listeDetails: CSSProperties = { margin: '8px 0 0', paddingLeft: '18px', color: '#4b5563', display: 'grid', gap: '4px' }

export const messageErreur = (error: unknown, defaut: string) =>
  (error instanceof Error && error.message) || defaut
