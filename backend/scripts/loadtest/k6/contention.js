// Test de CONTENTION D'ECRITURE cible - ONEC Smart.
//
// Objectif : provoquer deliberement la serialisation, pas la simuler.
// Le scenario `journeys.js` repartit les ecritures sur 8 services et 300
// postes : la contention y est diluee. Ici on fait l'inverse — tous les
// utilisateurs virtuels visent LA MEME ligne de base.
//
// Trois foyers, tous documentes :
//
//  1. ND (note de debit) : sequence CENTRALE au tenant, service_id = NULL
//     (backend/app/api/v1/endpoints/encaissements.py:690). Une seule ligne de
//     `document_sequences` pour tout le tenant. C'est le pire cas de
//     l'application : chaque POST /encaissements passe par le
//     `INSERT ... ON CONFLICT DO UPDATE ... RETURNING counter` de
//     backend/app/services/document_sequences.py:23-52, plus la boucle de
//     50 tentatives de encaissements.py:1437 en cas de collision, plus un
//     SELECT ... FOR UPDATE sur budget_postes (encaissements.py:309-315) et sur
//     caisse_centrale.
//
//  2. REQ : sequence PAR SERVICE (requisition_service.py:463). En pointant un
//     seul service on reproduit exactement le scenario de
//     backend/tests/test_document_sequences_concurrency.py (10/25/50/100
//     reservations concurrentes), mais a travers la pile HTTP complete et non
//     en appelant directement le service.
//
//  3. PAY : sequence par service ET verrou FOR UPDATE sur la ligne unique
//     `caisse_centrale` du tenant (sorties_fonds.py:1564, sorties_fonds.py:1603).
//
// Lancement :
//   k6 run -e MODE=nd  -e VUS=100 -e DURATION=3m contention.js
//   k6 run -e MODE=req -e VUS=100 -e DURATION=3m contention.js
//   k6 run -e MODE=pay -e VUS=50  -e DURATION=3m contention.js
//
// Le controle d'UNICITE des numeros ne se fait pas ici mais en SQL apres le
// tir : voir observe/pg_after.sql (requetes « doublons de numerotation »).

import exec from 'k6/execution';
import { Counter } from 'k6/metrics';
import { CTX, ok, post, get, uid, money, adminToken, currentUser } from './lib.js';

const MODE = (__ENV.MODE || 'nd').toLowerCase();
const VUS = parseInt(__ENV.VUS || '100', 10);
const DURATION = __ENV.DURATION || '3m';

// Cible unique : premier service, premier poste recette, premier poste depense.
const SERVICE = CTX.services[0];
const POSTE_RECETTE = CTX.postes_recette[0];
const POSTE_DEPENSE = CTX.postes_depense[0];

const conflits = new Counter('conflits_409');
const refus_metier = new Counter('refus_400');
const erreurs_5xx = new Counter('erreurs_5xx');

const EXEC_PAR_MODE = { nd: 'contentionND', req: 'contentionREQ', pay: 'contentionPAY' };

export const options = {
  scenarios: {
    contention: {
      // Pas de think time : on cherche la collision, pas le realisme.
      executor: 'constant-vus',
      vus: VUS,
      duration: DURATION,
      exec: EXEC_PAR_MODE[MODE] || 'contentionND',
    },
  },
  thresholds: {
    // CIBLES a valider, pas des mesures.
    // Le contrat metier attendu : aucune erreur serveur, aucune perte de
    // numero, et une latence qui ne s'effondre pas quand la concurrence monte.
    'erreurs_5xx': ['count<1'],
    'http_req_failed': ['rate<0.01'],
    'http_req_duration': ['p(50)<1000', 'p(95)<3000', 'p(99)<6000'],
  },
};

function suivre(res) {
  if (res.status >= 500) erreurs_5xx.add(1);
  if (res.status === 409) conflits.add(1);
  if (res.status === 400) refus_metier.add(1);
  return res;
}

// --- 1. Sequence ND centrale (+ caisse + poste budgetaire uniques) ----------
export function contentionND() {
  const u = currentUser();
  const montant = money(100, 5000);
  const res = suivre(post('/encaissements', u.token, {
    type_client: 'autre',
    client_nom: `Contention ${uid()}`,
    libelle: 'Encaissement de contention',
    montant: montant,
    montant_total: montant,
    mode_paiement: 'cash',
    canal: 'CAISSE',
    montant_paye: montant,
    montant_percu: montant,
    devise_perception: 'USD',
    statut_paiement: 'complet',
    budget_poste_id: POSTE_RECETTE.id,   // MEME poste pour tous : FOR UPDATE serialise
    service_id: SERVICE.id,
  }, 'encaissement_create', 'contention_nd'));
  ok(res, 'encaissement_create', [201, 409]);
}

// --- 2. Sequence REQ d'un service unique ------------------------------------
export function contentionREQ() {
  const auteur = adminToken(0);
  const viseur = adminToken(1);
  const montant = money(500, 8000);

  const creation = suivre(post('/requisitions', auteur, {
    objet: `Contention requisition ${uid()}`,
    mode_paiement: 'cash',
    type_requisition: 'classique',
    montant_total: montant,
    devise: 'USD',
    service_id: SERVICE.id,             // MEME service : une seule ligne de sequence REQ
    lignes: [{
      budget_poste_id: POSTE_DEPENSE.id, // MEME poste : recalcul d'engagement concurrent
      rubrique: POSTE_DEPENSE.libelle.slice(0, 200),
      description: `Ligne contention ${uid()}`,
      quantite: 1,
      montant_unitaire: montant,
      montant_total: montant,
      devise: 'USD',
    }],
  }, 'requisition_create', 'contention_req'));
  if (!ok(creation, 'requisition_create', [200, 201])) return;

  const id = creation.json('id');
  // Chaine d'ecritures immediate : c'est la ou le FOR UPDATE de
  // vise_requisition_logic (requisition_service.py:915) se voit.
  const validation = suivre(post(`/requisitions/${id}/validate`, auteur, {}, 'requisition_validate', 'contention_req'));
  if (!ok(validation, 'requisition_validate')) return;
  const visa = suivre(post(`/requisitions/${id}/vise`, viseur, {}, 'requisition_vise', 'contention_req'));
  ok(visa, 'requisition_vise');
}

// --- 3. Sequence PAY + verrou caisse_centrale -------------------------------
export function contentionPAY() {
  const stock = CTX.requisitions_approuvees;
  const index = exec.scenario.iterationInTest;
  if (!stock || index >= stock.length) {
    console.error('Stock de requisitions APPROUVEE epuise : rallongez --approuvees dans mint_tokens.py');
    return;
  }
  const cible = stock[index];
  const caissier = adminToken(2);
  suivre(get(`/sorties-fonds/requisitions/${cible.id}/solde`, caissier, 'sortie_solde', 'contention_pay'));
  const res = suivre(post('/sorties-fonds', caissier, {
    type_sortie: 'requisition',
    requisition_id: cible.id,
    service_id: cible.service_id,
    budget_poste_id: cible.budget_poste_id,
    montant_paye: cible.montant,
    mode_paiement: 'cash',
    devise: 'USD',
    canal: 'CAISSE',                    // toutes les sorties frappent la MEME ligne caisse_centrale
    motif: `Contention paiement ${uid()}`,
    beneficiaire: `Beneficiaire ${uid()}`,
  }, 'sortie_create', 'contention_pay'));
  ok(res, 'sortie_create', [200, 201]);
}
