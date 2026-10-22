# transform-splice-cover 可执行脚本

这些脚本实现了本 Skill 里**容易写错、且写错就会出毛边/黑边/漏字**的部分。
**优先调用它们，不要临场重写**——重写就等于把本 Skill 已经记录在案的坑重新踩一遍。

| 脚本 | 作用 |
|---|---|
| `detect_costume_point.py` | 帧级换装点检测：输出躯干区相邻帧差候选 + 每个候选的对照 contact sheet，供人工确认 C |
| `extract_overlay_layers.py` | 提取静态贴图/标题（填充+描边两 plate）与逐帧动态数字，全部带亚像素 matte |
| `compose_splice.py` | 前段映射 + 贴图合成 + 后段拼接 + 单次编码（同时输出无贴图版） |
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

## 脚本里已经固化的坑（别再改回去）

1. **取色用时间中值，不用时间均值** —— 均值会把烧录贴图 1px 亚像素抖动平均掉 → 贴图发虚。
2. **边缘 alpha 是投影式亚像素 matte** `a=(M−B)·(P−B)/|P−B|²` —— 二值掩膜会出 1px 毛边。
3. **边缘颜色取最近的核心像素本色 P**，绝不 `M/a` 反预乘 —— 会把 h264 噪声放大成麻点。
4. **深色元素只按明度 V 选** —— 近黑像素的 HSV 饱和度是 255 而非 0，带饱和度条件会漏掉整条描边。
5. **标题填充取「全部」合格连通域**，不是只取最大的那个 —— 否则只捞到半个字。
6. **标题的烧录连通域要从插画层剔除** —— 否则整行标题会糊进插画贴图。
7. **plate 叠放顺序跟原片渲染顺序**：插画 → 描边 → 彩色填充 → 动态数字。
8. **所有 QA 预览 1:1 原生像素或 NEAREST 放大** —— LANCZOS 缩放出来的预览本身就是模糊。

## 输出目录约定

```
<ROOT>/
├── layers/    overlay_geom.json  digit_meta.json  cluster.png  title_fill.png  title_stroke.png  digit/d####.png
├── qa/        pre_median.png  graphic_mask.png  *_checker.png  protection_zone.json  verification.json
└── out/       成片_最终含贴图.mp4  中间版_无贴图替换版.mp4  对比视频_原视频_vs_成片.mp4
```
