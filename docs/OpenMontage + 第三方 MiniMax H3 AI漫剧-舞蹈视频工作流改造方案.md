# OpenMontage + 第三方 MiniMax H3 AI漫剧/舞蹈视频工作流改造方案

## 0. 项目目标

请基于我当前本地已有的 OpenMontage 项目进行**增量改造**，不要推翻现有架构，也不要把其他开源项目整体复制进来。

当前生产链路：

```text
Codex
  ↓
OpenMontage
  ↓
第三方 MiniMax H3 API
  ↓
5s + 5s + 5s
  ↓
FFmpeg 拼接
  ↓
15s 成片
```

当前主要问题：

1. 使用参考舞蹈视频 + 固定角色参考图生成舞蹈视频时，人物动作明显比参考视频僵硬；
2. H3 容易为了保持人物身份牺牲肢体动作幅度；
3. 目前固定按 5 秒切成 3 段，切点经常发生在动作过程中；
4. 三个视频独立生成，没有共享上一个片段结束时的人物姿态和运动状态；
5. 片段之间存在构图、人物位置、身体姿态、运动方向突变；
6. 缺少统一的角色、服装、场景、动作、参考素材资产管理；
7. 希望未来可以低成本使用 H3 为主，并允许 Wan2.2 Animate 等模型作为复杂动作镜头兜底。

目标架构：

```text
                       Codex
                         │
                         ▼
                  OpenMontage
                 Production OS
                         │
       ┌─────────────────┼──────────────────┐
       │                 │                  │
       ▼                 ▼                  ▼
 Asset Registry     Motion Analyzer     H3 Prompt Skill
 资产事实源          动作分析/切点          H3 Prompt规范
       │                 │                  │
       └─────────────────┼──────────────────┘
                         ▼
                  Generation Router
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
       Third-party H3          Wan2.2 Animate
         DEFAULT                FALLBACK
              │                     │
              └──────────┬──────────┘
                         ▼
                  Continuity Gate
                         │
                 PASS / REGENERATE
                         │
                         ▼
                 OpenMontage Post
                         │
                         ▼
                    final.mp4
```

---

# 1. 总体开发原则

开始编码前必须先：

1. 阅读：
   - `AGENT_GUIDE.md`
   - `PROJECT_CONTEXT.md`
   - `CODEX.md`
   - `docs/ARCHITECTURE.md`
2. 阅读：
   - `pipeline_defs/` 中现有 pipeline
   - pipeline manifest schema
   - `tools/base_tool.py`
   - `tools/tool_registry.py`
3. 不要绕开 OpenMontage Pipeline 机制写一个独立脚本完成所有工作。
4. 新能力必须尽可能融入：
   - pipeline
   - tools
   - skills
   - schemas
   - checkpoint
5. 不修改已经可以工作的第三方 H3 API 调用，先封装 Adapter。
6. 所有模型能力不得散落 hardcode。
7. 不直接复制 Waoowaoo 源码，只借鉴“统一资产管理”理念，自建 Asset Registry。
8. 每个阶段完成后跑测试并提交独立 Git commit。
9. 如果当前仓库结构与本方案假设不一致，以当前 OpenMontage 最新实际代码为准。
10. 遇到不确定接口时先 inspect，不要猜 API 参数。

---

# 2. Phase P0：先解决当前舞蹈视频最明显的问题

这是最高优先级。

暂时：

**不要安装 ComfyUI。**

先证明现有：

```text
Codex + OpenMontage + H3
```

还能提升多少。

---

## 2.1 安装官方 H3 Prompt Skill

执行：

```bash
npx skills add https://github.com/MiniMax-AI/MiniMax-H3 --skill h3-prompt-writing
```

检查实际安装路径。

目标：

OpenMontage 调 H3 之前，Codex 必须先读取：

```text
h3-prompt-writing/SKILL.md
```

以及对应 reference guide。

注意：

这个 Skill **只负责 Prompt 编写**。

禁止让其直接调用 MiniMax 官方 API。

架构必须保持：

```text
H3 Prompt Skill
       │
       ▼
Canonical H3 Request
       │
       ▼
ThirdPartyH3Adapter
       │
       ▼
现有第三方 API
```

---

# 3. 增加 H3 Provider Adapter

先找到目前项目调用第三方 H3 的位置。

如果已经存在 Provider Tool：

直接重构。

如果没有，则按 OpenMontage BaseTool 规范新增类似：

```text
tools/video/
    h3_selector.py
    h3_third_party.py
```

不要固定要求文件名，如果当前仓库已有命名约定则遵循现有约定。

---

## 3.1 定义 H3CanonicalRequest

增加统一输入模型：

```python
H3CanonicalRequest
```

建议字段：

```yaml
mode:
  type: enum
  values:
    - T2VA
    - I2VA
    - FL2VA
    - L2VA
    - Ref2VA

prompt:
  type: string

duration_seconds:
  type: float

aspect_ratio:
  type: string

reference_images:
  type: list

reference_videos:
  type: list

reference_audios:
  type: list

first_frame:
  optional: true

last_frame:
  optional: true

resolution:
  optional: true

metadata:
  project_id:
  shot_id:
  attempt_id:
```

---

# 4. 增加 Provider Capability Profile

不要假设第三方 H3 和官方完全一致。

增加：

```text
config/providers/h3_third_party.yaml
```

例如：

```yaml
provider: my_h3_gateway

model_family: minimax_h3

capabilities:

  max_duration_seconds: 15

  supported_modes:
    - Ref2VA
    - I2VA

  reference_image:
    supported: true
    max_count: 2

  reference_video:
    supported: true
    max_count: 1

  reference_audio:
    supported: false

  first_frame:
    supported: true

  last_frame:
    supported: false

  first_last_frame:
    supported: false

  native_audio:
    supported: false

  aspect_ratios:
    - "9:16"
    - "16:9"

generation:

  preferred_duration_seconds: 15

  timeout_seconds: 600
```

以上仅为 schema 示例。

必须根据我现有第三方接口代码、请求参数或文档确定实际值。

不要凭猜测填 true。

---

# 5. H3 Prompt Compiler

新建一个 H3 Prompt Compiler。

职责：

```text
User Intent
+
Asset Binding
+
Motion Plan
+
Camera Constraints
+
H3 Prompt Skill
        ↓
Structured H3 Prompt
```

如果第三方 API 只有：

```json
{
  "prompt": "..."
}
```

则把 H3 Skill 产生的结构：

```text
subject_definitions
summary
retention_analysis
detailed_description
overall_soundscape
non_diegetic_music
```

按官方规定顺序拼成一个完整 prompt string。

**不能因为第三方 API 只有一个 prompt 字段，就放弃 H3 Skill 的结构化格式。**

---

# 6. 为“双人参考舞蹈”增加 Subject Mapping

新增：

```yaml
subject_mapping:
```

示例：

```yaml
subjects:

  - asset_id: character_rem_v1
    target_role: character_1
    reference_performer: dancer_left

  - asset_id: character_ram_v1
    target_role: character_2
    reference_performer: dancer_right
```

Prompt Compiler 必须明确告诉 H3：

```text
Character 1 always corresponds to the performer on the left
in the motion-reference video.

Character 2 always corresponds to the performer on the right.

The reference video is used for:
- body motion
- footwork
- body-weight transfer
- shoulder rotation
- hip rotation
- arm trajectories
- choreography timing
- relative position

Do NOT retain:
- performer identity
- performer face
- performer clothes
- original environment
```

不要只写：

```text
follow the reference dance
```

---

# 7. 增加 Camera Lock

舞蹈 Pipeline 默认建立：

```yaml
camera_policy:

  framing: full_body

  camera_motion: locked

  zoom: forbidden

  dolly: forbidden

  crop_feet: forbidden

  reframe: forbidden

  subject_full_body_visible: true
```

Prompt 必须明确包含：

```text
Static locked camera.

Maintain full-body framing for both performers throughout.

Both feet remain visible.

No zoom.

No push-in.

No dolly.

No camera re-framing.

Do not switch to medium shot or close-up.
```

允许用户主动覆盖。

---

# 8. 15 秒视频优先 One-shot

重构当前：

```text
5 + 5 + 5
```

规则。

新策略：

```text
if provider.max_duration >= target_duration:

    generate_one_shot()

else:

    segment_video()
```

即：

15 秒目标视频：

```text
H3支持15s
    ↓
优先一次生成15s
```

而不是默认拆 3 段。

增加配置：

```yaml
dance_pipeline:

  prefer_single_generation: true

  max_single_generation_seconds: provider_capability

  candidate_count: 2
```

候选数量默认 2。

避免成本失控。

---

# 9. 新增 Reference Dance Pipeline

不要继续复用通用视频 Pipeline。

按 OpenMontage 当前 manifest schema 新建：

```text
reference-dance
```

最终 stage 可以根据实际 schema 调整。

逻辑上至少包含：

```text
INGEST
↓
ANALYZE
↓
BIND_ASSETS
↓
PLAN
↓
GENERATE
↓
CONTINUITY_REVIEW
↓
REPAIR
↓
COMPOSE
```

必须遵守当前仓库 pipeline schema。

---

# 10. Pipeline：INGEST

输入：

```text
character reference images
dance reference video
optional background image
optional audio
duration
aspect ratio
```

输出：

```json
{
  "project_id": "...",
  "reference_video": "...",
  "characters": [],
  "target_duration": 15,
  "aspect_ratio": "9:16"
}
```

记录 ffprobe 信息：

```text
duration
fps
resolution
codec
audio
```

---

# 11. Phase P1：建设自己的 Asset Registry

不要集成整个 Waoowaoo。

我们自己建设轻量化资产系统。

首版：

```text
SQLite + filesystem
```

即可。

未来如有多人协作再切 MySQL / PostgreSQL。

---

# 12. Asset Registry 数据模型

至少包含：

## Project

```text
id
name
type
created_at
updated_at
```

---

## Asset

所有素材公共父实体：

```text
id
project_id
asset_type
name
version
file_path
source
sha256
metadata_json
created_at
```

asset_type：

```text
CHARACTER
CHARACTER_LOOK
SCENE
PROP
MOTION_REFERENCE
AUDIO_REFERENCE
FRAME
VIDEO
VOICE
```

---

## Character

```text
id
project_id
name
description
identity_prompt
negative_prompt
default_look_id
```

---

## CharacterLook

用于区分：

```text
蕾姆-女仆装
蕾姆-西装
蕾姆-日常装
```

字段：

```text
id
character_id
name
hair
clothing
body
makeup
style
reference_asset_ids
```

---

## Scene

```text
id
project_id
name
description
reference_asset_ids
lighting
camera_defaults
```

---

## MotionReference

```text
id
project_id
name
video_asset_id
duration
fps
performer_count
performer_mapping
motion_metadata
```

---

## Shot

```text
id
project_id
sequence
duration
prompt
generation_mode
provider
status
```

---

## GenerationAttempt

这是非常重要的一张表。

```text
id
shot_id

provider
model

prompt
request_json

output_asset_id

cost
latency

motion_score
continuity_score
identity_score

status
failure_reason

created_at
```

以后：

同一个 Shot：

```text
Attempt 1
Attempt 2
Attempt 3
```

全部可以追溯。

---

# 13. 文件目录

建议：

```text
projects/

  rem_dance_001/

    project.yaml

    assets/

      characters/

        rem/
          identity/
          looks/

        ram/
          identity/
          looks/

      scenes/

      props/

      motion/

        reference.mp4

      audio/

    shots/

      shot_001/

        attempts/

          attempt_001/
          attempt_002/

    continuity/

    output/
```

Asset Registry 保存索引。

文件本身保留在 filesystem。

---

# 14. 建立 Character Bible

每一个长期角色至少保存：

```text
front face
45-degree face
full body front
full body side
preferred expression
hair reference
body proportion
default costume
```

角色 JSON：

```yaml
id: rem_v1

identity:

  age_group: young_adult

  hair:
    color: blue
    style: short_bob

  eyes:
    color: light_blue

  body:
    build: slender

identity_constraints:

  preserve:
    - face
    - hairstyle
    - eye_color
    - body_proportion

  may_change:
    - clothing
    - expression
    - pose
```

---

# 15. 最关键的数据：Continuity State

每个视频片段生成完成后必须产生：

```text
ContinuityState
```

至少记录：

```yaml
shot_id:

timestamp:

characters:

  character_1:

    screen_position:
      x:
      y:

    facing:

    body_pose:

    left_hand_state:

    right_hand_state:

    left_foot_state:

    right_foot_state:

    weight_side:

    motion_direction:

  character_2:
    ...

camera:

  framing:

  zoom:

  camera_motion:

scene:

  lighting:

  background:

motion:

  velocity:

  direction:

  phase:
```

首版不要求所有字段完全由 AI 自动识别。

允许：

```text
自动分析
+
Codex vision summary
+
规则推导
```

组合产生。

---

# 16. Phase P1：Motion Analyzer

新增：

```text
tools/analysis/
```

中的 Motion Analyzer。

第一版不要强依赖 GPU。

先实现：

```text
FFmpeg
+
OpenCV
```

计算：

```text
frame difference
optical flow magnitude
motion energy
scene cut
```

每一帧输出：

```text
timestamp
motion_energy
```

例如：

```csv
timestamp,motion_energy
3.70,0.44
3.75,0.31
3.80,0.13
3.85,0.08
3.90,0.11
```

其中：

```text
motion_energy
```

局部低谷即：

```text
candidate_cut_point
```

---

# 17. 禁止固定 5 秒切段

如果第三方 H3 最多只能 5 秒：

旧：

```text
0-5
5-10
10-15
```

废弃。

改成：

```text
Motion Energy
       ↓
寻找动作低谷
       ↓
Semantic Cut
```

例如：

```text
0 → 4.32s
4.32 → 9.14s
9.14 → 15s
```

切点要求：

```text
motion_energy locally minimal
+
no hard scene cut
+
body relatively stable
```

---

# 18. 增加 Overlap

如果必须多段生成：

例如：

```text
Clip A
0.0 → 5.0

Clip B
4.5 → 9.5
```

保留：

```text
0.3~0.8s
```

动作 overlap。

增加参数：

```yaml
segmenting:

  overlap_seconds: 0.5

  min_segment_seconds: 3.5

  max_segment_seconds: provider_max
```

---

# 19. Continuation Generation

如果 Provider 支持：

```text
first frame
```

则下一段：

```text
上一段最后一帧
        ↓
next.first_frame
```

如果支持 FL2VA：

则同时考虑下一个目标姿态。

生成下一段时必须注入：

```text
previous ContinuityState
```

---

# 20. Seam Quality Gate

增加：

```text
continuity_score
```

第一版评分至少包含：

```text
boundary visual difference
motion direction difference
motion magnitude difference
subject center shift
bounding-box scale shift
```

输出：

```yaml
continuity:

  visual_score:

  motion_score:

  camera_score:

  total_score:
```

例如：

```text
>= 0.80 PASS

0.65 ~ 0.80 REPAIR

< 0.65 REGENERATE
```

阈值做配置，不硬编码。

---

# 21. 自动 Repair Policy

规则：

```text
轻微 seam
    ↓
transition / frame interpolation

明显姿态突变
    ↓
regenerate next clip

镜头大小突变
    ↓
regenerate

人物左右交换
    ↓
regenerate

动作方向错误
    ↓
regenerate
```

不要试图靠 Crossfade 修所有问题。

---

# 22. Phase P2：加入 DWPose，但做 Optional Dependency

完成 P0/P1 后再做。

集成：

```text
DWPose
```

用途不是生成视频。

用途：

```text
reference video
     ↓
whole-body pose extraction
     ↓
motion trajectory
```

对于每一个 dancer 产生：

```text
shoulder
elbow
wrist
hip
knee
ankle
```

等轨迹。

DWPose 不可用时：

Pipeline 必须能够退回：

```text
Optical Flow Analyzer
```

不能让整个系统挂掉。

---

# 23. Motion Fidelity Score

有 DWPose 后实现：

```text
Reference Pose
vs
Generated Pose
```

至少比较：

```text
arm trajectory
leg trajectory
body center trajectory
shoulder angle
hip angle
movement timing
```

归一化后：

```text
motion_fidelity_score = 0~1
```

不要追求学术级准确。

目标：

自动淘汰明显“不跳舞”的生成结果。

---

# 24. Candidate Selection

每次 H3：

```text
Candidate A
Candidate B
```

自动跑：

```text
Motion Fidelity
+
Continuity
+
Identity
+
Camera
```

最终：

```text
total_score =
    0.40 motion
  + 0.25 continuity
  + 0.20 identity
  + 0.15 camera
```

权重放配置。

舞蹈默认：

```text
motion 权重最高
```

普通剧情：

以后可以换 profile。

---

# 25. Phase P3：加入 ComfyUI + Wan2.2 Animate

只有前面全部稳定后再做。

目标不是用 ComfyUI 代替 OpenMontage。

而是增加：

```text
Motion Critical Fallback
```

架构：

```text
Generation Router

      │
      ├── H3
      │   cheap/default
      │
      └── Wan2.2 Animate
          motion-critical
```

---

# 26. Wan2.2 Animate Adapter

不要让 OpenMontage 直接操作 ComfyUI 节点。

增加：

```text
ComfyUIWanAnimateTool
```

负责：

```text
character image
+
reference performer video
+
workflow template
        ↓
ComfyUI API
        ↓
output video
```

ComfyUI Workflow JSON：

放：

```text
workflows/
    wan2_2_animate.json
```

不要写死进 Python。

---

# 27. Model Router

策略：

```yaml
routing_profiles:

  dialogue:
    preferred:
      - h3

  simple_motion:
    preferred:
      - h3

  dance:
    preferred:
      - h3
      - wan22_animate

  complex_motion:
    preferred:
      - wan22_animate
      - h3
```

自动切模型的条件：

```text
H3 attempt >= 2
AND
motion_score < threshold
```

则：

```text
fallback = wan22_animate
```

避免无限烧 H3 费用。

---

# 28. Cost Guard

增加：

```yaml
generation_budget:

  max_attempts_per_shot: 2

  max_h3_attempts: 2

  allow_wan_fallback: true

  max_total_generation_cost:
```

每次 GenerationAttempt 记录成本。

超过预算：

```text
STOP
+
ask human
```

---

# 29. 新增 Dance Pipeline Skill

为：

```text
reference-dance
```

创建专门 director skill。

其中写明确的导演原则：

## 第一原则

```text
MOTION > BEAUTY
```

舞蹈视频优先：

```text
动作完整度
```

再考虑：

```text
脸部绝对稳定
```

---

## 第二原则

禁止模型自行简化：

```text
footwork
knee bends
body weight transfers
hip rotation
shoulder rotation
arm trajectories
timing
```

---

## 第三原则

固定镜头：

```text
full body
static
no zoom
```

除非 Reference 明确有镜头运动。

---

## 第四原则

Reference Video Motion 是：

```text
HIGH PRIORITY
```

Reference Image Identity 是：

```text
HIGH PRIORITY
```

Reference Video 人物外形：

```text
IGNORE
```

---

# 30. OpenMontage Artifact 扩展

现有 artifact 机制里加入或映射：

```text
asset_manifest
motion_analysis
subject_mapping
generation_plan
generation_attempts
continuity_report
qa_report
```

每个阶段通过 checkpoint 落盘。

这样 Codex 会话中断后可以继续。

---

# 31. CLI / 使用入口

最后为用户提供一个简单入口。

例如：

```bash
python -m openmontage produce \
  --pipeline reference-dance \
  --project rem_dance_001
```

如果 OpenMontage 当前没有这种 CLI，不强行造类似形式。

遵循当前框架真实入口。

目标是用户最终只描述：

```text
用 rem_v1 和 ram_v1

参考：
assets/motion/dance01.mp4

生成：
15 秒
9:16
固定机位
优先 H3
```

Codex 自动完成剩余生产。

---

# 32. P0 验收标准

P0 完成后必须实际跑我现有的一次生成案例。

满足：

### 1.

能够读取官方 H3 Prompt Skill。

### 2.

仍调用我现有第三方 H3 API。

### 3.

Provider Adapter 与 Prompt Skill 完全解耦。

### 4.

如果接口支持 15 秒：

默认执行：

```text
ONE-SHOT 15s
```

### 5.

支持：

```text
2 characters
+
reference dance video
+
subject mapping
```

### 6.

Prompt 自动包含 Camera Lock。

### 7.

所有 GenerationAttempt 有日志。

### 8.

原有 Pipeline 不受影响。

---

# 33. P1 验收标准

Asset Registry 能完成：

```text
创建 Project

添加 Character

添加 CharacterLook

添加 Scene

添加 MotionReference

创建 Shot

记录 GenerationAttempt

保存输出素材
```

运行：

```text
asset list
```

或当前架构等价操作时能看到：

```text
REM
RAM
DanceReference01
```

---

# 34. Continuity 验收

对于多段生成：

系统必须检测：

```text
Clip A end
vs
Clip B start
```

至少输出：

```text
camera drift
motion mismatch
visual difference
```

并产生：

```text
PASS
REPAIR
REGENERATE
```

之一。

---

# 35. Phase 执行顺序

严格按照：

```text
P0
H3 Skill
Provider Adapter
15s One Shot
Subject Mapping
Camera Lock
Reference Dance Pipeline
        ↓
测试
        ↓
Git Commit

P1
Asset Registry
GenerationAttempt
ContinuityState
Motion Analyzer
Semantic Cut
        ↓
测试
        ↓
Git Commit

P2
DWPose
Motion Fidelity
Auto Candidate Selection
        ↓
测试
        ↓
Git Commit

P3
ComfyUI
Wan2.2 Animate
Model Router
        ↓
测试
        ↓
Git Commit
```

---

# 36. 不要做这些事

本轮明确禁止：

```text
❌ 整合整个 Waoowaoo
❌ 重写 OpenMontage
❌ 直接依赖 MiniMax 官方 SDK
❌ 删除现有第三方 H3
❌ 一开始安装十几个 ComfyUI Node
❌ 默认按 5 秒平均切视频
❌ 用 Crossfade 掩盖错误动作
❌ 把所有状态放 Prompt 里而不持久化
❌ 写死模型名称
❌ 写死 Provider capability
```

---

# 37. 第一步 Codex 要先给我输出 Audit Report

在修改代码前：

先阅读当前仓库并输出：

```markdown
# Current State Audit

## 1. OpenMontage version / structure

## 2. Current H3 integration

文件：
调用路径：
Provider：
API request：
支持参数：

## 3. Current pipeline

## 4. Current video stitching implementation

## 5. Existing asset management capability

## 6. Existing QA capability

## 7. Reusable modules

## 8. Changes required for P0

## 9. Changes required for P1

## 10. Risks / unknowns
```

尤其必须回答：

### 第三方 H3 目前实际支持什么？

```text
max duration = ?

reference image = ?

reference video = ?

reference audio = ?

first frame = ?

last frame = ?

first+last frame = ?

resolution = ?

aspect ratio = ?
```

从现有代码、真实 API 文档或已有调用证据确定。

不要猜。

---

# 38. 审核后再开始编码

Audit 完成后：

如果不存在阻塞问题：

直接从 P0 开始实施。

每完成一个 Phase：

输出：

```text
Files changed

Architecture changes

How to run

Tests

Known limitations

Next phase
```

并提交 Git：

```text
feat(dance): add h3 provider abstraction and prompt skill

feat(dance): add asset registry and continuity state

feat(dance): add motion analysis and semantic segmentation

feat(dance): add wan animate fallback
```

commit 名字可以根据实际改动调整。

---

# 39. 最终目标

最终我希望只需要告诉 Codex：

> 使用蕾姆 v1 和拉姆 v1。
>
> 参考 dance01.mp4。
>
> 生成一条 15 秒 9:16 双人舞。
>
> 人物外形保持角色资产。
>
> 动作尽可能严格跟随参考视频。
>
> 固定全身机位。
>
> H3 优先。
>
> 如果 H3 两次动作评分仍不合格，则使用 Wan2.2 Animate。

系统自动执行：

```text
Asset Resolve
      ↓
Reference Analysis
      ↓
Subject Mapping
      ↓
H3 Prompt Skill
      ↓
H3 Generation
      ↓
Motion QA
      ↓
Continuity QA
      ↓
Model Fallback
      ↓
Post-production
      ↓
final.mp4
```

这就是本次改造的最终验收目标。