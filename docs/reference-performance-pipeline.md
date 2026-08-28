# reference-performance 流水线

## 目标

基于一张目标人物设定图和一段参考视频生成新视频。目标人物的身份、脸型、发型和身体比例来自设定图；动作顺序、手势、身体重心、头部角度、眼神、眨眼、面部表情、停顿和节奏来自参考视频。若人物原始妆造与参考视频的视觉语言冲突，先生成并审核一组“同一角色、调整风格”的候选图，再进入视频生成。

这条流水线用于解决 `reference-dance` 中出现的两个问题：动作被概括成普通摆动，表情被重置成单一的默认表情。

## 与 reference-dance 的关系

`reference-dance` 保留为舞蹈任务的兼容流水线和回归基线。`reference-performance` 是更通用的表演迁移流水线，适用于舞蹈、换装动作之外的手势表演、镜头前情绪表演和角色动作复刻。

不自动迁移旧项目，也不覆盖旧的 GenerationAttempt。新旧结果应在独立项目中并排比较。

## 关键加强点

### 0. 先锁定生产方案，再进入性能分析

流水线现在在 intake 后增加 `proposal` 人工审批门：先确认这是
`motion_led` 的 reference-performance 任务、MiniMax-H3 仍是视频模型，并
明确 one-shot、分段桥接或 performance-first 三种执行策略。合成阶段的
`render_runtime` 与 `composition_mode` 也必须分别记录到 `proposal_packet`
和 `decision_log`，不能在 compose 阶段静默改成另一个运行时。

### 1. 先做外观适配，再锁定视频输入

`appearance_adaptation` 位于 `proposal` 之后、`performance_analysis` 之前，具有独立的人审门：

1. 从参考视频采样帧中分析服装轮廓、发型整理、妆容浓淡、灯光、色彩、场景气质和镜头语言。
2. 与人物设定图逐项比较，记录 `none`、`minor` 或 `major` 风格不匹配，并明确允许调整的属性。
3. 无明显冲突时写入 `NOT_NEEDED`，后续直接使用原人物图。
4. 有冲突时调用 `hairfree_image` 的编辑能力，以原人物图为身份基础生成 2-3 张候选图。候选图只能调整服装、发型整理、妆容、色彩、灯光和场景气质，不得复制参考视频人物的脸、身体、身份、文字、水印或背景。
5. 候选生成成功只代表 `CANDIDATES_READY`，不代表通过。用户选择一张后才写入 `APPROVED`，并要求该候选具有可被视频 Provider 读取的 HTTPS URL。

Planner 对 `CANDIDATES_READY` 和 `REJECTED` 直接失败关闭；即使调用方提供了候选 URL，也必须先存在一个明确的已批准候选。最终 `GenerationAttempt` 会记录候选 ID、采用 URL 和原始人物图 URL，便于复盘与复用。

### 2. 表演节拍不是粗粒度时间段

每个 beat 必须同时描述身体和脸部：

```json
{
  "beat_id": "beat_03",
  "start_seconds": 4.2,
  "end_seconds": 5.7,
  "action": "左肩先启动，右手从胸前向脸侧移动",
  "hand_gesture": "手腕跟随前臂，指尖放松",
  "head_angle": "向左倾斜约 10 度",
  "gaze": "停留在镜头",
  "expression": "眼神放松，嘴角轻微上扬",
  "blink": "动作结束后缓慢眨眼一次",
  "body_weight": "重心从左脚转移到右脚",
  "pause_after_seconds": 0.25,
  "intensity": "中等"
}
```

### 3. H3 提示词分离来源权威

- 无适配时，`reference_image`：身份、妆造和服装权威
- 有适配并获批时，Hairfree 候选图：身份保持不变，获批的妆造、服装、发型整理、色彩和灯光权威
- `reference_video`：动作和表演节奏权威
- 参考视频中的原人物、服装、背景、文字和水印全部排除

### 4. QA 不再只看运动能量

QA 同时输出：

- `action_order_score`
- `gesture_score`
- `expression_score`
- `gaze_score`
- `head_angle_score`
- `motion_score`
- `continuity_score`
- `identity_score`
- `camera_score`

其中表情和动作节拍需要人工或视觉模型逐 beat 复核。当前本地像素运动指标不能可靠识别“惊讶、温柔、克制”等语义情绪，因此缺少这一步时强制返回 `REVIEW_REQUIRED`，不能误判为 `PASS`。

## 当前能力边界

MiniMax-H3 可以通过多模态参考和结构化提示词提升迁移效果，但仅依靠提示词不能保证逐帧面部关键点或姿态关键点完全一致。若后续仍有明显偏差，再增加姿态/面部控制适配层；该适配层属于独立能力扩展，不在本流水线中静默启用。

## 推荐验证方式

使用相同人物图和参考视频分别跑 `reference-dance` 与 `reference-performance`：

1. 并排查看同一时间点的参考帧和输出帧。
2. 先比较动作顺序、手势和身体重心。
3. 再比较眼神、眨眼、头部角度和表情变化。
4. 最后比较身份、服装、镜头和技术参数。

不能只以“画面更好看”判定新流水线更好。

### 5. Fail-closed 规则

如果性能分析没有逐 beat 的动作、手势、头部角度、眼神、表情、眨眼、重心、
停顿和动作强度，Planner 会拒绝生成请求，不再回退成泛化动作提示。QA 也必须
覆盖全部 beat，并逐项提供动作、手势、表情、眼神和头部角度评分；只复核一部分
beat 或缺少任一项时返回 `REVIEW_REQUIRED`，不会错误放行。
