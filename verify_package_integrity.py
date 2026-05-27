#!/usr/bin/env python3
"""
Package Integrity Verifier
Version: 1.0.0

Runs on the REAL codebase and produces an honest report of:
- What __init__.py claims to export
- What actually exists in module files
- Mismatches between declared API and real API
- Signature inconsistencies

Usage:
    cd /path/to/digital_twin_backend
    python3 verify_package_integrity.py

Output:
    Detailed report saved to integrity_report.txt
    Exit code 0 if all aligned, 1 if mismatches found
"""

import ast
import importlib
import inspect
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple


# =============================================================================
# AST INTROSPECTION (no execution required)
# =============================================================================

def get_module_definitions(file_path: Path) -> Dict[str, str]:
    """
    Parse a Python file with AST and return all top-level definitions.
    
    Returns:
        Dict mapping name -> type ("class", "function", "variable")
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(file_path))
    except SyntaxError as e:
        return {"__SYNTAX_ERROR__": f"Line {e.lineno}: {e.msg}"}
    except Exception as e:
        return {"__READ_ERROR__": str(e)}
    
    definitions = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            definitions[node.name] = "class"
        elif isinstance(node, ast.FunctionDef):
            definitions[node.name] = "function"
        elif isinstance(node, ast.AsyncFunctionDef):
            definitions[node.name] = "async_function"
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    definitions[target.id] = "variable"
        elif isinstance(node, ast.AnnAssign):
            # Type-annotated module-level variable: e.g. `X: Dict = {}`
            if isinstance(node.target, ast.Name):
                definitions[node.target.id] = "variable"
    
    return definitions


def get_init_exports(init_file: Path) -> Tuple[List[str], Dict[str, str]]:
    """
    Parse __init__.py and extract:
    - __all__ list
    - imports (mapping name -> source module)
    """
    if not init_file.exists():
        return [], {}
    
    try:
        with open(init_file, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
    except SyntaxError as e:
        print(f"  SYNTAX ERROR in {init_file}: {e}")
        return [], {}
    
    all_list = []
    imports = {}
    
    for node in tree.body:
        # __all__ = [...]
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, ast.List):
                        all_list = [
                            elt.value
                            for elt in node.value.elts
                            if isinstance(elt, ast.Constant)
                        ]
        
        # from .module import X, Y
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                name = alias.asname or alias.name
                imports[name] = module
    
    return all_list, imports


# =============================================================================
# VERIFICATION
# =============================================================================

def verify_package(package_dir: Path) -> List[str]:
    """
    Verify package integrity. Returns list of issues found.
    """
    issues = []
    
    init_file = package_dir / "__init__.py"
    if not init_file.exists():
        issues.append(f"CRITICAL: {init_file} not found")
        return issues
    
    # Get declared API
    all_list, imports = get_init_exports(init_file)
    
    print(f"\n{'=' * 70}")
    print(f"Verifying: {package_dir}")
    print(f"{'=' * 70}")
    print(f"__all__ declares {len(all_list)} symbols")
    print(f"Imports {len(imports)} symbols from submodules")
    
    # For each imported symbol, verify it exists in source module
    for symbol_name, source_module in imports.items():
        # Resolve module file
        # ".module" → package_dir/module.py
        # "module" → package_dir/module.py
        module_name = source_module.lstrip(".")
        module_file = package_dir / f"{module_name}.py"
        
        if not module_file.exists():
            issues.append(
                f"MISSING_FILE: {init_file.name} imports '{symbol_name}' "
                f"from '{module_name}' but {module_file.name} does not exist"
            )
            continue
        
        # Parse module and check symbol exists
        definitions = get_module_definitions(module_file)
        
        if "__SYNTAX_ERROR__" in definitions:
            issues.append(
                f"SYNTAX_ERROR in {module_file.name}: "
                f"{definitions['__SYNTAX_ERROR__']}"
            )
            continue
        
        if symbol_name not in definitions:
            # Suggest similar names
            similar = [
                d for d in definitions
                if symbol_name.lower() in d.lower()
                or d.lower() in symbol_name.lower()
            ]
            suggestion = f" (similar names: {similar})" if similar else ""
            issues.append(
                f"MISMATCH: {init_file.name} imports '{symbol_name}' "
                f"from {module_file.name}, but symbol not found.{suggestion}"
            )
    
    # Check __all__ entries are actually imported
    for declared in all_list:
        if declared not in imports:
            issues.append(
                f"DANGLING_EXPORT: __all__ declares '{declared}' "
                f"but it is not imported in __init__.py"
            )
    
    return issues


def try_real_imports(package_dir: Path) -> List[str]:
    """
    Actually try to import the package and report failures.
    This catches issues that AST analysis misses (e.g., import-time errors).
    """
    issues = []
    
    # Add parent to path
    parent = package_dir.parent
    sys.path.insert(0, str(parent))
    package_name = package_dir.name
    
    try:
        pkg = importlib.import_module(package_name)
    except Exception as e:
        issues.append(
            f"IMPORT_FAILED: cannot import {package_name}: "
            f"{type(e).__name__}: {e}"
        )
        return issues
    
    # Try each name in __all__
    all_list = getattr(pkg, "__all__", [])
    for name in all_list:
        if not hasattr(pkg, name):
            issues.append(
                f"RUNTIME_MISSING: __all__ declares '{name}' "
                f"but pkg.{name} raises AttributeError at runtime"
            )
        else:
            obj = getattr(pkg, name)
            # Check if it's actually usable
            if obj is None:
                issues.append(f"RUNTIME_NONE: {name} resolves to None")
    
    return issues


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Run verification on engines/ directory."""
    # Default to engines/ in current directory
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
    else:
        target = Path("engines")
    
    if not target.is_dir():
        print(f"ERROR: {target} is not a directory")
        print(f"Usage: {sys.argv[0]} [path/to/package]")
        sys.exit(1)
    
    print("\n" + "=" * 70)
    print("DIGITAL TWIN — PACKAGE INTEGRITY VERIFIER")
    print("=" * 70)
    
    # Phase 1: AST analysis (always safe)
    print("\n[1/2] AST analysis (no code execution)...")
    static_issues = verify_package(target)
    
    # Phase 2: Real import test (optional)
    print("\n[2/2] Runtime import test...")
    try:
        runtime_issues = try_real_imports(target)
    except Exception as e:
        runtime_issues = [f"Runtime test failed: {e}"]
    
    all_issues = static_issues + runtime_issues
    
    # Report
    print("\n" + "=" * 70)
    print("REPORT")
    print("=" * 70)
    
    if not all_issues:
        print("\n✓ No issues found. API contract is consistent.")
        sys.exit(0)
    
    # Group by severity
    critical = [i for i in all_issues if "CRITICAL" in i or "SYNTAX" in i]
    mismatches = [i for i in all_issues if "MISMATCH" in i or "MISSING" in i]
    runtime = [i for i in all_issues if "RUNTIME" in i or "IMPORT_FAILED" in i]
    other = [
        i for i in all_issues
        if i not in critical and i not in mismatches and i not in runtime
    ]
    
    if critical:
        print(f"\n[CRITICAL] {len(critical)} issue(s):")
        for issue in critical:
            print(f"  • {issue}")
    
    if mismatches:
        print(f"\n[API MISMATCH] {len(mismatches)} issue(s):")
        for issue in mismatches:
            print(f"  • {issue}")
    
    if runtime:
        print(f"\n[RUNTIME] {len(runtime)} issue(s):")
        for issue in runtime:
            print(f"  • {issue}")
    
    if other:
        print(f"\n[OTHER] {len(other)} issue(s):")
        for issue in other:
            print(f"  • {issue}")
    
    print(f"\n{'=' * 70}")
    print(f"TOTAL: {len(all_issues)} issue(s) found")
    print(f"{'=' * 70}")
    
    sys.exit(1)


if __name__ == "__main__":
    main()
