---
name: video-auto-edit
display_name: 视频自动剪辑流水线
display_name_en: Video Auto Edit
description: 短视频自动剪辑流水线。读取小红书/抖音分享链接（单个或批量），下载视频，自动剔除片尾平台/作者水印卡片片段，把画面等比缩放到 3:4 (1080x1440) 且不变形（默认等比放大裁剪填满全屏，顺带裁掉角落作者 logo），尽量保留原画质，原声 AAC 直接 copy。输出目录、cookies、编码预设由 scripts/setup.py 首次配置决定。This skill should be used when the user provides 小红书/抖音 links and asks to 剪辑/处理/下载视频、调整比例/转竖屏 3:4, or asks for batch video processing. 仅当用户明确要求去杂音/换背景音乐时才启用 BGM 替换（--replace-music / --force-music，风格 chill 舒缓 / upbeat 轻快 / energetic 动感）。
description_zh: 批量把短视频整理成统一的 3:4 竖屏成品：自动去掉片尾的平台水印卡、等比裁剪不变形、保留原声不换 BGM、moov 写在文件头可直接上传。支持分享链接单条或批量处理，首次运行有配置向导选输出目录和 cookies。
description_en: Batch-normalise short videos into uniform 3:4 portrait clips. Strips trailing platform watermark cards, crops proportionally without distortion, keeps the original audio, and writes the moov atom at the head so the file uploads straight away. Works on single links or whole batches, with a first-run setup wizard for output folder and cookies.
version: "1.0.0"
author: 余荣成
examples_zh:
  - "把这几个分享链接批量转成 3:4 竖屏，存到我的视频文件夹"
  - "这条视频结尾有平台水印卡，帮我切掉再转竖屏"
  - "画面被裁掉太多了，改成模糊背景填充重新跑一遍"
agent_created: true
---

# video-auto-edit — 短视频自动剪辑

流水线：链接 → 下载 → **片尾水印剔除（末段突变检测，无损截断）** → **等比缩放 3:4（不变形）** → **保留原声** → 保存到配置的输出目录。

## 首次使用（换机器也要做一次）

```bash
python scripts/setup.py
```

向导会做三件事：环境自检（Python / 依赖 / ffmpeg / ffprobe）、问你要把成品存到哪、可选地贴一份 cookies.txt 路径。配置写进 `~/.video-auto-edit/config.json`。

不想交互就用参数一把过：
```bash
python scripts/setup.py --yes --out-dir ~/Videos/3x4          # 全默认
python scripts/setup.py --out-dir ~/Videos/3x4 --cookies ~/cookies.txt
python scripts/setup.py --show                                # 看当前生效配置
python scripts/setup.py --check                               # 只做环境自检
```

## 默认行为

1. **画面等比缩放到 3:4 (1080×1440)，绝不拉伸变形**。默认 `--fit crop`（等比放大后居中裁剪，填满全屏）；可选 `--fit blur`（模糊背景填充）或 `--fit black`（黑边）。**等比放大裁剪会把原画面角落的作者 logo 裁到画面外，因此角标水印无需单独处理。**
2. **默认保留原视频声音，不换背景音乐**。只有明确要求「去杂音 / 换音乐」时才加 `--replace-music`（检测后仅在嘈杂时换）或 `--force-music`（强制换）。
3. **默认自动剔除片尾平台/作者水印卡片**。下载后扫描末段（默认最后 12 秒），检测"画面突变 + 之后静止"的片尾卡片，用 stream copy 无损截断到卡片出现之前。这是启发式，可能漏删或偶发误删；用 `--no-trim-outro` 关闭，或 `--fallback-sec` 在检测失败时用固定秒数兜底。

## 画质

- 视频用 `libx264`，预设由配置的 `preset` 决定：
  - `quality` → CRF 18 / veryfast，画质最好
  - `fast` → CRF 20 / ultrafast，快，肉眼几乎无差
  - `auto`（默认）→ 短片走 quality，超过约 200 秒走 fast（长片在受限环境下更容易跑完）
- 原音频为 AAC 时**直接 stream copy 不重编码**（零音质损失）；非 AAC 才转码为 AAC 192k。
- `-movflags +faststart`，moov 索引写在文件头，可直接上传平台。

## 配置项

配置文件默认在 `~/.video-auto-edit/config.json`，三个脚本共享。查找顺序：`$VAE_CONFIG` → `~/.video-auto-edit/config.json` → `<skill>/config.json`（便携模式）。

| 键 | 说明 | 默认 | 环境变量 |
|---|---|---|---|
| `out_dir` | 成品保存目录 | `~/Videos/3x4` | `VAE_OUT_DIR` |
| `cookies` | Netscape cookies.txt 路径，可空 | `null` | `VAE_COOKIES` |
| `preset` | `auto` / `quality` / `fast` | `auto` | `VAE_PRESET` |
| `io_mode` | `normal` / `sandbox` | `normal` | `VAE_IO_MODE` |

优先级：命令行参数 > 环境变量 > 配置文件 > 默认值。
`io_mode` 只有一种情况需要改：运行环境的删除钩子会中断整个进程（某些沙箱），此时设 `sandbox`，脚本会留一个 1 字节 `.wtest` 探针而不去删它。正常机器保持 `normal`。

## 使用方法

`<PY>` 指装了依赖的 Python 解释器（建议独立 venv，见下）。

**一键流水线（首选，单个/批量通吃）：**
```bash
<PY> scripts/pipeline.py "用户发来的分享文本或链接"        # 单个
<PY> scripts/pipeline.py "链接1" "链接2" "链接3"          # 批量
<PY> scripts/pipeline.py --file links.txt                # 文件批量（每行一个）
```

常用开关：
- `--fit crop|blur|black`：3:4 适配方式（默认 crop，均不变形）。
- `--replace-music` / `--force-music`：**仅明确要求换音乐时使用**。
- `--style chill|upbeat|energetic`：替换 BGM 的风格。
- 片尾水印剔除：`--no-trim-outro`、`--tail-sec 12`、`--min-outro 0.3`、`--lead 0.3`、`--fallback-sec 0`。
- `--cookies`：临时指定 cookies.txt，覆盖配置。
- `--out-dir`：临时指定输出目录，覆盖配置。
- `--keep-tmp`：保留下载的原始视频。

**分步调用（需要更细控制时）：**
1. 下载：`<PY> scripts/download_video.py "链接" --out <临时目录>`
2. （可选）杂音检测：`<PY> scripts/detect_noise.py <视频文件>` → `noisy=true` 即有杂音
3. 处理：`<PY> scripts/process_video.py <视频> [--fit crop] [--replace-audio --style upbeat]`

所有脚本输出均为 JSON 行，便于解析。

## 环境

依赖四个 Python 包：`yt-dlp`、`requests`、`numpy`、`imageio-ffmpeg`。ffmpeg 由 `imageio-ffmpeg` 提供，不需要系统 PATH；ffprobe 不是必需的（缺了就自动改从 ffmpeg 的 `-i` 输出里读音频编解码器）。

```bash
python -m venv .venv
# Windows: .venv\Scripts\python.exe    macOS/Linux: .venv/bin/python
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/setup.py
```

## 执行注意

- 输出目录若不可写，脚本会报错并提示改目录，不会静默失败。
- 裁剪填满原理：`scale=1080:1440:force_original_aspect_ratio=increase` 等比放大到覆盖全屏，再 `crop=1080:1440` 居中裁剪 + `setsar=1`，保持原比例不变形；横屏视频会裁掉左右两侧，用户在意完整性时换 `--fit blur`。
- 小红书下载可能触发登录墙；失败时引导用户导出 cookies，详见 `references/troubleshooting.md`。
- 内置 BGM 为程序化合成的原创音乐，无版权问题；用户可把自己的 mp3 命名为 `chill.mp3`/`upbeat.mp3`/`energetic.mp3` 放入 `assets/bgm/` 覆盖，或用 `--bgm` 指定任意音乐文件。BGM 缺失时用 `<PY> scripts/make_bgm.py` 重新生成。
- 杂音检测是启发式（安静段谱平坦度 + SNR），可能误判；用户质疑结果时用 `--force-music` 或去掉 `--replace-music` 重跑。
- 只处理用户有权使用的素材；工具不内置任何 cookies 或绕过风控的默认手段。
- 处理完成后用 present_files 展示输出视频。
