# Guide RBAC - Christian KIDIKALA

Ce guide explique comment gerer les roles et permissions dans le systeme.

## 1) Principes
- Un role = une ligne dans la matrice.
- Une permission = une colonne.
- L'acces aux pages est deduit automatiquement des permissions (pas de doublon).

## 2) Actions courantes
### Ajouter un role
1. Aller dans Parametres > Securite & Utilisateurs.
2. Cliquer sur "+ Ajouter un role".
3. Donner un nom clair (ex: "Vice President").
4. Cocher les permissions necessaires.
5. Cliquer sur "Enregistrer les permissions".

### Renommer un role
1. Dans la matrice, modifier le champ "Nom du role".
2. Cliquer sur "Enregistrer les permissions".

### Supprimer un role
1. Cliquer sur la croix du role.
2. Confirmer la suppression.
3. Reassigner les utilisateurs concernes si besoin.

## 3) Permissions et acces (rappel)
- can_create_requisition: creer une requisition
- can_verify_technical: avis technique (rapporteur)
- can_validate_final: validation finale (president)
- can_execute_payment: sortie de fonds (caissier)
- can_manage_users: gestion des utilisateurs
- can_edit_settings: gestion des parametres
- can_view_reports: rapports et tableaux

## 4) Test rapide
1. Creer un role "Test".
2. Cocher uniquement can_create_requisition.
3. Assigner ce role a un utilisateur test.
4. Se connecter: seules les pages liees aux requisitions doivent apparaitre.

## 5) Bonnes pratiques
- Donner le minimum de permissions necessaires.
- Verifier les acces apres un changement de role.
- Garder une trace des changements importants (audit).
