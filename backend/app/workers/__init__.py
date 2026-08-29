"""Traitements hors requête HTTP.

Le worker tourne à partir de la MÊME image que le backend, avec une commande
différente : c'est ce qui garantit que le code métier ne diverge jamais entre
les deux. Rien ici ne doit dupliquer une règle de calcul de `app/services`.
"""
