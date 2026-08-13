---
name: trace
description: Analysis trace for every response. After drafting and before output, record the full analysis trajectory to ma-zhuang/trace/ folder — including input assessment, four-dim scan, five-complex scan, sub-skill invocations, article loads, response strategy, and self-check results.
---

# 分析轨迹记录

> 轨迹保存到 `ma-zhuang/trace/`（相对于项目根目录）。不加载知识库文章。

## 触发条件

用户调用本skill时，在用户已收到回应后，异步补写完整分析轨迹到 `ma-zhuang/trace/` 文件夹。trace 不阻塞用户看到回应。

## 输出格式

每个回应一个 `.md` 文件，命名 `YYYY-MM-DD-主题.md`。

## 必须记录
-分析的每一步
-调用的每个skill，和子skill，调用逻辑
-调用的知识库文章