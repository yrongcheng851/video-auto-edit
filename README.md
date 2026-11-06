# video-auto-edit

把小红书 / 抖音的竖版视频批量整理成统一的 **3:4 (1080×1440)** 成品：自动去掉片尾的平台水印卡、等比裁剪不变形、保留原声、moov 写在文件头可直接上传。

不是在线服务，就是几个 Python 脚本。没有账号、没有云端上传，视频只在你本机流转。

## 它能做什么

- **批量下载**：粘贴分享文本或一堆短链，自动挑出链接逐个处理。
- **去片尾卡**：扫末段画面，找「突变 + 之后静止」的平台卡片，stream copy 无损截断。极短的黑底署名卡也能识别。
- **转 3:4**：等比放大后居中裁剪填满，不变形。角落的作者 logo 顺带裁出画面外。
- **保原声**：音频是 AAC 就零重编码直接 copy。想换 BGM 是显式开关，默认不动。
- **保画质**：CRF 18（长片自动降到 CRF 20 换取成功率），`+faststart`。

## 快速开始

需要 Python 3.9+，无需系统 ffmpeg。

```bash
git clone <this-repo> video-auto-edit
cd video-auto-edit

python -m venv .venv
.venv/bin/pip install -r requirements.txt          # Windows: .venv\Scripts\pip install -r requirements.txt

# 一次性初始化：选自哪个文件夹、可选贴 cookies
.venv/bin/python scripts/setup.py

# 干活
.venv/bin/python scripts/pipeline.py "https://xhslink.cn/o/xxxxx"
```

Windows 用户把 `.venv/bin/python` 换成 `.venv\Scripts\python.exe`。

## 初始化向导

跑 `scripts/setup.py` 会依次问：

1. **环境自检** — Python 版本、四个依赖、ffmpeg / ffprobe 有没有。
2. **成品存到哪** — 默认 `~/Videos/3x4`。填完当场写一个探针文件验证能不能写，写不进去会让你重填，不会等到批量跑到一半才报错。
3. **cookies（可选）** — 小红书经常要登录才给视频地址。用浏览器扩展 `Get cookies.txt LOCALLY` 登录后导出 Netscape 格式文件，把路径贴进来。会顺手校验文件格式、告诉你覆盖了哪些站点。暂时不需要就回车跳过，以后随时重跑。
4. **编码预设 + 兼容模式** — 直接回车用推荐的就行。

配置写在 `~/.video-auto-edit/config.json`，跟仓库分开，升级代码不会覆盖你的设置。仓库里只有 `config.example.json` 作参考。

非交互场景：

```bash
python scripts/setup.py --yes
python scripts/setup.py --out-dir ~/Videos/3x4 --cookies ~/cookies.txt
python scripts/setup.py --show      # 看当前生效配置
python scripts/setup.py --check     # 只做环境自检
```

## 配置项

| 键 | 说明 | 默认 | 环境变量 |
|---|---|---|---|
| `out_dir` | 成品目录 | `~/Videos/3x4` | `VAE_OUT_DIR` |
| `cookies` | Netscape cookies.txt | 空 | `VAE_COOKIES` |
| `preset` | `auto` / `quality` / `fast` | `auto` | `VAE_PRESET` |
| `io_mode` | `normal` / `sandbox` | `normal` | `VAE_IO_MODE` |

优先级：命令行 > 环境变量 > 配置文件 > 默认值。临时换个输出目录不用改配置：

```bash
VAE_OUT_DIR=/tmp/out python scripts/pipeline.py "链接"
python scripts/pipeline.py "链接" --out-dir /tmp/out
```

`io_mode` 平时不用管。只有运行环境的删除钩子会中断整个进程时才设 `sandbox`——那种情况下脚本会留一个 1 字节的 `.wtest` 而不是去删探针文件。

## 常用参数

```bash
# 不想裁掉画面两侧（横屏素材）就换模糊填充
python scripts/pipeline.py "链接" --fit blur

# 关闭片尾卡检测
python scripts/pipeline.py "链接" --no-trim-outro

# 换背景音乐（默认不换）
python scripts/pipeline.py "链接" --force-music --style upbeat

# 从文件批量
python scripts/pipeline.py --file links.txt
```

完整参数见 `SKILL.md`。

## 已知限制

- **片尾卡检测是启发式的**。视频结尾自己就带着渐变、闪烁，或者卡片跟内容长得一样，可能漏删；反过来也可能误删内容。在意的话用 `--no-trim-outro` 关掉，或者 `--fallback-sec 2` 兜底固定切 2 秒。
- **`crop` 会丢边缘内容**。竖屏素材裁上下的情况少，横屏会裁掉左右。要完整画面用 `--fit blur`。
- **小红书抓取依赖页面结构**。`.cn` / `.com` 短链、鸿蒙分享链接都做了适配，但平台一改版就可能失效。
- **图文笔记下不了**。笔记里只有图片没有视频流，脚本会判定为下载失败并报错，这不是 bug。

## 法律与使用边界

工具本身只做视频转码和裁剪。你用它处理什么内容，取决于你自己是否拥有那些素材的版权或已获得授权。

不含任何 cookies、不含绕过风控的手段。需要登录才能看的内容，由使用者自己导出自己的 cookies。转发、商用他人视频前请自行确认授权，各平台的用户协议也请自行遵守。

## 目录

```
scripts/
  setup.py           首次配置向导 + 环境自检
  config.py          配置加载（三个脚本共享）
  pipeline.py        一键流水线：下载 → 去片尾 → 转 3:4 → 落盘
  download_video.py  小红书 / 抖音下载
  trim_outro.py      片尾水印卡检测与无损截断
  process_video.py   3:4 比例转换 + 编码
  detect_noise.py    杂音检测（仅换 BGM 时用）
  make_bgm.py        重新生成内置 BGM
assets/bgm/          程序化合成的三首原创 BGM
references/          故障排查
```

## License

MIT，见 `LICENSE`。
