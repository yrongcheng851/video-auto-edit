#!/usr/bin/env python3
"""CI：校验 SKILL.md 的 frontmatter。

开放平台解析技能包时，缺字段和版本号格式不对是最常见的驳回原因，
本地先卡一道，免得改完代码忘了补，上传了才发现要重新打包。

必填项与平台一致：
  name / display_name / display_name_en
  description_zh / description_en / version（SemVer 三段式）

**真正的 YAML 解析**也会跑一遍：平台用的是标准 YAML 解析器，未加引号的
长句里只要出现半角「冒号+空格」（例如 ``clips (1080×1440): trailing``），
就会报 `mapping values are not allowed in this context` 并拒绝解析。
只用正则逐行取值是发现不了这个问题的。
"""
import re
import sys
import pathlib

try:
    import yaml
except ImportError:                                     # 本地没装 PyYAML 时降级
    yaml = None

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

# ---- 1. 真 YAML 解析（平台同款校验，最容易漏的一道） ----
if yaml is None:
    print("提示：未安装 PyYAML，跳过真实 YAML 解析（pip install pyyaml 可开启）")
else:
    try:
        parsed = yaml.safe_load(block)
        if not isinstance(parsed, dict):
            errors.append("frontmatter 解析结果不是键值对结构")
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f"第 {mark.line + 1} 行第 {mark.column + 1} 列" if mark else "未知位置"
        errors.append(f"YAML 语法错误（{where}）：{getattr(e, 'problem', e)}")

# ---- 2. 未加引号的值里不允许出现「冒号+空格」，逐字段定位 ----
for i, line in enumerate(block.splitlines(), 1):
    km = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):[ \t]+(\S.*)$", line)
    if not km:
        continue
    key, val = km.group(1), km.group(2)
    if val[:1] in "\"'":
        continue
    hit = re.search(r":(\s|$)", val)
    if hit:
        snippet = val[max(0, hit.start() - 24):hit.start() + 12]
        errors.append(
            f'{key}（第 {i} 行）的值里有未加引号的半角「冒号+空格」：…{snippet}… '
            f"平台 YAML 解析会直接失败，改成「—」或全角「：」")

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


def count_list_items(block: str, key: str) -> int:
    """数某个 key 下的 YAML 列表项条数（- 开头且缩进）。"""
    lines = block.splitlines()
    total, inside = 0, False
    for line in lines:
        if re.match(rf"^{key}:\s*$", line):
            inside = True
            continue
        if inside:
            if re.match(r"^\s+-\s", line):
                total += 1
            elif line.strip() and not line.startswith((" ", "\t")):
                break
    return total


# 平台要求中英文示例条数一致，否则解析直接失败
n_zh = count_list_items(block, "examples_zh")
n_en = count_list_items(block, "examples_en")
if n_zh != n_en:
    errors.append(f"examples_zh 与 examples_en 数量必须一致：当前中文 {n_zh} 条、英文 {n_en} 条")

print(f"version          = {ver}")
print(f"display_name     = {values.get('display_name', '')}")
print(f"display_name_en  = {values.get('display_name_en', '')}")
print(f"examples         = zh {n_zh} 条 / en {n_en} 条")
print()

if errors:
    for e in errors:
        print(f"ERROR {e}", file=sys.stderr)
    sys.exit(1)

print("frontmatter 校验通过")
