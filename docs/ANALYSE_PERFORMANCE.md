# Analyse de performance — ONEC Smart

**Date :** 30/07/2026. **Méthode :** analyse statique du code (le profilage à l'exécution n'a pas pu être réalisé — environnement d'exécution indisponible). Les points sont rattachés à des fichiers réels ; les hypothèses sont signalées.

---

## 1. Ce qui est déjà bien fait (vérifié)

- **Le pire goulot est déjà corrigé.** `alembic/versions/20260722d_perf_indexes.py` documente que le dashboard/rapports faisaient des `CAST(date AS date)` / `func.date()` → **balayages complets de table (~22 s, timeouts gunicorn)**. Les requêtes ont été réécrites en comparaisons de plage sur la colonne brute, avec index composites `(organisation_id, date)` + un index fonctionnel sur `COALESCE(date_paiement, created_at)`.
- **Cache Redis en place et utilisé** : `core/cache.py` (28 réf.), `api/deps.py` (statut SaaS), `core/tenant_resolver.py` (résolution du tenant), `dashboard.py`. Évite de recalculer à chaque requête.
- **Index tenant systématiques** : `organisation_id` indexé sur toutes les tables métier ; index composites datés ajoutés.
- **Eager loading présent** là où il compte : `selectinload/joinedload` utilisés dans `admin.py`, `banques.py`, `encaissements.py`, `hr.py`, `services.py`, `treasury.py` (32 occurrences).
- **Async propre** : aucun HTTP synchrone (`requests`) ni `time.sleep` dans le code async ; l'envoi SMTP (bloquant) a été déplacé en tâche de fond.
- **Workers async** : gunicorn avec `uvicorn.workers.UvicornWorker` (`-w 4`).

**Conclusion : la base de performance est saine.** Les gains restants sont surtout côté **frontend** (ressenti de rapidité à la navigation) et sur quelques endpoints lourds.

---

## 2. Backend — points à améliorer

**[MOYEN] Endpoints monolithiques à nombreuses requêtes inline.** `requisitions.py` (2195 lignes, ~74 `db.execute`), `budget.py` (1954, ~97), `encaissements.py` (1806, ~65), `hr.py` (1323). Risque de requêtes redondantes/séquentielles sur un même appel. *Action :* profiler ces endpoints (`EXPLAIN ANALYZE` sur les requêtes chaudes) ; regrouper les requêtes séquentielles indépendantes ; envisager une couche repository pour mutualiser.

**[MOYEN] N+1 potentiel sur l'enrichissement des listes.** Les modèles lourds (`requisition.py`, `sorties_fonds.py`, `budget.py`) n'ont pas de `relationship` eager par défaut ; certaines listes enrichissent chaque ligne (bénéficiaire, réquisition liée, utilisateur). La liste des réquisitions utilise déjà le **bon** motif (maps agrégées : `montant_paye_map`, `lignes_count_map`), mais **à vérifier** pour `sorties-fonds` et les listes RH. *Action :* confirmer par profilage ; si N+1, remplacer les requêtes par-ligne par une requête groupée `IN (...)` ou `selectinload`.

**[MOYEN] Contention sous charge via `with_for_update`.** Les débits de caisse/budget/réquisition prennent un verrou pessimiste sur la ligne (correct pour l'intégrité), mais **sérialise** les opérations concurrentes sur la même caisse/le même poste → plafond de débit sous forte charge. *Action :* acceptable en l'état ; si volumétrie élevée, envisager des `UPDATE` atomiques conditionnels plutôt que lock+read+write, et raccourcir la portion verrouillée de la transaction.

**[FAIBLE] Réglage des workers.** `-w 4` est un défaut ; à ajuster selon le nombre de vCPU de l'instance (règle usuelle : `2×CPU+1` pour des workers async modérément I/O-bound). *Action :* paramétrer selon l'instance EC2 réelle.

**[FAIBLE] Image Docker mono-stage** (`build-essential` embarqué) → image lourde, **cold start / déploiements plus lents** (pas la latence runtime). *Action :* multi-stage (déjà noté dans l'audit DevOps).

---

## 3. Frontend — le principal levier de rapidité ressentie

**[ÉLEVÉ] Aucun cache de données serveur.** Aucune bibliothèque de type React Query / SWR (`@tanstack/react-query` absent — vérifié). Chaque page refait ses `fetch` dans `useEffect` (≈205 occurrences) à chaque montage : **pas de déduplication, pas de cache, pas de stale-while-revalidate**. Résultat : rechargements complets et attentes à chaque navigation, même pour des données déjà vues. *Action (fort impact) :* introduire TanStack Query pour les listes/détails (réquisitions, sorties, encaissements, RH) → navigation quasi instantanée + rafraîchissement en arrière-plan.

**[ÉLEVÉ] Aucun `React.memo`** (0 occurrence — vérifié) sur des **composants « dieu »** : `HRModule.tsx` (3747 lignes), `Requisitions.tsx` (3359), `Settings.tsx` (3151), `SortiesFonds.tsx` (2546), `SecretariatPage.tsx` (2247). Toute modification d'état re-rend l'intégralité du composant et des lignes de tableau. *Action :* découper par onglet/section + `React.memo` sur les lignes de liste avec `key` stables ; extraire les fetch dans des hooks dédiés.

**[MOYEN] Valeurs de contexte non mémoïsées.** Ex. `PermissionsContext` fournit `value={{...}}` recréé à chaque render → re-renders en cascade des consommateurs. *Action :* `useMemo` sur les `value` des providers.

**[MOYEN] Chunks lazy énormes.** Le lazy-loading par route existe (bon), mais un chunk comme `HRModule` (3747 lignes) reste massif → **premier affichage lent** de cette route. *Action :* sous-découper les gros modules en sous-routes/chunks.

**[FAIBLE] Détection mobile en JS.** `hooks/useMobile.ts` recalcule sur un listener `resize` → préférer `window.matchMedia`. **~975 styles inline** recréent des objets à chaque render (impact mineur).

---

## 4. Plan priorisé (rapidité)

**Gains rapides, fort impact (frontend) :**
1. Introduire **TanStack Query** sur 3-4 listes chaudes (réquisitions, sorties, encaissements, RH) → suppression des rechargements à la navigation.
2. `useMemo` sur les `value` des contextes ; `React.memo` sur les lignes de tableaux volumineux.

**Moyen terme (backend) :**
3. Profiler les 3 endpoints les plus lourds (`requisitions`, `budget`, `encaissements`) et éliminer les éventuels N+1 (map groupée / `selectinload`).
4. Ajuster le nombre de workers gunicorn à l'instance.

**Structurel :**
5. Découper les composants « dieu » et les gros endpoints (aussi bénéfique pour la maintenabilité).
6. Image Docker multi-stage (cold start / déploiement).

---

## 5. Non vérifié (nécessiterait un profilage à l'exécution)

- Temps de réponse réels par endpoint et présence effective de N+1 (analyse statique uniquement — pas d'`EXPLAIN ANALYZE` ni d'APM).
- Taille réelle du bundle frontend et temps de premier affichage (pas de build mesuré).
- Comportement sous charge concurrente (contention des verrous), latence réseau vers les fournisseurs IA, temps de la base sous volumétrie réelle.
- Efficacité réelle du cache Redis (taux de hit) et TTL adaptés.
