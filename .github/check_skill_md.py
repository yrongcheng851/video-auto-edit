#!/usr/bin/env python3
"""CI：校验 SKILL.md 的 frontmatter。

开放平台解析技能包时，缺字段和版本号格式不对是最常见的驳回原因，
本地先卡一道，免得改完代码忘了补，上传了才发现要重新打包。

必填项与平台一致：
  name / display_name / display_name_en
  description_zh / description_en / version（SemVer 三段式）
"""
import re
import sys
import pathlib

REQUIRED = [
    "name",
    "display_name",
    "display_name_en",
    "description_zh",
    "description_en",
    "version",
]

text = pathlib.Path("SKILL.md").read_text(encoding="utf-8")
m = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.S)
if not m:
    print("SKILL.md 开头没有找到 --- 包裹的 frontmatter", file=sys.stderr)
    sys.exit(1)

block = m.group(1)
values = {}
for line in block.splitlines():
    km = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
    if km:
        values[km.group(1)] = km.group(2).strip().strip('"').strip("'")

errors = []
for key in REQUIRED:
    if not values.get(key):
        errors.append(f"缺少 {key}")

ver = values.get("version", "")
if ver and not re.fullmatch(r"\d+\.\d+\.\d+", ver):
    errors.append(f'version 必须是三段式（如 1.0.0），当前是 "{ver}"')

for key in ("display_name", "display_name_en"):
    val = values.get(key, "")
    if val and len(val) > 60:
        errors.append(f"{key} 过长（{len(val)} 字符），展示名建议 15 字以内")

print(f"version          = {ver}")
print(f"display_name     = {values.get('display_name', '')}")
print(f"display_name_en  = {values.get('display_name_en', '')}")
print()

if errors:
    for e in errors:
        print(f"ERROR {e}", file=sys.stderr)
    sys.exit(1)

print("frontmatter 校验通过")
