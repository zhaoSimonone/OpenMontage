# OpenMontage 情景短剧 Agent 升级改造方案

日期：2026-08-26
状态：待确认，确认后进入实施
目标：在不改变已冻结的 `reference-dance` V1 行为的前提下，让 OpenMontage 能够以“一句话创意 + 一张人物参考图”为输入，稳定产出约 30 秒、9:16 的中文情景短剧，并在叙事连贯、角色一致、声音、字幕、可恢复执行和交付可审计性上达到或超过已分析的公司 AIGC Agent。

## 1. 结论

**建议在当前 OpenMontage 增量改造，不另起炉灶。**

新增一个与舞蹈完全隔离的 `narrative-short` pipeline。它把公司 Agent 已验证有效的做法，沉淀为可审查、可复用、可恢复的生产链路：

```text
一句创意 + 一张人物参考图
        ↓
故事规划与角色锁定
        ↓
两段 15 秒的叙事分镜 + 跨段桥接契约
        ↓
MiniMax-H3 分段生成（同一角色参考）
        ↓
旁白 / 对白 / BGM 的独立音频时间轴
        ↓
0.3 秒叙事型转场、字幕与最终混音
        ↓
分段 QA + 拼接 QA + 成片 QA + GenerationAttempt 审计
```

不建议另建项目，原因如下：

| 维度 | 当前 OpenMontage 已有能力 | 另起炉灶的代价 |
|---|---|---|
| H3 接入 | 已有 `minimax_h3_video`，支持 9:16、4-15 秒、多参考图/视频/音频、任务轮询和落盘 | 重做 Provider、轮询、错误处理、成本估算与 CDN 约束 |
| 工件与恢复 | 已有 `projects/<id>/`、checkpoint、Backlot、GenerationAttempt 习惯 | 重新设计存储、状态与人工审核路径 |
| 后期 | 已有 `video_stitch`、`video_compose`、`audio_mixer`、`subtitle_gen` | 重复实现拼接、混音、字幕和成片检查 |
| 声音 | 已有 Doubao 与 DashScope TTS，前者有时间戳，后者有自然语言表演指令 | 重建多 Provider 选择和回退逻辑 |
| QA | 已有视频分析、抽帧、容器/音频检查；舞蹈线已有 GenerationAttempt/质量门范式 | 重新建立可追溯的质检与失败恢复 |
| 风险隔离 | 可将新能力限定在新 pipeline 和新工具中 | 两套代码库会分裂素材、Provider 及质量规范 |

当前项目的架构刚好适合此类扩展：创作判断留在 pipeline director skill，Python 只做确定性的请求编译、文件落盘、媒体处理和检查。不会引入一个不可审查的“大而全 Python 编排器”。

## 2. 已分析的公司 Agent 与可复用经验

本方案依据以下已保存执行记录和成片分析，而不是只根据界面猜测：

- `~/Desktop/AIGC/langbridge-aigc/单人情景剧.html`
- `~/Desktop/AIGC/langbridge-aigc/舞蹈视频.html`
- 单人情景剧最终视频：30.0 秒、768x1344、9:16、H.264 + AAC、25 fps。

### 2.1 公司 Agent 的实际生产路径

已观察到的单人情景剧执行链路如下：

```text
读取 H3 提示词规范
→ 理解人物参考图
→ H3 片段 1（15 秒）
→ H3 片段 2（15 秒）
→ 选取男声音色与 BGM
→ 独立 TTS 生成男主旁白
→ 0.3 秒 crossfade 拼接
→ 分段抽帧与视觉 QA
→ 失败时缩小 QA 采样范围重试
→ 旁白混音（保留女主原生对白）
→ BGM
→ ASR 字幕；校正失败时手写 SRT
→ 字幕烧录与最终抽帧 QA
```

它的连续性并非来自“两个 H3 片段严格保持同一姿态”。其成功关键是**叙事连续性**：

- 两段都使用同一人物参考图和服装；
- 使用同一个纸袋作为跨段道具；
- 前段“玄关拿着纸袋”，后段“餐桌放下纸袋”，是明确的因果延续；
- 片段边界用约 0.3 秒暗场式交叉过渡隐藏微小画面跳变；
- 男主旁白、音乐和字幕跨越边界连续进行。

这套方法适合情景短剧，不能直接用于需要逐帧姿态连续的双人舞蹈。舞蹈继续由 `reference-dance` 负责，情景短剧不复用其动作评分或提示词。

### 2.2 当前第三方 H3 Provider 的真实边界

当前 OpenMontage 的 `tools/video/minimax_h3_video.py` 已支持：

- `MiniMax-H3`、4-15 秒、`9:16`、`768P`/`2K`；
- 文生、图生、参考图/参考视频/参考音频；
- 首帧、尾帧和首尾帧模式；
- 任务提交、轮询、下载、成本估计和输出落盘。

当前接口**没有被验证或暴露**以下能力：

- 固定 `seed`、`fps`、`steps`；
- 内置 `narrationMode`、`dialogueTurns`、`speakerBindings`；
- 可保证的原生角色对白；
- 将 `reference_to_video` 与上一段的首/尾帧控制在同一请求中混用。

因此，本项目的可达目标是“以同一参考图、叙事桥、后期声音和 QA 复现公司 Agent 的产品效果”，而不是承诺逐字段复制公司内部 H3 封装。声音主路径由 OpenMontage 独立生成和混音；是否保留 H3 偶发产生的自然对白，交由 QA 后逐条决策。

## 3. 产品边界与验收目标

### 3.1 V1 输入和输出

**输入**

1. 一句话创意，例如：`帮我生成一个 30 秒的情景短剧，男主第一人称看女主，男主不出镜。`
2. 一张人物主参考图（URL 或本地文件；需要远端生成时由现有素材/CDN 流程提供可访问 URL）。
3. 可选：角色姓名、目标平台、禁忌内容、参考视频、指定台词、已有 BGM。

**输出**

- 约 30 秒、9:16 成片，默认 `768P`；
- 两段 15 秒 H3 视觉素材及所有原始请求；
- 故事脚本、分镜、跨段桥接契约、音频时间轴、SRT、混音和最终 QA；
- 每次付费调用都有独立 `GenerationAttempt`，可定位到具体片段并只重试失败段；
- Backlot 可查看当前阶段、决策和产物。

### 3.2 V1 非目标

- 不声称逐帧复刻舞蹈或复杂长动作；该需求继续走 `reference-dance`。
- 不在未经明确批准时切换到 Wan、ComfyUI、Seedance 或其他付费 Provider。
- 不在 P0/P1 训练角色 LoRA、安装 DWPose 或实现姿态控制工作流。
- 不默认生成未经授权的真人声音克隆。
- 不保证 H3 生成的角色原生对白可用；音频可控性以独立 TTS 主路径为准。

### 3.3 目标与测量

“超越”必须用实际样本验证，不应先写成结论。首轮以公司 Agent 保存的单人情景剧和 OpenMontage 的新基准样本进行人工并排评审。

| 指标 | V1 通过线 | 目标水平 | 证据 |
|---|---:|---:|---|
| 输出规格 | 9:16、28.5-31.0 秒、可播放、有音频 | 30.0 +/- 0.5 秒 | `final_review`、ffprobe |
| 角色一致性 | 两段服装、发型、脸部不明显漂移 | 5 个指定帧均可认定为同一角色 | 抽帧联系表 + 人工判定 |
| 叙事清晰度 | 2 秒内建立情境；结尾完成一个情绪/动作闭环 | 无需解释即可理解两段因果 | 人工盲评 |
| 片段衔接 | 无突兀人物/服装/关键道具跳变 | 桥接道具、声音与情绪均连续 | seam QA + 人工盲评 |
| 声音自然度 | 旁白可听清，停顿和情绪与脚本一致 | 优于旧版生硬 TTS | 听感盲评 |
| 字幕正确性 | 与批准脚本一致，无遮挡脸部 | 全片字幕无需人工修正 | 时间轴比对 + OCR/抽帧复核 |
| 可恢复性 | 单段失败只重跑该段，已完成工件复用 | 任意检查点可继续 | 故障注入测试 |
| 成本可解释性 | 每段估价、实际 task id、重试原因可追溯 | 可按镜头比较生成成本 | `GenerationAttempt` + cost log |

## 4. 目标架构

```text
                         narrative-short pipeline

  用户一句话 + 主参考图
             │
             ▼
  ① intake / identity lock ──────► asset_manifest
             │                       character_lock
             ▼
  ② story plan ──────────────────► script + scene_plan
             │                       2 x 15s beats
             ▼
  ③ bridge contract ─────────────► segment_bridge_contract
             │                       prop / state / audio / transition
             ▼
  ④ H3 request compiler ─────────► shot_001/002 request JSON
             │                       planned GenerationAttempt
             ▼
  ⑤ controlled generation ───────► two raw clips + response metadata
             │
             ├──► clip QA / seam QA ── fail ──► only regenerate failed clip
             │
             ▼
  ⑥ audio timeline ──────────────► TTS segments + BGM + SFX + canonical SRT
             │
             ▼
  ⑦ stitch / compose ────────────► 30s vertical final.mp4
             │
             ▼
  ⑧ final QA / report ───────────► final_review + validation_report
```

设计原则：

1. **一个故事只用一个视觉支点。** 每个 30 秒作品只围绕一个场景转折、一种核心关系和一个可重复的关键道具展开。
2. **叙事连续性优先于伪造的姿态连续性。** 两段之间避免让角色在同一复杂动作中接续；让场景、道具或视线承担连接任务。
3. **先审批请求，再付费生成。** 请求、估价、角色映射、桥接契约都必须在 H3 调用前落盘。
4. **视频负责表演，后期负责时间。** H3 只承担 15 秒视觉表演；声音、BGM、字幕、淡化和最终时长由可控本地工具决定。
5. **失败定位到镜头。** 片段 2 身份漂移，不重跑片段 1、TTS 和字幕。

## 5. 新 Pipeline 设计

新增：`pipeline_defs/narrative-short.yaml`，版本 `0.1`，类别 `custom`，稳定性 `beta`。

| 阶段 | 目的 | 输入 | 核心产物 | 质量门 / 审批 |
|---|---|---|---|---|
| `intake` | 固定任务边界、画幅、时长、人物主参考和禁忌 | 用户输入、图片 | `narrative_short_brief`、`asset_manifest`、`character_lock` | 主图存在、角色为成年人、9:16/30 秒明确 |
| `story_plan` | 将一句话收敛为一个可在 30 秒完成的情节 | brief、character lock | `script`、`scene_plan` | 两段均有明确情绪/动作目标，无镜头堆砌 |
| `bridge_contract` | 为两段建立可执行的视觉、因果、声音衔接 | script、scene plan | `segment_bridge_contract` | 有唯一桥接物/行为；无“同动作硬接” |
| `plan_generation` | 编译两份可审查的 H3 请求与计划记录 | assets、script、bridge | 两份 request JSON、planned attempts、`decision_log` | 人工批准；未发送付费请求 |
| `generate` | 按段生成、落盘、记录 task id | approved requests | raw clips、submitted attempts | 每段分别检查；失败只重试该段 |
| `audio_post` | 生成/选择声音，建立可控音频与字幕时间轴 | approved script、raw clips | TTS、BGM、SFX、`audio_timeline`、SRT | TTS 样本试听批准；字幕来自脚本而非仅 ASR |
| `review` | 进行单段、seam、声音、字幕与成片前检查 | clips、audio timeline | `narrative_short_qa`、`final_review` | 通过后才能合成；失败返回对应阶段 |
| `compose` | 转场、混音、字幕烧录、平台成片 | review、edit decisions | `renders/final.mp4`、render report、validation report | 成片规格与人工观察完整 |

每个阶段都在 `projects/<project-id>/` 下落盘，沿用项目既有目录约定：

```text
projects/<project-id>/
├── artifacts/
│   ├── narrative_short_brief.json
│   ├── character_lock.json
│   ├── script.json
│   ├── scene_plan.json
│   ├── segment_bridge_contract.json
│   ├── shot_001_attempt_001_minimax_h3_request.json
│   ├── shot_002_attempt_001_minimax_h3_request.json
│   ├── generation_attempts/
│   ├── audio_timeline.json
│   ├── narrative_short_qa.json
│   └── validation_report.md
├── assets/
│   ├── images/
│   ├── video/
│   │   ├── shot_001_attempt_001.mp4
│   │   └── shot_002_attempt_001.mp4
│   ├── audio/
│   ├── music/
│   └── subtitles.srt
└── renders/
    ├── stitch_preview.mp4
    └── final.mp4
```

## 6. 跨段桥接契约

这是本次改造的核心工件。它将“看起来会衔接”改成可检查、可生成、可复用的约束。

### 6.1 约束规则

- 两段均重复相同的 `character_lock`、服装、场景调色和镜头语言；
- 每条边界只允许一个**桥接物**或一个**桥接行为**，不能同时承载多个复杂变化；
- 段 1 收于“可切换状态”，段 2 从“同一因果结果”开始；
- 不要求 H3 精确复刻上段最后一帧；
- 视觉无法精确续接时，默认使用 `fade-through-black` 或 `crossfade` 0.3 秒，并让声音跨段连续；
- `crossfade` 后总时长会减少 0.3 秒，最终用结尾 0.3 秒自然停顿/定格补足，目标保持在 30 秒附近；
- 不接受“角色正在转身、挥手到一半、镜头快速运动中”作为切点。

### 6.2 数据结构

```json
{
  "version": "1.0",
  "target_duration_seconds": 30,
  "segments": [
    {
      "id": "shot_001",
      "start_seconds": 0,
      "end_seconds": 15,
      "purpose": "建立情境并让女主带着纸袋在门口出现",
      "terminal_state": {
        "character_position": "doorway, three-quarter body, looking toward camera",
        "key_prop": "small kraft paper bag held in right hand",
        "emotion": "gentle anticipation",
        "camera": "first-person eye-level, slow natural push-in"
      }
    },
    {
      "id": "shot_002",
      "start_seconds": 15,
      "end_seconds": 30,
      "purpose": "在餐桌展开纸袋，完成照顾男主的情绪落点",
      "initial_state": {
        "character_position": "beside dining table, three-quarter body",
        "key_prop": "same kraft paper bag placed on table",
        "emotion": "relieved warmth",
        "camera": "same lens family and eye-level POV"
      }
    }
  ],
  "joins": [
    {
      "from": "shot_001",
      "to": "shot_002",
      "semantic_bridge": {
        "kind": "prop_cause_effect",
        "bridge_prop": "small kraft paper bag",
        "from_action": "she turns inward carrying the bag",
        "to_action": "she puts the same bag on the dining table"
      },
      "visual_lock": ["character_lock_v1", "wardrobe_v1", "warm-evening-home", "50mm-natural-perspective"],
      "transition": {"type": "fade", "duration_seconds": 0.3},
      "audio_policy": {
        "narration_continues": true,
        "music_crossfades": true,
        "room_tone_continues": true
      }
    }
  ]
}
```

`segment_bridge_contract` 会有 JSON schema，P0 在请求编译前校验：没有桥接物/状态/转场/音频策略的计划不能提交 H3。

## 7. H3 请求编译规范

新增一个**确定性的** `narrative_short_h3_plan` 工具。它不创作剧情、不调用付费 API，只将已批准的结构化工件编译为 H3 请求 JSON 和 planned `GenerationAttempt`。创作判断由 `plan-generation-director.md` 完成。

### 7.1 角色锁定块

每一个片段重复相同锁定块，防止第二段逐渐变成另一张脸：

```text
[identity_lock]
The supplied reference image is the canonical appearance of the only visible
adult female character. Preserve her recognizable face shape, hairstyle,
hair color, wardrobe, body scale, age presentation, and calm natural makeup.
She is the same person in every shot. Do not introduce another person.

[pov_rule]
The camera is the adult male protagonist's first-person point of view.
Never show his face, body, hands, shadow, reflection, or silhouette.
Only the adult female character is visible.
```

### 7.2 每段请求模板

请求采用英文，以便模型执行稳定，结构固定：

```text
[format]
15-second vertical 9:16 cinematic live-action short, natural 50mm perspective,
soft realistic skin and hair texture, no captions or watermark.

[identity_lock]
<canonical character lock>

[scene_lock]
<location, time of day, lighting, color, wardrobe and lens policy>

[story_beat]
<only this 15-second segment's beginning, turn, terminal state>

[bridge_state]
<prop, orientation, emotion, and camera state that connects to the other segment>

[performance]
Natural restrained acting; clear gaze toward the camera; small believable pauses;
one action at a time; no rushed multi-step choreography.

[camera]
<explicit POV policy and allowed camera movement>

[negative_constraints]
No male body, hand, face, shadow, reflection, extra people, identity drift,
wardrobe change, scenery jump, text, subtitles, logo, watermark, distorted hands,
plastic CGI skin, exaggerated seduction, abrupt close-up rewrite.
```

### 7.3 两段生成策略

默认采用**相同主参考图 + 两个独立 `reference_to_video` 请求 + 叙事桥接**。这是当前 metaso H3 接口下身份稳定性和可恢复性的最佳折中。

首尾帧模式是受控实验项，不作为默认依赖，原因是当前 Provider 不支持和 `reference_to_video` 参考素材可靠混用。只有在一次能力探测明确证实可用、且不会降低身份一致性时，才将上一段尾帧作为第二段的起始控制。

## 8. 音频、对白与字幕方案

### 8.1 声音分层

当前 Provider 标记为 `native_audio: false`，因此音频主路径不能依赖 H3。按可控性从高到低采用：

1. **男主旁白**：优先独立 TTS，使用 `dashscope_tts` 的 `qwen3-tts-instruct-flash` 做短样本试听；需要精确字幕时使用 `doubao_tts`，其结果会写入句级/字级时间戳。
2. **女主对白**：优先短句、少量、情绪明确。若 H3 不提供可靠口型，不强行塞入复杂对白；以女主自然表情和男主旁白承载情绪。后期对白仅在画面不需要精确唇形的镜头使用。
3. **环境声与 SFX**：衣料、脚步、门、纸袋等轻量效果，放在动作因果点，不堆砌。
4. **BGM**：全片统一曲目，跨越边界连续；有人声时由 `audio_mixer` duck，避免盖住台词。

TTS 选择不凭“模型名”决定。每个作品先合成 6-10 秒高情绪样本，按可懂度、情绪、停顿、机械感进行人工试听后锁定 Provider/voice/instructions，写入 `decision_log`，再生成全片。

### 8.2 时间轴优先于 ASR

字幕主来源是批准后的 `script.json` 和 TTS 返回时间戳，不是“先 ASR 再猜字幕”。

```text
批准脚本 + TTS 时间戳
→ audio_timeline.json
→ subtitle_gen
→ subtitles.srt
→ video_compose 烧录
→ 最终抽帧检查
```

ASR 只作为音频内容检查和回退。ASR 失败时，使用脚本与已知 TTS 时间戳生成 SRT，不阻断成片。

### 8.3 混音固定规则

- 目标响度：短视频默认 `-14 LUFS`；
- BGM 默认起始音量 `0.20-0.30`，旁白期间 duck 至 `0.12-0.18`；
- 片段边界音乐和 room tone 均做 0.3 秒 crossfade；
- 所有语音和音乐先合成为一个 approved mix，再由 `video_compose` 替换最终视频音频，避免分别处理时失去同步。

## 9. QA、停止条件与失败恢复

新增 `narrative_short_qa`。它是确定性的本地质量检查工具，负责技术和片段关系，不替代人的审美判断。视觉语义由 `visual_qa` 抽帧后由 reviewer skill 复核。

### 9.1 自动检查

| 层级 | 检查内容 | 失败动作 |
|---|---|---|
| 输入 | 主参考图、URL 可访问性、时长/画幅、成人角色限制 | 阻断进入生成计划 |
| 单段技术 | 容器、9:16、时长、解码、黑帧、音频流 | 仅重跑受影响步骤 |
| 单段视觉 | 起/中/末关键帧：人物数量、主脸、服装、场景、关键道具、POV 约束 | 重跑该片段；不全链路重跑 |
| seam | 边界亮度跳变、关键道具存在、颜色/镜头尺度、转场前后帧差 | 调整转场；必要时重跑片段 2 |
| 音频 | 语音存在、削波、意外静音、BGM duck、时长对齐 | 重混音或重 TTS |
| 字幕 | 与批准文本一致、时间不越界、不落在脸部区域 | 重建 SRT 或调整字幕样式 |
| 成片 | 9:16、28.5-31 秒、H.264/AAC、文件可播放 | 返回 compose |

### 9.2 人工 reviewer 的固定观察表

每次至少审查以下帧：`0s, 3s, 8s, 14.7s, 15.2s, 20s, 26s, 29s`。

- 女主是否仍为同一人、同一发型、同一衣服？
- 有没有男主身体、手、影子或镜中反射？
- 关键道具是否在因果上可解释？
- 边界是否是在动作低谷或情绪停顿处？
- 声音是否像自然情绪，而不是把字逐个读完？
- 字幕是否妨碍面部和关键动作？

### 9.3 有界恢复策略

```text
请求校验失败
  → 修复 artifact；不调用 H3

H3 超时 / 网络失败
  → 使用同一 idempotency 信息查询一次；无 task id 才重提该段

片段 1 不通过视觉 QA
  → 重跑片段 1；片段 2 尚未生成则不提交

片段 2 不通过角色/道具/情绪 QA
  → 重跑片段 2；保留片段 1、声音和已批准 script

seam 不通过但两段都合格
  → 优先尝试 0.3 秒 fade/crossfade 和音频桥；仍不通过才重跑片段 2

TTS 不自然
  → 仅重做 6-10 秒样本和整段音频；不重跑视频

ASR / OCR 校验失败
  → 用 canonical script + TTS timestamps 重建 SRT；不重跑视频

连续两次同片段 H3 都不能通过人工视觉门
  → 停止自动重试，输出原因与候选 Provider；等待用户明确批准，不自动切换模型
```

## 10. 文件级实施清单

### P0：建立可生成、可审查、可恢复的 30 秒闭环

新增：

- `pipeline_defs/narrative-short.yaml`
- `skills/pipelines/narrative-short/executive-producer.md`
- `skills/pipelines/narrative-short/intake-director.md`
- `skills/pipelines/narrative-short/story-plan-director.md`
- `skills/pipelines/narrative-short/bridge-contract-director.md`
- `skills/pipelines/narrative-short/plan-generation-director.md`
- `skills/pipelines/narrative-short/generate-director.md`
- `skills/pipelines/narrative-short/audio-post-director.md`
- `skills/pipelines/narrative-short/review-director.md`
- `skills/pipelines/narrative-short/compose-director.md`
- `tools/video/narrative_short_h3_plan.py`
- `tools/video/narrative_short_generator.py`
- `tools/analysis/narrative_short_qa.py`
- `schemas/artifacts/segment_bridge_contract.schema.json`
- `schemas/artifacts/narrative_short_brief.schema.json`
- `schemas/artifacts/audio_timeline.schema.json`
- `tests/contracts/test_narrative_short_pipeline.py`
- `tests/tools/test_narrative_short_h3_plan.py`
- `tests/tools/test_narrative_short_qa.py`

复用，不复制：

- `tools/video/minimax_h3_video.py`
- `tools/video/video_stitch.py`
- `tools/video/video_compose.py`
- `tools/audio/audio_mixer.py`
- `tools/audio/doubao_tts.py`
- `tools/audio/dashscope_tts.py`
- `tools/subtitle/subtitle_gen.py`
- `tools/analysis/video_analyzer.py`
- `tools/analysis/visual_qa.py`
- `lib/checkpoint.py`
- `tools/cost_tracker.py`

P0 验收：

1. 用 mock H3 响应跑通从计划到 QA 的单元/契约测试；
2. 从一句话与一张人物图生成两份审查用 H3 request，均包含 identity lock、POV rule、故事段落和 bridge state；
3. 每份 request 都写出 planned GenerationAttempt，且不产生付费调用；
4. 可将两个符合规格的 fixture 视频转为约 30 秒成片，带确定性 SRT 和合成音频；
5. `reference-dance` 的现有 contract tests 保持通过，确保 Freeze 不被破坏。

### P1：提高成片质量和交互效率

新增能力：

- “高风险复杂动作”检测：含拥抱、跑动、多人、换装、镜子、复杂口型的故事自动拆成更安全的镜头动作；
- 用首段结束帧生成内部 review contact sheet，辅助片段 2 Prompt 审查，但不默认改变 Provider 模式；
- 双 TTS 小样 A/B 比较与一次性锁定 voice profile；
- 字幕 face-safe 区域规则和必要时的动态上下位置；
- 自动生成 `validation_report.md`，包含 H3 Prompt、请求、抽帧、音频、QA 和人工观察模板；
- Backlot 对 narrative-short 显示片段状态、当前桥接物、重试次数和成本。

P1 验收：

1. 连续完成 3 个不同情景短剧样本；
2. 每个样本只在不合格片段上重试，未发生全链路无意义重跑；
3. 三个样本均有完整审计链和人工最终观察；
4. 盲评中，至少 2/3 被评为“能看懂、人物没明显换脸、声音自然、边界不突兀”。

### P2：达到或超过公司 Agent 的产品化体验

在 P0/P1 样本证明质量后再做：

- 将“一句话 + 一张图”包装为 Backlot 的新项目模板；
- 提供 3 个自动生成的故事方向与成本区间，用户一次批准后执行；
- 为稳定授权角色建立可版本化的 `character_lock`/素材库引用；
- 根据真实生成记录统计 H3 通过率、片段重试率、单条成本和人工评分；
- 对比公司 Agent 参考成片，发布客观 benchmark 和差异说明；
- 只有当两次 H3 同类题材失败时，才把一个新 Provider 作为**需人工批准的**试验分支接入。

P2 验收：

1. 用户从一次输入到可审核生成计划，无需手动写两段提示词；
2. 30 秒成片的工件完整率为 100%；
3. 成片可播放和字幕脚本一致率为 100%；
4. 以至少 5 条样本和同一评审表，报告相对公司 Agent 的叙事、角色、声音、衔接、可审计性和成本对比；
5. 只有当数据和人工盲评都支持时，才声明达到或超越。

## 11. 不影响舞蹈 V1 Freeze 的隔离规则

- 不修改 `pipeline_defs/reference-dance.yaml` 的行为与阶段顺序；
- 不改动 `reference_dance_h3_plan` 的 prompt 语义、阈值或 fallback 规则；
- 不安装 DWPose、不安装 Wan2.2 Animate、不扩展舞蹈 Asset Registry；
- narrative-short 的 schema、skill、planner、QA 和测试均使用独立命名空间；
- 公共工具只在发现真实缺陷时做向后兼容修复，并额外运行 `reference-dance` 回归测试；
- 所有新生成内容进入新的 `projects/<new-project-id>/`，不改写 `rem-ram-dance-ep01` baseline dataset。

## 12. 实施顺序与第一次付费验证

确认后按以下顺序实施：

1. 完成 P0 的 schemas、pipeline manifest、director skills、H3 request compiler、QA 和测试。
2. 执行全量可运行测试与 `reference-dance` 回归；修复由本次改造引入的问题。
3. 初始化一个新的 narrative-short 项目，生成并展示：brief、script、scene plan、bridge contract、两份 H3 request、成本估计和 TTS 小样方案。
4. 等待你明确批准这一次的 Provider（第三方 metaso MiniMax-H3）、模型（MiniMax-H3）、分辨率、两段 15 秒付费生成和 TTS 选择。
5. 仅在批准后生成两个片段，运行 clip/seam QA、音频/字幕合成和 `validation_report.md`。
6. 停止等待人工审核；不自动切换 Provider，也不自动进入 Wan/ComfyUI fallback。

## 13. 风险与诚实边界

| 风险 | 影响 | 方案中的控制 |
|---|---|---|
| 公司内部 H3 封装比 metaso API 有更多隐式参数 | 无法逐项复刻其原生对白/稳定性 | 复现流程与成片体验，不承诺隐藏参数；用后期声音与桥接提高可控性 |
| 一张图不足以覆盖所有角度 | 第二段可能有脸型漂移 | 强 identity lock；P1 再引入可版本化辅助视角素材，且先人工审批 |
| H3 对复杂互动和口型不稳定 | 短剧显得假或动作错误 | 一段一个动作，减少复杂肢体接触；对白短句化，必要时改为旁白 |
| 两段独立生成仍会跳变 | 衔接不如单镜头 | 道具因果桥、场景锁、0.3 秒转场、连续声音；只重跑问题段 |
| TTS 听感差异大 | 情绪不可信 | 强制短样本试听，保存 voice/instructions，必要时切换已批准的 TTS Provider |
| 付费生成随机性 | 成本不可控 | 先请求审核、每段估价、重试上限、GenerationAttempt 与失败停止条件 |

## 14. 最终决策请求

建议批准：**在当前 OpenMontage 内实施 P0，新增隔离的 `narrative-short` pipeline，以第三方 metaso MiniMax-H3 继续作为唯一视频生成 Provider。**

P0 完成后先展示非付费的完整生产包和测试结果。任何 H3、TTS 或新 Provider 的付费调用均另行明确确认。这样先把产品能力和质量控制建立起来，再用同一套可审计流程与公司 Agent 做真实对比。
## 15. Provider-ready 素材上传

MiniMax-H3 当前通过 `image_url` 读取参考图，因此不要求特定 CDN 品牌，要求的是
Provider 服务端无需登录即可访问的 HTTPS 图片地址。新增 `tencent_cos_upload`
工具负责：

1. 使用腾讯官方 COS SDK 签名上传本地图片、视频或音频；
2. 默认使用 `openmontage/<project-id>/` 前缀，支持显式 object key；
3. 上传后以匿名 `HEAD` 请求检查 HTTP 200、Content-Type 和文件大小；
4. 只将公开 URL、对象信息和 SHA-256 写入工件，不写入 SecretId/SecretKey。

COS 桶保持“公有读、私有写”。OpenMontage 需要在本地 `.env` 配置：

```env
TENCENT_COS_SECRET_ID=
TENCENT_COS_SECRET_KEY=
TENCENT_COS_BUCKET=public-cos-1257258774
TENCENT_COS_REGION=ap-guangzhou
TENCENT_COS_PREFIX=openmontage/
```

上传子用户只授予当前桶对象范围内的 `cos:PutObject` 和 `cos:HeadObject`。
`reference-dance` 不接入该阶段；`narrative-short` 在 `plan_generation` 编译 H3
请求前使用它准备本地参考素材。
