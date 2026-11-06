# 故障排查

## 小红书下载失败（登录墙）

现象：`XHS page did not expose a video url (login wall?)` 或 `download suspiciously small`。

**重要**：小红书页面必须带 `xsec_token` 参数（只在用户分享的原始链接里有）。仅凭笔记 ID
拼 `https://www.xiaohongshu.com/explore/<id>` 会被风控拦截（yt-dlp 报 No video formats found）。
所以要重下某个视频时，必须让用户重新发原始分享链接，不要用 ID 重建 URL。

解决：导出一份已登录状态的 cookies：

1. 浏览器装扩展 `Get cookies.txt LOCALLY`（Chrome / Edge 都有）。
2. 打开 xiaohongshu.com 并登录，导出 Netscape 格式 cookies.txt。
3. 把路径交给向导，之后不用再传参数：
   ```bash
   python scripts/setup.py --cookies /path/to/cookies.txt
   ```
   或者单次临时指定：
   ```bash
   python scripts/pipeline.py "链接" --cookies /path/to/cookies.txt
   ```
   也可以设环境变量 `VAE_COOKIES=/path/to/cookies.txt`。

cookies 过期了会重新撞登录墙，重新导一份覆盖原文件即可。

备用方案：在手机 App 里把视频「保存到相册」，把本地 mp4 直接交给
`process_video.py` / `detect_noise.py` 处理（跳过下载步骤）。

## 提示 "XHS page did not expose a video url" 但其实不是登录墙

纯图文笔记就是这个报错。页面里只有 `imageList` 图片、没有任何视频地址，脚本没有东西可下。
判断方法：抓下页面 grep 一下 `imageList` 和 `masterUrl`，只有前者说明是图集。

图集要变成视频属于另一条工序（图片 + 转场 + 节奏），不在本流水线范围内。

## 抖音下载失败

- 链接是口令/分享文本：`download_video.py` 会用正则提取其中的 http(s) 链接，整段粘贴即可。
- 地区限制或风控：加 `--cookies`；或让用户提供本地视频文件。
- yt-dlp 版本过旧导致解析失效：
  ```bash
  .venv/bin/pip install -U yt-dlp
  ```

## ffmpeg / ffprobe

- `ffmpeg not found`：装 `imageio-ffmpeg`（`pip install imageio-ffmpeg`），或把系统 ffmpeg 加进 PATH。
- **ffprobe 不是必需的**。`imageio-ffmpeg` 只带 ffmpeg 不带 ffprobe，脚本会自动改从
  `ffmpeg -i` 的输出里解析音频编解码器，行为一致。
- 罕见编码（HEVC / AV1）解码失败：先转封装再进流水线
  `ffmpeg -i input -c:v libx264 -c:a aac tmp.mp4`。

## 画面比例问题

- 输出画布固定为 3:4（1080×1440）。
- 默认 `--fit crop`：等比放大后居中裁剪填满全屏。横屏素材会裁掉左右两侧。
- 觉得裁剪丢了内容 → 换 `--fit blur`（模糊背景填充，完整保留画面）或 `--fit black`（黑边）。
- **不要**改成直接 `scale=1080:1440` 的硬拉伸，画面会严重变形。

## 输出目录写不进去

`setup.py` 在保存前会真写一个探针文件验证，写不进去会当场让你重填。事后要改：

```bash
python scripts/setup.py --out-dir /path/that/is/writable
```

Windows 上如果选的是盘符根目录下的新建文件夹，常见原因是 ACL 只给了管理员写权限，
换到用户目录（如 `%USERPROFILE%\Videos\3x4`）最稳。

## 受限 / 沙箱环境下的两个坑

如果你的运行环境会限制子进程的运行时长、或拦截文件删除，会遇到这两个：

1. **长编码被中途 kill，产物没有 moov 无法播放**。mp4 的索引写在文件末尾，进程被打断
   就等于文件全废。对策：把 `preset` 设为 `fast`（CRF 20 / ultrafast），或者用
   `--keep-tmp` 保留中间文件；已经跑起来的任务不要中途停。判断产物是否完整：
   `ffmpeg -i out.mp4` 能读出 `Duration:` 才算成功。
2. **删除临时文件的操作被打断**。把 `io_mode` 设为 `sandbox`，脚本会保留一个 1 字节
   `.wtest` 探针而不去删它，主流程不受影响。正常环境保持 `normal` 即可，会自动清理。

## 杂音检测误判

启发式阈值（谱平坦度 0.25 / SNR 8 dB）对极端素材可能误判。默认流程不做检测、保留原声；
只有明确要换音乐时才用 `--replace-music`（检测后按需换）或 `--force-music`（强制换）。

## BGM 想换成自己的音乐

把 mp3 放进 `assets/bgm/`，命名 `chill.mp3` / `upbeat.mp3` / `energetic.mp3` 即可覆盖内置曲目；
或单次使用 `process_video.py --bgm <路径>`。内置三首是程序化合成的，可自由使用。
