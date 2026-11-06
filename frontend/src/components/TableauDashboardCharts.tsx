import { useEffect, useRef, useState } from 'react'
import type { TableauStats } from '../api/tableau'
import styles from './TableauDashboardCharts.module.css'

/* Couleurs d'état (réservées aux conclusions) ; le texte reste à l'encre, jamais à la couleur. */
const ETATS = [
  { cle: 'en_regle', libelle: 'En règle', couleur: '#0ca30c', encre: '#ffffff' },
  { cle: 'a_deliberer', libelle: 'À délibérer', couleur: '#fab219', encre: '#0b0b0b' },
  { cle: 'non_en_regle', libelle: 'Non en règle', couleur: '#d03b3b', encre: '#ffffff' },
  { cle: 'sans_conclusion', libelle: 'Sans conclusion', couleur: '#c3c2b7', encre: '#0b0b0b' },
] as const
type CleEtat = typeof ETATS[number]['cle']

const CRITERES = [
  { cle: 'cotisation', libelle: 'Cotisation à jour', ok: 'à jour', ko: 'en défaut' },
  { cle: 'formation', libelle: 'Formation (NHV) atteinte', ok: 'atteinte', ko: 'insuffisante' },
  { cle: 'assurance', libelle: 'Assurance valide', ok: 'valide', ko: 'non valide' },
  { cle: 'chiffre_affaires', libelle: "Chiffre d'affaires déclaré", ok: 'déclaré', ko: 'non déclaré' },
] as const

const PROFILS = [
  { cle: 'sexe', libelle: 'Sexe', aide: 'personnes physiques', parts: [['M', 'Hommes'], ['F', 'Femmes'], ['inconnu', 'Non renseigné']] },
  { cle: 'anciennete', libelle: 'Ancienneté', aide: "selon le N° d'ordre", parts: [['Ancien', 'Anciens'], ['Nouveau', 'Nouveaux'], ['inconnu', 'À vérifier']] },
  { cle: 'actif', libelle: 'Actifs', aide: 'personnes physiques', parts: [['oui', 'Actifs'], ['non', 'Inactifs'], ['inconnu', 'Non renseigné']] },
] as const
/* Profil : une teinte, du plus foncé au plus clair ; la troisième part (inconnu) en gris. */
const TEINTES_PROFIL = ['var(--viz-brand)', 'var(--viz-brand-light)', '#c3c2b7']

const pourcent = (part: number, total: number) => (total > 0 ? (part / total) * 100 : 0)
const fmtPct = (valeur: number) => `${valeur.toLocaleString('fr-FR', { maximumFractionDigits: valeur < 10 && valeur > 0 ? 1 : 0 })} %`
const fmt = (valeur: number) => valeur.toLocaleString('fr-FR')

function mouvementReduit() {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

/** Passe à vrai juste après le premier rendu : les transitions CSS partent de zéro. */
function useApparition(cle: unknown) {
  const [visible, setVisible] = useState(false)
  useEffect(() => {
    setVisible(false)
    const id = requestAnimationFrame(() => requestAnimationFrame(() => setVisible(true)))
    return () => cancelAnimationFrame(id)
  }, [cle])
  return visible
}

/** Compte de 0 à la valeur, une fois ; immédiat si l'utilisateur limite les animations. */
function useCompteur(valeur: number, duree = 1100) {
  const [courant, setCourant] = useState(mouvementReduit() ? valeur : 0)
  useEffect(() => {
    if (mouvementReduit()) {
      setCourant(valeur)
      return
    }
    let debut: number | null = null
    let id = 0
    const pas = (t: number) => {
      debut ??= t
      const avance = Math.min(1, (t - debut) / duree)
      setCourant(valeur * (1 - Math.pow(1 - avance, 3)))
      if (avance < 1) id = requestAnimationFrame(pas)
    }
    id = requestAnimationFrame(pas)
    return () => cancelAnimationFrame(id)
  }, [valeur, duree])
  return courant
}

/* Infobulle partagée : suit le pointeur, ou se pose sous l'élément qui a le focus clavier. */
type Bulle = { x: number; y: number; titre: string; lignes: string[] } | null
function useBulle() {
  const [bulle, setBulle] = useState<Bulle>(null)
  const zone = useRef<HTMLDivElement>(null)
  const props = (titre: string, lignes: string[]) => ({
    tabIndex: 0,
    'aria-label': `${titre} : ${lignes.join(', ')}`,
    onMouseMove: (event: React.MouseEvent) => {
      const cadre = zone.current?.getBoundingClientRect()
      if (cadre) setBulle({ x: event.clientX - cadre.left, y: event.clientY - cadre.top, titre, lignes })
    },
    onMouseLeave: () => setBulle(null),
    onFocus: (event: React.FocusEvent) => {
      const cadre = zone.current?.getBoundingClientRect()
      const cible = (event.currentTarget as Element).getBoundingClientRect()
      if (cadre) setBulle({ x: cible.left - cadre.left + cible.width / 2, y: cible.bottom - cadre.top, titre, lignes })
    },
    onBlur: () => setBulle(null),
  })
  const rendu = bulle && (
    <div className={styles.tooltip} style={{ left: bulle.x, top: bulle.y }} role="status">
      <strong>{bulle.titre}</strong>
      {bulle.lignes.map(ligne => <span key={ligne}>{ligne}</span>)}
    </div>
  )
  return { zone, props, rendu }
}

/** Anneau-jauge : un seul rapport (une part d'un tout), piste du même ton. */
function Anneau({
  valeur, taille, epaisseur, couleur, visible, delai = 0, children,
}: {
  valeur: number; taille: number; epaisseur: number; couleur: string; visible: boolean; delai?: number; children?: React.ReactNode
}) {
  const rayon = (taille - epaisseur) / 2
  const circonference = 2 * Math.PI * rayon
  const rempli = Math.max(0, Math.min(100, valeur)) / 100
  return (
    <div className={styles.ring} style={{ width: taille, height: taille }}>
      <svg width={taille} height={taille} viewBox={`0 0 ${taille} ${taille}`} aria-hidden="true">
        <circle cx={taille / 2} cy={taille / 2} r={rayon} fill="none" stroke="var(--viz-track)" strokeWidth={epaisseur} />
        <circle
          cx={taille / 2}
          cy={taille / 2}
          r={rayon}
          fill="none"
          stroke={couleur}
          strokeWidth={epaisseur}
          strokeLinecap={rempli > 0 ? 'round' : 'butt'}
          strokeDasharray={circonference}
          strokeDashoffset={visible ? circonference * (1 - rempli) : circonference}
          transform={`rotate(-90 ${taille / 2} ${taille / 2})`}
          className={styles.ringArc}
          style={{ transitionDelay: `${delai}ms` }}
        />
      </svg>
      <div className={styles.ringCenter}>{children}</div>
    </div>
  )
}

/** Barre segmentée : un tout découpé en parts, chacune séparée par un liseré de surface. */
function Segments({
  parts, total, visible, hauteur, etiquettes, bulle, titre, delai = 0,
}: {
  parts: Array<{ cle: string; libelle: string; valeur: number; couleur: string; encre?: string }>
  total: number
  visible: boolean
  hauteur: number
  etiquettes: boolean
  bulle: ReturnType<typeof useBulle>['props']
  titre: string
  delai?: number
}) {
  return (
    <div className={styles.segments} style={{ height: hauteur }} role="img" aria-label={`${titre} : ${parts.map(p => `${p.libelle} ${p.valeur}`).join(', ')}`}>
      {parts.filter(p => p.valeur > 0).map((part, index) => {
        const pct = pourcent(part.valeur, total)
        return (
          <div
            key={part.cle}
            className={styles.segment}
            style={{
              background: part.couleur,
              color: part.encre || '#ffffff',
              flexBasis: visible ? `${pct}%` : '0%',
              transitionDelay: `${delai + index * 90}ms`,
            }}
            {...bulle(`${titre} — ${part.libelle}`, [`${fmt(part.valeur)} sur ${fmt(total)}`, fmtPct(pct)])}
          >
            {/* Une étiquette n'est posée que si elle tient dans sa part. */}
            {etiquettes && visible && pct >= 9 && <span className={styles.segmentLabel}>{fmtPct(pct)}</span>}
          </div>
        )
      })}
    </div>
  )
}

function Legende({ items }: { items: Array<{ libelle: string; couleur: string; valeur?: string }> }) {
  return (
    <ul className={styles.legend}>
      {items.map(item => (
        <li key={item.libelle}>
          <span className={styles.swatch} style={{ background: item.couleur }} aria-hidden="true" />
          <span>{item.libelle}</span>
          {item.valeur && <strong>{item.valeur}</strong>}
        </li>
      ))}
    </ul>
  )
}

/**
 * Graphiques du tableau de bord : conformité générale, conformité par critère,
 * conclusions par catégorie et profil des membres. Tout vient de la base
 * consolidée (`/tableau/stats`) ; chaque carte a son tableau de chiffres.
 */
export default function TableauDashboardCharts({ stats }: { stats: TableauStats }) {
  const visible = useApparition(stats.last_exercice)
  const { zone, props: bulle, rendu } = useBulle()
  const total = stats.membres_base ?? 0
  const comptes: Record<CleEtat, number> = {
    en_regle: stats.en_regle ?? 0,
    a_deliberer: stats.a_deliberer ?? 0,
    non_en_regle: stats.non_en_regle ?? 0,
    sans_conclusion: stats.sans_conclusion ?? 0,
  }
  const etats = ETATS.filter(etat => etat.cle !== 'sans_conclusion' || comptes.sans_conclusion > 0)
  const taux = pourcent(comptes.en_regle, total)
  const tauxAnime = useCompteur(taux)
  const membresAnimes = useCompteur(total)

  if (total === 0) {
    return <div className={styles.empty}>Aucun membre dans la base pour l'instant : importez un fichier pour voir les graphiques.</div>
  }

  return (
    <div className={styles.root} ref={zone}>
      {/* 1. Conformité générale */}
      <section className={`${styles.card} ${styles.hero}`} aria-labelledby="viz-conformite">
        <header className={styles.cardHead}>
          <h3 id="viz-conformite">Conformité de la base</h3>
          <p>Exercice {stats.last_exercice} · {fmt(total)} membres en exercice</p>
        </header>
        <div className={styles.heroBody}>
          <div {...bulle('Taux de conformité', [`${fmt(comptes.en_regle)} en règle sur ${fmt(total)}`])} className={styles.focusable}>
            <Anneau valeur={taux} taille={184} epaisseur={16} couleur="var(--viz-brand)" visible={visible}>
              <span className={styles.heroValue}>{fmtPct(tauxAnime)}</span>
              <span className={styles.heroLabel}>en règle</span>
            </Anneau>
          </div>
          <div className={styles.heroSide}>
            <div className={styles.heroCount}>
              <strong>{fmt(Math.round(membresAnimes))}</strong>
              <span>membres analysés selon les règles de délibération</span>
            </div>
            <Segments
              titre="Conclusions"
              parts={etats.map(etat => ({ cle: etat.cle, libelle: etat.libelle, valeur: comptes[etat.cle], couleur: etat.couleur, encre: etat.encre }))}
              total={total}
              visible={visible}
              hauteur={34}
              etiquettes
              bulle={bulle}
              delai={250}
            />
            <Legende items={etats.map(etat => ({ libelle: etat.libelle, couleur: etat.couleur, valeur: fmt(comptes[etat.cle]) }))} />
            {!!stats.membres_sortis && (
              <p className={styles.note}>{fmt(stats.membres_sortis)} membre(s) sorti(s) du Tableau ne sont pas comptés.</p>
            )}
          </div>
        </div>
      </section>

      {/* 2. Conformité par critère */}
      <section className={styles.card} aria-labelledby="viz-criteres">
        <header className={styles.cardHead}>
          <h3 id="viz-criteres">Conformité par critère</h3>
          <p>Part des membres soumis au critère qui le remplissent</p>
        </header>
        <div className={styles.criteria}>
          {CRITERES.map((critere, index) => {
            const valeurs = stats.criteres?.[critere.cle] || { ok: 0, ko: 0, inconnu: 0 }
            const soumis = valeurs.ok + valeurs.ko + valeurs.inconnu
            const pct = pourcent(valeurs.ok, soumis)
            return (
              <div key={critere.cle} className={styles.criterion}>
                <div
                  className={styles.focusable}
                  {...bulle(critere.libelle, [
                    `${fmt(valeurs.ok)} ${critere.ok}`, `${fmt(valeurs.ko)} ${critere.ko}`, `${fmt(valeurs.inconnu)} non renseignés`,
                  ])}
                >
                  <Anneau valeur={pct} taille={112} epaisseur={11} couleur="var(--viz-brand)" visible={visible} delai={150 + index * 120}>
                    <span className={styles.ringValue}>{soumis ? fmtPct(pct) : '—'}</span>
                  </Anneau>
                </div>
                <strong className={styles.criterionTitle}>{critere.libelle}</strong>
                <span className={styles.criterionMeta}>
                  {fmt(valeurs.ok)} {critere.ok} · {fmt(valeurs.ko)} {critere.ko}
                </span>
                {valeurs.inconnu > 0 && (
                  <span className={styles.criterionUnknown}>{fmt(valeurs.inconnu)} non renseigné{valeurs.inconnu > 1 ? 's' : ''} ({fmtPct(pourcent(valeurs.inconnu, soumis))})</span>
                )}
              </div>
            )
          })}
        </div>
      </section>

      {/* 3. Conclusions par catégorie : plusieurs touts côte à côte, en 100 %. */}
      <section className={styles.card} aria-labelledby="viz-categories">
        <header className={styles.cardHead}>
          <h3 id="viz-categories">Conclusions par catégorie</h3>
          <p>Répartition en pourcentage ; le nombre de membres à droite</p>
        </header>
        <Legende items={etats.map(etat => ({ libelle: etat.libelle, couleur: etat.couleur }))} />
        <div className={styles.categoryRows}>
          {(stats.par_categorie || []).map((ligne, index) => (
            <div key={ligne.categorie} className={styles.categoryRow}>
              <span className={styles.categoryName}>{ligne.categorie}</span>
              <Segments
                titre={ligne.categorie}
                parts={etats.map(etat => ({ cle: etat.cle, libelle: etat.libelle, valeur: Number(ligne[etat.cle] || 0), couleur: etat.couleur, encre: etat.encre }))}
                total={ligne.total}
                visible={visible}
                hauteur={22}
                etiquettes
                bulle={bulle}
                delai={300 + index * 110}
              />
              <span className={styles.categoryTotal}>{fmt(ligne.total)}</span>
            </div>
          ))}
        </div>
      </section>

      {/* 4. Profil des membres */}
      <section className={styles.card} aria-labelledby="viz-profil">
        <header className={styles.cardHead}>
          <h3 id="viz-profil">Profil des membres</h3>
          <p>Qui compose la base de l'exercice</p>
        </header>
        <div className={styles.profiles}>
          {PROFILS.map((profil, index) => {
            const valeurs = stats.profil?.[profil.cle] || {}
            const parts = profil.parts
              .map(([cle, libelle], rang) => ({ cle, libelle, valeur: Number(valeurs[cle] || 0), couleur: TEINTES_PROFIL[rang] }))
              .filter(part => part.cle !== 'inconnu' || part.valeur > 0)
            const somme = parts.reduce((acc, part) => acc + part.valeur, 0)
            return (
              <div key={profil.cle} className={styles.profile}>
                <div className={styles.profileHead}>
                  <strong>{profil.libelle}</strong>
                  <span>{profil.aide} · {fmt(somme)}</span>
                </div>
                <Segments titre={profil.libelle} parts={parts} total={somme} visible={visible} hauteur={12} etiquettes={false} bulle={bulle} delai={400 + index * 120} />
                <Legende items={parts.map(part => ({ libelle: part.libelle, couleur: part.couleur, valeur: `${fmt(part.valeur)} · ${fmtPct(pourcent(part.valeur, somme))}` }))} />
              </div>
            )
          })}
        </div>
      </section>

      {/* Les mêmes chiffres en tableau : lecture sans couleur, copie, lecteur d'écran. */}
      <details className={styles.tableView}>
        <summary>Voir les chiffres en tableau</summary>
        <table>
          <thead>
            <tr>
              <th scope="col">Catégorie</th>
              {etats.map(etat => <th key={etat.cle} scope="col">{etat.libelle}</th>)}
              <th scope="col">Total</th>
            </tr>
          </thead>
          <tbody>
            {(stats.par_categorie || []).map(ligne => (
              <tr key={ligne.categorie}>
                <th scope="row">{ligne.categorie}</th>
                {etats.map(etat => <td key={etat.cle}>{fmt(Number(ligne[etat.cle] || 0))}</td>)}
                <td>{fmt(ligne.total)}</td>
              </tr>
            ))}
            <tr className={styles.totalRow}>
              <th scope="row">Ensemble</th>
              {etats.map(etat => <td key={etat.cle}>{fmt(comptes[etat.cle])}</td>)}
              <td>{fmt(total)}</td>
            </tr>
          </tbody>
        </table>
        <table>
          <thead>
            <tr><th scope="col">Critère</th><th scope="col">Rempli</th><th scope="col">En défaut</th><th scope="col">Non renseigné</th><th scope="col">Taux</th></tr>
          </thead>
          <tbody>
            {CRITERES.map(critere => {
              const v = stats.criteres?.[critere.cle] || { ok: 0, ko: 0, inconnu: 0 }
              return (
                <tr key={critere.cle}>
                  <th scope="row">{critere.libelle}</th>
                  <td>{fmt(v.ok)}</td><td>{fmt(v.ko)}</td><td>{fmt(v.inconnu)}</td>
                  <td>{fmtPct(pourcent(v.ok, v.ok + v.ko + v.inconnu))}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </details>

      {rendu}
    </div>
  )
}
