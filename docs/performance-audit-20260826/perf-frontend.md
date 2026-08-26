# Audit de performance — frontend ONEC Smart

**Date :** 26/08/2026 · **Périmètre :** `frontend/` (Vite 5 + React 18 + TS, CSS Modules, react-query v5, react-router v6)
**Mode :** lecture seule. Aucun fichier du dépôt modifié.
**Base mesurée :** `frontend/dist/` du 26/08 17:38, **vérifié à jour** (`find src vite.config.ts index.html -newer dist/index.html` → vide). Tailles gzip calculées avec `gzip -9`.
**Non mesurable ici :** Docker mort → pas de runtime, pas de profil React DevTools, pas de Lighthouse, pas de trace réseau réelle.

## Préambule : l'état des lieux de `docs/ANALYSE_PERFORMANCE.md` est périmé

Ce document (30/07) affirme « `@tanstack/react-query` absent — vérifié » et « aucun `React.memo` ». Depuis le commit **9478b9d**, react-query est installé et utilisé, et les contextes ont été mémoïsés. **Ne pas s'y fier.** Ce qui reste vrai : `React.memo` = **0 occurrence** dans tout `src/` (MESURÉ, `grep -rn "React\.memo\|\bmemo("` → 0).

### Ce qui est déjà en place et **effectivement** actif (vérifié, ne pas re-proposer)

| Optimisation | Statut | Preuve |
|---|---|---|
| gzip nginx + `immutable` sur `/assets/` | ✅ actif | `frontend/nginx.conf:14-19`, `:70-71` |
| `manualChunks` vendors isolés | ✅ actif | `frontend/vite.config.ts:19-84` ; 9 chunks vendor distincts dans `dist/assets/` |
| Correctif `vite/preload-helper` (évitait 420 kB de jsPDF préchargés partout) | ✅ actif | `vendor-preload-helper-D7HrI6pR.js` = **1017 o** ; c'est bien lui qui est `modulepreload`é, pas jspdf |
| Lazy routes (`React.lazy`) | ✅ actif, 45 routes | `App.tsx:19-62` |
| **recharts jamais sur le chemin critique** | ✅ actif | seul `AnnualBarChart-9CpBFLVj.js` (844 o) importe `vendor-recharts`, et il n'est chargé qu'en `import()` depuis `Rapports-BJ8kXuTE.js`. **368 kB / 108 kB gz jamais téléchargés hors onglet Synthèse.** |
| **html2canvas jamais chargé statiquement** | ✅ actif | 0 importeur statique ; seulement `import()` interne de jspdf (`.html()`) |
| `value` des contextes mémoïsés | ✅ 4/5 | Auth, Permissions, OrganisationSettings, App — voir constat **C5** pour le 5ᵉ |
| `staleTime` / `refetchOnWindowFocus:false` | ✅ configuré | `App.tsx:361-368` — `staleTime: 30_000`, `refetchOnWindowFocus: false`, `retry: 1` |

### Chemin critique du premier rendu (MESURÉ)

| Chunk eager (`dist/index.html`) | brut | gzip |
|---|---:|---:|
| `index-BU9GeQZr.js` | 94 823 | **27 696** |
| `vendor-react` | 164 207 | **53 305** |
| `vendor-react-query` | 41 483 | **12 307** |
| `vendor-icons` (lucide, tree-shaké) | 56 947 | **10 572** |
| `vendor-preload-helper` | 1 017 | 652 |
| `index-CoYx4QUU.css` | 47 459 | **10 503** |
| **Total avant tout rendu de route** | **405 936** | **115 035** |

C'est sain. Le chemin critique **n'est pas** le problème. Le problème est **après-login, par route**.

---

## Tableau des constats — classés par (gain attendu × confiance)

| # | Constat | Gain attendu | Confiance | Coût du fix | Statut |
|---|---|---|---|---|---|
| **C1** | **jsPDF (135 kB gz) et xlsx (142 kB gz) tirés en import *statique* par 6 chunks de route** — le travail de lazy-loading de 9478b9d a des fuites | **−135 à −277 kB gz par route concernée** (jusqu'à **−95 % du JS** de `/services/mon-espace/:id`) | **Haute** | Faible, mécanique (6 fichiers, patron déjà écrit dans le dépôt) | **MESURÉ** |
| **C2** | **`Requisitions` charge jusqu'à 5000 lignes hydratées puis filtre/trie/compte 3× en mémoire à chaque frappe, sans mémoïsation** | Saisie fluide vs. saccadée ; payload réseau divisé par ~100 | **Haute** (code) / Moyenne (volumétrie réelle inconnue) | Moyen (mémoïsation triviale ; passage en pagination serveur = plus lourd) | **DÉDUIT** |
| **C3** | **3 champs de recherche déclenchent 1 (ou 3) requête(s) HTTP par frappe** — aucun debounce, aucun `AbortController` | −90 % d'appels réseau pendant la frappe ; supprime aussi un bug de réponses désordonnées | **Haute** | Très faible (`useDebouncedValue` existe déjà) | **DÉDUIT** |
| **C4** | **0 `React.memo`, 0 virtualisation, listes RH rendues intégralement** ; `HRModule.tsx` = 4421 l., 40 `useState`, **0 `useCallback`** | Élevé sur RH/gros tableaux, mais dépend de la volumétrie | Moyenne | Élevé (refonte structurelle) | **DÉDUIT** |
| **C5** | `ConfirmContext` : `value` **non mémoïsé** + état de saisie dans le provider global | Frappe fluide dans les modales « motif de rejet » | Haute | Très faible (1 `useMemo`) | **DÉDUIT** |
| **C6** | **Cascade auth → le chunk de route ne commence à se télécharger qu'après 3 aller-retours réseau** | −300 ms à −1,2 s au rechargement d'une page authentifiée | Moyenne (dépend du RTT réel en RDC) | Faible-moyen | **DÉDUIT** |
| **C7** | Génération PDF/Excel **100 % sur le thread principal**, aucun Web Worker | Supprime un gel de l'UI de plusieurs secondes sur les gros exports | Moyenne | Élevé (jsPDF en worker est délicat) | **DÉDUIT** |
| **C8** | Migration react-query **partielle** : 10 fichiers sur ~43 ; ~55 `useEffect`-fetch restants ; `useCachedResource.ts` est du **code mort** | Navigation instantanée sur les pages restantes | Moyenne | Élevé (chantier long) | **MESURÉ** (comptage) |

**Les 3 correctifs qui rapportent le plus : C1, C3, C2** — dans cet ordre. C1 seul rend jusqu'à 277 kB gz par navigation, coûte une demi-journée, et ne présente aucun risque fonctionnel. C3 coûte une heure. C2 est le seul qui demande une vraie décision d'architecture.

---

## C1 — jsPDF / xlsx tirés en import statique par 6 chunks de route ⚠️ LE PLUS RENTABLE

**Statut : MESURÉ** (sur le bundle produit, pas sur le code source seul).

### Symptôme utilisateur
L'utilisateur ouvre « Mon espace unité opérationnelle » ou « Comptabilité » : le squelette de page reste bloqué le temps de télécharger **~280 kB gzip** de bibliothèques PDF/Excel dont il ne se servira peut-être jamais. Sur une connexion 3G/4G congestionnée, c'est plusieurs secondes d'écran vide. Idem, à moindre échelle, sur Encaissements, Sorties de fonds et les deux écrans d'examen de dossier.

### Preuve

Test sur le bundle : quels chunks contiennent une arête d'import **statique** vers les vendors lourds ?

```
$ cd frontend/dist/assets
$ grep -l 'from"./vendor-xlsx-D_0l8YDs.js"' *.js
Comptabilite-PYnwtGfP.js  ImportBudgetPostes-…  ImportHistory-…  ImportModules-…
ImportTableauDossiers-…   ServicePortal-DandhFo5.js

$ grep -l 'from"./vendor-jspdf-DSi243q7.js"' *.js
Comptabilite-…  DossiersExamen-…  Encaissements-…  ExamenDossier-…
ServicePortal-…  SortiesFonds-…   + les 9 chunks utils/pdfGenerator*
```

Chaînes fautives, dans le source :

1. **`frontend/src/pages/ServicePortal.tsx:2-4`** — le pire cas. Trois imports statiques, alors que le fichier porte lui-même, **31 lignes plus bas**, un commentaire qui affirme le contraire :
```tsx
2: import { jsPDF } from 'jspdf'
3: import autoTable from 'jspdf-autotable'
4: import * as XLSX from 'xlsx'
...
35: // jsPDF/jspdf-autotable sont lourds : chargement dynamique au moment de l'action.
```
2. **`frontend/src/pages/Encaissements.tsx:25`** — `import { generateEncaissementsReportPDF } from '../utils/pdfGeneratorReports'` → `utils/pdfGeneratorReports.ts:1-2` importe statiquement `jspdf` + `jspdf-autotable`.
3. **`frontend/src/pages/SortiesFonds.tsx:43`** — `import { generateSortiesReportPDF } from '../utils/pdfGeneratorReports'`, même chaîne.
4. **`frontend/src/pages/DossiersExamen.tsx:33`** et **`frontend/src/pages/ExamenDossier.tsx:31`** — `import { refreshRequisitionBonBeforeExamen } from '../utils/requisitionBon'` → `utils/requisitionBon.ts:2` : `import { generateSingleRequisitionPDF } from './pdfGenerator'` → `utils/pdfGenerator.ts:1-2` : jspdf. Les deux pages portent elles aussi un commentaire « chargement dynamique au moment de l'action » qui ne correspond pas au code.
5. **`frontend/src/pages/Comptabilite.tsx:19-20`** — `ComptaEtatsPanel` → `utils/comptaExports.ts:10-11` (xlsx **et** pdfGeneratorReports), `ComptaEtatsFinanciersPanel` → `utils/comptaEtatsExports.ts:9-10` (idem).

### Chiffrage (MESURÉ, gzip -9)

| Route | JS de la page | Vendors tirés en plus | Total | Part de poids mort |
|---|---:|---:|---:|---:|
| `/services/mon-espace/:id` | 13,6 kB | jspdf 135,1 + xlsx 141,8 = **276,9** | 290,5 kB | **95 %** |
| `/comptabilite` | 19,8 kB | jspdf 135,1 + xlsx 141,8 = **276,9** | 296,7 kB | **93 %** |
| `/encaissements` | 25,5 kB (+4,8 pdfGenReports) | jspdf **135,1** | 165,4 kB | **82 %** |
| `/sorties-fonds` | 24,6 kB (+4,8) | jspdf **135,1** | 164,5 kB | **82 %** |
| `/dossiers-examen` | 9,8 kB (+16,2 pdfGenerator +26,9 police greatVibes) | jspdf **135,1** | 188,0 kB | **72 %** |
| `/examen-dossier/:id` | 4,9 kB (+16,2 +26,9) | jspdf **135,1** | 183,1 kB | **74 %** |

Note : `pdfGenerator` embarque en plus `greatVibes-DdnvmrXo.js` (26,9 kB gz — une police de signature en base64), qui suit donc jusque sur les écrans d'examen.

### Contre-preuve utile : le patron correct existe déjà dans le dépôt

`frontend/src/pages/Requisitions.tsx:36-40` fait exactement ce qu'il faut :
```ts
type PdfGeneratorReportsModule = typeof import('../utils/pdfGeneratorReports')
let _pdfGeneratorReportsModulePromise: Promise<PdfGeneratorReportsModule> | null = null
  if (!_pdfGeneratorReportsModulePromise) _pdfGeneratorReportsModulePromise = import('../utils/pdfGeneratorReports')
```
Résultat mesuré : `Requisitions-B6w-QEr6.js` n'a **aucune** arête vers `vendor-jspdf`. C'est la preuve que le correctif fonctionne et qu'il suffit de le répliquer.

### Coût / risque
**Faible.** 6 fichiers, patron de copie disponible, aucun changement de logique métier. Seule précaution : les handlers deviennent `async` (déjà le cas partout ailleurs) et il faut un état « génération en cours » pour éviter le double-clic. Risque de régression fonctionnelle : quasi nul, détectable au premier clic d'export.

### Fondement de l'estimation
Tailles gzip réelles des chunks émis + graphe d'import statique extrait du bundle. Le gain de temps ressenti dépend du débit : à 1,5 Mbit/s effectif, 277 kB ≈ **1,5 s** économisée par ouverture de `/comptabilite` ou `/services/mon-espace`. Non mesuré en conditions réelles.

---

## C2 — `Requisitions` : 5000 lignes chargées, puis 3 passes de filtre/tri non mémoïsées à chaque frappe

**Statut : DÉDUIT** (lecture de code ; la volumétrie réelle de la table `requisitions` n'a pas pu être mesurée — Docker mort).

### Symptôme utilisateur
La page Réquisitions met longtemps à s'afficher au premier chargement (téléchargement + parsing d'un JSON pouvant faire plusieurs Mo). Ensuite, taper dans « Rechercher par numéro ou objet » saccade : chaque caractère déclenche un re-rendu complet d'un composant de 3845 lignes, précédé de trois parcours complets du tableau.

### Preuve

**(a) Chargement massif** — `frontend/src/pages/Requisitions.tsx:290-310` :
```ts
const requisitionsQuery = useQuery({
  queryKey: requisitionsQueryKey,
  queryFn: async () => {
    const resp = await apiRequest('GET', '/requisitions', {
      params: {
        include: 'demandeur,validateur,approbateur,examinateur,caissier',
        ...
        limit: 5000,
        offset: 0,
      }
```
5000 lignes **avec 5 relations hydratées chacune**, en une seule réponse.

**(b) Trois passes non mémoïsées, dans le corps du composant** — `Requisitions.tsx:1672`, `:1701`, `:1711` :
```ts
1672:  const baseFilteredRequisitions = requisitionsList.filter(req => { … })   // passe 1
1701:  const statusCounts = (() => { baseFilteredRequisitions.forEach(…) })()   // passe 2 (IIFE)
1711:  const filteredRequisitions = baseFilteredRequisitions
         .filter(req => …)                                                     // passe 3
         .sort((a, b) => …)                                                    // + tri O(n log n)
```
Aucune n'est dans un `useMemo`. Elles s'exécutent à **chaque** rendu. Le filtre de la passe 1 fait, par ligne : un `toLowerCase()` sur la requête, une concaténation de chaîne pour le demandeur, 3 `includes`, et jusqu'à 3 `new Date()`.

**(c) Le déclencheur** — `Requisitions.tsx:2219-2221`, l'input est non contrôlé en debounce :
```tsx
value={searchQuery}
onChange={(e) => setSearchQuery(e.target.value)}
```
→ 1 rendu par frappe × 3 passes sur ≤ 5000 éléments.

**(d) Une mémoïsation qui ne sert à rien** — `Requisitions.tsx:1758-1762` :
```ts
const paginatedRequisitions = filteredRequisitions.slice(…)      // nouvelle référence chaque rendu
const selectablePageIds = useMemo(
  () => paginatedRequisitions.filter(canSelectRequisition).map(…),
  [paginatedRequisitions]                                         // ← ne peut jamais faire cache-hit
)
```

**(e) Bug corrélé — la `queryKey` ne couvre pas les paramètres envoyés au serveur.** `Requisitions.tsx:288` :
```ts
const requisitionsQueryKey = ['requisitions', filterServiceId, filterBudgetPosteId] as const
```
Or la `queryFn` (`:296-305`) envoie aussi `date_debut`, `date_fin`, `status`, `mode_paiement`, `type_requisition`, `search`, `objet`. Ces sept paramètres **ne provoquent aucun refetch** : ils sont figés à la valeur qu'ils avaient lors de la première exécution de la `queryFn`. C'est ce qui rend le filtrage client obligatoire aujourd'hui — et cela veut dire que le filtrage par dates est *silencieusement* appliqué avec de mauvaises bornes côté serveur. À traiter en même temps.

### Gain estimé et son fondement
- **Mémoïsation seule** (`useMemo` sur les 3 passes, clés sur les filtres) : supprime ~3n opérations par frappe. Sur 2000 lignes, ~6000 itérations dont des `new Date()` → de l'ordre de **10-30 ms de blocage par caractère** évités. Fondement : ordre de grandeur usuel (~5-10 µs/ligne pour ce type de prédicat) — **non mesuré**, aucun profil disponible.
- **Pagination serveur** (aligner sur ce que fait déjà `SortiesFonds.tsx:245-262` et `ExpertsComptables.tsx:313-314`) : divise le payload initial par ~100 et supprime le problème à la racine.

### Coût / risque
- Mémoïsation : **faible**, 30 min, aucun risque.
- Pagination serveur + `queryKey` complète : **moyen**. La sélection multi-lignes (`selectedIds`, `Requisitions.tsx:1135-1148`) et les compteurs par statut (`statusCounts`) supposent aujourd'hui d'avoir toute la liste en mémoire ; il faut un endpoint d'agrégation pour les compteurs. Risque fonctionnel réel — à faire avec des tests.

---

## C3 — Recherches sans debounce : une requête HTTP par frappe

**Statut : DÉDUIT.**

### Symptôme utilisateur
Taper « REQ-2026-0142 » (13 caractères) dans un de ces champs génère 13 (ou 39) requêtes HTTP. La liste clignote, saute d'un résultat à l'autre, et peut finir sur un résultat **faux** si une réponse ancienne arrive après une récente — il n'y a aucune annulation.

### Preuve — 3 emplacements

**1. `frontend/src/pages/ExpertsComptables.tsx:645-646` + `:331-333`** — le plus visible, la liste des experts-comptables :
```tsx
645:  value={search}
646:  onChange={(e) => setSearch(e.target.value)}
...
331:  useEffect(() => { loadExperts() },
333:    [search, filterStatutProf, filterActive, filterProvince, filterCategory, sortField, sortDirection, pageSize, page])
```
`search` est branché directement en dépendance d'effet → **1 requête `/experts-comptables` par caractère**.

**2. `frontend/src/pages/SortiesFonds.tsx:1871` + `:234-272`** — le pire des trois, car la `queryFn` fait **trois** appels :
```tsx
1871:  value={filterNumeroRequisition}
1872:  onChange={(e) => setFilterNumeroRequisition(e.target.value)}
```
`filterNumeroRequisition` est dans la `queryKey` (`:240`), et la `queryFn` (`:248-272`) exécute :
```ts
const [sortiesRes, reqRes, servicesRes] = await Promise.all([
  apiRequest('GET', '/sorties-fonds', …),
  apiRequest('GET', '/requisitions', { params: { …, limit: 300 } }),
  getServices({ active: true }),
])
```
→ **3 requêtes par frappe**, dont un `/requisitions?limit=300` et un `/services` totalement indépendants du champ tapé. Ces deux-là sont d'ailleurs refetchés aussi à chaque changement de page — ils devraient être des `useQuery` séparés avec leur propre clé.

**3. `frontend/src/pages/Settings.tsx:1815-1821`** — appel réseau **directement dans le `onChange`** :
```tsx
value={userSearch}
onChange={(e) => {
  const next = e.target.value
  setUserSearch(next)
  loadUsers({ page: 1, pageSize: usersPerPage, search: next })
}}
```

**Aggravant : `frontend/src/lib/apiClient.ts`** n'expose aucun `AbortSignal` (`grep -n "signal\|AbortController"` sur les 480 lignes → **0 occurrence**). Les requêtes obsolètes ne sont donc jamais annulées : elles consomment de la bande passante et un worker gunicorn chacune, et la dernière arrivée gagne.

### Contre-exemple : le dépôt sait déjà faire
`frontend/src/hooks/useDebouncedValue.ts` existe (300 ms par défaut) et `frontend/src/pages/Encaissements.tsx:111-112` l'utilise correctement :
```ts
const debouncedNumeroRecu = useDebouncedValue(filterNumeroRecu)
const debouncedClient = useDebouncedValue(filterClient)
```
`pages/Clients.tsx:78` et `pages/RemboursementTransport.tsx:744` ont chacun leur propre debounce artisanal. Trois pages seulement sur six.

### Gain estimé et fondement
Une saisie moyenne de 10 caractères passe de 10 (ou 30) requêtes à **1**. C'est ~90-97 % d'appels en moins sur ce geste. Côté backend, cela retire directement de la charge sur `/requisitions` et `/experts-comptables` — deux des endpoints identifiés comme lourds dans `docs/ANALYSE_PERFORMANCE.md §2`. Fondement : arithmétique sur le nombre de frappes, pas une mesure de latence.

### Coût / risque
**Très faible.** Remplacer `search` par `useDebouncedValue(search)` dans la dépendance/queryKey : 3 lignes par page. Ajouter `signal` à `apiClient` et le passer aux `queryFn` react-query : ~1 h, gain de robustesse en prime.

---

## C4 — Aucun `React.memo`, aucune virtualisation, listes RH intégrales

**Statut : DÉDUIT.**

### Symptôme utilisateur
Sur le module RH, toute interaction (frappe dans la recherche, ouverture d'une fiche, changement de filtre) redessine l'intégralité de la liste des agents. La sensation est celle d'une latence constante de quelques dizaines de millisecondes sur chaque clic.

### Preuve

**Densité de hooks (MESURÉ, comptage `grep -c`) :**

| Page | lignes | `useState` | `useEffect` | `useMemo` | `useCallback` | `memo` |
|---|---:|---:|---:|---:|---:|---:|
| `HRModule.tsx` | 4421 | 40 | 11 | 7 | **0** | 0 |
| `Settings.tsx` | 3648 | 22 | 10 | **1** | **0** | 0 |
| `Requisitions.tsx` | 3845 | 17 | 17 | 19 | **0** | 0 |
| `Rapports.tsx` | 2114 | 13 | 13 | 12 | **0** | 0 |
| `SecretariatPage.tsx` | 2252 | 18 | 2 | 8 | **0** | 0 |
| `Budget.tsx` | 1981 | 27 | 9 | 2 | 4 | 0 |
| `SortiesFonds.tsx` | 3432 | 20 | 13 | 15 | 14 | 0 |

`SortiesFonds.tsx` est le seul gros écran correctement instrumenté. `HRModule.tsx` et `Settings.tsx` sont à l'opposé : ~40 et ~22 sources de re-rendu, zéro handler stabilisé, donc **chaque fonction passée en prop est recréée à chaque rendu** — ce qui rendrait de toute façon un `React.memo` inopérant s'il était ajouté sans `useCallback`.

**Aucune pagination sur la liste des agents** — `frontend/src/api/hr.ts:440` :
```ts
export const getHREmployees = (params?: { q?: string; statut?: string }) =>
  apiRequest<HREmployee[]>('GET', '/hr/employees', { params })
```
Pas de `limit`/`offset` possible. Et le rendu (`frontend/src/pages/HRModule.tsx:846` cartes, `:970` tableau) fait `employees.map(...)` sur la totalité, sans fenêtrage.

**Filtre non mémoïsé dans le corps** — `frontend/src/pages/HRModule.tsx:375-381` :
```ts
const filteredEmployees = employees.filter((e) => {
  const haystack = `${e.matricule} ${fullName(e)} ${e.service?.libelle || ''} ${e.fonction?.libelle || ''}`.toLowerCase()
  const matchSearch = haystack.includes(search.toLowerCase())
  ...
})
```
Concaténation + deux `toLowerCase()` par ligne, à chaque rendu, donc à chaque frappe.

**Autres listes intégrales dans le même fichier :** `HRModule.tsx:1410` (`leaves.map`), `:1500` (`contracts.map`), `:1579` (`documents.map`), et `employees.map` répété en `<option>` aux lignes 1707, 1740, 1768 — trois listes déroulantes contenant chacune tous les agents.

**Aucune bibliothèque de virtualisation** dans `frontend/package.json` (ni `react-window`, ni `react-virtual`, ni `@tanstack/react-virtual`).

### Nuance honnête sur la hiérarchie
Les tableaux **financiers** sont, eux, correctement paginés côté serveur — ce n'est pas un problème général de l'application :
- `SortiesFonds.tsx:259-260` : `limit: pageSize, offset: (page - 1) * pageSize`
- `Encaissements.tsx:148-149` : idem, `pageSize` par défaut **15** (`:78`)
- `ExpertsComptables.tsx:313-314` : idem, `pageSize` **25** (`:244`)
- `Comptabilite.tsx:139-140` : idem, `pageSize` **20**
- `Settings.tsx` (utilisateurs) : `usersPerPage` **25**, pagination serveur

Les seules exceptions sont `Requisitions` (constat C2 : pagination **client** sur 5000 lignes, `:1758`, `pageSize` 50) et **RH** (aucune pagination du tout). `AgentTableauPage.tsx:481` tronque brutalement à `.slice(0, 50)` — pas de fuite mémoire, mais l'utilisateur ne voit jamais les lignes au-delà de la 50ᵉ, ce qui est un bug fonctionnel déguisé en optimisation.

### Gain estimé et fondement
Non chiffrable sans profilage ni volumétrie. **Si** l'ONEC a ~50-150 agents, l'impact est modéré et ce constat reste en 4ᵉ position. **Si** la liste dépasse le millier, il remonte devant C2. Il faut connaître `SELECT count(*) FROM hr_employees` avant d'investir ici — je n'ai pas pu l'obtenir.

### Coût / risque
**Élevé.** Découper `HRModule.tsx` (4421 l.) et `Settings.tsx` (3648 l.) par onglet, extraire les lignes en composants `memo`, stabiliser ~40 handlers avec `useCallback`. C'est plusieurs jours, avec un vrai risque de régression. **Ne pas commencer par là.** Le sous-ensemble rentable et bon marché : ajouter `limit`/`offset` à `getHREmployees` et mémoïser `filteredEmployees` (`HRModule.tsx:375`).

Bénéfice collatéral du découpage : `Settings-ClRifauB.js` fait **238 902 o / 60 363 gz** — le plus gros chunk de page de l'application, chargé en entier pour ouvrir n'importe lequel de ses onglets.

---

## C5 — `ConfirmContext` : la seule `value` de contexte non mémoïsée

**Statut : DÉDUIT.** Le commit 9478b9d annonce « mémoïsation des `value` des cinq Contexts ». Il y en a **six**, et celui-ci a été oublié.

### Symptôme utilisateur
Dans les modales de confirmation à saisie (motif de rejet, motif d'annulation), taper du texte fait re-rendre toutes les grosses pages abonnées au contexte, en arrière-plan. Sur Réquisitions ou Sorties de fonds, la frappe dans le champ « motif » saccade.

### Preuve — `frontend/src/contexts/ConfirmContext.tsx:100`
```tsx
return (
  <ConfirmContext.Provider value={{ confirm, confirmWithInput }}>
```
Objet littéral, recréé à chaque rendu du provider. Or le provider porte lui-même l'état de saisie — `ConfirmContext.tsx:39` :
```ts
const [inputValue, setInputValue] = useState('')
```
alimenté par `onChange={(e) => setInputValue(e.target.value)}` aux lignes **:114** (textarea) et **:122** (input).

Chaîne complète : frappe → `setInputValue` → re-rendu de `ConfirmProvider` → nouvelle référence de `value` → **tous les consommateurs de `ConfirmContext` re-rendent**. `{children}` lui-même est épargné (même référence d'élément, React court-circuite), mais pas les abonnés.

**17 fichiers consommateurs** (MESURÉ, `grep -rln "useConfirm"`), dont les six plus gros écrans : `Requisitions.tsx`, `SortiesFonds.tsx`, `HRModule.tsx`, `Settings.tsx`, `Budget.tsx`, `Encaissements.tsx`.

Pour comparaison, les cinq autres contextes sont corrects : `AuthContext.tsx:64`, `PermissionsContext.tsx:63`, `OrganisationSettingsContext.tsx:41`, `AppContext.tsx:150`, `NotificationContext.tsx:60` utilisent tous `useMemo`.

*Remarque mineure sur `NotificationContext.tsx:60-70`* : la `value` mémoïsée inclut le tableau `notifications`. À chaque apparition/disparition de toast, tous les consommateurs (19 fichiers) re-rendent. Le découplage classique (deux contextes, actions vs état) serait plus propre, mais l'impact est faible — un toast toutes les quelques minutes.

### Gain estimé et fondement
Supprime N re-rendus de composants de 2000-4400 lignes par caractère tapé, où N = nombre de pages montées abonnées (en pratique 1 à 2, l'app ne monte qu'une route à la fois). Gain réel donc modéré mais le correctif est trivial. Fondement : sémantique de React Context, pas une mesure.

### Coût / risque
**Très faible.** `const value = useMemo(() => ({ confirm, confirmWithInput }), [confirm, confirmWithInput])` — `confirm` et `confirmWithInput` sont déjà des `useCallback` stables (`:41`, et son homologue). Une ligne. Correctif plus complet : sortir le dialogue dans un composant enfant qui porte `inputValue`, pour que la frappe ne remonte pas au provider du tout.

---

## C6 — Cascade d'authentification : le chunk de route attend 3 aller-retours réseau

**Statut : DÉDUIT.**

### Symptôme utilisateur
Au rechargement (F5) d'une page authentifiée, ou en arrivant par une URL directe, l'écran affiche « Vérification de la session… » puis « Chargement des autorisations… » — et **ce n'est qu'ensuite** que le téléchargement du JavaScript de la page commence. L'attente réseau et le téléchargement sont séquentiels au lieu d'être parallèles.

### Preuve

**Étape 1-2, séquentielles** — `frontend/src/contexts/AuthContext.tsx:32-42` :
```ts
if (hasRefreshMarker()) {
  await refresh()          // aller-retour 1
  await reloadProfile()    // aller-retour 2 (GET /auth/me) — attend le premier
}
...
finally { setLoading(false) }
```

**Étape 3, déclenchée seulement après** — `frontend/src/contexts/PermissionsContext.tsx:25-51` : l'effet est gardé par `if (!user) { … return }` et sa dépendance est `[user?.id]`. Il ne peut donc partir qu'une fois l'étape 2 terminée. `OrganisationSettingsContext.tsx:35` est dans le même cas (`[user?.organisation_id]`).

**Le blocage du chunk** — `frontend/src/App.tsx:79-84` et `:104-107` :
```tsx
function PrivateRoute({ children }) {
  const { user, loading } = useAuth()
  if (loading) return <PageLoader label="Vérification de la session..." />
  ...
function ProtectedRoute({ children, permission }) {
  const { loading: authLoading } = useAuth()
  const { loading: permissionsLoading } = usePermissions()
  if (authLoading || permissionsLoading) return <PageLoader label="Chargement des autorisations..." />
```
Tant que le garde renvoie `PageLoader`, l'élément `lazy` n'est **jamais rendu** — donc `React.lazy` ne déclenche pas son `import()`, donc le navigateur ne demande pas le chunk. Séquence réelle : `refresh` → `me` → `menu-permissions` → **puis seulement** `GET /assets/Requisitions-….js` → puis les requêtes de données de la page. Cinq étapes en série.

### Gain estimé et fondement
3 RTT × latence. À 150 ms de RTT (fibre Kinshasa), ~450 ms de temps mort ; à 400 ms (4G congestionnée), ~1,2 s. Le chunk de route pèse 24-60 kB gz, donc son téléchargement se serait entièrement caché derrière l'attente auth. **Ce chiffrage repose sur des RTT hypothétiques : je n'ai mesuré aucune latence réelle.**

### Correctifs possibles, du moins cher au plus cher
1. **Préchargement du chunk en parallèle du contrôle d'auth** — dans `App.tsx`, appeler la fonction `lazy` correspondant à `window.location.pathname` dès le montage, sans attendre le garde. ~20 lignes, aucun risque, récupère la quasi-totalité du gain.
2. **Fusionner `/auth/me` et `/permissions/menu`** en un seul endpoint (ou faire renvoyer les permissions par `refresh`) : supprime un RTT. Nécessite une modification backend.
3. Rendre les gardes optimistes (afficher la page et n'invalider qu'en cas de refus) — plus risqué côté sécurité perçue, à éviter.

### Coût / risque
Correctif 1 : **faible**. Correctif 2 : **moyen** (touche le backend).

---

## C7 — Génération PDF/Excel entièrement sur le thread principal

**Statut : DÉDUIT.**

### Symptôme utilisateur
Cliquer sur « Exporter PDF » sur un gros rapport gèle l'onglet : plus de scroll, plus de clic, éventuellement le message « la page ne répond pas ». Aucun indicateur de progression n'est possible tant que le travail est synchrone.

### Preuve
**Aucun Web Worker dans tout le frontend** (MESURÉ) :
```
$ grep -rn "new Worker\|requestIdleCallback\|OffscreenCanvas" src/ --include=*.ts --include=*.tsx
(aucun résultat)
```
Le code de génération représente **5 881 lignes** réparties sur 9 modules (`utils/pdfGenerator*.ts`, `utils/compta*Exports.ts`), dont `utils/pdfGenerator.ts` seul fait 2 885 lignes avec 26 boucles de construction.

Les exports ré-interrogent le serveur en mode « tout charger » — `frontend/src/pages/Encaissements.tsx:451` et `frontend/src/pages/Rapports.tsx:1103-1104` demandent `limit: 5000`, puis construisent le classeur/le PDF ligne à ligne dans la boucle d'événements. `Rapports.tsx:1100-1104` fait bien le `import('xlsx')` en parallèle des fetches (bon patron), mais la construction qui suit est synchrone.

À noter : **ce n'est pas systématiquement mauvais.** Les exports serveur existent aussi (`AuditLogs.tsx:316` `/audit-logs/export-xlsx`, `ClotureCaisse.tsx:259` `/clotures/export-xlsx`), et le commit 9478b9d a déjà déplacé la génération openpyxl/reportlab **côté backend** dans un thread. Le chemin « export côté serveur » est donc disponible et éprouvé.

### Gain estimé et fondement
Non chiffrable sans exécution. Ordre de grandeur usuel pour `jspdf-autotable` : ~1-3 ms par ligne selon la complexité de la cellule → 5000 lignes ≈ **5 à 15 s de thread principal bloqué**. **C'est une extrapolation de la littérature, pas une mesure sur ce code.** Un test réel prendrait 10 minutes une fois l'app démarrable.

### Coût / risque
- **Web Worker pour jsPDF : élevé et fragile** (jsPDF touche au DOM pour les polices et l'API `html()`). Je ne le recommande pas en premier.
- **Alternative bien moins chère :** router les exports volumineux (> quelques centaines de lignes) vers les endpoints backend qui existent déjà, et ne garder la génération client que pour les pièces unitaires (un bon, un reçu, un bulletin) où elle est instantanée. Coût moyen, risque faible, et cela allège aussi C1 puisque moins de pages ont besoin de jsPDF.
- **Palliatif immédiat, quasi gratuit :** `xlsx` supporte `XLSX.write(wb, { type:'array' })` découpable ; et une simple boucle `await new Promise(r => setTimeout(r, 0))` tous les N blocs rend la main au navigateur et permet d'afficher une barre de progression.

---

## C8 — Migration react-query partielle, et un cache maison en code mort

**Statut : MESURÉ** (comptages).

### Symptôme utilisateur
Sur les pages non migrées, revenir en arrière recharge tout depuis zéro : écran de chargement, attente réseau, alors que les données ont été vues il y a dix secondes. L'expérience est incohérente — Réquisitions et Sorties de fonds reviennent instantanément (cache 30 s), Budget et RH non.

### Preuve

**Configuration react-query : correcte** — `frontend/src/App.tsx:361-368` :
```ts
const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false, retry: 1 } },
})
```
`refetchOnWindowFocus: false` élimine les refetch parasites au retour d'onglet. `gcTime` n'est pas défini → défaut v5 de 5 min, ce qui est raisonnable. **Rien à corriger ici.**

**Couverture : 10 fichiers sur ~43** (MESURÉ) — `useQuery` n'apparaît que dans :
`Dashboard.tsx`, `Requisitions.tsx`, `SortiesFonds.tsx`, `Rapports.tsx`, `Comptabilite.tsx`, `AuditSortie.tsx`, et 4 panneaux `components/comptabilite/`.

**Ce qui reste en `useEffect` + fetch manuel** (comptage par script, `useEffect` contenant `apiRequest`/`await getX`/`fetch`) :
```
Budget 7 · Requisitions 6 · Rapports 5 · Settings 5 · Login 5 · Dashboard 4
Encaissements 4 · RemboursementTransport 4 · AuditLogs 3 · ClotureCaisse 3
SortiesFonds 3 · Validation 3 · ExpertsComptables 2 · Checkout 2 · … (≈ 55 au total)
```
`Budget.tsx` (1981 l., 7 fetches manuels, 2 `useMemo`) et `HRModule.tsx` (chargement complet par onglet, `HRModule.tsx:371-378`, `:399-406`, `:415-424`…) sont les plus gros absents.

**Code mort à supprimer :** `frontend/src/hooks/useCachedResource.ts` (101 lignes) implémente un stale-while-revalidate maison avec un `Map` global. `grep -rln "useCachedResource"` → **le fichier lui-même uniquement, aucun consommateur**. Il a été écrit avant l'adoption de react-query et n'a jamais été branché. Le garder entretient la confusion sur la stratégie de cache.

### Gain estimé et fondement
Sur une page migrée, un retour arrière dans les 30 s coûte 0 requête au lieu de N. Sur `Budget.tsx`, cela ferait 7 requêtes économisées par aller-retour. Fondement : comptage statique des `useEffect`-fetch, pas une mesure de temps.

### Coût / risque
**Élevé en volume, faible unitairement.** ~55 conversions, chacune mécanique mais chacune demandant de vérifier les invalidations après mutation (le risque réel : afficher un solde de caisse périmé après un paiement). À faire par lots, en commençant par les données de référence peu mutables (`getServices`, `getBudgetPostes`, `getPrintSettings`) qui sont refetchées par presque toutes les pages et ne changent presque jamais.

---

## Constats mineurs (à ne pas prioriser)

- **`hooks/useMobile.ts:19-27`** — écouteur `resize` non throttlé appelant `setIsMobile` à chaque événement. React court-circuite quand le booléen ne change pas, donc l'impact se limite à une comparaison par événement. `window.matchMedia` serait plus propre. Négligeable.
- **`pages/AgentTableauPage.tsx:481`** — `dossiers.slice(0, 50)` sans pagination ni indication : les lignes au-delà de la 50ᵉ sont invisibles. **C'est un bug fonctionnel**, pas une optimisation.
- **Brotli absent** de `frontend/nginx.conf` (gzip seul, `:14-19`). Brotli apporterait ~15-20 % de plus sur les gros chunks JS, soit ~20 kB gz sur `vendor-jspdf`. Nécessite `ngx_brotli` dans l'image nginx. À considérer **après** C1 — inutile de mieux compresser ce qu'on peut ne pas envoyer du tout.
- **CSS : 752 kB bruts au total**, dont `Requisitions.module.css` 46,6 kB et `Encaissements.module.css` 48,1 kB (9,7 kB gz chacun). Correctement découpé par route, pas un problème.
- **`SortiesFonds.tsx:249-272`** — la `queryFn` regroupe `/sorties-fonds`, `/requisitions?limit=300` et `/services` dans un `Promise.all`. Bon pour la latence (pas de cascade), mauvais pour le cache : les deux dernières ressources sont refetchées à chaque changement de page ou de filtre alors qu'elles ne dépendent d'aucun des deux. À scinder en `useQuery` séparés.

---

## Ce que je n'ai pas pu vérifier

**Rien de ce qui suit n'est estimé dans ce rapport ; ce sont des trous, pas des non-problèmes.**

1. **Aucune mesure d'exécution.** Docker mort → pas de backend, pas de base, pas d'application démarrable. Aucun profil React DevTools, aucun Lighthouse, aucune trace Performance, aucun waterfall réseau. Tous les temps cités (450 ms de cascade auth, 1,5 s sur `/comptabilite`, 5-15 s de gel à l'export) sont des **extrapolations à partir de tailles et de RTT hypothétiques**. Le seul socle mesuré est le bundle : tailles brutes, tailles gzip, et graphe d'imports statiques extrait des chunks.

2. **La volumétrie réelle des données.** Combien de réquisitions dans la fenêtre de 30 jours par défaut ? Combien d'agents dans `hr_employees` ? Combien d'experts-comptables ? Sans ces chiffres, C2 et C4 ne peuvent pas être départagés : si la table `requisitions` contient 80 lignes, le `limit: 5000` est inoffensif et C2 tombe au 6ᵉ rang ; si elle en contient 4000, il passe devant C1.

3. **Le comportement réel des `queryFn` à `queryKey` incomplète.** J'ai déduit de la lecture du code que `Requisitions.tsx:288` ne refetche pas sur changement de dates/statut. Il faudrait le confirmer par l'onglet Réseau — c'est peut-être aussi un bug de fraîcheur des données, pas seulement de performance.

4. **Le coût CPU réel du filtre/tri de `Requisitions.tsx:1672-1735`.** Un simple `console.time` autour de ces trois blocs donnerait le chiffre exact en une minute. Je ne l'ai pas.

5. **La durée réelle des exports PDF/Excel** et le seuil de lignes à partir duquel l'UI devient inutilisable. Mesurable en 10 minutes une fois l'app démarrable.

6. **La latence réseau réelle** entre les postes utilisateurs (Kinshasa) et l'API. C'est le multiplicateur de C6 : sans elle, je ne peux pas dire si la cascade auth coûte 300 ms ou 1,5 s.

7. **Le taux de rebond du cache HTTP en production.** `immutable` est bien configuré (`nginx.conf:70-71`), mais je ne peux pas vérifier qu'un CDN ou un proxy intermédiaire ne le neutralise pas.

8. **Le comportement mobile.** Aucun test sur appareil réel ; les CPU mobiles amplifient d'un facteur 4 à 6 tous les coûts de rendu de C2, C4 et C7.
