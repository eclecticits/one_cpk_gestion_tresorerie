// Helpers partages par les scenarios k6 de ONEC Smart.
// Aucune donnee en dur : tout vient de context.json, produit par
// seed/mint_tokens.py contre la base reellement semee.

import http from 'k6/http';
import { check, sleep } from 'k6';
import { SharedArray } from 'k6/data';

export const BASE_URL = (__ENV.BASE_URL || 'http://localhost:8000/api/v1').replace(/\/+$/, '');
export const CONTEXT_FILE = __ENV.CONTEXT_FILE || './context.json';

// SharedArray, mais element par element — la nuance decide de tout.
//
// La version precedente rangeait TOUT le contexte dans un seul element :
//
//     const ctxHolder = new SharedArray('contexte', () => [JSON.parse(open(F))]);
//     export const CTX = ctxHolder[0];
//
// L'intention etait bonne, l'effet nul : k6 deserialise une copie a chaque
// acces a un element. Lire `ctxHolder[0]` une fois au niveau module donnait
// donc a CHAQUE VU sa propre copie integrale du fichier. Mesure a 25 VU :
// 603 Mo de pic pour le generateur — l'ordre de grandeur exact des deux
// processus k6 tues par l'OOM-killer le 27/08 (anon-rss 606 et 610 Mo).
//
// Ici chaque grande liste est son propre SharedArray : k6 ne materialise que
// l'element reellement lu. `requisitions_approuvees` pese a lui seul 11 785
// entrees, l'essentiel du fichier.
function chargerContexte() {
  return JSON.parse(open(CONTEXT_FILE));
}

// Petites structures : scalaires, services, postes. Quelques centaines
// d'entrees au total, une copie par VU reste negligeable.
const META = new SharedArray('meta', function () {
  const d = chargerContexte();
  return [{
    organisation_id: d.organisation_id,
    organisation_slug: d.organisation_slug,
    annee: d.annee,
    compte_bancaire_id: d.compte_bancaire_id,
    services: d.services,
    postes_recette: d.postes_recette,
    postes_depense: d.postes_depense,
    identifiants_plein_droit: d.identifiants_plein_droit,
  }];
});

// Grandes listes : un element de SharedArray par entree.
const UTILISATEURS = new SharedArray('utilisateurs', function () {
  return chargerContexte().utilisateurs;
});
const UTILISATEURS_PD = new SharedArray('utilisateurs_pd', function () {
  return chargerContexte().utilisateurs_plein_droit;
});
const REQ_APPROUVEES = new SharedArray('req_approuvees', function () {
  return chargerContexte().requisitions_approuvees;
});

// CTX garde la meme forme pour les scenarios : les trois grandes listes sont
// des SharedArray, qui exposent `length` et l'indexation comme un tableau.
export const CTX = Object.assign({}, META[0], {
  utilisateurs: UTILISATEURS,
  utilisateurs_plein_droit: UTILISATEURS_PD,
  requisitions_approuvees: REQ_APPROUVEES,
});

export const TENANT_HEADER = String(CTX.organisation_id);

export function headers(token, extra) {
  return Object.assign(
    {
      Authorization: `Bearer ${token}`,
      // Resolution du tenant par en-tete : accepte par
      // backend/app/api/deps.py:242 (extract_tenant_hint). En production le
      // front passe par le sous-domaine (cn.exemple.org) ; l'en-tete evite de
      // devoir gerer un DNS de test cote generateur.
      'X-Tenant-ID': TENANT_HEADER,
      'Content-Type': 'application/json',
    },
    extra || {}
  );
}

function pick(list, index) {
  return list[index % list.length];
}

// Un VU = un utilisateur stable pendant tout le tir (le cache d'auth
// AUTH_CONTEXT_CACHE_TTL_SECONDS=30 se comporte alors comme en production).
export function currentUser() {
  return pick(CTX.utilisateurs, __VU);
}

export function adminToken(offset) {
  return pick(CTX.utilisateurs_plein_droit, __VU + (offset || 0));
}

export function randomService() {
  return CTX.services[Math.floor(Math.random() * CTX.services.length)];
}

export function randomPosteRecette() {
  return CTX.postes_recette[Math.floor(Math.random() * CTX.postes_recette.length)];
}

export function randomPosteDepense() {
  return CTX.postes_depense[Math.floor(Math.random() * CTX.postes_depense.length)];
}

export function money(min, max) {
  return (Math.floor(Math.random() * (max - min)) + min).toFixed(2);
}

export function uid() {
  return `${__VU}-${__ITER}-${Math.floor(Math.random() * 1e6)}`;
}

// Fenetre de dates realiste : le front ouvre ses ecrans sur le mois courant.
export function periode(joursEnArriere) {
  const fin = new Date();
  const debut = new Date(fin.getTime() - (joursEnArriere || 30) * 86400000);
  const iso = (d) => d.toISOString().slice(0, 10);
  return { date_debut: iso(debut), date_fin: iso(fin) };
}

export function think(min, max) {
  const lo = min === undefined ? 0.5 : min;
  const hi = max === undefined ? 2.0 : max;
  sleep(lo + Math.random() * (hi - lo));
}

// Verifie ET nomme l'echec : sans le corps de reponse, un 400 metier et un 500
// d'infrastructure se ressemblent dans le rapport.
export function ok(res, name, attendus) {
  const codes = attendus || [200, 201];
  const succes = check(res, {
    [`${name}: statut attendu`]: (r) => codes.indexOf(r.status) !== -1,
  });
  if (!succes) {
    console.warn(`${name} -> HTTP ${res.status} ${String(res.body).slice(0, 200)}`);
  }
  return succes;
}

export function get(path, token, name, journey) {
  return http.get(`${BASE_URL}${path}`, {
    headers: headers(token),
    tags: { journey: journey, name: name },
  });
}

export function post(path, token, body, name, journey) {
  return http.post(`${BASE_URL}${path}`, JSON.stringify(body), {
    headers: headers(token),
    tags: { journey: journey, name: name },
  });
}

export { http, check, sleep };
