# transform-splice-cover 可执行脚本

这些脚本实现了本 Skill 里**容易写错、且写错就会出毛边/黑边/漏字**的部分。
**优先调用它们，不要临场重写**——重写就等于把本 Skill 已经记录在案的坑重新踩一遍。

| 脚本 | 作用 |
|---|---|
| `detect_costume_point.py` | 帧级换装点检测：输出躯干区相邻帧差候选 + 每个候选的对照 contact sheet，供人工确认 C |
| `extract_overlay_layers.py` | 提取静态贴图/标题（填充+描边两 plate）与逐帧动态数字，全部带亚像素 matte |
| `extract_overlay_layers_v2.py` | **v2 提取器**：静态层时间窗、白字+黑描边标题、彩色贴纸、不透明矩形贴图、白色动态倒计时 |
| `compose_splice.py` | 前段映射 + 贴图合成 + 后段拼接 + 单次编码（同时输出无贴图版） |
| `compose_splice_yuv.py` | **YUV 域合成器**：后段逐字保真（见下面「坑 9」「坑 10」） |
| `verify_splice.py` | 全帧验收：容器一致性、后段 PSNR、保护区零改动、贴图稳定性、文字卫生、复原残差、字形保真度、音频 MD5、左右对比视频 |

依赖：`python3` + `opencv-python` + `numpy`，以及 `ffmpeg` / `ffprobe`。

## 典型流程

```bash
S=.agents/skills/transform-splice-cover/scripts
ROOT=projects/transform-splice-cover-<tag>
mkdir -p $ROOT/{layers,qa,out}

# 1) 换装点候选（分析窗口必须越过 C 至少 16 帧，否则最大的帧差正好被截掉）
python3 $S/detect_costume_point.py <reel.mp4> $ROOT/qa 300
#    人工看 qa/costume_candidate1_fXXX.jpg，确认 C

# 2) 提取贴图层（title_roi / digit_roi 需覆盖标题带与倒计时位）
python3 $S/extract_overlay_layers.py <reel.mp4> $ROOT <C> \
        "x0,y0,x1,y1" "x0,y0,x1,y1"

# 3) 合成（同时产出含贴图版与无贴图版）
python3 $S/compose_splice.py <v1.mp4> <reel.mp4> $ROOT 16

# 4) 全帧验收
python3 $S/verify_splice.py <v1.mp4> <reel.mp4> \
        "$ROOT/out/成片_最终含贴图.mp4" "$ROOT/out/中间版_无贴图替换版.mp4" $ROOT
```

### 静态贴图会在半程消失 / 白字标题 / 白色倒计时 —— 用 v2 流程

v1 提取器假设「静态层贯穿整个 PRE 段、标题是饱和色填充、数字是饱和色填充」。
真实片源常常不是这样。**先确认静态贴图的时间窗**，再选提取器：

```bash
# 2b) 写一个 spec.json，声明静态层的时间窗与各层类型
cat > $ROOT/extract_spec.json <<'EOF'
{
  "pre_end": 180,
  "layers": [
    {"name": "cluster", "type": "opaque_rect", "box": [306, 1288, 774, 1910]},
    {"name": "title",   "type": "white_text",  "roi": [175, 1195, 915, 1285], "tol": 8},
    {"name": "digit",   "type": "white_digit", "roi": [450, 1430, 640, 1560],
                        "window": [180, 251], "white_v": 235}
  ]
}
EOF
python3 $S/extract_overlay_layers_v2.py <reel.mp4> $ROOT <C> $ROOT/extract_spec.json

# 3b) YUV 域合成（后段逐字保真）
python3 $S/compose_splice_yuv.py <v1.mp4> <reel.mp4> $ROOT 16
```

`pre_end` 是**静态贴图存在的最后一帧 + 1**。v1 提取器在 `0..C-1` 全段取中值，
贴图若在中途整帧消失，中值会把贴图与人物平均掉（贴图发虚甚至消失）。

## 脚本里已经固化的坑（别再改回去）

1. **取色用时间中值，不用时间均值** —— 均值会把烧录贴图 1px 亚像素抖动平均掉 → 贴图发虚。
2. **边缘 alpha 是投影式亚像素 matte** `a=(M−B)·(P−B)/|P−B|²` —— 二值掩膜会出 1px 毛边。
3. **边缘颜色取最近的核心像素本色 P**，绝不 `M/a` 反预乘 —— 会把 h264 噪声放大成麻点。
4. **深色元素只按明度 V 选** —— 近黑像素的 HSV 饱和度是 255 而非 0，带饱和度条件会漏掉整条描边。
5. **标题填充取「全部」合格连通域**，不是只取最大的那个 —— 否则只捞到半个字。
6. **标题的烧录连通域要从插画层剔除** —— 否则整行标题会糊进插画贴图。
7. **plate 叠放顺序跟原片渲染顺序**：插画 → 描边 → 彩色填充 → 动态数字。
8. **所有 QA 预览 1:1 原生像素或 NEAREST 放大** —— LANCZOS 缩放出来的预览本身就是模糊。
9. **前段映射用 `floor(k × src_fps / out_fps)`，不要用 `floor(k × N1 / C)`** ——
   后者在两段帧率不同时会**真的变速**（把视频1拉快/压慢），抬手与握拳的相位会错位。
   前者保持视频1原生 1× 速度，用帧复制吸收帧率差，多余尾帧按原速截掉。
10. **rawvideo 管道必须显式声明输入色彩属性** —— demuxer 不带色彩元数据，ffmpeg 会把
    limited-range 源当 full-range 重新拉伸亮度。实测后段 Y 平面平均偏 **2.6 灰阶**
    （PSNR 39.2 dB）；在 `-i -` **之前**加
    `-color_range tv -colorspace bt709 -color_primaries bt709 -color_trc bt709`
    后降到 0.2 灰阶（PSNR **52.8 dB**），优于对原片做纯转码的对照组。
11. **字腔是合法镂空，不能 flood-fill** —— `a`/`o`/`p` 的字腔是封闭孔洞，
    整块填洞会把原视频的头发/墙面冻进贴图层。只填 ≤12px 的针孔。
12. **黑描边要靠「明度 + 邻接字形 + 时间稳定性」三重判定** —— 贴在运动人体上的黑描边与
    黑发/黑衣在像素层面同色，只有时间稳定性能把二者分开。
13. **贴图层要带时间窗** —— 静态贴图可能在中途整帧消失（实测某片 f180 起标题与插画卡同时消失）。
    合成时按 `from/to` 过滤，否则贴图会残留到片尾。
14. **后段保真要独立解码验证** —— 用 ffmpeg 直接解 Y/U/V 平面比对，不要只用 OpenCV 解码
    两侧对比（同一个解码器会把色彩矩阵偏差抵消掉，测不出来）。
15. **rawvideo 解码必须加 `-fps_mode passthrough`** —— rawvideo muxer 会把帧重新对到输出
    时基上，对不上就**复制帧**。实测视频流 `start_time=0.1s` 的 231 帧 30fps 片源，不加这个
    参数解出 **234 帧**：此后每个帧号都指向错的画面，C、后段搬运和全部验收会静默错位 3 帧。
    合成器与验证脚本的 `read_yuv420()` 都已加上。
16. **前段缺口补重复帧时，落点要「逐个贪心 + 重算映射」** —— 每插一个重复帧，其后所有输出帧
    的源帧号整体 −1，所以在**原始映射**上排名会挑到相邻帧运动量在均值附近的假「静止点」。
    正确代价函数是 `cost(s) = max(motion[s], motion[s+1])`（重复 s 前后两个相邻帧差的较大者），
    且必须每选一个就重算一次。实测同一片源：一次性排名选出的落点 cost = 5.9/7.0/5.1，
    重算后真实 cost = 5.2/11.5/6.9 —— 差一倍，肉眼正好能看出停顿。
17. **「贴图层数量为 0」是一个合法的交付结论，不是漏做** —— 先做全片烧录层盘点（每 4 帧密集
    缩略 + 全分辨率抽查 + 上下边条 2× 放大）再动手，否则会照着提示词去硬造一张不存在的贴图。
    同理，黑色遮挡检测为 0 时，必须附「注入式自检」证明检测器可用（往画面里贴一块纯黑矩形
    看它是否命中），否则「0 命中」和「检测器坏了」无法区分。

## 输出目录约定

```
<ROOT>/
├── layers/    overlay_geom.json  digit_meta.json  cluster.png  title_fill.png  title_stroke.png  digit/d####.png
├── qa/        pre_median.png  graphic_mask.png  *_checker.png  protection_zone.json  verification.json
└── out/       成片_最终含贴图.mp4  中间版_无贴图替换版.mp4  对比视频_原视频_vs_成片.mp4
```
