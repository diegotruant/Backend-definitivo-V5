#!/usr/bin/env python3
"""
Audit script — maps the entire package: who imports what, who reads which
fields from which producer output, who classifies as what tier.
Used to plan the v3.3.0 refactor.
"""
import ast
import re
from pathlib import Path
from collections import defaultdict


ENGINES_DIR = Path("engines")


def collect_module_info():
    """Return: {module_name: {imports, public_classes, public_funcs, stream_attrs_read, snapshot_fields_read}}"""
    info = {}
    
    for py_file in sorted(ENGINES_DIR.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        
        name = py_file.stem
        src = py_file.read_text()
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            print(f"  ⚠️ {name}: SyntaxError at line {e.lineno}")
            continue
        
        m = {
            "imports_from_package": [],
            "imports_external": [],
            "public_classes": [],
            "public_funcs": [],
            "stream_attrs_read": set(),
            "snapshot_fields_read": set(),
            "result_dict_fields_produced": set(),
            "lines": len(src.splitlines()),
        }
        
        # Imports
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                names = [a.name for a in node.names]
                if mod.startswith("engines"):
                    m["imports_from_package"].append((mod, names))
                else:
                    m["imports_external"].append((mod, names))
            elif isinstance(node, ast.Import):
                for a in node.names:
                    m["imports_external"].append((a.name, []))
        
        # Top-level definitions
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                m["public_classes"].append(node.name)
            elif isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                m["public_funcs"].append(node.name)
        
        # Stream attribute access: stream.X
        for x in re.findall(r"stream\.([a-z_]+)", src):
            m["stream_attrs_read"].add(x)
        
        # Snapshot field reads
        for x in re.findall(r'(?:snapshot|metabolic_snapshot|baseline_snapshot)(?:\["|\[\']|\.get\(["\'])([\w]+)', src):
            m["snapshot_fields_read"].add(x)
        
        # Dict literal keys (rough: keys in return dicts)
        # Find return statements with dict
        for node in ast.walk(tree):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
                for k in node.value.keys:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        m["result_dict_fields_produced"].add(k.value)
        
        info[name] = m
    
    return info


def main():
    info = collect_module_info()
    
    print("=" * 78)
    print("PACKAGE AUDIT — v3.2.2 baseline (target: v3.3.0)")
    print("=" * 78)
    
    print(f"\nTotal modules: {len(info)}")
    print(f"Total LOC: {sum(m['lines'] for m in info.values())}")
    
    print("\n" + "=" * 78)
    print("MODULE INVENTORY")
    print("=" * 78)
    for name, m in sorted(info.items()):
        print(f"\n  {name}.py  ({m['lines']} lines)")
        if m["public_classes"]:
            print(f"    classes:  {', '.join(m['public_classes'])}")
        if m["public_funcs"]:
            funcs = m["public_funcs"]
            shown = funcs[:5] + ([f"...+{len(funcs)-5}"] if len(funcs) > 5 else [])
            print(f"    funcs:    {', '.join(shown)}")
        if m["imports_from_package"]:
            deps = [mod.replace("engines.", "") for mod, _ in m["imports_from_package"]]
            print(f"    depends:  {', '.join(deps)}")
    
    print("\n" + "=" * 78)
    print("STREAM ATTRIBUTE ACCESS (potential schema drift)")
    print("=" * 78)
    for name, m in sorted(info.items()):
        if m["stream_attrs_read"]:
            attrs = sorted(m["stream_attrs_read"])
            print(f"  {name}: {attrs}")
    
    print("\n" + "=" * 78)
    print("SNAPSHOT FIELD CONSUMERS")
    print("=" * 78)
    for name, m in sorted(info.items()):
        if m["snapshot_fields_read"]:
            print(f"  {name}: {sorted(m['snapshot_fields_read'])}")
    
    print("\n" + "=" * 78)
    print("DEPENDENCY GRAPH (who depends on whom)")
    print("=" * 78)
    reverse = defaultdict(set)
    for name, m in info.items():
        for mod, _ in m["imports_from_package"]:
            target = mod.replace("engines.", "").split(".")[0]
            if target != name:
                reverse[target].add(name)
    for target in sorted(reverse):
        deps = sorted(reverse[target])
        print(f"  {target} ← {', '.join(deps)}")
    
    print("\n" + "=" * 78)
    print("ORPHANS (no one imports them)")
    print("=" * 78)
    all_targets = set(reverse.keys())
    for name in sorted(info.keys()):
        if name not in all_targets and name not in {"__init__"}:
            print(f"  {name}")
    
    return info


if __name__ == "__main__":
    main()
