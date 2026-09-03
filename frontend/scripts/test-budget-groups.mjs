/**
 * Vérifie la règle de dépassement budgétaire des groupes de dépense.
 *
 * Pourquoi un script plutôt qu'un test de framework : le projet n'embarque
 * aucun exécuteur de tests, et l'environnement n'a pas d'accès réseau pour en
 * installer un. On se sert donc du `typescript` déjà présent en dépendance pour
 * transpiler le seul module visé, puis on l'exécute avec `node:assert`. Même
 * esprit que `audit-floating-ui.mjs` : une vérification qui tourne avec ce que
 * le dépôt contient déjà.
 *
 *   npm run test:budget-groups
 */
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const racine = new URL('..', import.meta.url).pathname
const source = join(racine, 'src/utils/budgetGroups.ts')
// Sortie dans node_modules : le dossier est déjà ignoré par git, et il reste
// dans le paquet ESM (`"type": "module"`) — sans quoi l'import échouerait.
const sortie = mkdtempSync(join(racine, 'node_modules', '.budget-groups-'))

let module
try {
  execFileSync(
    process.execPath,
    [
      join(racine, 'node_modules/typescript/bin/tsc'),
      source,
      '--outDir', sortie,
      '--module', 'esnext',
      '--target', 'es2020',
      '--moduleResolution', 'bundler',
    ],
    { stdio: 'pipe' },
  )
  module = await import(pathToFileURL(join(sortie, 'budgetGroups.js')).href)
} catch (error) {
  console.error('Transpilation ou chargement du module impossible :')
  console.error(error.stdout?.toString() || error.message)
  process.exit(1)
}

const { sousTotalGroupeUsd, trouverGroupeEnDepassement } = module

// Taux fictif : 2000 CDF pour 1 USD.
const toUsd = (montant, devise) => {
  const valeur = Number(montant ?? 0)
  return devise === 'CDF' ? valeur / 2000 : valeur
}

const ligne = (montant, devise = 'USD') => ({ montant_total: montant, devise })
const groupe = (budget_poste_id, lignes) => ({ budget_poste_id, lignes })

const echecs = []
function verifier(intitule, fn) {
  try {
    fn()
  } catch (error) {
    echecs.push(`${intitule}\n    ${error.message.split('\n')[0]}`)
  }
}

verifier('sous-total : additionne les lignes du groupe', () => {
  assert.equal(sousTotalGroupeUsd(groupe(1, [ligne(300), ligne(200)]), toUsd), 500)
})

verifier('sous-total : convertit le CDF vers la devise pivot', () => {
  assert.equal(sousTotalGroupeUsd(groupe(1, [ligne(100), ligne(2000, 'CDF')]), toUsd), 101)
})

verifier('sous-total : un groupe vide vaut zéro', () => {
  assert.equal(sousTotalGroupeUsd(groupe(1, []), toUsd), 0)
})

// --- Le cœur de la règle -----------------------------------------------------
// C'est la raison d'être du groupement : avant lui, le contrôle comparait
// CHAQUE LIGNE au disponible. Deux lignes de 300 sur un poste qui n'a que 500
// passaient donc toutes les deux, et la réquisition franchissait le plafond.
verifier('DÉPASSEMENT : deux lignes du même poste se cumulent avant comparaison', () => {
  const groupes = [groupe(1, [ligne(300), ligne(300)])]
  const trouve = trouverGroupeEnDepassement(groupes, {
    toUsd,
    disponiblePourPoste: () => 500,
    groupeSansPosteDepasse: true,
  })
  assert.ok(trouve, 'le cumul 600 > 500 doit être détecté')
  // Contre-épreuve : prises isolément, aucune des deux lignes ne dépasse.
  assert.ok(sousTotalGroupeUsd(groupe(1, [ligne(300)]), toUsd) <= 500)
})

verifier('sous le disponible : rien à signaler', () => {
  const groupes = [groupe(1, [ligne(200), ligne(200)])]
  assert.equal(
    trouverGroupeEnDepassement(groupes, {
      toUsd,
      disponiblePourPoste: () => 500,
      groupeSansPosteDepasse: true,
    }),
    undefined,
  )
})

verifier('égalité stricte : consommer tout le disponible ne dépasse pas', () => {
  const groupes = [groupe(1, [ligne(500)])]
  assert.equal(
    trouverGroupeEnDepassement(groupes, {
      toUsd,
      disponiblePourPoste: () => 500,
      groupeSansPosteDepasse: true,
    }),
    undefined,
  )
})

verifier('chaque poste a son propre plafond', () => {
  const groupes = [groupe(1, [ligne(400)]), groupe(2, [ligne(400)])]
  const disponibles = { 1: 500, 2: 300 }
  const trouve = trouverGroupeEnDepassement(groupes, {
    toUsd,
    disponiblePourPoste: (id) => disponibles[id] ?? null,
    groupeSansPosteDepasse: true,
  })
  assert.equal(trouve?.budget_poste_id, 2, 'seul le poste 2 (400 > 300) dépasse')
})

// --- Les deux appelants ne veulent pas la même chose d'un poste inconnu ------
verifier('poste inconnu : dépassement à la validation de la pièce', () => {
  const groupes = [groupe(null, [ligne(10)])]
  assert.ok(
    trouverGroupeEnDepassement(groupes, {
      toUsd,
      disponiblePourPoste: () => null,
      groupeSansPosteDepasse: true,
    }),
  )
})

verifier("poste inconnu : hors sujet pour l'allocation du service", () => {
  const groupes = [groupe(null, [ligne(10)])]
  assert.equal(
    trouverGroupeEnDepassement(groupes, {
      toUsd,
      disponiblePourPoste: () => null,
      groupeSansPosteDepasse: false,
    }),
    undefined,
  )
})

verifier('le CDF est converti avant comparaison', () => {
  // 1 200 000 CDF = 600 USD, au-dessus d'un disponible de 500.
  const groupes = [groupe(1, [ligne(1200000, 'CDF')])]
  assert.ok(
    trouverGroupeEnDepassement(groupes, {
      toUsd,
      disponiblePourPoste: () => 500,
      groupeSansPosteDepasse: true,
    }),
  )
})

rmSync(sortie, { recursive: true, force: true })

if (echecs.length > 0) {
  console.error(`\n${echecs.length} échec(s) :\n`)
  echecs.forEach((echec) => console.error(`  ✗ ${echec}`))
  process.exit(1)
}

console.log('budget-groups : 10 vérifications passées')
