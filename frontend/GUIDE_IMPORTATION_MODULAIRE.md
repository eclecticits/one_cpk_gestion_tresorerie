# Guide d'Importation Modulaire - Experts-Comptables

## Vue d'ensemble

Le système d'importation modulaire permet d'importer des experts-comptables selon 4 catégories distinctes, chacune avec ses propres règles de validation et colonnes obligatoires.

## Les 4 Modules d'Importation

### 1️⃣ SEC - Sociétés d'Expertise Comptable

**Description:** Import des personnes morales (cabinets)

**Colonnes obligatoires:**
- N° d'ordre ⚠️
- Dénomination ⚠️
- Raison sociale ⚠️
- Associé gérant ⚠️

**Colonnes optionnelles:**
- N° de téléphone
- E-mail

**Règles de validation:**
- Le N° d'ordre doit être unique
- L'e-mail doit avoir un format valide
- Tous les champs obligatoires doivent être renseignés

**Exemple de ligne Excel:**
```
N° d'ordre: 001
Dénomination: Cabinet Expert Conseil
Raison sociale: Expert Conseil SARL
N° de téléphone: +243 XXX XXX XXX
E-mail: contact@expertconseil.cd
Associé gérant: Jean DUPONT
```

---

### 2️⃣ Experts-comptables en cabinet

**Description:** Import des experts travaillant en cabinet

**Colonnes obligatoires:**
- N° d'ordre ⚠️
- Noms ⚠️
- Sexe ⚠️
- Cabinet d'attache ⚠️

**Colonnes optionnelles:**
- N° de téléphone
- E-mail

**Règles de validation:**
- Le N° d'ordre doit être unique
- Le sexe doit être "M" ou "F"
- Le cabinet d'attache ne doit pas être vide
- L'e-mail doit avoir un format valide

**Exemple de ligne Excel:**
```
N° d'ordre: 101
Noms: MUKENDI Pierre
Sexe: M
N° de téléphone: +243 XXX XXX XXX
E-mail: pmukendi@cabinet.cd
Cabinet d'attache: Cabinet Expert Conseil
```

---

### 3️⃣ Experts-comptables indépendants

**Description:** Import des experts indépendants

**Colonnes obligatoires:**
- N° d'ordre ⚠️
- Noms ⚠️
- Sexe ⚠️
- NIF ⚠️

**Colonnes optionnelles:**
- N° de téléphone
- E-mail

**Règles de validation:**
- Le N° d'ordre doit être unique
- Le sexe doit être "M" ou "F"
- Le NIF est obligatoire
- L'e-mail doit avoir un format valide

**Exemple de ligne Excel:**
```
N° d'ordre: 201
Noms: KALALA Marie
Sexe: F
N° de téléphone: +243 XXX XXX XXX
E-mail: mkalala@gmail.com
NIF: A1234567X
```

---

### 4️⃣ Experts-comptables salariés

**Description:** Import des experts salariés

**Colonnes obligatoires:**
- N° d'ordre ⚠️
- Noms ⚠️
- Sexe ⚠️
- Nom de l'employeur ⚠️

**Colonnes optionnelles:**
- N° de téléphone
- E-mail

**Règles de validation:**
- Le N° d'ordre doit être unique
- Le sexe doit être "M" ou "F"
- Le nom de l'employeur est obligatoire
- L'e-mail doit avoir un format valide

**Exemple de ligne Excel:**
```
N° d'ordre: 301
Noms: MBALA Joseph
Sexe: M
N° de téléphone: +243 XXX XXX XXX
E-mail: jmbala@entreprise.cd
Nom de l'employeur: Société ABC
```

---

## Comment utiliser le système d'importation

### Étape 1: Accéder au module d'importation

1. Ouvrez la page "Experts-Comptables"
2. Cliquez sur le bouton **"Importer Excel"**
3. Une fenêtre s'ouvre avec les 4 modules disponibles

### Étape 2: Choisir le module approprié

Sélectionnez le module correspondant au type d'experts que vous souhaitez importer :
- **SEC** pour les cabinets (personnes morales)
- **En Cabinet** pour les experts travaillant en cabinet
- **Indépendant** pour les experts indépendants
- **Salarié** pour les experts salariés

### Étape 3: Télécharger le modèle Excel

1. Cliquez sur **"📥 Télécharger le modèle Excel"**
2. Un fichier Excel avec les colonnes appropriées sera téléchargé
3. Le modèle contient déjà une ligne d'exemple pour vous guider

### Étape 4: Remplir le fichier Excel

1. Ouvrez le fichier Excel téléchargé
2. Supprimez la ligne d'exemple
3. Remplissez vos données en respectant :
   - Les noms de colonnes (ne pas les modifier)
   - Les champs obligatoires
   - Les règles de validation

### Étape 5: Importer le fichier

1. Cliquez sur **"📤 Sélectionner le fichier à importer"**
2. Sélectionnez votre fichier Excel rempli
3. Le système va :
   - Valider toutes les lignes
   - Afficher les erreurs s'il y en a
   - Importer les données valides

### Étape 6: Vérifier le résultat

Si l'importation réussit :
- Un message de succès s'affiche
- Le nombre d'experts importés est indiqué
- La page se met à jour automatiquement

Si des erreurs sont détectées :
- Un tableau d'erreurs s'affiche
- Chaque erreur indique : la ligne, la colonne, et le problème
- Corrigez les erreurs dans votre fichier Excel
- Recommencez l'importation

---

## Règles Importantes

### Validation des données

✅ **Format e-mail:** doit contenir @ et un domaine valide
✅ **Sexe:** uniquement "M" ou "F" (majuscule ou minuscule)
✅ **N° d'ordre:** doit être unique dans toute la base
✅ **Champs obligatoires:** ne peuvent pas être vides

### Gestion des doublons

- Si un N° d'ordre existe déjà, les données seront **mises à jour**
- Cela permet de corriger ou compléter des fiches existantes
- Soyez prudent lors de la mise à jour de données existantes

### Conseils pratiques

1. **Testez d'abord avec quelques lignes** pour vérifier que tout fonctionne
2. **Vérifiez les N° d'ordre** avant l'import pour éviter les doublons non intentionnels
3. **Respectez la casse** pour le sexe (M ou F)
4. **Utilisez toujours le modèle** fourni pour éviter les erreurs de colonnes
5. **Conservez les noms de colonnes** exactement comme dans le modèle

---

## Résolution de problèmes

### "Colonnes manquantes"
➡️ Vous avez modifié les noms de colonnes. Utilisez le modèle fourni.

### "Champ obligatoire manquant"
➡️ Une cellule obligatoire est vide. Remplissez toutes les colonnes marquées obligatoires.

### "Format e-mail invalide"
➡️ L'e-mail ne respecte pas le format standard (doit contenir @ et un domaine).

### "Doit être M ou F"
➡️ La colonne Sexe contient une valeur incorrecte. Utilisez uniquement M ou F.

### "Fichier vide"
➡️ Le fichier Excel ne contient aucune donnée. Ajoutez au moins une ligne.

---

## Support Technique

Pour toute question ou problème avec le système d'importation, contactez l'administrateur système.

**Version:** 1.0
**Date:** Janvier 2026
