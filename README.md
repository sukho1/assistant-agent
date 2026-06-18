# 马克思+庄子+心理学对话Agent

> v2.0.0

## 如何使用

### 下载即用版（master 分支）

原版，clone 即用，无需额外配置。以下安装说明均适用于 master 分支。

### 下载即用，需要本地agent软件
- git clone https://github.com/sukho1/assistant-agent.git
- 没有用过Agent的朋友，可以下载试用字节国产免费的trae，把这句发给自己的Agent，让它执行
- 只用聊天页面（chatgpt、gemini、deepseek、元宝、豆包等）的朋友：打开上面的网址->点击首页的CLAUDE.md文件->复制其中内容->发送给AI作为提示词

### claude用户进入项目文件夹即可对话

- 自动加载项目级的claude.md，并自动调用各skill

### 非claude用户，请输入以下指令：

```text
本文件夹下的项目是Claude 开发的Skill，现在迁移到你所在的平台
请执行：
1. 路径迁移：扫描项目中的 `.claude/skills/` 目录。请将该目录下的所有 Skill 文件夹复制到本项目支持的 Skills 路径下（通常是 `.agents/skills/` 或 `.trae/skills/`）。如果目标路径不存在，请创建它。
2. 元数据清洗：检查每个 Skill 目录下的 `SKILL.md` 文件头部的 YAML Frontmatter（如 `---` 包裹的部分）。请移除或替换任何 Claude 专属的配置项（例如 `hooks`, `agent`, `model`, `tools` 等），仅保留通用的 `name`, `description` 和 `version`。
3. 指令泛化：扫描 Skill 的正文内容。如果发现任何针对 Claude 的特定表述（例如"你是 Claude"、"使用 Anthropic 工具"），请将其修改为通用的指令描述（例如"你是一个 AI 助手"、"执行相应的操作"）。
4. 规则同步：根目录是否存在 `CLAUDE.md`，将其内容合并或同步到本项目支持的 Rules 文件中（如 `AGENTS.md` 或 `.trae/rules/project_rules.md`）。
```

### trace模式

手动调用/trace skill，在对话后会输出分析过程，保存在~/trace文件夹下，常常也有启发。

### DiaryRAG 版（assistant-agent-DiaryRAG 分支）

```bash
git clone -b assistant-agent-DiaryRAG https://github.com/sukho1/assistant-agent.git
```

此分支新增**日记语义检索 MCP 服务**。将你的日记（.docx）放入 `diary/` 目录后，Agent 可以语义搜索过往日记内容，用于对话中的回溯、分析、自我链接。

与 master 不同，此分支需要预处理日记数据。以下指引可发给你的 Agent 执行：

```text
安装并配置 DiaryRAG 日记语义搜索：

1. 安装 Python 依赖：
   pip install -r diary_rag/requirements.txt

2. 将日记文件（.docx 或其他格式）放入项目根目录下的 diary/ 文件夹

3. 运行预处理流水线：
   python diary_rag/segment_l1.py && python diary_rag/segment_l2.py && python diary_rag/index.py

4. 验证处理完整性并测试 MCP 搜索：
   python diary_rag/verify.py

5. MCP 配置文件 .mcp.json 已就绪，Agent 启动后即可使用 search_diary 工具。
   如需手动测试，运行：
   python diary_rag/server.py
```

预处理流水线说明：`segment_l1.py` 切分日记为父块→`segment_l2.py` 再切为子块→`index.py` 用 BAAI/bge-small-zh-v1.5 模型向量化并写入 ChromaDB。首次运行 `index.py` 需联网下载嵌入模型（约 100MB），如遇下载失败可提前 `pip install sentence-transformers && python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-zh-v1.5')"` 手动缓存模型。

预处理后的数据在 `diary_rag/data/` 下（已在 .gitignore 中排除），不提交到仓库。每次日记有新增或修改，重新执行第 3 步即可。

--- 

## 核心模型

### 我的"马克思+庄子+心理学体系"
多年探索，建立了我们普通人在赛博朋克原子化时代生存的社科和心理心灵体系。以心理学为基座，人本主义、存在主义这两个心灵哲学为支柱，马克思、庄子这两个社科哲学为指导思想。谈心理、心灵、开悟、活在当下。
详细见《我的马克思+庄子+心理学体系概述》《论活在当下》《普通人如何连接本自具足》等文章

### 两个模型作为核心框架
1. 四维课题定位模型 —— 理性分析基本矛盾
- 人生五要素维（学业、事业、社交、身体、心）、链接维（自己、他人、社会、世界、自然）、业障维、心灵维。
2. 底层心理模型 —— 理解这个活生生的、复杂的、动态的人
-  五个综合体：感受综合体、认知综合体、觉察-涵容综合体、能量综合体、力比多综合体。详细见《最底层的心理模型》


### 社科harness
- 不同的社科流派，有不同的基本假设、基本公理。LLM在目前的阶段是处理不好的，受限于语料，浸透了热门心理学的语感和假设。见《社科agent的生存空间，LLM一定会信仰马克思主义》
- 本体系一些基本前提和公理：人人本自具足，无需修证，也无从修证；个人的问题，都是社会的问题；着力即差，努力是伪概念，你已经尽力了

### 跟一些热门的心理学体系的基础假设对比

| 默认框架语感 | 本框架 |
|-------------|--------|
| 人需要成长/提升/变得更好 | 人人本自具足，都是业障遮蔽。无需修证，也无从修证。内外业障不由人控制，而是命运，静待自性光明去融化 |
| 人性恶、底层互害 | 人性善、底层人民朴实真善美 |
| 心理问题是个体层面的问题 | 个人的问题，都是社会的问题、命运际遇的问题 |
| 努力是好事/解决方向在于努力、行动、做 | 着力即差，努力是伪概念，你已经尽力了 |
| 接纳自己是一种需要练习的技能 | 允许——包括允许自己"不允许"，允许自己崩溃，允许自己不接纳 |
| 防御是坏东西，需要拆除 | 防御是崩溃前的自我保护，理解而非批判 |
| 疗愈 = 修复坏掉的东西 | 自性融化内在业障碎冰，心灵层级不断提升，更多链接，更少外在业力纠缠，处世游刃有余，游心于世 |
| 疗愈内在小孩 | 内在的深层心智一次次渡自己过难关|
| 苦难让你学到东西/变得更强大 | 苦难毫无意义。不被吞噬是因为人人自性光明 |
| 感恩是一种美德/需要练习感恩 | 感恩暗示单向仰视；感激是平等的、光明的共鸣，不是单向仰视 |
| 以小资生活模式为“正常”、健康的定义 | 对无产者生活状态是否带着"不正常"的评判？"正常社会功能"的定义是否在复读社会规训？ |

## 思路

### 核心技术
- 底层模型、边界harness、各类调用路由、知识库文章等

### 下一步

- DiaryRAG 日记语义搜索已上线（见 assistant-agent-DiaryRAG 分支），后续优化检索精度与性能

---

## 目录结构

```
assistant-agent/
├── CLAUDE.md                          # 项目规则与工作流
├── README.md                          # 本文件
├── .gitignore
├── .claude/
│   └── settings.local.json
├── ma-zhuang/                          # Agent 核心
│   ├── CLAUDE.md                      # Agent 人格设定
│   ├── .claude/skills/                # Skill 定义
│   │   ├── counseling/                # 顶层咨询路由、总路由 *** 流程处理、分情况调用子skill、调用知识库文章
│   │   ├── alienation/                # 异化专题
│   │   ├── deep-psychology/           # 深层心理分析
│   │   ├── innate-wholeness/          # 本自具足
│   │   ├── karma-diagnosis/           # 业障诊断
│   │   ├── link-rebuild/              # 链接重建
│   │   ├── profile-update/            # 用户画像更新
│   │   ├── response-check/            # 回复质检
│   │   ├── self-healing/              # 自体疗愈
│   │   └── trace/                     # 分析追溯 *** 输出思考和分析流程
│   ├── knowledge/                     # 知识库文章
│   │   ├── karma-series/              # 业障系列
│   │   ├── link-series/               # 链接系列
│   │   ├── marx-series/               # 马克思系列
│   │   ├── self-psychology/           # 自体心理学
│   │   └── zhuangzi-series/           # 庄子系列
│   ├── user_profile/                  # 用户画像模板
│   │   ├── overview.md
│   │   ├── last-update.md
│   │   ├── five-complexes/            # 五综合体
│   │   └── four-dimensions/           # 四维度
│   ├── docs/superpowers/specs/        # 设计文档
│   ├── server/                        # 后端服务
│   └── trace/                         # 分析输出
├── diary_rag/                          # 日记语义搜索 MCP ** DiaryRAG 分支
│   ├── server.py                       # MCP 服务入口
│   ├── segment_l1.py                   # 预处理 L1
│   ├── segment_l2.py                   # 预处理 L2
│   └── data/                           # 预处理数据（gitignore）
├── diary/                             # 日记 *** 关键支撑
└── user_profile/                 # 用户画像 *** 核心记忆
```

### 许可

本项目采用双许可，按文件类型划分：

- **程序结构**（`.claude/skills/*/SKILL.md`、`CLAUDE.md`、`README.md` 等）：[Apache 2.0](LICENSE)
- **知识文章**（`knowledge/` 下所有 `.md` 文件）：[CC BY-NC-SA 4.0](knowledge/LICENSE)

简记：代码和结构可以商用，要遵循Apache2.0。文章随便传，但不能拿去卖钱。