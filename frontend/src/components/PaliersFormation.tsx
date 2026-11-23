import { Plus, Trash2 } from 'lucide-react'
import type { PalierFormation } from '../api/tableau'

// Colonnes d'heures validées du bilan Forco, de l'année la plus ancienne à la plus récente.
const COLONNES = ['Hv1', 'Hv2', 'Hv3', 'Hv4']

// Miroir de `DEFAULT_FORMATION_PALIERS` (verdict.py) : affiché tant que le serveur n'a rien renvoyé.
export const PALIERS_PAR_DEFAUT: PalierFormation[] = [
  { anciennete: 0, colonnes: [], par_an_min: null, cumul: false, total_min: null },
  { anciennete: 1, colonnes: ['Hv4'], par_an_min: 20, cumul: false, total_min: null },
  { anciennete: 2, colonnes: ['Hv3', 'Hv4'], par_an_min: 20, cumul: false, total_min: null },
  { anciennete: 3, colonnes: ['Hv2', 'Hv3', 'Hv4'], par_an_min: 20, cumul: true, total_min: null },
]

// Totaux proposés pour une ligne : 20 h puis 30 h par année jugée (20 h sur 1 an ;
// 40 h ou 60 h sur 2 ans). Le minimum de la catégorie s'ajoute à part.
const PAR_AN_PROPOSES = [20, 30]

const h = (valeur: number) => `${Number.isInteger(valeur) ? valeur : valeur.toFixed(1)} h`

/** Ce que la ligne exige, en clair : « 20 h chaque année et 40 h au total sur les 2 années ». */
function exigence(palier: PalierFormation, heuresMin: number, impose: boolean): string {
  const annees = palier.colonnes.length
  const periode = annees > 1 ? `les ${annees} années` : "l'année"
  const total = impose || palier.cumul ? heuresMin : palier.total_min ?? null
  if (annees === 1 && !impose) {
    // Sur une seule année, minimum annuel et total disent la même chose : le plus exigeant.
    const seul = Math.max(palier.par_an_min ?? 0, total ?? 0)
    return seul ? `Exigé : ${h(seul)} sur l'année.` : 'Rien n\'est exigé : la ligne vaut non applicable dans les faits.'
  }
  const morceaux = []
  if (palier.par_an_min != null) morceaux.push(`${h(palier.par_an_min)} chaque année`)
  if (total != null) morceaux.push(`${h(total)} au total sur ${impose ? `les ${PERIODE_ANCIENS_ANS} dernières années` : periode}`)
  if (!morceaux.length) return 'Rien n\'est exigé : la ligne vaut non applicable dans les faits.'
  const phrase = `Exigé : ${morceaux.join(' et ')}.`
  return palier.par_an_min == null && total != null && annees > 1
    ? `${phrase} Une année faible peut être compensée par une autre.`
    : phrase
}

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

// Miroir de `PERIODE_FORMATION_ANCIENS_ANS` (verdict.py) : règlement FORCO 2022.
const PERIODE_ANCIENS_ANS = 3

// Miroir de `_paliers_valides` (verdict.py) : la dernière ligne exige toujours
// le minimum de « Conditions pour être en règle ».
function cumulImpose(palier: PalierFormation, dernier: boolean): boolean {
  return dernier && palier.colonnes.length > 0
}

export default function PaliersFormation({ paliers, heuresMin, modifiable, onChange }: PaliersFormationProps) {
  const tries = [...paliers].sort((a, b) => a.anciennete - b.anciennete)
  const modifier = (index: number, modif: Partial<PalierFormation>) => {
    onChange(tries.map((palier, i) => {
      if (i !== index) return palier
      const suivant = { ...palier, ...modif }
      // Sans colonne à juger, il n'y a rien à exiger.
      return suivant.colonnes.length ? suivant : { ...suivant, par_an_min: null, cumul: false, total_min: null }
    }))
  }
  const ajouter = () => {
    const prochaine = tries.length ? Math.max(...tries.map(p => p.anciennete)) + 1 : 0
    onChange([...tries, { anciennete: prochaine, colonnes: [], par_an_min: null, cumul: false, total_min: null }])
  }

  return (
    <div style={{ marginTop: '18px' }}>
      <h3 style={{ fontSize: '13px', fontWeight: 700, color: '#111827', margin: '0 0 4px' }}>Formation selon l'ancienneté</h3>
      <p style={{ fontSize: '12px', color: '#6b7280', margin: '0 0 8px' }}>
        L'ancienneté se compte par le N° d'ordre : exercice moins l'année d'inscription. Chaque ligne vaut
        pour son ancienneté et au-delà, jusqu'à la ligne suivante. La dernière ligne exige toujours les {heuresMin} h
        de « Conditions pour être en règle » ; les lignes précédentes, ce qui y est exigé. Le minimum
        annuel et le total s'ajoutent ; videz le minimum annuel pour qu'une année faible soit compensée
        par une autre.
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
              const impose = cumulImpose(palier, dernier)
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
                            placeholder="—"
                            onChange={e => modifier(index, { par_an_min: e.target.value === '' ? null : Number(e.target.value) })}
                            style={champ}
                          />
                          h au minimum chaque année
                        </label>
                        {impose ? (
                          <span title="Le minimum de « Conditions pour être en règle » s'applique toujours ici.">
                            {heuresMin} h sur les {PERIODE_ANCIENS_ANS} dernières années
                            <span style={{ color: '#6b7280' }}> (Conditions pour être en règle)</span>
                          </span>
                        ) : (
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}
                            role="group" aria-label={`Total sur ${annees > 1 ? `les ${annees} années` : "l'année"}`}>
                            <span>Total sur {annees > 1 ? `les ${annees} années` : "l'année"} :</span>
                            {([
                              { cle: 'aucun', libelle: 'Aucun', actif: !palier.cumul && palier.total_min == null,
                                modif: { cumul: false, total_min: null } },
                              ...PAR_AN_PROPOSES.map(par => par * annees)
                                .filter((total, i, liste) => liste.indexOf(total) === i && total !== heuresMin)
                                .map(total => ({ cle: String(total), libelle: h(total), actif: !palier.cumul && palier.total_min === total,
                                  modif: { cumul: false, total_min: total } })),
                              { cle: 'categorie', libelle: `${h(heuresMin)} (minimum de la catégorie)`, actif: palier.cumul,
                                modif: { cumul: true, total_min: null } },
                            ] as Array<{ cle: string; libelle: string; actif: boolean; modif: Partial<PalierFormation> }>).map(choix => (
                              <label key={choix.cle} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                                <input type="radio" name={`total-palier-${index}`} checked={choix.actif} disabled={!modifiable}
                                  onChange={() => modifier(index, choix.modif)} />
                                {choix.libelle}
                              </label>
                            ))}
                            <label style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                              autre
                              <input
                                type="number" min={0} disabled={!modifiable} aria-label="Autre total, en heures"
                                value={!palier.cumul && palier.total_min != null && !PAR_AN_PROPOSES.some(par => par * annees === palier.total_min)
                                  ? palier.total_min : ''}
                                onChange={e => modifier(index, e.target.value === ''
                                  ? { cumul: false, total_min: null }
                                  : { cumul: false, total_min: Number(e.target.value) })}
                                style={champ}
                              />
                              h
                            </label>
                          </div>
                        )}
                        <span style={{ width: '100%', fontSize: '12px', color: '#6b7280' }}>
                          {exigence(palier, heuresMin, impose)}
                        </span>
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
