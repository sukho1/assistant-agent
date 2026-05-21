---
name: trace
description: Analysis trace for every response. After drafting and before output, record the full analysis trajectory to trace/ folder — including input assessment, four-dim scan, five-complex scan, sub-skill invocations, article loads, response strategy, and self-check results.
---

# 分析轨迹记录

## 触发条件

用户调用本skill时，在生成输出后，将完整分析轨迹写入 `trace/` 文件夹。

## 输出格式

每个回应一个 `.md` 文件，命名 `YYYY-MM-DD-主题.md`。

## 必须记录
-分析的每一步
-调用的每个skill，和子skill，调用逻辑
-调用的知识库文章