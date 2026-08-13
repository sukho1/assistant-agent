---
name: trace
description: Analysis trace for every response. After drafting and before output, record the full analysis trajectory to ma-zhuang/trace/ folder — including input assessment, four-dim scan, five-complex scan, sub-skill invocations, article loads, response strategy, and self-check results.
---

# 分析轨迹记录

> 轨迹保存到 `ma-zhuang/trace/`（相对于项目根目录）。不加载知识库文章。

## 触发条件

**A 类咨询回复必写；B 类纯信息/技术回复不写。**

## 延迟写入机制（强制）

当前运行时中，最终回复发出即本轮结束，之后无法再执行工具。因此"异步补写"必须落实为：

1. **回复发出前**：只向 `ma-zhuang/pending/` 写登记文件 `YYYY-MM-DD-主题.md`（内容即按下面模板备好的 trace 本体 + profile 更新范围）。此步几秒内完成，是回复前唯一允许的写入。
2. **下一次会话开始时**：flush——把登记文件移入 `ma-zhuang/trace/`，并按登记范围执行 profile 更新，然后才处理新消息。
3. 任何回复开始前，先检查 `ma-zhuang/pending/`：非空则先 flush，再进入分析。

## 输出格式

每个回应一个 `.md` 文件，命名 `YYYY-MM-DD-主题.md`，先写在本目录（`ma-zhuang/pending/`），flush 时移动到 `ma-zhuang/trace/`。

登记文件模板：

```markdown
# Pending: YYYY-MM-DD 主题
- trace目标: ma-zhuang/trace/YYYY-MM-DD-主题.md
- profile范围: <文件列表 / 无>
- 以下为 trace 本体（精简模板）
...
```

## 精简模板（强制）

要点式，单行短句，禁止长段落、禁止过程流水账、禁止重复档案已有内容：

```markdown
# 分析轨迹 YYYY-MM-DD 主题
- 输入分析：A/B 判定 + 1-2 句（诉求类型、当下状态、期待方向）
- 策略：策略名 + 1 句
- 四维/五综合体：核心定位 + 子skill 路由（各 1-2 句）
- 加载：skill + 知识文章（列名即可）
- 日记检索：检索路径 + 关键命中（1-2 句）
- 回应形成：1-2 句
- 自检：逐条 pass/fail 一行
- 档案更新：有/无 + 更新范围
```

## 必须记录

- 分析的关键决策（输入判定、策略、路由）
- 调用的 skill、子 skill，及调用逻辑
- 调用的知识库文章

## 时间预算

整个 trace 写入应在 5 秒内完成。若需要写超过 30 行，说明格式偏离模板，立即收束。
