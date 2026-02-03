# Modèle d'import Excel - Experts-Comptables

## Format du fichier

Le fichier Excel pour importer les experts-comptables doit contenir les colonnes suivantes :

### Colonnes requises

| Nom de la colonne | Type | Obligatoire | Description |
|-------------------|------|-------------|-------------|
| **Numéro Ordre** ou **numero_ordre** ou **Numero** | Texte | OUI | Numéro d'ordre unique de l'expert-comptable |
| **Nom** ou **nom_denomination** ou **Denomination** | Texte | OUI | Nom complet ou dénomination de l'EC |

### Colonnes optionnelles

| Nom de la colonne | Type | Obligatoire | Description |
|-------------------|------|-------------|-------------|
| **Type** ou **type_ec** | Texte | NON | Type d'EC : SEC, EC, Cabinet, Société, Indépendant (par défaut: EC) |
| **Email** ou **email** | Email | NON | Adresse email de contact |
| **Téléphone** ou **telephone** ou **Tel** | Texte | NON | Numéro de téléphone |

## Exemple de fichier Excel

### Feuille 1 (Sheet1)

| Numéro Ordre | Nom | Type | Email | Téléphone |
|--------------|-----|------|-------|-----------|
| EC-001 | KABONGO Jean-Pierre | EC | jkabongo@email.cd | +243 81 234 5678 |
| EC-002 | MUMBERE Marie | SEC | mmumbere@email.cd | +243 82 345 6789 |
| CAB-003 | Cabinet FINANCE PLUS SARL | Cabinet | contact@financeplus.cd | +243 99 876 5432 |
| EC-004 | TSHILOMBO André | EC | atshilombo@email.cd | +243 85 123 4567 |
| SOC-005 | AUDIT Congo SA | Société | info@auditcongo.cd | +243 81 999 8888 |

## Règles d'import

1. **Fichier accepté** : Format `.xlsx` ou `.xls`
2. **Première ligne** : Doit contenir les en-têtes de colonnes
3. **Données** : Commencent à la ligne 2
4. **Numéros d'ordre** :
   - Doivent être uniques
   - En cas de doublon, les données existantes seront mises à jour
   - Recommandé : Utilisez un préfixe (EC-, SEC-, CAB-, SOC-)
5. **Champs vides** :
   - Les colonnes optionnelles peuvent être vides
   - Les lignes sans numéro d'ordre ou nom seront ignorées
6. **Types acceptés** :
   - SEC (Stagiaire Expert-Comptable)
   - EC (Expert-Comptable)
   - Cabinet
   - Société
   - Indépendant
   - Tout autre texte sera accepté mais ces valeurs sont recommandées

## Exemple de données complètes

Voici un exemple avec différents cas :

| Numéro Ordre | Nom | Type | Email | Téléphone |
|--------------|-----|------|-------|-----------|
| EC-001 | KABONGO Jean-Pierre | EC | jkabongo@email.cd | +243 81 234 5678 |
| SEC-002 | MUMBERE Marie (Stagiaire) | SEC | mmumbere@email.cd | +243 82 345 6789 |
| CAB-003 | Cabinet FINANCE PLUS SARL | Cabinet | contact@financeplus.cd | +243 99 876 5432 |
| EC-004 | TSHILOMBO André | EC | | +243 85 123 4567 |
| SOC-005 | AUDIT CONGO SA | Société | info@auditcongo.cd | |
| EC-006 | MUKENDI Pascal | Indépendant | | |
| EC-007 | ILUNGA Sophie | EC | silunga@email.cd | +243 81 555 1234 |
| CAB-008 | Cabinet COMPTEX | Cabinet | comptex@email.cd | +243 82 666 7890 |

## Comment importer

1. Préparez votre fichier Excel selon le modèle ci-dessus
2. Enregistrez-le en format `.xlsx` ou `.xls`
3. Dans l'application :
   - Allez dans "Experts-Comptables"
   - Cliquez sur "Importer Excel"
   - Sélectionnez votre fichier
   - L'import s'effectue automatiquement
4. Un message de confirmation indiquera le nombre d'experts-comptables importés

## Mise à jour des données

- Si vous importez un fichier avec des numéros d'ordre déjà existants, les informations seront **mises à jour**
- Cela permet de corriger ou compléter les données sans créer de doublons
- Pour ajouter de nouveaux EC, ajoutez simplement de nouvelles lignes avec de nouveaux numéros d'ordre

## Conseils pratiques

1. **Sauvegardez** votre fichier source avant l'import
2. **Testez** d'abord avec quelques lignes pour vérifier le format
3. **Vérifiez** les numéros d'ordre pour éviter les doublons non intentionnels
4. **Complétez** au maximum les emails et téléphones pour faciliter les contacts
5. **Utilisez** des préfixes cohérents pour les numéros d'ordre (EC-, SEC-, CAB-, SOC-)

## Résolution de problèmes

| Problème | Solution |
|----------|----------|
| "Aucune donnée valide trouvée" | Vérifiez que les colonnes "Numéro Ordre" et "Nom" sont présentes et remplies |
| "Erreur lors de l'import" | Vérifiez le format du fichier (.xlsx ou .xls) et que les données sont dans la première feuille |
| Certaines lignes non importées | Vérifiez que ces lignes ont bien un numéro d'ordre et un nom renseignés |
| Caractères spéciaux affichés bizarrement | Enregistrez votre fichier en UTF-8 dans Excel |

## Télécharger un modèle vide

Vous pouvez créer un fichier Excel avec ces en-têtes :

```
Numéro Ordre | Nom | Type | Email | Téléphone
```

Puis remplissez les lignes avec vos données et importez-le dans l'application.
