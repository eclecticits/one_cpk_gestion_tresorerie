"""Le cache des critères multi-tenant ne doit jamais mélanger deux organisations.

Depuis l'optimisation de `_apply_tenant_criteria`, les `with_loader_criteria`
ne sont plus reconstruits à chaque SELECT ORM mais mémorisés par organisation.
C'est ce cache qui porte désormais le cloisonnement : ces tests le verrouillent.
"""

import uuid

from app.db.session import _tenant_loader_options


def test_meme_organisation_reutilise_le_meme_tuple():
    """C'est la propriété qui fait le gain : deux SELECT ne reconstruisent rien."""
    tenant_id = uuid.uuid4()
    _tenant_loader_options.cache_clear()

    premier = _tenant_loader_options(tenant_id)
    second = _tenant_loader_options(tenant_id)

    assert premier is second
    assert _tenant_loader_options.cache_info().hits == 1


def test_deux_organisations_ont_des_criteres_distincts():
    """Le risque du cache : servir à B les critères construits pour A."""
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    _tenant_loader_options.cache_clear()

    criteres_a = _tenant_loader_options(org_a)
    criteres_b = _tenant_loader_options(org_b)

    assert criteres_a is not criteres_b
    assert len(criteres_a) == len(criteres_b)
    # Chaque option est un objet distinct : aucune n'est partagée entre les deux.
    assert not {id(option) for option in criteres_a} & {id(option) for option in criteres_b}

    # Et A reste A après le passage de B : la LRU ne réécrit pas l'entrée existante.
    assert _tenant_loader_options(org_a) is criteres_a


def test_le_cache_est_borne():
    """Sans borne, un flux de tenants éphémères ferait croître la mémoire sans fin."""
    assert _tenant_loader_options.cache_info().maxsize is not None
