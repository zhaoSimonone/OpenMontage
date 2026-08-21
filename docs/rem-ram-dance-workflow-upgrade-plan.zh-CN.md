# 蕾姆/拉姆双人舞蹈视频工作流升级方案

日期：2026-08-21

项目：`projects/rem-ram-dance-ep01`

适用范围：基于当前 OpenMontage 项目和第三方 MiniMax-H3 / metaso API，对蕾姆、拉姆双人舞蹈视频生产链路做增量升级。

## 1. 结论

当前工作流需要升级，但不需要推翻 OpenMontage，也不需要把 MiniMax-H3 换掉。

现有问题的根因不是“没有 H3 Provider”，而是当前生产链路仍偏实验脚本和普通视频生成思路：参考舞蹈、双人角色映射、固定机位、片段衔接、动作评分和失败重试策略都没有形成舞蹈专用流程。结果就是技术上能生成、能拼接、能播放，但动作仍然僵硬，三段之间也容易出现构图和姿态跳变。

升级方向应是：

```text
现有 MiniMax-H3 Provider
        ↓
参考舞蹈专用 Prompt Compiler
        ↓
角色/服装/动作/镜头的结构化绑定
        ↓
15 秒 one-shot 优先
        ↓
必要时才做多段生成
        ↓
Motion QA + Continuity Gate
        ↓
合格后再拼接/出片
```

## 2. 当前状态审计

### 2.1 OpenMontage 结构

OpenMontage 当前是 agent-first 的视频生产系统：

- `pipeline_defs/` 定义 pipeline；
- `skills/pipelines/` 定义每个阶段的导演规则；
- `tools/` 提供实际工具能力；
- `projects/` 保存项目级素材、提示词、生成结果和 QA 记录；
- `docs/` 保存架构、供应商、方案和长期文档。

当前还没有专门的 `reference-dance` pipeline。蕾姆/拉姆项目主要通过项目目录里的 prompt、request JSON、脚本和手工 QA 推进。

### 2.2 当前 MiniMax-H3 集成

当前仓库已经有 MiniMax-H3 provider：

- 文件：`tools/video/minimax_h3_video.py`
- 工具名：`minimax_h3_video`
- Provider：`minimax_h3`
- API 路由：`https://metaso.cn/api/minimax`
- 提交接口：`/v2/video_generation`
- 查询接口：`/v2/query/video_generation/{task_id}`
- 主环境变量：`MINIMAX_H3_API_KEY`
- 兼容环境变量：`METASO_MINIMAX_API_KEY`、`MINIMAX_API_KEY`

合约测试已通过：

```bash
python3 -m pytest tests/contracts/test_minimax_h3_video.py -q
```

结果：

```text
18 passed
```

所以 P0 阶段不应再新增一个裸 H3 API 脚本，也不应绕过工具体系。应该在现有 `minimax_h3_video` 之上增加舞蹈专用工作流。

### 2.3 当前 H3 实际支持能力

基于当前代码和测试，实际支持能力如下：

| 能力 | 当前状态 |
|---|---|
| 模型 | `MiniMax-H3` |
| 时长 | 4 到 15 秒，整数 |
| 分辨率 | `768P`、`2K` |
| 画幅 | `21:9`、`16:9`、`4:3`、`1:1`、`3:4`、`9:16` |
| 文生视频 | 支持 |
| 图生视频 | 支持 |
| 参考图 | 支持，`reference_image` |
| 参考视频 | 支持，`reference_video` |
| 参考音频 | 当前工具声明支持，`reference_audio` |
| 首帧 | 支持，`first_frame` |
| 尾帧 | 支持，`last_frame` |
| 首尾帧 | 支持同一 `image_to_video` 请求内使用 |
| reference 与 first/last 混用 | 当前工具禁止混用 |
| 原生音频 | 不支持 |
| 水印控制 | 支持 `aigc_watermark` |

关键约束：

- `reference_to_video` 可以同时传参考图、参考视频、参考音频；
- `image_to_video` 可传首帧/尾帧，但比例会走 `adaptive`；
- 当前 H3 工具不允许在同一个请求里混用 `reference_*` 和 `first_frame` / `last_frame`；
- 因此多段续接时，不能简单假设“参考视频 + 上一段尾帧”能同时工作，必须按 provider 实际模式设计。

### 2.4 当前项目素材状态

当前项目素材已经整理得比较完整：

- 角色素材：`projects/rem-ram-dance-ep01/assets/character_refs/`
- 角色设定：`projects/rem-ram-dance-ep01/artifacts/character_bible_zh.md`
- 素材清单：`projects/rem-ram-dance-ep01/artifacts/asset_inventory.md`
- 正确参考视频锁定：`projects/rem-ram-dance-ep01/REFERENCE_VIDEO_LOCK.md`
- 正确舞蹈参考：`projects/rem-ram-dance-ep01/reference_analysis/douyin_friend_dance/source.mp4`
- 15 秒参考视频：`projects/rem-ram-dance-ep01/reference_analysis/douyin_friend_dance/source_trimmed_15s.mp4`
- 参考音频：`projects/rem-ram-dance-ep01/reference_analysis/douyin_friend_dance/reference_audio_15s.wav`
- 当前主提示词包：`projects/rem-ram-dance-ep01/prompts/rem_ram_friend_dance_motion_pack.md`

素材不是主要瓶颈。主要瓶颈是素材没有被更严格地结构化绑定进生成流程。

### 2.5 当前成片 QA 的不足

当前 `final_review.json` 主要验证：

- 容器是否有效；
- 分辨率、时长、fps 是否正常；
- 是否黑帧；
- 是否有音频；
- 是否可播放；
- 是否有字幕/渲染路径问题。

这些属于技术 QA，不是舞蹈质量 QA。

缺失的关键评价：

- 是否真的跟随参考视频的节奏；
- 两个人是否保持同一舞蹈 groove；
- 下半身是否有持续重心转移；
- 肩、胯、膝、脚是否参与动作；
- 是否只是在摆手；
- 是否出现 mannequin stillness；
- 片段边界的身体速度、方向、姿态是否连续；
- 蕾姆/拉姆是否左右互换；
- 画面尺度和机位是否跳变。

这就是为什么技术 QA 可以通过，但用户仍然觉得“不丝滑、不像参考视频”。

### 2.6 环境问题

当前 shell 下 `ffmpeg` 和 `ffprobe` 不在 PATH 中，OpenMontage provider menu 也显示 ffmpeg 相关 video_post / analysis 能力不可用。

这会影响：

- 参考视频抽帧；
- motion energy 分析；
- semantic cut 计算；
- seam frame 自动提取；
- 多段衔接评分；
- 最终视频更可靠的 ffprobe 验证。

因此升级 P0 的第一步应先修复 ffmpeg / ffprobe。

## 3. 现有工作流问题

### 3.1 默认 3 x 5 秒切段不合理

当前逻辑偏向：

```text
5s + 5s + 5s
```

问题是切点不一定落在动作低谷。舞蹈动作如果正在转身、抬手、换重心，直接切段会让下一段很容易重置姿态。

更合理的策略：

```text
如果 H3 支持 15 秒：
    优先一次生成 15 秒
否则：
    用 motion energy 找动作低谷切点
    必要时加 overlap
```

### 3.2 参考视频没有被精确拆解成模型可执行约束

只写“参考这个舞蹈视频”不够。

必须明确告诉 H3：

- 参考视频只用于动作、节奏、双人相对站位；
- 不保留参考视频里的真实人物身份；
- 不保留参考视频里的原服装；
- 不保留平台 UI、字幕、水印、背景；
- 左边参考舞者对应蓝发角色；
- 右边参考舞者对应粉发角色；
- 全程固定 Rem 左 / Ram 右，除非剧本明确要求交换。

### 3.3 角色身份和动作幅度存在冲突

H3 容易为了稳定人脸和服装而降低动作幅度，表现为：

- 手臂幅度变小；
- 下半身不动；
- 肩膀和胯没有节奏；
- 两个人像摆姿势而不是跳舞。

舞蹈视频应采用原则：

```text
Motion > Beauty
```

先保证舞蹈动作成立，再保留脸部稳定。否则成片会好看但无聊。

### 3.4 当前 seam review 太依赖人工

已有 `clip_seam_protocol.md` 和 `clip_seam_review.md`，方向是对的，但仍偏人工观察。

下一步需要自动输出：

- visual difference；
- subject center shift；
- camera scale drift；
- motion magnitude difference；
- motion direction mismatch；
- PASS / REPAIR / REGENERATE。

## 4. 升级目标架构

推荐目标架构：

```text
Codex / Agent
      ↓
OpenMontage reference-dance 工作流
      ↓
Asset Binding
      ↓
Motion Analysis
      ↓
H3 Dance Prompt Compiler
      ↓
Generation Plan
      ↓
MiniMax-H3 Provider
      ↓
GenerationAttempt Log
      ↓
Motion + Continuity QA
      ↓
合格：Compose / Stitch
不合格：Repair / Regenerate
```

这个架构保持 H3 作为当前主路径，不改变用户已充值和已验证的 metaso MiniMax-H3 API。

## 5. P0：不换模型的工作流升级

目标：先证明现有 H3 在更强工作流约束下还能提升多少。

### 5.1 修复 ffmpeg / ffprobe

目的：

- 恢复 video_post；
- 支持参考视频抽帧；
- 支持 motion energy；
- 支持 seam QA；
- 支持稳定的本地视频检查。

验收：

```bash
ffmpeg -version
ffprobe -version
```

都能在当前 OpenMontage shell 中运行。

### 5.2 建立 reference-dance 最小工作流

首版可以先做最小闭环，不必一次完成完整 pipeline：

```text
ingest
  ↓
bind_assets
  ↓
plan_generation
  ↓
compile_h3_prompt
  ↓
generate_candidate
  ↓
qa_motion_continuity
  ↓
compose_or_retry
```

后续再正式沉淀为 `pipeline_defs/reference-dance.yaml` 和 `skills/pipelines/reference-dance/`。

### 5.3 H3 Dance Prompt Compiler

新增一个舞蹈专用 prompt 编译层，输入包括：

- 用户目标；
- 角色设定；
- 服装设定；
- 参考视频；
- subject mapping；
- camera policy；
- choreography beats；
- negative constraints；
- provider capability。

输出 H3 可直接使用的结构化 prompt。

推荐 prompt 顺序：

```text
1. 视频总目标
2. 角色身份锁定
3. Subject Mapping
4. 服装锁定
5. 参考视频使用规则
6. Camera Lock
7. 分秒动作计划
8. 音频要求
9. 负面约束
```

### 5.4 Subject Mapping

必须明确写入生成提示词：

```text
Character 1 = blue-haired fictional adult woman = Rem-inspired character.
Character 1 always maps to the left performer in the reference video.

Character 2 = pink-haired fictional adult woman = Ram-inspired character.
Character 2 always maps to the right performer in the reference video.

Use the reference video only for body motion, footwork, weight transfer,
shoulder rhythm, hip rhythm, arm trajectory, timing, and relative spacing.

Do not copy the reference performers' faces, bodies, clothes, masks,
background, captions, platform UI, or watermark.
```

### 5.5 Camera Lock

必须明确写入：

```text
Static locked camera.
9:16 vertical frame.
Full-body two-shot.
Both dancers visible together for the entire clip.
Both feet remain visible.
No zoom.
No push-in.
No dolly.
No reframing.
No close-up rewrite.
No approach-to-camera ending.
```

### 5.6 15 秒 one-shot 优先

当前 H3 支持 4 到 15 秒，所以下一次测试应优先：

```text
1 x 15s reference_to_video
```

而不是继续：

```text
3 x 5s
```

原因：

- 避免三段独立生成导致的身份漂移；
- 避免片段间姿态重置；
- 避免构图尺度跳变；
- 更容易保留整体 groove。

如果 15 秒 one-shot 的动作还是不达标，再进入多段策略。

### 5.7 多段生成降级策略

如果必须多段：

```text
不再固定 0-5 / 5-10 / 10-15。
```

改为：

```text
参考视频 motion energy
      ↓
寻找动作低谷
      ↓
选择语义切点
      ↓
必要时加 0.3 到 0.8 秒 overlap
```

### 5.8 GenerationAttempt 日志

每次生成都必须记录：

- shot id；
- attempt id；
- provider；
- model；
- prompt；
- request JSON；
- response JSON；
- output path；
- cost；
- latency；
- motion score；
- continuity score；
- identity score；
- camera score；
- status；
- failure reason。

这样后续不会再靠聊天记忆判断哪次好、哪次坏。

## 6. P1：动作与连续性 QA

目标：让系统能自动发现“技术可播放但舞蹈不好”的问题。

### 6.1 Motion Energy Analyzer

首版不依赖 GPU，只用：

- FFmpeg；
- OpenCV；
- frame difference；
- optical flow magnitude。

输出：

```text
timestamp,motion_energy
0.00,0.12
0.05,0.18
...
```

用途：

- 找参考视频的动作低谷；
- 找生成视频是否出现大段静止；
- 判断 seam 前后运动是否突变。

### 6.2 Seam Quality Gate

多段生成时，每个边界输出：

```yaml
boundary:
  previous_clip:
  next_clip:
  visual_difference:
  center_shift:
  camera_scale_shift:
  motion_magnitude_delta:
  motion_direction_delta:
  decision: PASS | REPAIR | REGENERATE
```

建议阈值：

```text
>= 0.80：PASS
0.65 - 0.80：REPAIR
< 0.65：REGENERATE
```

阈值应放配置，不写死。

### 6.3 Stiffness Review

新增舞蹈专用 QA 项：

- 是否有下半身重心转移；
- 是否有膝盖弹性；
- 是否有肩部 rhythm；
- 手部动作是否由躯干带动；
- 两个人是否有半拍呼应；
- 是否长时间站桩；
- 是否只摆手不跳舞；
- 是否保持全身入镜。

## 7. P2：DWPose 可选升级

P2 再考虑 DWPose，不要 P0 就上。

用途：

- 从参考视频提取肩、肘、腕、髋、膝、踝轨迹；
- 从生成视频提取对应轨迹；
- 计算 motion fidelity score。

DWPose 不可用时必须降级到 Optical Flow Analyzer，不能让整个流程挂掉。

## 8. P3：Wan2.2 Animate / ComfyUI 兜底

P3 才考虑 ComfyUI + Wan2.2 Animate。

定位不是替代 OpenMontage，也不是替代 H3，而是：

```text
复杂动作兜底
```

触发条件建议：

```text
H3 attempt >= 2
AND motion_score < threshold
```

才允许切到 Wan2.2 Animate。

这样可以避免无限烧 H3，也避免过早引入 ComfyUI 的安装和模型复杂度。

## 9. 近期执行顺序

### 第一步

修复 `ffmpeg` / `ffprobe`。

### 第二步

创建 H3 dance prompt compiler，先生成一个 15 秒 one-shot 请求 artifact，不直接付费生成。

输出路径建议：

```text
projects/rem-ram-dance-ep01/artifacts/minimax_h3_oneshot_15s_request.json
```

### 第三步

人工 review 请求：

- 是否仍是 MiniMax-H3；
- 是否 9:16；
- 是否 15 秒；
- 是否只出现蕾姆/拉姆两个人；
- 是否 Rem 左、Ram 右；
- 是否明确 reference video 只用于动作；
- 是否明确固定全身机位；
- 是否没有误回医院短剧/TTS/男主 POV。

### 第四步

获得确认后，再跑一次 15 秒 one-shot H3。

### 第五步

用新 QA 检查：

- 角色；
- 动作；
- 镜头；
- 全身入镜；
- 舞蹈连续性；
- stiff / mannequin 问题。

### 第六步

如果 one-shot 失败，再进入 motion-energy 分段和多候选策略。

## 10. 验收标准

P0 完成后应满足：

- 仍使用当前 metaso MiniMax-H3 API；
- 不再绕过 provider 工具写裸 curl 作为主路径；
- 支持 15 秒 one-shot 请求；
- prompt 中有明确 subject mapping；
- prompt 中有明确 camera lock；
- 所有生成 attempt 都有日志；
- 不再默认 3 x 5 秒；
- 不再只用 ffprobe/黑帧检查判定成片合格。

P1 完成后应满足：

- 可以输出参考视频 motion energy；
- 可以自动建议动作低谷切点；
- 可以对多段 seam 输出 PASS / REPAIR / REGENERATE；
- 可以识别明显动作僵硬；
- 可以把 motion score 作为候选选择的第一权重。

## 11. 明确不做

本阶段不做：

- 不重写 OpenMontage；
- 不复制其他开源项目；
- 不绕过 pipeline/tool registry 长期维护裸脚本；
- 不默认换 Seedance；
- 不默认上 ComfyUI；
- 不默认安装 Wan2.2 Animate；
- 不用 crossfade 掩盖姿态突变；
- 不把技术 QA 当成舞蹈 QA；
- 不再让任务漂回医院短剧、男主 POV、TTS 对白。

## 12. 推荐下一步

推荐马上执行：

```text
P0-1：修复 ffmpeg / ffprobe
P0-2：生成 15 秒 one-shot H3 请求 artifact
P0-3：人工 review 请求
P0-4：确认后再付费生成
```

这样风险最低，也最符合当前目标：继续使用 MiniMax-H3，但让它在更严格的舞蹈生产工作流里发挥到上限。

## 13. 当前落地状态（2026-08-22）

- 已补上 `reference_dance_qa`，用 FFmpeg + Pillow + numpy 做 motion / continuity 评分，不依赖 OpenCV。
- `reference-dance` pipeline 的 review stage 现在要求这个 QA 工具，避免只靠黑帧、ffprobe 和人工感觉判断舞蹈好坏。
- `reference_dance_h3_plan` 已把 `quality_gate` 写进 planned GenerationAttempt，和 review 侧共用同一套门槛。
- 当前锁定的 one-shot 成片在新 QA 下得到 `motion_score = 0.687066`、`continuity_score = 1.0`、`decision = REPAIR`，说明技术上可用，但动作还不够“丝滑”和“有劲”。
- 如果后续连续两次 H3 都无法跨过 motion pass 线，QA 会把 `comfyui_video` + Wan 2.2 作为“建议兜底”，但不会自动切模型。
