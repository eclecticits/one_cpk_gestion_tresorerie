# Guide d'Importation des Experts-Comptables

## Format du fichier Excel

Le fichier Excel d'importation doit contenir les colonnes suivantes:

### Colonnes Obligatoires

| Colonne | Description | Exemple |
|---------|-------------|---------|
| **Numéro Ordre** | Numéro d'ordre de l'expert-comptable | CPK123 |
| **Nom** ou **Dénomination** | Nom complet (personne physique) ou dénomination (personne morale) | KABILA Jean ou CABINET FIDUCIAIRE SARL |

### Colonnes Optionnelles

| Colonne | Description | Valeurs possibles | Exemple |
|---------|-------------|-------------------|---------|
| **Email** | Adresse email | - | expert@email.com |
| **Téléphone** | Numéro de téléphone | - | +243 999 999 999 |
| **Catégorie Personne** | Type de personne | "Personne Physique" ou "Personne Morale" | Personne Physique |
| **Statut Professionnel** | Statut professionnel | "En Cabinet", "Indépendant", "Salarié", "Cabinet" | En Cabinet |
| **Cabinet Attache** | Nom du cabinet d'attache (pour experts en cabinet) | - | Cabinet EXPERTISE PLUS |

**Note importante:** Le champ "Type" n'est plus nécessaire. Pour les Personnes Morales, le type "SEC" est automatiquement assigné.

## Logique de Catégorisation

### Pour une Personne Physique:

1. **Expert en Cabinet**
   - Catégorie Personne: `Personne Physique`
   - Statut Professionnel: `En Cabinet`
   - Cabinet Attache: Nom du cabinet

2. **Expert Indépendant**
   - Catégorie Personne: `Personne Physique`
   - Statut Professionnel: `Indépendant`
   - Cabinet Attache: (vide)

3. **Expert Salarié**
   - Catégorie Personne: `Personne Physique`
   - Statut Professionnel: `Salarié`
   - Cabinet Attache: (vide)

### Pour une Personne Morale:

- Catégorie Personne: `Personne Morale`
- Statut Professionnel: `Cabinet`
- Type: `SEC` (automatiquement assigné)
- Cabinet Attache: (vide, car la personne morale EST le cabinet)

## Exemple de Fichier Excel

| Numéro Ordre | Nom | Email | Téléphone | Catégorie Personne | Statut Professionnel | Cabinet Attache |
|--------------|-----|-------|-----------|-------------------|---------------------|-----------------|
| CPK001 | MUKENDI Albert | mukendi@email.com | +243 999 111 222 | Personne Physique | En Cabinet | Cabinet EXPERTISE PLUS |
| CPK002 | KALALA Marie | kalala@email.com | +243 999 333 444 | Personne Physique | Indépendant | |
| CPK003 | TSHIMANGA Paul | tshimanga@email.com | +243 999 555 666 | Personne Physique | Salarié | |
| CPK004 | CABINET FIDUCIAIRE SARL | contact@fiduciaire.com | +243 999 777 888 | Personne Morale | Cabinet | |
| CPK005 | EXPERTISE COMPTABLE SEC | info@expertise.com | +243 999 999 000 | Personne Morale | Cabinet | |

**Note:** La colonne "Type" a été retirée du fichier d'import. Pour les Personnes Morales, le type "SEC" est automatiquement assigné par le système.

## Notes Importantes

1. **Doublons**: Les experts avec le même numéro d'ordre seront automatiquement mis à jour
2. **Encodage**: Le fichier doit être au format Excel (.xlsx ou .xls)
3. **Noms de colonnes**: Les noms peuvent varier légèrement (avec ou sans accents), le système les reconnaît automatiquement
4. **Champs vides**: Les colonnes optionnelles peuvent être laissées vides
5. **Validation**: Seules les lignes avec un Numéro d'Ordre et un Nom/Dénomination valides seront importées

## Accès à la fonctionnalité

1. Aller sur la page **Experts-Comptables**
2. Cliquer sur le bouton **Importer Excel**
3. Sélectionner le fichier Excel
4. Le système importera automatiquement les données

## Messages d'erreur courants

- **"Aucune donnée valide trouvée"**: Le fichier ne contient pas les colonnes obligatoires ou les données sont mal formatées
- **"Ce numéro d'ordre existe déjà"**: Lors de l'ajout manuel, un expert avec ce numéro existe déjà
- **Erreur de contrainte**: Les valeurs pour Catégorie Personne ou Statut Professionnel ne correspondent pas aux valeurs autorisées
