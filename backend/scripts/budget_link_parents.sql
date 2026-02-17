-- Normaliser les codes (optionnel)
UPDATE budget_postes
SET code = trim(both '.' from regexp_replace(regexp_replace(code, '\\s+', '', 'g'), '\\.+', '.', 'g'))
WHERE code IS NOT NULL;

-- Lier les enfants à leur parent le plus proche (même exercice)
UPDATE budget_postes AS enfant
SET parent_id = parent.id
FROM budget_postes AS parent
WHERE enfant.exercice_id = parent.exercice_id
  AND enfant.code LIKE parent.code || '.%'
  AND enfant.code <> parent.code
  AND length(parent.code) = (
    SELECT max(length(p2.code))
    FROM budget_postes AS p2
    WHERE p2.exercice_id = enfant.exercice_id
      AND enfant.code LIKE p2.code || '.%'
      AND enfant.code <> p2.code
  );

-- Recalculer les montants des parents (premier niveau)
UPDATE budget_postes AS parent
SET montant_prevu = COALESCE((
  SELECT sum(enfant.montant_prevu)
  FROM budget_postes AS enfant
  WHERE enfant.parent_id = parent.id
), 0)
WHERE parent.id IN (
  SELECT DISTINCT parent_id FROM budget_postes WHERE parent_id IS NOT NULL
);
