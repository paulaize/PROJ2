"""Guard the desktop application's dependency direction."""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
APP_ROOT = SOURCE_ROOT / "lys_bbb_app"
BACKEND_ROOT = SOURCE_ROOT / "lys_bbb"


def _python_files(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(root.rglob("*.py")))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def _app_module(path: Path) -> str:
    relative = path.relative_to(SOURCE_ROOT).with_suffix("")
    return ".".join(relative.parts)


def _app_dependency_graph() -> dict[str, set[str]]:
    files = _python_files(APP_ROOT)
    modules = {_app_module(path) for path in files}
    graph: dict[str, set[str]] = {}
    for path in files:
        module = _app_module(path)
        graph[module] = {
            imported for imported in _imports(path) if imported in modules
        }
    return graph


def _dependency_cycles(graph: dict[str, set[str]]) -> list[tuple[str, ...]]:
    cycles: list[tuple[str, ...]] = []
    visited: set[str] = set()
    active: list[str] = []

    def visit(module: str) -> None:
        if module in active:
            start = active.index(module)
            cycles.append(tuple(active[start:] + [module]))
            return
        if module in visited:
            return
        active.append(module)
        for dependency in graph[module]:
            visit(dependency)
        active.pop()
        visited.add(module)

    for module in graph:
        visit(module)
    return cycles


def test_desktop_package_has_no_internal_import_cycles() -> None:
    assert _dependency_cycles(_app_dependency_graph()) == []


def test_backend_does_not_depend_on_desktop_application() -> None:
    offenders = {
        str(path.relative_to(PROJECT_ROOT)): sorted(
            imported for imported in _imports(path) if imported.startswith("lys_bbb_app")
        )
        for path in _python_files(BACKEND_ROOT)
    }
    assert {path: imports for path, imports in offenders.items() if imports} == {}


def test_domain_and_services_do_not_depend_on_qt() -> None:
    checked_files = _python_files(APP_ROOT / "domain") + _python_files(
        APP_ROOT / "services"
    )
    offenders = {
        str(path.relative_to(PROJECT_ROOT)): sorted(
            imported for imported in _imports(path) if imported.startswith("PySide6")
        )
        for path in checked_files
    }
    assert {path: imports for path, imports in offenders.items() if imports} == {}
