import styles from './TenantSelector.module.css'

export type TenantOption = {
  id: number
  name: string
  slug: string
}

type TenantSelectorProps = {
  tenants: TenantOption[]
  selectedTenant: TenantOption | null
  onSelect: (tenant: TenantOption) => void
}

export default function TenantSelector({ tenants, selectedTenant, onSelect }: TenantSelectorProps) {
  if (!tenants.length) return null
  return (
    <div className={styles.wrapper}>
      <label className={styles.label}>Sélectionnez votre site d'accès</label>
      <div className={styles.list}>
        {tenants.map((tenant) => (
          <button
            key={tenant.id}
            type="button"
            onClick={() => onSelect(tenant)}
            className={`${styles.item} ${selectedTenant?.id === tenant.id ? styles.itemActive : ''}`}
          >
            <span className={styles.name}>{tenant.name}</span>
            <span className={styles.slug}>{tenant.slug}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
