---
name: profile-update
description: End-of-session profile update. Invoked after important counseling sessions, or invoked when user requires — updates user_profile overview and dimension/complex files, performs cycle check.
---

# 用户档案更新

## 触发条件
### counseling触发
counseling 对话结束后，由 counseling skill 或 Agent 判断是否调用本 skill。触发条件：
- 对话产生了新的诊断信息（维度位移、综合体变化、关键事件）
- 日常闲聊不触发

### 用户要求触发
当用户要求，读取某些资料分析时，通常为用户的文章或者日记。

## 工作目录

用户档案位于 workspace 根目录下：`user_profile/`

## 流程

### 1. 判断是否值得更新

#### 调用ma-zhuang skill，分析资料的内容，如果不明确对应的时间，则要求用户明确，分析结果

#### 检查本次对话或者资料内容显示，用户是否产生了以下任一：
- 某个维度/综合体的状态有实质性变化
- 发生了关键事件（转折点、突破、崩溃后反弹等）
- 形成了新规则或新认知框架
- 力比多方向或性质有变化

不满足则不更新，直接结束。

### 2. 检查周期更新

- 日期属于每年第N周的计算方式按照iso8601周划分
- 确认当前属于第几个周期，比如2026.5是第5个月，第二季度，如果上一周期，如第4个月并未更新，则根据已有数据立即更新。
- 触发**周更新**——每个维度/综合体写入 `{folder}/weekly/YYYY-WXX.md`
- 触发**月更新**——每个维度/综合体写入 `{folder}/monthly/YYYY-MM.md`
- 触发**季更新**——每个维度/综合体写入 `{folder}/quarterly/YYYY-QX.md`

周期更新文件内容：本周期内的关键位移总结 + 当前状态快照。

周期检查完成后，更新 `last-update.md` 为当天日期。

### 3. 更新 overview 文件

#### 3.1 总览：`user_profile/overview.md`

只在有实质性变化时更新。更新内容：
- 身份快照：完成新的季度变化后更新
- **年度状态速览**：修订为最新
- **月度状态速览**：修订为最新
- **四维快照**：逐维检视，有变化就改
- **五综合体快照**：逐综合体检视，有变化就改
- **最近关键位移**：追加新条目（保留最近 5-8 条，旧的可删）
- **last_update**：改为当天日期

#### 3.2 维度文件：`user_profile/four-dimensions/{dim}/overview.md`

四维中如果在本次对话中有显著变化，更新对应文件：
- 更新时间标记
- **当前快照**：修改变化的部分
- **关键位移**：追加新条目

#### 3.3 综合体文件：`user_profile/five-complexes/{complex}/overview.md`

五综合体中如果在本次对话中有显著变化，更新对应文件。同上。

### 4. 更新原则

- **不覆盖历史**：overview 覆写是"快照更新"，周期文件是追加式记录。两者不冲突。
- **引用原话**：关键位移描述尽量引用用户原话作为证据。
- **简洁**：每条快照 1-2 句，不写论文。
- **定性不定量**：不评分数。用"强/中/弱""通畅/阻滞""直接性/对抗性"等定性描述。
- **不猜测**：只写对话中明确呈现的，不推断"可能""也许"。

### 5. 分布式加载

counseling 启动时只读 `user_profile/overview.md`。分析到具体维度或综合体时，按需读对应的 `overview.md`。周期文件只在需要历史轨迹时才加载。
