import ast
from pathlib import Path

SOURCE = (Path(__file__).parent.parent / "dashboard" / "plugin_api.py").read_text()


def _routes():
    tree = ast.parse(SOURCE)
    return [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(isinstance(d, ast.Call) and getattr(d.func, "attr", "") in {"get", "post"} for d in node.decorator_list)]


def test_every_route_is_a_plain_function():
    """FastAPI runs plain routes in a worker thread, so slow store access never holds up the dashboard."""
    routes = _routes()
    assert len(routes) == 10
    assert all(isinstance(route, ast.FunctionDef) for route in routes)
