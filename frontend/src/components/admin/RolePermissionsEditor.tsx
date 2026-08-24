import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Pencil,
  Plus,
  RotateCcw,
  Save,
  Search,
  ShieldCheck,
  X,
} from 'lucide-react'
import styles from './RolePermissionsEditor.module.css'
import type { PermissionInfo, RoleInfo } from '../../api/admin'
import {
  ACTION_KIND_LABELS,
  PERMISSION_TREE,
  findPermissionLocation,
  findUnmappedCodes,
  type ActionKind,
  type PermissionMenu,
  type PermissionModule,
  type PermissionTask,
} from '../../data/permissionTree'

/* ------------------------------------------------------------------ */
/* Niveaux d'accès                                                      */
/* ------------------------------------------------------------------ */

type AccessLevel = 'none' | 'read' | 'contribute' | 'full'
type LevelState = AccessLevel | 'custom'

const LEVEL_ORDER: AccessLevel[] = ['none', 'read', 'contribute', 'full']

const LEVEL_LABELS: Record<AccessLevel, string> = {
  none: 'Aucun',
  read: 'Lecture',
  contribute: 'Lecture + création',
  full: 'Complet',
}

const LEVEL_SHORT: Record<AccessLevel, string> = {
  none: 'Aucun',
  read: 'Lecture',
  contribute: 'Lect. + créat.',
  full: 'Complet',
}

const LEVEL_HINTS: Record<AccessLevel, string> = {
  none: "Aucun accès à ce menu.",
  read: "Consulter seulement. Ne peut rien créer ni modifier.",
  contribute: "Saisir et corriger. Ne peut ni supprimer, ni valider, ni annuler, ni exporter.",
  full: "Toutes les tâches du menu, y compris supprimer, valider, annuler et exporter.",
}

/** Codes d'accès au module (la porte d'entrée posée au niveau du routeur). */
const MODULE_ACCESS_CODE: Record<string, string | undefined> = {
  tresorerie: undefined,
  rh: undefined,
  secretariat: 'menu_secretariat',
  comptabilite: 'menu_comptabilite',
}

const KIND_CLASS: Record<ActionKind, string> = {
  read: styles.kindRead,
  create: styles.kindCreate,
  update: styles.kindUpdate,
  delete: styles.kindDelete,
  validate: styles.kindValidate,
  cancel: styles.kindCancel,
  export: styles.kindExport,
  manage: styles.kindManage,
  other: styles.kindOther,
}

const UNMAPPED_KEY = '__unmapped__'

/* ------------------------------------------------------------------ */
/* Utilitaires                                                          */
/* ------------------------------------------------------------------ */

const normalize = (value: string) =>
  value.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')

const sameSet = (a: Set<string>, b: Set<string>) => {
  if (a.size !== b.size) return false
  for (const item of a) if (!b.has(item)) return false
  return true
}

/** Les tâches d'un menu réellement utilisables : non masquées ET connues du serveur. */
function usableTasks(menu: PermissionMenu, serverCodes: Set<string>): PermissionTask[] {
  return menu.tasks.filter((task) => !task.hidden && serverCodes.has(task.code))
}

/** Jeu de codes correspondant à un niveau d'accès pour un menu donné. */
function codesForLevel(
  menu: PermissionMenu,
  level: AccessLevel,
  tasks: PermissionTask[],
): Set<string> {
  if (level === 'none') return new Set()
  if (level === 'full') return new Set(tasks.map((t) => t.code))

  const codes = new Set<string>()
  // Le code d'accès n'est ajouté d'office que s'il est une simple porte
  // (`other`) ou un droit de consultation (`read`). Quand le code du menu est
  // lui-même un droit substantiel — `compta.parametrage`, `rh.settings.manage`,
  // `compta.export` — il suit sa propre famille : « Lecture » ne doit jamais
  // accorder un droit de gestion ou d'extraction.
  const gate = tasks.find((t) => t.code === menu.menuCode)
  if (gate && (gate.kind === 'other' || gate.kind === 'read')) codes.add(gate.code)
  tasks.forEach((task) => {
    if (task.kind === 'read') codes.add(task.code)
  })
  if (level === 'read') return codes

  // contribute : lecture + création/modification + actions génératives (`other`)
  tasks.forEach((task) => {
    // La porte pure (`other`) a déjà été traitée ci-dessus ; en revanche un code
    // de menu qui est lui-même un droit de saisie — `compta.saisie` — doit bien
    // être accordé au niveau « Lecture + création ».
    if (task.code === menu.menuCode && task.kind === 'other') return
    if (task.kind === 'create' || task.kind === 'update' || task.kind === 'other') {
      codes.add(task.code)
    }
  })
  return codes
}

/** Niveau courant d'un menu, ou 'custom' si la sélection ne colle à aucun preset. */
function detectLevel(
  menu: PermissionMenu,
  tasks: PermissionTask[],
  granted: Set<string>,
): LevelState {
  const current = new Set(tasks.filter((t) => granted.has(t.code)).map((t) => t.code))
  for (const level of LEVEL_ORDER) {
    if (sameSet(current, codesForLevel(menu, level, tasks))) return level
  }
  return 'custom'
}

type TriState = 'all' | 'none' | 'partial'

/** Niveau d'un module : le niveau commun à tous ses menus, sinon 'custom'. */
function detectModuleLevel(module: PermissionModule, granted: Set<string>): LevelState {
  let common: LevelState | null = null
  for (const menu of module.menus) {
    const level = detectLevel(menu, menu.tasks, granted)
    if (common === null) common = level
    else if (common !== level) return 'custom'
  }
  return common ?? 'none'
}

function triStateOf(tasks: PermissionTask[], granted: Set<string>): TriState {
  if (tasks.length === 0) return 'none'
  const count = tasks.reduce((acc, t) => acc + (granted.has(t.code) ? 1 : 0), 0)
  if (count === 0) return 'none'
  if (count === tasks.length) return 'all'
  return 'partial'
}

/* ------------------------------------------------------------------ */
/* Case tri-state                                                       */
/* ------------------------------------------------------------------ */

function TriStateBox({
  state,
  disabled,
  label,
  onToggle,
}: {
  state: TriState
  disabled?: boolean
  label: string
  onToggle: () => void
}) {
  const ref = useRef<HTMLInputElement | null>(null)
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = state === 'partial'
  }, [state])
  return (
    <input
      ref={ref}
      type="checkbox"
      className={styles.triState}
      checked={state === 'all'}
      disabled={disabled}
      aria-label={label}
      onChange={onToggle}
      onClick={(event) => event.stopPropagation()}
    />
  )
}

/* ------------------------------------------------------------------ */
/* Props                                                                */
/* ------------------------------------------------------------------ */

export interface RolePermissionsEditorProps {
  roles: RoleInfo[]
  permissions: PermissionInfo[]
  /** Enregistre UN rôle. Ne reçoit jamais le rôle `admin`. */
  onSaveRole: (roleId: number, permissionCodes: string[], label: string) => Promise<void>
  onAddRole: () => void | Promise<void>
  onDeleteRole: (roleId: number) => void | Promise<void>
  loading?: boolean
}

/* ------------------------------------------------------------------ */
/* Composant                                                            */
/* ------------------------------------------------------------------ */

export default function RolePermissionsEditor({
  roles,
  permissions,
  onSaveRole,
  onAddRole,
  onDeleteRole,
  loading = false,
}: RolePermissionsEditorProps) {
  const [selectedRoleId, setSelectedRoleId] = useState<number | null>(null)
  const [granted, setGranted] = useState<Set<string>>(new Set())
  const [initialGranted, setInitialGranted] = useState<Set<string>>(new Set())
  const [labelDraft, setLabelDraft] = useState('')
  const [initialLabel, setInitialLabel] = useState('')
  const [renaming, setRenaming] = useState(false)

  const [activeModuleKey, setActiveModuleKey] = useState<string>(PERMISSION_TREE[0]?.key ?? '')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [roleSearch, setRoleSearch] = useState('')
  const [taskSearch, setTaskSearch] = useState('')
  const [onlyGranted, setOnlyGranted] = useState(false)

  const [saving, setSaving] = useState(false)
  const [banner, setBanner] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const [pulsing, setPulsing] = useState<string | null>(null)
  const [autoNote, setAutoNote] = useState<{ menuKey: string; text: string } | null>(null)

  const serverCodes = useMemo(() => new Set(permissions.map((p) => p.code)), [permissions])

  /* ---- Arbre effectivement affichable (piloté par le catalogue serveur) ---- */

  const tree: PermissionModule[] = useMemo(() => {
    const base = PERMISSION_TREE.map((module) => ({
      ...module,
      menus: module.menus
        .map((menu) => ({ ...menu, tasks: usableTasks(menu, serverCodes) }))
        .filter((menu) => menu.tasks.length > 0),
    })).filter((module) => module.menus.length > 0)

    const unmapped = findUnmappedCodes(permissions.map((p) => p.code))
    if (unmapped.length > 0) {
      base.push({
        key: UNMAPPED_KEY,
        label: 'Non classés',
        color: '#b91c1c',
        menus: [
          {
            key: 'unmapped_all',
            label: 'Permissions non rattachées à un menu',
            tasks: unmapped.map((code) => ({
              code,
              label: permissions.find((p) => p.code === code)?.description || code,
              kind: 'other' as ActionKind,
            })),
          },
        ],
      })
    }
    return base
  }, [permissions, serverCodes])

  const activeModule = useMemo(
    () => tree.find((m) => m.key === activeModuleKey) ?? tree[0],
    [tree, activeModuleKey],
  )

  /* ---- Rôles ---- */

  const orderedRoles = useMemo(
    () =>
      [...roles].sort((a, b) =>
        (a.label || a.code || '').trim().localeCompare((b.label || b.code || '').trim(), 'fr'),
      ),
    [roles],
  )

  const filteredRoles = useMemo(() => {
    const query = normalize(roleSearch.trim())
    if (!query) return orderedRoles
    return orderedRoles.filter(
      (role) =>
        normalize(role.code || '').includes(query) || normalize(role.label || '').includes(query),
    )
  }, [orderedRoles, roleSearch])

  const selectedRole = useMemo(
    () => roles.find((r) => r.id === selectedRoleId) ?? null,
    [roles, selectedRoleId],
  )
  const isAdminRole = selectedRole?.code === 'admin'

  /** Total des tâches affichables, tous modules confondus. */
  const totalTasks = useMemo(
    () => tree.reduce((acc, m) => acc + m.menus.reduce((a, menu) => a + menu.tasks.length, 0), 0),
    [tree],
  )

  const countFor = useCallback(
    (role: RoleInfo) => {
      if (role.code === 'admin') return totalTasks
      const codes = new Set(role.permissions ?? [])
      return tree.reduce(
        (acc, m) =>
          acc + m.menus.reduce((a, menu) => a + menu.tasks.filter((t) => codes.has(t.code)).length, 0),
        0,
      )
    },
    [tree, totalTasks],
  )

  /** Répartition par module, pour la barre de profil de la carte de rôle. */
  const spreadFor = useCallback(
    (role: RoleInfo) => {
      const codes = role.code === 'admin' ? null : new Set(role.permissions ?? [])
      return tree.map((m) => {
        const all = m.menus.reduce((a, menu) => a + menu.tasks.length, 0)
        const on = codes
          ? m.menus.reduce((a, menu) => a + menu.tasks.filter((t) => codes.has(t.code)).length, 0)
          : all
        return { key: m.key, color: m.color, on }
      })
    },
    [tree],
  )

  const dirty = useMemo(
    () => !sameSet(granted, initialGranted) || labelDraft !== initialLabel,
    [granted, initialGranted, labelDraft, initialLabel],
  )

  /* ---- Sélection d'un rôle ---- */

  const adoptRole = useCallback((role: RoleInfo) => {
    setSelectedRoleId(role.id)
    const codes = new Set(role.permissions ?? [])
    setGranted(codes)
    setInitialGranted(new Set(codes))
    setLabelDraft(role.label || '')
    setInitialLabel(role.label || '')
    setRenaming(false)
    setBanner(null)
    setAutoNote(null)
  }, [])

  const confirmDiscard = useCallback(() => {
    if (!dirty) return true
    const ok = window.confirm(
      "Des modifications n'ont pas été enregistrées.\nVoulez-vous quitter sans enregistrer ?",
    )
    // Abandonner doit abandonner : sinon les modifications « quittées »
    // survivent en mémoire et repartent au prochain enregistrement.
    if (ok) {
      setGranted(new Set(initialGranted))
      setLabelDraft(initialLabel)
      setAutoNote(null)
    }
    return ok
  }, [dirty, initialGranted, initialLabel])

  const selectRole = (role: RoleInfo) => {
    if (role.id === selectedRoleId) return
    if (!confirmDiscard()) return
    adoptRole(role)
  }

  // Ré-adopte l'instantané serveur quand la liste des rôles change (création,
  // suppression, rechargement) — mais jamais par-dessus des modifications en cours.
  useEffect(() => {
    if (selectedRoleId === null) return
    const fresh = roles.find((r) => r.id === selectedRoleId)
    if (!fresh) {
      setSelectedRoleId(null)
      setGranted(new Set())
      setInitialGranted(new Set())
      return
    }
    if (dirty) return
    const codes = new Set(fresh.permissions ?? [])
    if (!sameSet(codes, initialGranted)) {
      setGranted(codes)
      setInitialGranted(new Set(codes))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roles])

  useEffect(() => {
    if (!dirty) return
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty])

  /* ---- Mutations ---- */

  const pulse = (code: string) => {
    setPulsing(code)
    window.setTimeout(() => setPulsing((prev) => (prev === code ? null : prev)), 700)
  }

  const moduleAccessCode = activeModule ? MODULE_ACCESS_CODE[activeModule.key] : undefined

  const applyChange = (mutate: (draft: Set<string>) => void) => {
    if (isAdminRole || saving) return
    setGranted((prev) => {
      const draft = new Set(prev)
      mutate(draft)
      return draft
    })
    setBanner(null)
  }

  const toggleTask = (
    menu: PermissionMenu,
    task: PermissionTask,
    next: boolean,
    allTasks = menu.tasks,
  ) => {
    applyChange((draft) => {
      if (next) {
        draft.add(task.code)
        const gate = autoGateOf(menu)
        if (gate && gate !== task.code && !draft.has(gate)) {
          draft.add(gate)
          if (allTasks.some((t) => t.code === gate)) {
            pulse(gate)
            setAutoNote({ menuKey: menu.key, text: 'Accès au menu activé automatiquement.' })
          }
        }
        if (moduleAccessCode && serverCodes.has(moduleAccessCode) && !draft.has(moduleAccessCode)) {
          draft.add(moduleAccessCode)
          pulse(moduleAccessCode)
        }
      } else {
        draft.delete(task.code)
        // Porte masquée (les 5 `secretariat.use_agent_*`) : elle n'est jamais
        // rendue, donc jamais décochée à la main. Quand la dernière tâche
        // visible du menu s'éteint, la porte doit s'éteindre avec elle — sinon
        // le rôle garde le droit d'appeler l'agent alors que l'écran affiche
        // « 0/3 — Aucun ».
        const gate = hiddenGate(menu, allTasks)
        if (gate && !allTasks.some((t) => draft.has(t.code))) draft.delete(gate)
        if (menu.menuCode && task.code === menu.menuCode) {
          const removed = allTasks.filter((t) => t.code !== menu.menuCode && draft.has(t.code))
          removed.forEach((t) => draft.delete(t.code))
          if (removed.length > 0) {
            setAutoNote({
              menuKey: menu.key,
              text: `Le retrait de l'accès au menu a désactivé ${removed.length} tâche${
                removed.length > 1 ? 's' : ''
              }.`,
            })
          }
        }
      }
    })
  }

  /**
   * Le code d'accès d'un menu ne doit être coché AUTOMATIQUEMENT que lorsqu'il
   * est une simple porte (`other`) ou un droit de consultation (`read`).
   * Sur cinq menus, le `menuCode` est en réalité un droit substantiel :
   * `compta.saisie`, `compta.parametrage`, `compta.export`, `rh.settings.manage`,
   * `secretariat.manage_ai_settings`. Les accorder d'office parce qu'on coche
   * « Valider une écriture » ou « Journaux d'audit » serait une élévation de
   * privilège silencieuse.
   */
  const autoGateOf = (menu: PermissionMenu): string | undefined => {
    if (!menu.menuCode || !serverCodes.has(menu.menuCode)) return undefined
    const kind = findPermissionLocation(menu.menuCode)?.task.kind
    return kind === 'other' || kind === 'read' ? menu.menuCode : undefined
  }

  /** Porte d'accès d'un menu absente de la liste affichée (tâche masquée). */
  const hiddenGate = (menu: PermissionMenu, tasks: PermissionTask[]) =>
    menu.menuCode && serverCodes.has(menu.menuCode) && !tasks.some((t) => t.code === menu.menuCode)
      ? menu.menuCode
      : undefined

  const applyLevelTo = (
    draft: Set<string>,
    menu: PermissionMenu,
    level: AccessLevel,
    allTasks: PermissionTask[],
  ) => {
    allTasks.forEach((t) => draft.delete(t.code))
    const gate = hiddenGate(menu, allTasks)
    if (gate) draft.delete(gate)
    if (level === 'none') return
    const wanted = codesForLevel(menu, level, allTasks)
    wanted.forEach((code) => draft.add(code))
    // La porte masquée ne se rallume que si le niveau accorde effectivement
    // quelque chose : « Lecture » sur un menu sans tâche `read` n'accorde rien,
    // et ne doit donc pas rouvrir la porte.
    if (gate && wanted.size > 0) draft.add(gate)
  }

  const setMenuLevel = (menu: PermissionMenu, level: AccessLevel, allTasks = menu.tasks) => {
    applyChange((draft) => {
      applyLevelTo(draft, menu, level, allTasks)
      if (level !== 'none' && moduleAccessCode && serverCodes.has(moduleAccessCode)) {
        draft.add(moduleAccessCode)
      }
    })
    setAutoNote(null)
  }

  const toggleMenu = (menu: PermissionMenu, allTasks = menu.tasks) => {
    const state = triStateOf(allTasks, granted)
    setMenuLevel(menu, state === 'all' ? 'none' : 'full', allTasks)
  }

  const toggleModule = (module: PermissionModule) => {
    const all = module.menus.flatMap((m) => m.tasks)
    const state = triStateOf(all, granted)
    applyChange((draft) => {
      module.menus.forEach((menu) =>
        applyLevelTo(draft, menu, state === 'all' ? 'none' : 'full', menu.tasks),
      )
      if (state !== 'all' && moduleAccessCode && serverCodes.has(moduleAccessCode)) {
        draft.add(moduleAccessCode)
      }
    })
    setAutoNote(null)
  }

  const setModuleLevel = (module: PermissionModule, level: AccessLevel) => {
    applyChange((draft) => {
      module.menus.forEach((menu) => applyLevelTo(draft, menu, level, menu.tasks))
      if (level !== 'none' && moduleAccessCode && serverCodes.has(moduleAccessCode)) {
        draft.add(moduleAccessCode)
      }
    })
    setAutoNote(null)
  }

  /* ---- Enregistrement ---- */

  const resetChanges = () => {
    setGranted(new Set(initialGranted))
    setLabelDraft(initialLabel)
    setAutoNote(null)
    setBanner(null)
  }

  const handleSave = async () => {
    if (!selectedRole || isAdminRole || !dirty) return
    setSaving(true)
    setBanner(null)
    try {
      // Les tâches masquées et les codes hors arbre ne sont jamais rendus :
      // on les réémet tels quels pour ne rien perdre à l'enregistrement.
      await onSaveRole(selectedRole.id, Array.from(granted), labelDraft)
      setInitialGranted(new Set(granted))
      setInitialLabel(labelDraft)
      setRenaming(false)
      setBanner({
        kind: 'success',
        text: `Les permissions du rôle « ${labelDraft || selectedRole.code} » ont été enregistrées.`,
      })
    } catch (error: any) {
      setBanner({
        kind: 'error',
        text: error?.payload?.detail || error?.message || "L'enregistrement a échoué.",
      })
    } finally {
      setSaving(false)
    }
  }

  const handleAdd = async () => {
    if (!confirmDiscard()) return
    await onAddRole()
  }

  const handleDelete = async (roleId: number) => {
    if (!confirmDiscard()) return
    await onDeleteRole(roleId)
  }

  /* ---- Filtrage de l'arbre ---- */

  const query = normalize(taskSearch.trim())

  const visibleMenus = useMemo(() => {
    if (!activeModule) return []
    return activeModule.menus
      .map((menu) => {
        let tasks = menu.tasks
        if (query) {
          const menuHit = normalize(menu.label).includes(query)
          tasks = menuHit
            ? tasks
            : tasks.filter(
                (t) => normalize(t.label).includes(query) || normalize(t.code).includes(query),
              )
        }
        if (onlyGranted) tasks = tasks.filter((t) => granted.has(t.code) || isAdminRole)
        // `tasks` = ce qui est AFFICHÉ ; `allTasks` = le menu entier.
        // Les niveaux, la case tri-state et le compteur raisonnent toujours sur
        // le menu entier : un filtre ne doit jamais changer ce qu'une action fait.
        return { ...menu, tasks, allTasks: menu.tasks }
      })
      .filter((menu) => menu.tasks.length > 0)
  }, [activeModule, query, onlyGranted, granted, isAdminRole])

  const otherModuleHits = useMemo(() => {
    if (!query) return []
    return tree
      .filter((m) => m.key !== activeModule?.key)
      .map((m) => ({
        key: m.key,
        label: m.label,
        count: m.menus.reduce(
          (acc, menu) =>
            acc +
            (normalize(menu.label).includes(query)
              ? menu.tasks.length
              : menu.tasks.filter(
                  (t) => normalize(t.label).includes(query) || normalize(t.code).includes(query),
                ).length),
          0,
        ),
      }))
      .filter((m) => m.count > 0)
  }, [tree, activeModule, query])

  // La recherche déplie automatiquement ce qu'elle a trouvé.
  useEffect(() => {
    if (!query) return
    setExpanded(new Set(visibleMenus.map((m) => m.key)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, activeModuleKey])

  const grantedInModule = useMemo(() => {
    if (!activeModule) return 0
    return activeModule.menus.reduce(
      (acc, menu) => acc + menu.tasks.filter((t) => granted.has(t.code) || isAdminRole).length,
      0,
    )
  }, [activeModule, granted, isAdminRole])

  const totalInModule = useMemo(
    () => activeModule?.menus.reduce((acc, menu) => acc + menu.tasks.length, 0) ?? 0,
    [activeModule],
  )

  const grantedTotal = isAdminRole
    ? totalTasks
    : tree.reduce(
        (acc, m) => acc + m.menus.reduce((a, menu) => a + menu.tasks.filter((t) => granted.has(t.code)).length, 0),
        0,
      )

  /* ---- Rendu ---- */

  const renderLevels = (
    menu: PermissionMenu,
    allTasks: PermissionTask[],
    current: LevelState,
    onPick: (level: AccessLevel) => void,
    ariaLabel: string,
  ) => {
    if (allTasks.length < 2) return null
    return (
      <div className={styles.levels} role="group" aria-label={ariaLabel}>
        {LEVEL_ORDER.map((level) => {
          const codes = codesForLevel(menu, level, allTasks)
          const previous = LEVEL_ORDER[LEVEL_ORDER.indexOf(level) - 1]
          const redundant =
            previous !== undefined && sameSet(codes, codesForLevel(menu, previous, allTasks))
          return (
            <button
              key={level}
              type="button"
              className={current === level ? styles.levelActive : undefined}
              disabled={isAdminRole || saving || redundant}
              aria-pressed={current === level}
              title={redundant ? "Ce menu n'a pas de tâche de ce niveau." : LEVEL_HINTS[level]}
              onClick={(event) => {
                event.stopPropagation()
                onPick(level)
              }}
            >
              <span className={styles.levelFull}>{LEVEL_LABELS[level]}</span>
              <span className={styles.levelShort}>{LEVEL_SHORT[level]}</span>
            </button>
          )
        })}
        {current === 'custom' && (
          <span
            className={styles.levelCustom}
            title="La sélection ne correspond à aucun niveau prédéfini. Choisissez un niveau pour la réinitialiser."
          >
            Personnalisé
          </span>
        )}
      </div>
    )
  }

  return (
    <div className={styles.wrapper}>
      <header className={styles.pageHeader}>
        <h2 className={styles.pageTitle}>
          <ShieldCheck size={16} aria-hidden="true" />
          Rôles et permissions
        </h2>
        <p className={styles.pageHint}>
          Choisissez un rôle, puis un module. Chaque menu se déplie sur ses tâches.
        </p>
      </header>

      <div className={styles.permsShell}>
        {/* ─── Panneau gauche : les rôles ─────────────────────────────── */}
        <aside className={styles.rolesPanel} aria-label="Rôles">
          <div className={styles.rolesHeader}>
            <h3>Rôles</h3>
            <span>
              {filteredRoles.length} sur {roles.length}
            </span>
          </div>

          <div className={styles.rolesTools}>
            <label className={styles.searchBox}>
              <Search size={14} aria-hidden="true" />
              <input
                type="search"
                value={roleSearch}
                onChange={(e) => setRoleSearch(e.target.value)}
                placeholder="Rechercher un rôle"
                aria-label="Rechercher un rôle"
              />
            </label>
          </div>

          <div className={styles.rolesList}>
            {loading &&
              Array.from({ length: 6 }).map((_, index) => (
                <div key={`sk-${index}`} className={styles.roleSkeleton} aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </div>
              ))}

            {!loading &&
              filteredRoles.map((role) => {
                const isActive = role.id === selectedRoleId
                const count = countFor(role)
                const spread = spreadFor(role)
                const spreadTotal = spread.reduce((a, s) => a + s.on, 0) || 1
                return (
                  <div
                    key={role.id}
                    className={`${styles.roleItem} ${isActive ? styles.roleItemActive : ''}`}
                    role="button"
                    tabIndex={0}
                    aria-current={isActive ? 'true' : undefined}
                    onClick={() => selectRole(role)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        selectRole(role)
                      }
                    }}
                  >
                    <div className={styles.roleTopLine}>
                      <span className={styles.roleCode}>{role.code}</span>
                      {role.code === 'admin' ? (
                        <span className={`${styles.rolePill} ${styles.rolePillAdmin}`}>
                          Tous droits
                        </span>
                      ) : null}
                    </div>
                    <span className={styles.roleLabel} title={role.label || role.code}>
                      {role.label || role.code}
                    </span>
                    <span className={styles.roleMeta}>
                      {count} tâche{count > 1 ? 's' : ''} sur {totalTasks}
                    </span>
                    <span className={styles.roleSpread} aria-hidden="true">
                      {spread.map((segment) => (
                        <i
                          key={segment.key}
                          style={{
                            background: segment.color,
                            width: `${(segment.on / spreadTotal) * 100}%`,
                          }}
                        />
                      ))}
                    </span>
                    {role.code !== 'admin' && (
                      <button
                        type="button"
                        className={styles.roleDelete}
                        title="Supprimer le rôle"
                        aria-label={`Supprimer le rôle ${role.label || role.code}`}
                        onClick={(event) => {
                          event.stopPropagation()
                          void handleDelete(role.id)
                        }}
                      >
                        <X size={13} />
                      </button>
                    )}
                  </div>
                )
              })}

            {!loading && filteredRoles.length === 0 && (
              <div className={styles.emptyState}>Aucun rôle ne correspond à cette recherche.</div>
            )}
          </div>

          <div className={styles.rolesFooter}>
            <button type="button" className={styles.secondaryButton} onClick={handleAdd}>
              <Plus size={14} aria-hidden="true" />
              Nouveau rôle
            </button>
          </div>
        </aside>

        {/* ─── Panneau droit : l'éditeur ──────────────────────────────── */}
        <section className={styles.editorPanel}>
          {!selectedRole ? (
            <div className={styles.placeholder}>
              <ShieldCheck size={32} aria-hidden="true" />
              <h3>Sélectionnez un rôle</h3>
              <p>Choisissez un rôle à gauche pour consulter et modifier ses permissions.</p>
            </div>
          ) : (
            <>
              <div className={styles.editorHeader}>
                <div className={styles.editorIdentity}>
                  <span className={styles.editorKicker}>Rôle</span>
                  {renaming && !isAdminRole ? (
                    <input
                      className={styles.renameInput}
                      value={labelDraft}
                      autoFocus
                      onChange={(e) => setLabelDraft(e.target.value)}
                      onBlur={() => setRenaming(false)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === 'Escape') setRenaming(false)
                      }}
                      placeholder="Nom du rôle"
                      aria-label="Nom du rôle"
                    />
                  ) : (
                    <button
                      type="button"
                      className={styles.editorName}
                      onClick={() => !isAdminRole && setRenaming(true)}
                      disabled={isAdminRole}
                      title={isAdminRole ? undefined : 'Renommer le rôle'}
                    >
                      {labelDraft || selectedRole.code}
                      {!isAdminRole && <Pencil size={12} aria-hidden="true" />}
                    </button>
                  )}
                  <code className={styles.editorCode}>{selectedRole.code}</code>
                </div>
                <div className={styles.editorStatus}>
                  {dirty && (
                    <span className={styles.dirtyBadge}>
                      <AlertCircle size={13} aria-hidden="true" />
                      Non enregistré
                    </span>
                  )}
                  <span className={styles.editorCount}>
                    {grantedTotal} / {totalTasks} tâches accordées
                  </span>
                </div>
              </div>

              <div className={styles.moduleTabs} role="tablist" aria-label="Modules">
                {tree.map((module) => {
                  const total = module.menus.reduce((a, m) => a + m.tasks.length, 0)
                  const on = isAdminRole
                    ? total
                    : module.menus.reduce(
                        (a, m) => a + m.tasks.filter((t) => granted.has(t.code)).length,
                        0,
                      )
                  const isActive = module.key === activeModule?.key
                  return (
                    <button
                      key={module.key}
                      type="button"
                      role="tab"
                      aria-selected={isActive}
                      className={`${styles.moduleTab} ${isActive ? styles.moduleTabActive : ''} ${
                        module.key === UNMAPPED_KEY ? styles.moduleTabWarn : ''
                      }`}
                      style={isActive ? { borderTopColor: module.color, color: module.color } : undefined}
                      onClick={() => setActiveModuleKey(module.key)}
                    >
                      {module.label}
                      <span className={styles.tabPill}>
                        {on}/{total}
                      </span>
                    </button>
                  )
                })}
              </div>

              <div className={styles.toolbar}>
                <label className={styles.searchBox}>
                  <Search size={14} aria-hidden="true" />
                  <input
                    type="search"
                    value={taskSearch}
                    onChange={(e) => setTaskSearch(e.target.value)}
                    placeholder="Rechercher une tâche"
                    aria-label="Rechercher une tâche"
                  />
                </label>
                <label className={styles.checkToggle}>
                  <input
                    type="checkbox"
                    checked={onlyGranted}
                    onChange={(e) => setOnlyGranted(e.target.checked)}
                  />
                  Uniquement les tâches accordées
                </label>
                <button
                  type="button"
                  className={styles.linkButton}
                  onClick={() =>
                    setExpanded((prev) =>
                      prev.size === 0 ? new Set(visibleMenus.map((m) => m.key)) : new Set(),
                    )
                  }
                >
                  {expanded.size === 0 ? 'Tout déplier' : 'Tout replier'}
                </button>
                <span className={styles.toolbarCount}>
                  {visibleMenus.length} menu{visibleMenus.length > 1 ? 's' : ''} · {totalInModule}{' '}
                  tâches · {grantedInModule} accordées
                </span>
              </div>

              <div className={styles.treeScroll} role="tree" aria-label={`Permissions du module ${activeModule?.label ?? ''}`}>
                {isAdminRole && (
                  <div className={styles.adminNotice}>
                    <ShieldCheck size={15} aria-hidden="true" />
                    <span>
                      Le rôle Administrateur dispose de tous les droits par conception
                      (court-circuit d'autorisation côté serveur). Cet écran ne le modifie pas.
                    </span>
                  </div>
                )}

                {banner && (
                  <div
                    className={banner.kind === 'success' ? styles.successBanner : styles.errorBanner}
                    role="status"
                  >
                    {banner.kind === 'success' ? (
                      <CheckCircle2 size={15} aria-hidden="true" />
                    ) : (
                      <AlertCircle size={15} aria-hidden="true" />
                    )}
                    <span>{banner.text}</span>
                  </div>
                )}

                {activeModule && (
                  <div className={styles.moduleSummary} style={{ borderLeftColor: activeModule.color }}>
                    <TriStateBox
                      state={triStateOf(
                        activeModule.menus.flatMap((m) => m.tasks),
                        isAdminRole ? new Set(Array.from(serverCodes)) : granted,
                      )}
                      disabled={isAdminRole || saving}
                      label={`Toutes les permissions du module ${activeModule.label}`}
                      onToggle={() => toggleModule(activeModule)}
                    />
                    <span className={styles.moduleSummaryLabel}>
                      Module {activeModule.label}
                      <em>
                        {grantedInModule} tâche{grantedInModule > 1 ? 's' : ''} accordée
                        {grantedInModule > 1 ? 's' : ''} sur {totalInModule}
                      </em>
                    </span>
                    <div className={styles.levels} role="group" aria-label="Niveau d'accès du module">
                      {LEVEL_ORDER.map((level) => {
                        const current = isAdminRole
                          ? 'full'
                          : detectModuleLevel(activeModule, granted)
                        // Désactivé quand appliquer ce niveau ne changerait rien
                        // par rapport au niveau inférieur sur TOUS les menus.
                        const redundant = LEVEL_ORDER.indexOf(level) > 0 &&
                          activeModule.menus.every((menu) =>
                            sameSet(
                              codesForLevel(menu, level, menu.tasks),
                              codesForLevel(
                                menu,
                                LEVEL_ORDER[LEVEL_ORDER.indexOf(level) - 1],
                                menu.tasks,
                              ),
                            ),
                          )
                        return (
                          <button
                            key={level}
                            type="button"
                            className={current === level ? styles.levelActive : undefined}
                            aria-pressed={current === level}
                            disabled={isAdminRole || saving || redundant}
                            title={
                              redundant
                                ? "Aucun menu de ce module n'a de tâche de ce niveau."
                                : LEVEL_HINTS[level]
                            }
                            onClick={() => setModuleLevel(activeModule, level)}
                          >
                            <span className={styles.levelFull}>{LEVEL_LABELS[level]}</span>
                            <span className={styles.levelShort}>{LEVEL_SHORT[level]}</span>
                          </button>
                        )
                      })}
                      {!isAdminRole && detectModuleLevel(activeModule, granted) === 'custom' && (
                        <span
                          className={styles.levelCustom}
                          title="Les menus de ce module n'ont pas tous le même niveau."
                        >
                          Personnalisé
                        </span>
                      )}
                    </div>
                  </div>
                )}

                {visibleMenus.length === 0 && (
                  <div className={styles.emptyTree}>
                    <p>
                      {query
                        ? `Aucune tâche ne correspond à « ${taskSearch} » dans ce module.`
                        : 'Aucune tâche à afficher avec ce filtre.'}
                    </p>
                    {otherModuleHits.length > 0 && (
                      <div className={styles.otherHits}>
                        <span>Résultats dans d'autres modules :</span>
                        {otherModuleHits.map((hit) => (
                          <button
                            key={hit.key}
                            type="button"
                            onClick={() => setActiveModuleKey(hit.key)}
                          >
                            {hit.label} ({hit.count})
                          </button>
                        ))}
                      </div>
                    )}
                    <button
                      type="button"
                      className={styles.linkButton}
                      onClick={() => {
                        setTaskSearch('')
                        setOnlyGranted(false)
                      }}
                    >
                      Effacer les filtres
                    </button>
                  </div>
                )}

                <ul className={styles.treeGroup} role="group">
                  {visibleMenus.map((menu, index) => {
                    const isOpen = expanded.has(menu.key)
                    const all = menu.allTasks
                    const state = isAdminRole ? 'all' : triStateOf(all, granted)
                    const level: LevelState = isAdminRole
                      ? 'full'
                      : detectLevel(menu, all, granted)
                    const on = all.filter((t) => isAdminRole || granted.has(t.code)).length
                    const hasRead = all.some(
                      (t) => t.kind === 'read' && (isAdminRole || granted.has(t.code)),
                    )
                    const hasWrite = all.some(
                      (t) =>
                        ['create', 'update', 'delete', 'export'].includes(t.kind) &&
                        (isAdminRole || granted.has(t.code)),
                    )
                    const readGap = hasWrite && !hasRead && all.some((t) => t.kind === 'read')
                    return (
                      <li key={menu.key}>
                        <div
                          role="treeitem"
                          aria-expanded={isOpen}
                          aria-checked={state === 'partial' ? 'mixed' : state === 'all'}
                          aria-level={1}
                          aria-posinset={index + 1}
                          aria-setsize={visibleMenus.length}
                          tabIndex={0}
                          className={styles.menuRow}
                          onClick={() =>
                            setExpanded((prev) => {
                              const next = new Set(prev)
                              if (next.has(menu.key)) next.delete(menu.key)
                              else next.add(menu.key)
                              return next
                            })
                          }
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault()
                              setExpanded((prev) => {
                                const next = new Set(prev)
                                if (next.has(menu.key)) next.delete(menu.key)
                                else next.add(menu.key)
                                return next
                              })
                            }
                            if (e.key === 'ArrowRight')
                              setExpanded((prev) => new Set(prev).add(menu.key))
                            if (e.key === 'ArrowLeft')
                              setExpanded((prev) => {
                                const next = new Set(prev)
                                next.delete(menu.key)
                                return next
                              })
                          }}
                        >
                          <span className={styles.chev} aria-hidden="true">
                            {isOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                          </span>
                          <TriStateBox
                            state={state}
                            disabled={isAdminRole || saving}
                            label={`Toutes les tâches du menu ${menu.label}`}
                            onToggle={() => toggleMenu(menu, all)}
                          />
                          <span className={styles.menuLabel} title={menu.label}>
                            {menu.label}
                            {readGap && (
                              <span
                                className={styles.warnPill}
                                title="Ce rôle pourra agir sans pouvoir consulter la liste."
                              >
                                sans « Consulter »
                              </span>
                            )}
                          </span>
                          <span className={styles.countPill}>
                            {on}/{all.length}
                          </span>
                          {renderLevels(
                            menu,
                            all,
                            level,
                            (picked) => setMenuLevel(menu, picked, all),
                            `Niveau d'accès du menu ${menu.label}`,
                          )}
                        </div>

                        {autoNote?.menuKey === menu.key && (
                          <div className={styles.autoNote} role="status" aria-live="polite">
                            {autoNote.text}
                          </div>
                        )}

                        {isOpen && (
                          <ul className={styles.taskGroup} role="group">
                            {menu.tasks.map((task) => {
                              const checked = isAdminRole || granted.has(task.code)
                              const changed =
                                !isAdminRole && granted.has(task.code) !== initialGranted.has(task.code)
                              return (
                                <li
                                  key={task.code}
                                  role="treeitem"
                                  aria-checked={checked}
                                  aria-level={2}
                                  tabIndex={-1}
                                  className={`${styles.taskRow} ${changed ? styles.taskRowChanged : ''} ${
                                    pulsing === task.code ? styles.taskRowPulse : ''
                                  }`}
                                >
                                  <span className={`${styles.kindPill} ${KIND_CLASS[task.kind]}`}>
                                    {ACTION_KIND_LABELS[task.kind]}
                                  </span>
                                  <span className={styles.taskLabel} title={task.label}>
                                    {task.label}
                                    {menu.menuCode === task.code && (
                                      <span className={styles.requiredPill}>requis</span>
                                    )}
                                  </span>
                                  <code className={styles.taskCode} title={task.code}>
                                    {task.code}
                                  </code>
                                  <label
                                    className={styles.switch}
                                    aria-label={`${task.label} — ${checked ? 'accordé' : 'refusé'}`}
                                  >
                                    <input
                                      type="checkbox"
                                      checked={checked}
                                      disabled={isAdminRole || saving}
                                      onChange={(e) => toggleTask(menu, task, e.target.checked, all)}
                                    />
                                    <span />
                                  </label>
                                </li>
                              )
                            })}
                          </ul>
                        )}
                      </li>
                    )
                  })}
                </ul>
              </div>

              <footer className={styles.actionBar}>
                <button
                  type="button"
                  className={styles.secondaryButton}
                  onClick={resetChanges}
                  disabled={!dirty || saving || isAdminRole}
                >
                  <RotateCcw size={14} aria-hidden="true" />
                  Annuler les modifications
                </button>
                <button
                  type="button"
                  className={`${styles.primaryButton} ${dirty ? styles.primaryButtonActive : ''}`}
                  onClick={handleSave}
                  disabled={!dirty || saving || isAdminRole}
                >
                  <Save size={14} aria-hidden="true" />
                  {saving ? 'Enregistrement…' : 'Enregistrer'}
                </button>
              </footer>
            </>
          )}
        </section>
      </div>
    </div>
  )
}
