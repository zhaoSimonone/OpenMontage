# 蕾姆 / 拉姆舞蹈视频工作流改造状态

更新时间：2026-08-22  
项目：`rem-ram-dance-ep01`  
主模型：`MiniMax-H3`  
目标：基于原舞蹈参考视频，制作蕾姆与拉姆的 9:16 双人舞蹈视频。

## 一、结论

当前 P0、P1 已完成，P2 的代码接入已完成，但还没有用新路由器发起新的付费生成，也没有实际跑通 Wan 2.2 fallback 成片。

当前工作流已经具备“生成、动作评分、连续性检查、失败决策和人工批准后回退”的基本闭环，但还没有达到“动作严格复刻参考舞蹈”的最终目标。

## 二、已完成

### 1. 舞蹈专用 Pipeline

- 新增并启用 `reference-dance` pipeline。
- Pipeline 阶段包括：
  - `ingest`
  - `bind_assets`
  - `plan_generation`
  - `generate`
  - `review`
  - `compose`
- 增加对应的生成和 review 导演规则。
- 明确禁止任务漂移到医院短剧、男主 POV、TTS 对白或其他无关剧情。

文件：

- [`pipeline_defs/reference-dance.yaml`](../pipeline_defs/reference-dance.yaml)
- [`skills/pipelines/reference-dance/generate-director.md`](../skills/pipelines/reference-dance/generate-director.md)
- [`skills/pipelines/reference-dance/review-director.md`](../skills/pipelines/reference-dance/review-director.md)

### 2. MiniMax-H3 主生成路径

- 保留现有 `minimax_h3_video` Provider。
- 继续使用 metaso 的 MiniMax-H3 API。
- 增加提交请求和查询请求的独立超时配置。
- 支持 15 秒 one-shot 生成。
- 支持 9:16 竖屏比例。
- 支持人物参考图、参考舞蹈视频和参考音频角色绑定。
- 没有新增裸 curl 作为主生成路径。

### 3. H3 舞蹈 Prompt 规划器

新增 `reference_dance_h3_plan`，用于在付费生成前生成可审核的请求 JSON 和 GenerationAttempt 计划记录。

当前 Prompt 已包含：

- 蕾姆固定左侧；
- 拉姆固定右侧；
- 两人保持固定相对站位；
- 两人全身入镜；
- 双脚保持可见；
- 固定机位；
- 9:16 竖屏；
- 动作、节奏和双人配合优先；
- 参考视频只用于动作和节奏，不复制原人物、服装和场景；
- 禁止医院房间、第一人称 POV、男主、对话剧情等错误方向。

### 4. Motion / Continuity QA

新增 `reference_dance_qa`，使用 FFmpeg、Pillow 和 numpy 进行本地检查，不依赖 OpenCV。

当前检查内容：

- 参考视频和候选视频的 motion energy；
- 候选动作与参考动作的整体能量对比；
- 下半身动作占比；
- 动作活跃度；
- 多片段之间的视觉跳变；
- 边界处的 motion energy 跳变；
- 边界处的下半身节奏变化；
- `PASS / REPAIR / REGENERATE` 决策。

当前阈值：

| 指标 | 阈值 | 含义 |
|---|---:|---|
| `motion_score` | `>= 0.70` | 动作达到通过线 |
| `motion_score` | `< 0.55` | 动作明显不合格，需要重新生成 |
| `continuity_score` | `>= 0.70` | 连续性通过 |
| `continuity_score` | `< 0.65` | 需要修复片段衔接 |

### 5. 当前成片 QA 结果

对已有的 15 秒 H3 one-shot 成片检查结果：

```text
motion_score:      0.687066
continuity_score:  1.0
decision:           REPAIR
```

结论：视频技术上可播放，连续性没有明显问题，但动作强度和下半身运动还没有达到参考舞蹈要求。

### 6. P2 回退路由

新增 `reference_dance_video_generate`，作为舞蹈生成阶段的受控路由器。

行为规则：

- 默认委托 `minimax_h3_video`；
- 读取 `reference_dance_qa` 输出的 `next_action`；
- 只有 QA 输出 `consider_fallback_provider` 且目标是 `comfyui_video` 时，才进入回退候选；
- 回退必须显式传入 `fallback_approved=true`；
- 未批准时只写入 `approval_required` 日志，不会调用任何回退 Provider；
- Provider 变化、模型、原因、QA 结果和输出路径都会记录到 GenerationAttempt。

文件：

- [`tools/video/reference_dance_generator.py`](../tools/video/reference_dance_generator.py)
- [`tests/tools/test_reference_dance_generator.py`](../tests/tools/test_reference_dance_generator.py)

### 7. Wan 2.2 ComfyUI 参数接入

已接入标准 `comfyui_video` Wan 2.2 I2V 工作流参数：

- 9:16：`576 x 1024`；
- 15 秒：`240` 帧；
- 默认模型栈：`wan2.2-14b-fp8-4step`；
- 支持人物参考图路径或 URL；
- 输出自动写入项目 `assets/video/` 目录。

需要明确：标准 Wan 2.2 I2V 可以保持人物参考图，但不能把参考舞蹈视频当作逐帧姿态控制输入，因此它是动作质量兜底，不是严格动作复刻方案。

## 三、部分完成

### 1. P1 已评分，但还没有自动分段

当前 QA 可以分析动作能量并检查多片段 seam，但还没有自动完成：

- 根据 motion energy 自动寻找最佳切点；
- 自动加入 overlap；
- 自动生成多段候选；
- 自动选择最佳片段组合。

目前仍然需要由生成计划和人工审核决定是否分段。

### 2. 角色身份和机位检查仍不是完整的视觉模型 QA

当前报告中的 `identity` 和 `camera` 分数仍为 `None`。

人物左右位置、全身入镜、固定机位等要求目前主要依靠：

- Prompt 约束；
- 参考素材绑定；
- 抽帧人工检查；
- 基础画面指标。

还没有接入专门的人脸身份一致性和人体位置检测模型。

### 3. 历史脚本还未全部迁移

项目中仍保留历史 curl / shell 生成脚本。当前新流程已经提供正式 Provider 和路由器，但旧脚本尚未全部删除或改造成统一调用入口。

## 四、尚未完成

### 1. 尚未用新流程生成新的付费候选

目前改造后的代码和 QA 已完成，但还没有基于新路由器重新调用 MiniMax-H3 生成一版新视频。

因此当前还不能声称“改造后的 Prompt 已经证明比旧视频更好”。

### 2. 尚未实际执行 Wan 2.2 fallback

Wan 2.2 的路由代码已完成，但尚未完成真实运行验证：

- ComfyUI 服务是否已启动；
- Wan 2.2 模型是否齐全；
- 本机显存是否满足当前工作流；
- 实际视频动作是否优于 H3。

### 3. 尚未接入 DWPose

DWPose 仍未实现，当前没有肩、肘、腕、髋、膝、踝的逐帧轨迹提取和姿态相似度评分。

### 4. 尚未接入 Wan2.2 Animate 姿态控制

当前接入的是标准 Wan 2.2 I2V，不是 Wan2.2 Animate 或基于 DWPose 的姿态控制工作流。

因此还不能保证：

- 严格复刻参考视频的舞步；
- 两个人每一拍都同步；
- 下半身轨迹和原视频一致；
- 长时间舞蹈不出现动作重置。

### 5. 尚未重新合成最终成片

新候选尚未生成，因此也尚未完成：

- 新旧版本对比；
- 新候选的动作 QA；
- 片段衔接复核；
- 最终 15 秒输出；
- 视频号发布规格验收。

## 五、测试状态

本次改造相关测试：

```text
108 passed
```

已覆盖：

- H3 Provider 合约；
- ComfyUI Provider 合约；
- reference-dance pipeline；
- Motion / Continuity QA；
- H3 默认路由；
- fallback 审批阻断；
- 批准后 Wan 2.2 路由；
- 9:16 尺寸映射；
- 15 秒 / 240 帧映射；
- GenerationAttempt 日志。

整仓测试尚未完全通过，原因是当前系统 Python 环境缺少仓库既有依赖：

- `fastapi`；
- `python-dotenv`；
- `google-genai`。

这些依赖缺失导致部分无关的 Backlot、Google 音乐和 Google 视频测试无法收集或执行，不是本次舞蹈改造代码的测试失败。

## 六、当前代码提交状态

最新 P2 改造目前还没有提交到 Git，未提交文件包括：

- `docs/rem-ram-dance-workflow-upgrade-plan.zh-CN.md`；
- `pipeline_defs/reference-dance.yaml`；
- `skills/pipelines/reference-dance/generate-director.md`；
- `skills/pipelines/reference-dance/review-director.md`；
- `tests/contracts/test_reference_dance_pipeline.py`；
- `tests/tools/test_reference_dance_generator.py`；
- `tools/video/reference_dance_generator.py`。

## 七、下一步执行顺序

1. 提交当前 P2 代码和文档。
2. 通过 `reference_dance_video_generate` 以 MiniMax-H3 生成新的 15 秒 one-shot 候选。
3. 使用 `reference_dance_qa` 对新旧视频进行动作和连续性对比。
4. 如果连续两次 H3 的 `motion_score` 仍未达到通过线，再向用户展示 Wan 2.2 / ComfyUI 回退选项。
5. 获得明确批准后，检查 ComfyUI、模型和显存，再实际执行 Wan 2.2 fallback。
6. 如果标准 I2V 仍不能解决动作僵硬，再进入 DWPose / Wan2.2 Animate 姿态控制升级。

## 八、相关文件

- 工作流方案：[`docs/rem-ram-dance-workflow-upgrade-plan.zh-CN.md`](rem-ram-dance-workflow-upgrade-plan.zh-CN.md)
- Pipeline：[`pipeline_defs/reference-dance.yaml`](../pipeline_defs/reference-dance.yaml)
- H3 计划器：[`tools/video/reference_dance_h3_plan.py`](../tools/video/reference_dance_h3_plan.py)
- 生成路由器：[`tools/video/reference_dance_generator.py`](../tools/video/reference_dance_generator.py)
- 动作 QA：[`tools/analysis/reference_dance_qa.py`](../tools/analysis/reference_dance_qa.py)
- Wan 2.2 Provider：[`tools/video/comfyui_video.py`](../tools/video/comfyui_video.py)
