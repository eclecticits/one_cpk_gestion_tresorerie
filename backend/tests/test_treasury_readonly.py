import ast
import inspect
import textwrap

from app.api.v1.endpoints import treasury


def _function_tree(func):
    return ast.parse(textwrap.dedent(inspect.getsource(func)))


def test_get_treasury_balances_has_no_write_calls():
    tree = _function_tree(treasury.get_treasury_balances)
    forbidden = {"add", "flush", "commit", "delete"}
    calls = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]

    assert not forbidden.intersection(calls)


def test_get_treasury_balances_does_not_assign_persisted_soldes():
    tree = _function_tree(treasury.get_treasury_balances)
    assigned_attrs = [
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store)
    ]

    assert "solde_usd" not in assigned_attrs
    assert "solde_cdf" not in assigned_attrs


def test_persistent_recalculation_is_explicit_post_handler():
    tree = _function_tree(treasury.recalculate_treasury_balances)
    calls = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]

    assert "commit" in calls
