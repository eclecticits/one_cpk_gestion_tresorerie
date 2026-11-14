import { Plus, Trash2 } from 'lucide-react'
import type { PalierFormation } from '../api/tableau'

// Colonnes d'heures validées du bilan Forco, de l'année la plus ancienne à la plus récente.
const COLONNES = ['Hv1', 'Hv2', 'Hv3', 'Hv4']

// Miroir de `DEFAULT_FORMATION_PALIERS` (verdict.py) : affiché tant que le serveur n'a rien renvoyé.
export const PALIERS_PAR_DEFAUT: PalierFormation[] = [
  { anciennete: 0, colonnes: [], par_an_min: null, cumul: false },
  { anciennete: 1, colonnes: ['Hv4'], par_an_min: 20, cumul: false },
  { anciennete: 2, colonnes: ['Hv3', 'Hv4'], par_an_min: 20, cumul: false },
  { anciennete: 3, colonnes: ['Hv2', 'Hv3', 'Hv4'], par_an_min: 20, cumul: true },
]

interface PaliersFormationProps {
  paliers: PalierFormation[]
  /** Le minimum d'heures réglé au-dessus : c'est lui que le cumul exige. */
  heuresMin: number
  modifiable: boolean
  onChange: (paliers: PalierFormation[]) => void
}

const cellule: React.CSSProperties = { padding: '8px 10px', borderTop: '1px solid #e5e7eb', verticalAlign: 'middle' }
const entete: React.CSSProperties = { padding: '8px 10px', textAlign: 'left', fontSize: '12px', fontWeight: 600, color: '#374151' }
const champ: React.CSSProperties = { border: '1px solid #d1d5db', borderRadius: '5px', padding: '5px 8px', fontSize: '13px', width: '70px' }

export default function PaliersFormation({ paliers, heuresMin, modifiable, onChange }: PaliersFormationProps) {
  const tries = [...paliers].sort((a, b) => a.anciennete - b.anciennete)
  const modifier = (index: number, modif: Partial<PalierFormation>) => {
    onChange(tries.map((palier, i) => {
      if (i !== index) return palier
      const suivant = { ...palier, ...modif }
      // Sans colonne à juger, il n'y a rien à exiger.
      return suivant.colonnes.length ? suivant : { ...suivant, par_an_min: null, cumul: false }
    }))
  }
  const ajouter = () => {
    const prochaine = tries.length ? Math.max(...tries.map(p => p.anciennete)) + 1 : 0
    onChange([...tries, { anciennete: prochaine, colonnes: [], par_an_min: null, cumul: false }])
  }

  return (
    <div style={{ marginTop: '18px' }}>
      <h3 style={{ fontSize: '13px', fontWeight: 700, color: '#111827', margin: '0 0 4px' }}>Formation selon l'ancienneté</h3>
      <p style={{ fontSize: '12px', color: '#6b7280', margin: '0 0 8px' }}>
        L'ancienneté se compte par le N° d'ordre : exercice moins l'année d'inscription. Chaque ligne vaut
        pour son ancienneté et au-delà, jusqu'à la ligne suivante.
      </p>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: '13px', border: '1px solid #e5e7eb' }}>
          <thead style={{ background: '#f9fafb' }}>
            <tr>
              <th style={entete}>Ancienneté</th>
              <th style={entete}>Ce qui est exigé</th>
              <th style={entete}>Colonnes du BilanForco</th>
              {modifiable && <th style={entete} aria-label="Actions" />}
            </tr>
          </thead>
          <tbody>
            {tries.map((palier, index) => {
              const dernier = index === tries.length - 1
              const annees = palier.colonnes.length
              return (
                <tr key={index}>
                  <td style={cellule}>
                    <input
                      type="number" min={0} max={100} value={palier.anciennete} disabled={!modifiable}
                      aria-label="Ancienneté en années"
                      onChange={e => modifier(index, { anciennete: Math.max(0, Math.round(Number(e.target.value))) })}
                      style={champ}
                    />
                    <span style={{ marginLeft: '6px', color: '#374151' }}>
                      {palier.anciennete > 1 ? 'ans' : 'an'}{dernier ? ' et plus' : ''}
                    </span>
                  </td>
                  <td style={cellule}>
                    {annees === 0 ? (
                      <span style={{ color: '#6b7280' }}>Non applicable</span>
                    ) : (
                      <div style={{ display: 'flex', gap: '14px', flexWrap: 'wrap', alignItems: 'center' }}>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <input
                            type="number" min={0} value={palier.par_an_min ?? ''} disabled={!modifiable}
                            onChange={e => modifier(index, { par_an_min: e.target.value === '' ? null : Number(e.target.value) })}
                            style={champ}
                          />
                          h au minimum chaque année
                        </label>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <input
                            type="checkbox" checked={palier.cumul} disabled={!modifiable}
                            onChange={e => modifier(index, { cumul: e.target.checked })}
                          />
                          {heuresMin} h sur {annees > 1 ? `les ${annees} années` : "l'année"}
                        </label>
                      </div>
                    )}
                  </td>
                  <td style={cellule}>
                    <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                      {COLONNES.map(colonne => (
                        <label key={colonne} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <input
                            type="checkbox" checked={palier.colonnes.includes(colonne)} disabled={!modifiable}
                            onChange={e => modifier(index, {
                              colonnes: COLONNES.filter(c => (c === colonne ? e.target.checked : palier.colonnes.includes(c))),
                            })}
                          />
                          {colonne}
                        </label>
                      ))}
                    </div>
                  </td>
                  {modifiable && (
                    <td style={{ ...cellule, width: '40px', textAlign: 'center' }}>
                      <button
                        type="button" title="Retirer cette ligne" aria-label="Retirer cette ligne"
                        onClick={() => onChange(tries.filter((_, i) => i !== index))}
                        style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7280', padding: '4px' }}
                      >
                        <Trash2 size={15} />
                      </button>
                    </td>
                  )}
                </tr>
              )
            })}
            {tries.length === 0 && (
              <tr>
                <td style={{ ...cellule, color: '#6b7280' }} colSpan={modifiable ? 4 : 3}>
                  Aucune ligne : l'exemption « nouveau membre » et le minimum d'heures s'appliquent seuls.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {modifiable && (
        <button
          type="button" onClick={ajouter}
          style={{ marginTop: '8px', display: 'inline-flex', alignItems: 'center', gap: '6px', background: '#fff', border: '1px solid #d1d5db', borderRadius: '5px', padding: '6px 10px', fontSize: '12px', cursor: 'pointer' }}
        >
          <Plus size={14} />
          Ajouter une ancienneté
        </button>
      )}
    </div>
  )
}
