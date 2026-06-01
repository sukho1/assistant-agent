# Overview 文件模板

> 事实与分析分离的核心规则见 SKILL.md。

## Overview 特有规则

- Overview 是**快照覆写式**更新——有变化的时间层级覆写，无变化则保持原样
- 上层周期（年/季）只在有结构性变化时修订，不机械每周重写
- 下层周期的变化若构成上层周期的结构性变化，向上传导
- 周期文件的追加式记录规范见 `_cycle-file-rules.md`

---

## 统一模板

四个 overview 文件（comprehensive + dim1/dim2/dim3）共用此骨架，仅当前快照的事实字段不同。

```
---
last_update: YYYY-MM-DD
---

# {档案名}

## 用户事实

### 当前快照
{维度事实字段，每条标注 YYYY-MM-DD，字母编号 a. b. c. ...}

---
## Agent 分析

### 近三年状态 (YYYY-YYYY)
主要矛盾: xxx
主要变化: xxx

### 年度状态 (YYYY)
主要矛盾: xxx
主要变化: xxx

### 季度状态 (QX)
主要矛盾: xxx
主要变化: xxx

### 月度状态 (M月)
主要矛盾: xxx
主要变化: xxx

### 周度状态 (WXX)
主要矛盾: xxx
主要变化: xxx

### 最近关键变化
- YYYY-MM-DD 变化描述
（追加式列表，保留 7-8 条）
```

### 各 overview 当前快照字段

| 文件 | 快照字段 |
|------|---------|
| comprehensive/overview | 身份(年龄/定位/关键节点) + 最近一天状态(自评/身体/社交) |
| dim1-elements/overview | 学业 / 事业 / 社交 / 身体 / 心理心灵 |
| dim2-links/overview | 核心定位 + 自己/他人/社会/历史/自然宇宙/学业事业 |
| dim3-karma/overview | 内在业障 / 外在业障 |

### 五综合体动态（comprehensive 专属）

```
### 五综合体动态
能量-xxx；力比多-xxx；涵容-xxx；感受-xxx；认知-xxx

### 心灵维动态
xxx

### 当前交互动态
### 核心链一：[方向概括]
[事件链，用→连接]
方向: [因果方向]
为什么是核心链: [理由]
证据来源: [简注]
```
