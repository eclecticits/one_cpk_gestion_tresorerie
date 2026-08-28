// Campagne de charge ONEC Smart - 7 parcours metier.
//
// Chaque sequence d'appels ci-dessous est relevee dans le code, pas imaginee :
// les references `fichier:ligne` sont donnees en commentaire au-dessus de
// chaque parcours et reprises dans perf-loadtest.md.
//
// Lancement type :
//   k6 run -e BASE_URL=http://localhost:8000/api/v1 -e VUS=100 -e DURATION=10m journeys.js

import exec from 'k6/execution';
import { Counter, Trend } from 'k6/metrics';
import {
  BASE_URL, CTX, http, headers, ok, get, post, think, uid, money, periode,
  currentUser, adminToken, randomService, randomPosteRecette, randomPosteDepense,
} from './lib.js';

const VUS = parseInt(__ENV.VUS || '100', 10);
const DURATION = __ENV.DURATION || '10m';
const RAMP = __ENV.RAMP || '1m';
// EXPORT_RATE=0 retire completement le scenario d'export : k6 refuse un
// constant-arrival-rate a 0. C'est la variable qui isole le cout des exports
// du reste de la charge — mesure du 27/08 : un export d'exercice complet
// occupe un worker plusieurs dizaines de secondes, 4/min en demandent plus
// que la machine n'en a.
const EXPORT_RATE = parseInt(__ENV.EXPORT_RATE || '4', 10);

// Repartition du parc de VU entre parcours. Les proportions suivent le mix
// deja utilise par backend/scripts/load_campaign.py:489-524 (lectures
// largement majoritaires) en y ajoutant les parcours d'ecriture manquants.
function part(fraction) {
  return Math.max(1, Math.round(VUS * fraction));
}

const erreursServeur = new Counter('erreurs_5xx');
const saturation = new Counter('reponses_saturation'); // 502/503/504
const cycleRequisition = new Trend('cycle_requisition_complet_ms', true);

function comptabiliser(res) {
  if (res.status >= 500) erreursServeur.add(1);
  if (res.status === 502 || res.status === 503 || res.status === 504) saturation.add(1);
  return res;
}

export const options = {
  discardResponseBodies: false,
  scenarios: {
    // 1. Connexion reelle. Volontairement minuscule : POST /auth/login est
    //    limite a 3 appels / 3 minutes / IP (auth.py:307). Un debit superieur
    //    mesurerait l'anti-bruteforce, pas l'application.
    login_probe: {
      executor: 'constant-arrival-rate',
      rate: 2, timeUnit: '3m', duration: DURATION,
      preAllocatedVUs: 1, maxVUs: 2,
      exec: 'parcoursConnexion',
      tags: { journey: 'login' },
    },
    // 2. Chemin critique : arrivee sur le tableau de bord.
    dashboard: {
      executor: 'ramping-vus', startVUs: 0, gracefulRampDown: '30s',
      stages: [{ duration: RAMP, target: part(0.25) }, { duration: DURATION, target: part(0.25) }],
      exec: 'parcoursDashboard',
    },
    // 3. Grosses listes + filtrage.
    listes: {
      executor: 'ramping-vus', startVUs: 0, gracefulRampDown: '30s',
      stages: [{ duration: RAMP, target: part(0.25) }, { duration: DURATION, target: part(0.25) }],
      exec: 'parcoursListes',
    },
    // 4. Budget et rapports (lectures lourdes).
    rapports: {
      executor: 'ramping-vus', startVUs: 0, gracefulRampDown: '30s',
      stages: [{ duration: RAMP, target: part(0.2) }, { duration: DURATION, target: part(0.2) }],
      exec: 'parcoursRapports',
    },
    // 5. Saisie d'un encaissement (ecriture).
    encaissement: {
      executor: 'ramping-vus', startVUs: 0, gracefulRampDown: '30s',
      stages: [{ duration: RAMP, target: part(0.12) }, { duration: DURATION, target: part(0.12) }],
      exec: 'parcoursEncaissement',
    },
    // 6. Cycle de requisition : creation -> validation technique -> visa.
    requisition: {
      executor: 'ramping-vus', startVUs: 0, gracefulRampDown: '30s',
      stages: [{ duration: RAMP, target: part(0.08) }, { duration: DURATION, target: part(0.08) }],
      exec: 'parcoursCycleRequisition',
    },
    // 7. Sortie de fonds sur requisition approuvee.
    sortie: {
      executor: 'ramping-vus', startVUs: 0, gracefulRampDown: '30s',
      stages: [{ duration: RAMP, target: part(0.05) }, { duration: DURATION, target: part(0.05) }],
      exec: 'parcoursSortieFonds',
    },
    // 8. Export Excel : debit fixe et bas. Un export est un pic CPU dans le
    //    worker (openpyxl), pas une action repetee par tous les utilisateurs.
    export_excel: {
      executor: 'constant-arrival-rate',
      rate: Math.max(EXPORT_RATE, 1), timeUnit: '1m', duration: DURATION,
      preAllocatedVUs: 4, maxVUs: 10,
      exec: 'parcoursExport',
      tags: { journey: 'export' },
    },
  },

  // --- CIBLES a valider. Ce ne sont PAS des mesures : aucune campagne n'a ete
  // executee pour produire ce fichier. Elles sont derivees du critere d'entree
  // de docs/PERFORMANCE_WORKER_SCALING_20260817.md (erreurs < 1 %, p95 < 3 s)
  // en le declinant par parcours : un tableau de bord n'a pas le meme budget
  // de latence qu'un export Excel.
  thresholds: {
    'http_req_failed': ['rate<0.01'],
    'erreurs_5xx': ['count<1'],
    'reponses_saturation': ['count<1'],

    'http_req_duration{journey:dashboard}': ['p(50)<400', 'p(95)<1500', 'p(99)<3000'],
    'http_req_failed{journey:dashboard}': ['rate<0.005'],

    'http_req_duration{journey:listes}': ['p(50)<600', 'p(95)<2000', 'p(99)<4000'],
    'http_req_failed{journey:listes}': ['rate<0.01'],

    'http_req_duration{journey:rapports}': ['p(50)<900', 'p(95)<3000', 'p(99)<6000'],
    'http_req_failed{journey:rapports}': ['rate<0.01'],

    'http_req_duration{journey:encaissement}': ['p(50)<700', 'p(95)<2000', 'p(99)<4000'],
    'http_req_failed{journey:encaissement}': ['rate<0.01'],

    'http_req_duration{journey:requisition}': ['p(50)<800', 'p(95)<2500', 'p(99)<5000'],
    'http_req_failed{journey:requisition}': ['rate<0.01'],
    'cycle_requisition_complet_ms': ['p(95)<7000'],

    'http_req_duration{journey:sortie}': ['p(50)<900', 'p(95)<2500', 'p(99)<5000'],
    'http_req_failed{journey:sortie}': ['rate<0.01'],

    'http_req_duration{journey:export}': ['p(95)<10000', 'p(99)<20000'],
    'http_req_failed{journey:export}': ['rate<0.02'],

    'http_req_duration{journey:login}': ['p(95)<2000'],
  },
};

// Le scenario d'export ne se desactive pas par un debit nul (k6 exige rate > 0) :
// on le retire de la liste. Sans cette porte, impossible de mesurer les six autres
// parcours sans que les exports monopolisent les workers.
if (EXPORT_RATE <= 0) {
  delete options.scenarios.export_excel;
  delete options.thresholds['http_req_duration{journey:export}'];
  delete options.thresholds['http_req_failed{journey:export}'];
}

// ---------------------------------------------------------------------------
// 1. CONNEXION
// POST /auth/login                       backend/app/api/v1/endpoints/auth.py:306
// puis le front enchaine sur le contexte : GET /auth/me (auth.py:794) et
// GET /permissions/menu (permissions.py:17), cf. frontend/src/api/auth.ts:115
// et frontend/src/api/permissions.ts:4.
// ---------------------------------------------------------------------------
export function parcoursConnexion() {
  const compte = CTX.identifiants_plein_droit[exec.scenario.iterationInTest % CTX.identifiants_plein_droit.length];
  const res = comptabiliser(
    http.post(
      `${BASE_URL}/auth/login`,
      JSON.stringify({ email: compte.email, password: compte.password, tenant_id: CTX.organisation_id }),
      { headers: { 'Content-Type': 'application/json', 'X-Tenant-ID': String(CTX.organisation_id) },
        tags: { journey: 'login', name: 'auth_login' } }
    )
  );
  // 429 attendu si le tir depasse la fenetre anti-bruteforce : c'est une
  // information, pas un echec applicatif.
  ok(res, 'auth_login', [200, 429]);
  if (res.status !== 200) return;
  const token = res.json('access_token');
  comptabiliser(get('/auth/me', token, 'auth_me', 'login'));
  comptabiliser(get('/permissions/menu', token, 'permissions_menu', 'login'));
}

// ---------------------------------------------------------------------------
// 2. TABLEAU DE BORD (chemin critique de tous les utilisateurs)
// Sequence exacte du front : frontend/src/pages/Dashboard.tsx:279-288 lance en
// parallele (Promise.all) 5 appels, apres GET /permissions/menu.
//   GET /dashboard/stats?...&devise=USD   dashboard.py:77
//   GET /dashboard/stats?...&devise=CDF
//   GET /budget/summary                   budget.py:985
//   GET /tresorerie/soldes                treasury.py:35
//   GET /print-settings                   settings.py (prefix /print-settings)
// ---------------------------------------------------------------------------
export function parcoursDashboard() {
  const u = currentUser();
  const p = periode(30);
  const qs = `period_type=month&date_debut=${p.date_debut}&date_fin=${p.date_fin}`;

  comptabiliser(get('/auth/me', u.token, 'auth_me', 'dashboard'));
  comptabiliser(get('/permissions/menu', u.token, 'permissions_menu', 'dashboard'));

  const lot = http.batch([
    ['GET', `${BASE_URL}/dashboard/stats?${qs}&devise=USD`, null, { headers: headers(u.token), tags: { journey: 'dashboard', name: 'dashboard_stats_usd' } }],
    ['GET', `${BASE_URL}/dashboard/stats?${qs}&devise=CDF`, null, { headers: headers(u.token), tags: { journey: 'dashboard', name: 'dashboard_stats_cdf' } }],
    ['GET', `${BASE_URL}/budget/summary`, null, { headers: headers(u.token), tags: { journey: 'dashboard', name: 'budget_summary' } }],
    ['GET', `${BASE_URL}/tresorerie/soldes`, null, { headers: headers(u.token), tags: { journey: 'dashboard', name: 'tresorerie_soldes' } }],
    ['GET', `${BASE_URL}/print-settings`, null, { headers: headers(u.token), tags: { journey: 'dashboard', name: 'print_settings' } }],
  ]);
  lot.forEach(comptabiliser);
  ok(lot[0], 'dashboard_stats_usd');
  ok(lot[2], 'budget_summary');
  think(3, 8); // on reste sur le tableau de bord avant de naviguer
}

// ---------------------------------------------------------------------------
// 3. GROSSES LISTES ET FILTRAGE
// Encaissements : frontend/src/pages/Encaissements.tsx, endpoint
//   GET /encaissements  encaissements.py:773 (limit max 5000, include_summary)
// Requisitions : frontend/src/pages/Requisitions.tsx:293-308 demande
//   include=demandeur,validateur,... ET limit=5000 — la liste n'est pas
//   paginee cote client, c'est le pire cas de lecture de l'application.
//   GET /requisitions   requisitions.py:932
// ---------------------------------------------------------------------------
export function parcoursListes() {
  const u = currentUser();
  const p = periode(90);
  const svc = randomService();

  // Premiere page + totaux, comme a l'ouverture de l'ecran.
  comptabiliser(get(
    `/encaissements?limit=50&offset=0&include_summary=true&include=expert_comptable&date_debut=${p.date_debut}&date_fin=${p.date_fin}`,
    u.token, 'encaissements_page1', 'listes'));
  think(1, 3);

  // Filtrage : statut + canal + poste budgetaire.
  const poste = randomPosteRecette();
  comptabiliser(get(
    `/encaissements?limit=50&offset=0&include_summary=true&statut_paiement=complet&canal=CAISSE&budget_poste_id=${poste.id}&date_debut=${p.date_debut}&date_fin=${p.date_fin}`,
    u.token, 'encaissements_filtre', 'listes'));
  think(1, 3);

  // Pagination profonde (offset eleve = tri sur un gros ensemble).
  const offset = 1000 + Math.floor(Math.random() * 4000);
  comptabiliser(get(
    `/encaissements?limit=50&offset=${offset}&order=date_encaissement.desc`,
    u.token, 'encaissements_offset', 'listes'));
  think(1, 2);

  // La liste des requisitions telle que le front la demande vraiment.
  comptabiliser(get(
    `/requisitions?include=demandeur,validateur,approbateur,examinateur,caissier&type_requisition=classique` +
    `&date_debut=${p.date_debut}&date_fin=${p.date_fin}&limit=5000&offset=0`,
    u.token, 'requisitions_liste_5000', 'listes'));
  think(2, 5);

  // Filtrage par service + statut, puis recherche texte (ILIKE).
  comptabiliser(get(
    `/requisitions?service_id=${svc.id}&status=APPROUVEE&limit=200&offset=0`,
    u.token, 'requisitions_filtre', 'listes'));
  comptabiliser(get(
    `/requisitions?search=charge&limit=200&offset=0`,
    u.token, 'requisitions_recherche', 'listes'));
  think(2, 5);

  // Experts comptables : liste avec totaux (endpoint signale comme lent dans
  // docs/PERFORMANCE_WRITE_CONTENTION_20260803.md).
  comptabiliser(get('/experts-comptables?include_summary=true&limit=50&offset=0',
    u.token, 'experts_liste', 'listes'));
  think(2, 6);
}

// ---------------------------------------------------------------------------
// 4. BUDGET ET RAPPORTS (lectures lourdes)
//   GET /budget/postes/tree      budget.py:1738  (optimise en Phase 3)
//   GET /budget/lines/autorisees budget.py:1886  (appele a chaque changement
//                                de service dans le formulaire de requisition,
//                                frontend/src/pages/Requisitions.tsx:345)
//   GET /reports/summary         reports.py:135  (cache Redis 15 s)
//   GET /reports/synthese-annuelle reports.py:1043
//   GET /reports/journal-tresorerie reports.py:1245
//   GET /reports/top-depenses    reports.py:1195
// ---------------------------------------------------------------------------
export function parcoursRapports() {
  const u = currentUser();
  const p = periode(180);
  const svc = randomService();
  const annee = CTX.annee;

  comptabiliser(get(`/budget/postes/tree?annee=${annee}&type=DEPENSE`, u.token, 'budget_tree_depense', 'rapports'));
  comptabiliser(get(`/budget/postes/tree?annee=${annee}&type=RECETTE`, u.token, 'budget_tree_recette', 'rapports'));
  think(2, 5);

  comptabiliser(get(`/budget/lines/autorisees?type=DEPENSE&active=true&service_id=${svc.id}`,
    u.token, 'budget_lignes_autorisees', 'rapports'));
  comptabiliser(get(`/budget/lines/tree?annee=${annee}`, u.token, 'budget_lignes_tree', 'rapports'));
  think(2, 5);

  // Le filtre de dates fait volontairement varier la cle de cache Redis :
  // un tir qui tape toujours la meme periode mesure le cache, pas la base.
  comptabiliser(get(`/reports/summary?date_debut=${p.date_debut}&date_fin=${p.date_fin}`,
    u.token, 'reports_summary', 'rapports'));
  think(1, 4);

  comptabiliser(get(`/reports/synthese-annuelle?year=${annee}&devise=USD&canal=ALL`,
    u.token, 'reports_synthese_annuelle', 'rapports'));
  comptabiliser(get(`/reports/top-depenses?date_debut=${p.date_debut}&date_fin=${p.date_fin}`,
    u.token, 'reports_top_depenses', 'rapports'));
  comptabiliser(get(`/reports/journal-tresorerie?canal=CAISSE&devise=USD&date_debut=${p.date_debut}&date_fin=${p.date_fin}`,
    u.token, 'reports_journal_caisse', 'rapports'));
  think(3, 8);
}

// ---------------------------------------------------------------------------
// 5. SAISIE D'UN ENCAISSEMENT (ecriture)
//   GET  /comptes-bancaires?active=true  banques.py:277 (charge par l'ecran,
//        frontend/src/pages/Encaissements.tsx:279)
//   POST /encaissements                  encaissements.py:1239
// Points chauds provoques par cet appel :
//   - sequence documentaire ND, CENTRALE au tenant (service_id=None) :
//     encaissements.py:690 -> une seule ligne de document_sequences pour TOUT
//     le tenant, c'est le point de serialisation le plus dur de l'application ;
//   - boucle de 50 tentatives sur collision de numero (encaissements.py:1437) ;
//   - SELECT ... FOR UPDATE sur budget_postes (encaissements.py:309-315) ;
//   - SELECT ... FOR UPDATE sur caisse_centrale.
// ---------------------------------------------------------------------------
export function parcoursEncaissement() {
  // Utilisateur de plein droit, comme les deux autres parcours d'ecriture.
  // Avec currentUser() (tirage dans les 400 comptes semes, tous roles
  // confondus), 14 des 21 POST /encaissements du tir du 27/08 revenaient en
  // 403 : la moitie du scenario d'ecriture mesurait le controle de permission
  // au lieu de la contention. Un caissier reel n'ouvre pas un ecran qu'il n'a
  // pas le droit d'utiliser.
  const u = adminToken(3);
  const poste = randomPosteRecette();
  const svc = randomService();

  comptabiliser(get('/comptes-bancaires?active=true', u.token, 'comptes_bancaires', 'encaissement'));
  think(2, 6); // saisie du formulaire

  const montant = money(500, 50000);
  const res = comptabiliser(post('/encaissements', u.token, {
    type_client: 'autre',
    client_nom: `Client charge ${uid()}`,
    libelle: 'Encaissement de charge',
    montant: montant,
    montant_total: montant,
    mode_paiement: 'cash',
    canal: 'CAISSE',
    montant_paye: montant,
    montant_percu: montant,
    devise_perception: 'USD',
    statut_paiement: 'complet',
    budget_poste_id: poste.id,
    service_id: svc.id,
  }, 'encaissement_create', 'encaissement'));
  // 409 = detection d'operation en double, comportement metier attendu.
  ok(res, 'encaissement_create', [201, 409]);
  think(2, 5);
}

// ---------------------------------------------------------------------------
// 6. CYCLE DE REQUISITION (ecritures en chaine)
//   GET  /budget/lines/autorisees?service_id=..   budget.py:1886
//   POST /requisitions                            requisitions.py:1825
//   POST /requisitions/{id}/validate              requisitions.py:2007 (validation technique,
//        permission can_verify_technical)
//   POST /requisitions/{id}/vise                  requisitions.py:2071 (validation finale,
//        permission can_validate_final)
// Deux jetons DISTINCTS sont necessaires : vise_requisition_logic refuse le
// viseur qui a deja valide (requisition_service.py:923).
// Contentions provoquees : sequence REQ par service (document_sequences.py:19),
// SELECT ... FOR UPDATE sur la requisition (requisition_service.py:915),
// recalcul de montant_engage sur budget_postes (budget_engagement.py:97).
// ---------------------------------------------------------------------------
export function parcoursCycleRequisition() {
  const auteur = adminToken(0);
  const viseur = adminToken(1);
  const svc = randomService();
  const debut = Date.now();

  comptabiliser(get(`/budget/lines/autorisees?type=DEPENSE&active=true&service_id=${svc.id}`,
    auteur, 'budget_lignes_autorisees', 'requisition'));
  think(3, 8); // redaction de la requisition

  const p1 = randomPosteDepense();
  const p2 = randomPosteDepense();
  const m1 = money(1000, 20000);
  const m2 = money(1000, 20000);
  const total = (parseFloat(m1) + parseFloat(m2)).toFixed(2);

  const creation = comptabiliser(post('/requisitions', auteur, {
    objet: `Depense de charge ${uid()}`,
    mode_paiement: 'cash',
    type_requisition: 'classique',
    montant_total: total,
    devise: 'USD',
    service_id: svc.id,
    a_valoir: false,
    decaissement_progressif: false,
    lignes: [
      { budget_poste_id: p1.id, rubrique: p1.libelle.slice(0, 200), description: `Ligne A ${uid()}`, quantite: 1, montant_unitaire: m1, montant_total: m1, devise: 'USD' },
      { budget_poste_id: p2.id, rubrique: p2.libelle.slice(0, 200), description: `Ligne B ${uid()}`, quantite: 1, montant_unitaire: m2, montant_total: m2, devise: 'USD' },
    ],
  }, 'requisition_create', 'requisition'));
  if (!ok(creation, 'requisition_create', [200, 201])) return;

  const id = creation.json('id');
  think(1, 3);

  const validation = comptabiliser(post(`/requisitions/${id}/validate`, auteur, {},
    'requisition_validate', 'requisition'));
  if (!ok(validation, 'requisition_validate')) return;
  think(1, 3);

  const visa = comptabiliser(post(`/requisitions/${id}/vise`, viseur, {},
    'requisition_vise', 'requisition'));
  ok(visa, 'requisition_vise');

  cycleRequisition.add(Date.now() - debut);
  think(2, 5);
}

// ---------------------------------------------------------------------------
// 7. SORTIE DE FONDS
//   GET  /sorties-fonds/requisitions/{id}/solde   sorties_fonds.py:804
//   POST /sorties-fonds                           sorties_fonds.py:1040
// Contentions : sequence PAY par service (sorties_fonds.py:1603), verrou
// FOR UPDATE sur caisse_centrale (sorties_fonds.py:1564) et sur le compte
// bancaire, mise a jour de budget_postes.
// Chaque iteration consomme UNE requisition APPROUVEE du stock exporte par
// mint_tokens.py : `iterationInTest` est unique sur tout le tir, donc deux VU
// ne visent jamais la meme requisition (sinon 400 « montant deja paye »).
// ---------------------------------------------------------------------------
export function parcoursSortieFonds() {
  const stock = CTX.requisitions_approuvees;
  if (!stock || stock.length === 0) {
    console.error('Aucune requisition APPROUVEE dans context.json : scenario sortie ignore.');
    return;
  }
  const index = exec.scenario.iterationInTest;
  if (index >= stock.length) {
    console.error(`Stock de requisitions APPROUVEE epuise (${stock.length}) : rallongez --approuvees.`);
    return;
  }
  const cible = stock[index];
  const caissier = adminToken(2);

  comptabiliser(get(`/sorties-fonds/requisitions/${cible.id}/solde`, caissier, 'sortie_solde', 'sortie'));
  think(2, 5);

  const res = comptabiliser(post('/sorties-fonds', caissier, {
    type_sortie: 'requisition',
    requisition_id: cible.id,
    service_id: cible.service_id,
    budget_poste_id: cible.budget_poste_id,
    montant_paye: cible.montant,
    mode_paiement: 'cash',
    devise: 'USD',
    canal: 'CAISSE',
    motif: `Paiement de charge ${uid()}`,
    beneficiaire: `Beneficiaire ${uid()}`,
  }, 'sortie_create', 'sortie'));
  ok(res, 'sortie_create', [200, 201]);
  think(2, 5);
}

// ---------------------------------------------------------------------------
// 8. EXPORT EXCEL (chemin couteux en CPU)
//   GET /exports/encaissements  exports.py:1165
//   GET /exports/requisitions   exports.py:1764
//   GET /exports/budget         exports.py:488
// Le rendu openpyxl s'execute DANS le worker : il occupe un coeur Python
// pendant toute la generation, ce qui est exactement le goulot identifie par
// docs/PERFORMANCE_WORKER_SCALING_20260817.md.
// ---------------------------------------------------------------------------
export function parcoursExport() {
  const u = CTX.utilisateurs_plein_droit[exec.scenario.iterationInTest % CTX.utilisateurs_plein_droit.length];
  const p = periode(365);
  const cible = exec.scenario.iterationInTest % 3;

  let chemin;
  let nom;
  if (cible === 0) {
    chemin = `/exports/encaissements?date_debut=${p.date_debut}&date_fin=${p.date_fin}&est_proforma=false`;
    nom = 'export_encaissements';
  } else if (cible === 1) {
    chemin = `/exports/requisitions?date_debut=${p.date_debut}&date_fin=${p.date_fin}&type_requisition=classique`;
    nom = 'export_requisitions';
  } else {
    chemin = `/exports/budget?annee=${CTX.annee}`;
    nom = 'export_budget';
  }

  const res = comptabiliser(http.get(`${BASE_URL}${chemin}`, {
    headers: headers(u),
    timeout: '120s',
    tags: { journey: 'export', name: nom },
  }));
  ok(res, nom);
}
