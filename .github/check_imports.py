#!/usr/bin/env python3
"""CI：确认 scripts/ 下每个模块都能被导入。

语法能过不代表能跑——少个依赖、循环导入、顶层代码写错，只有真正 import 才暴露。
"""
import importlib
import pathlib
import sys

sys.path.insert(0, "scripts")

mods = sorted(p.stem for p in pathlib.Path("scripts").glob("*.py"))
if not mods:
    print("scripts/ 下没有找到任何 .py 文件", file=sys.stderr)
    sys.exit(1)

failed = []
for name in mods:
    try:
        importlib.import_module(name)
    except Exception as exc:  # noqa: BLE001 — 任何异常都算失败
        failed.append((name, f"{type(exc).__name__}: {exc}"))
        print(f"FAIL {name}  {type(exc).__name__}: {exc}")
    else:
        print(f"ok   {name}")

print()
if failed:
    print(f"{len(failed)}/{len(mods)} 个模块导入失败")
    sys.exit(1)
print(f"{len(mods)} 个模块全部导入成功")
