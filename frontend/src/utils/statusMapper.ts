export type StatusMeta = {
  label: string
  description?: string
  bg: string
  color: string
}

export const STATUS_MAP: Record<string, StatusMeta> = {
  BROUILLON: {
    label: 'Brouillon',
    description: 'À signer par le service/commission.',
    bg: '#f3f4f6',
    color: '#374151',
  },
  SIGNEE_SERVICE: {
    label: 'Signée (Service)',
    description: 'Signée par le service, prête à être soumise à l’examen.',
    bg: '#dcfce7',
    color: '#15803d',
  },
  EN_ATTENTE_COMMISSION: {
    label: 'En examen commission',
    description: 'Le dossier est en cours d’examen interne.',
    bg: '#fef3c7',
    color: '#92400e',
  },
  EN_ATTENTE: {
    label: 'En attente validation 1/2',
    description: 'En attente de la première validation.',
    bg: '#e0f2fe',
    color: '#0369a1',
  },
  AUTORISEE: {
    label: 'Validation 1/2',
    description: 'Validée (1/2), en attente de la validation finale.',
    bg: '#dbeafe',
    color: '#1e40af',
  },
  APPROUVEE: {
    label: 'Validation 2/2',
    description: 'Validée (2/2), prête pour le décaissement.',
    bg: '#dcfce7',
    color: '#166534',
  },
  PAYEE: {
    label: 'Payée',
    description: 'Transaction finalisée.',
    bg: '#e2e8f0',
    color: '#475569',
  },
  REJETEE: {
    label: 'Rejetée',
    description: 'Réquisition rejetée par le workflow.',
    bg: '#fee2e2',
    color: '#dc2626',
  },
}

export const getStatusMeta = (raw?: string | null): StatusMeta => {
  if (!raw) return STATUS_MAP.EN_ATTENTE_COMMISSION
  const key = String(raw).toUpperCase()
  if (key === 'BROUILLON') {
    return STATUS_MAP.BROUILLON
  }
  if (key === 'EN_ATTENTE' || key === 'A_VALIDER') {
    return STATUS_MAP.EN_ATTENTE
  }
  if (key === 'APPROUVE_COMMISSION') {
    return STATUS_MAP.EN_ATTENTE
  }
  if (key === 'VALIDE_TECHNIQUE') {
    return STATUS_MAP.AUTORISEE
  }
  if (key === 'DECAISSE') {
    return STATUS_MAP.PAYEE
  }
  if (key === 'REJETTE') {
    return STATUS_MAP.REJETEE
  }
  if (key === 'VALIDEE') {
    return STATUS_MAP.AUTORISEE
  }
  return STATUS_MAP[key] || STATUS_MAP.EN_ATTENTE
}
