import { useCallback, useLayoutEffect, useRef, useState } from 'react'

/**
 * Recentre la branche qu'on vient de déplier dans une arborescence.
 *
 * Dans un dropdown ou une table longue, déplier un parent situé en bas de la
 * liste pousse ses enfants sous le bord visible, et l'utilisateur doit scroller
 * à la main pour voir ce que son clic a produit. On ramène donc le bloc
 * « parent + enfants révélés » au centre du conteneur.
 *
 * Le recentrage part de la ligne cliquée et remonte au conteneur via
 * `[data-tree-scroll]`, ce qui permet à plusieurs dropdowns d'un même écran
 * de partager le hook sans se confondre.
 *
 * L'élément DOM cliqué n'est pas mémorisé : `BudgetDropdownNode` est déclaré
 * dans le corps de ses pages, donc React remonte tout le sous-arbre à chaque
 * rendu et la référence serait détachée du document. On retient l'id et on
 * re-interroge le conteneur, lui stable, après le commit.
 */

const EDGE_PADDING = 8

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function centerBranch(container: HTMLElement, nodeId: string): void {
  const escapedId = typeof CSS !== 'undefined' && typeof CSS.escape === 'function'
    ? CSS.escape(nodeId)
    : nodeId
  const row = container.querySelector<HTMLElement>(`[data-tree-node="${escapedId}"]`)
  if (!row) return
  const branchRows = Array.from(
    container.querySelectorAll<HTMLElement>(`[data-tree-branch~="${escapedId}"]`)
  )
  const branch = branchRows[branchRows.length - 1] ?? null

  const containerRect = container.getBoundingClientRect()
  const rowRect = row.getBoundingClientRect()
  const blockTop = rowRect.top - containerRect.top + container.scrollTop
  const blockBottom = (branch ? branch.getBoundingClientRect().bottom : rowRect.bottom)
    - containerRect.top
    + container.scrollTop
  const blockHeight = blockBottom - blockTop
  const viewport = container.clientHeight

  // Une branche plus haute que le cadre ne peut pas être centrée sans masquer
  // son parent : on cale alors le parent en haut, l'utilisateur déroule la
  // suite lui-même.
  const target = blockHeight >= viewport - EDGE_PADDING * 2
    ? blockTop - EDGE_PADDING
    : blockTop - (viewport - blockHeight) / 2

  const maxScroll = Math.max(0, container.scrollHeight - viewport)
  if (maxScroll === 0) {
    row.scrollIntoView({ block: 'center', behavior: prefersReducedMotion() ? 'auto' : 'smooth' })
    return
  }
  const top = Math.max(0, Math.min(target, maxScroll))
  if (Math.abs(top - container.scrollTop) < 1) return

  container.scrollTo({ top, behavior: prefersReducedMotion() ? 'auto' : 'smooth' })
}

export function useTreeBranchReveal(): (row: HTMLElement | null) => void {
  const pending = useRef<{ container: HTMLElement; nodeId: string } | null>(null)
  const [commit, setCommit] = useState(0)

  useLayoutEffect(() => {
    const target = pending.current
    if (!target) return
    pending.current = null
    // Le conteneur peut avoir été démonté entre le clic et le commit (fermeture
    // du dropdown sur blur, par exemple).
    if (!target.container.isConnected) return
    centerBranch(target.container, target.nodeId)
  }, [commit])

  return useCallback((row: HTMLElement | null) => {
    if (!row) return
    const container = row.closest<HTMLElement>('[data-tree-scroll]')
    const nodeId = row.dataset.treeNode
    if (!container || !nodeId) return
    pending.current = { container, nodeId }
    setCommit((value) => value + 1)
  }, [])
}
