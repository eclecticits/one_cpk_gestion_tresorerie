import styles from './ExportAnnulationsToggle.module.css'

interface Props {
  checked: boolean
  onChange: (value: boolean) => void
}

/**
 * Ce que l'export fait des opérations annulées ou supprimées.
 *
 * Cochée (par défaut), elles restent dans le classeur pour la trace : grisées,
 * barrées, hors de tout total, et rassemblées dans l'onglet « Journal des
 * annulations ». Décochée, le classeur ne porte que les actives — une liste
 * propre, à transmettre.
 *
 * À n'afficher qu'à qui a le droit de voir les annulées : le serveur les
 * refuse de toute façon aux autres.
 */
export default function ExportAnnulationsToggle({ checked, onChange }: Props) {
  return (
    <label
      className={styles.toggle}
      title="Les opérations annulées ou supprimées restent dans le classeur, grisées et barrées, sans compter dans les totaux."
    >
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} />
      Exporter avec les annulations
    </label>
  )
}
