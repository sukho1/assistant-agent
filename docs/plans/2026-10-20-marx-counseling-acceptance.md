# AA / Web 小庄马庄内外业障改造验收

日期：2026-10-20。范围：原 AA 的 Claude / Codex 指令与本地私有 skill；Web 的参考资产及真实 pipeline。生产未部署。本记录区分工程接通、模型抽样与客户端端到端，不相互替代。

## 需求核对

- 异化定位说明后加入马克思主义哲学、异化与人本主义指导思想。责任归位完整保留阿富汗女孩、越南工人、美国蓝领及“面对处境不等于承担罪责”；链接人民完整保留普通人的劳动、互助、快乐、艰辛、无条件存在和平等、归属与存在感。
- 根人格主干改为庄子与马克思，保留 AA 原工作区已有的马庄体系及知识库说明。counseling 四维模型与 karma 内外区分段完整加入用户的内外业障 / 自性辩证法，系统联系社会历史处境与内在防御。
- 业障维必须联合 karma-diagnosis 与 alienation，主次维均适用；karma 分析外部业障必调 alienation；alienation 明示两个入口，同轮复用，不循环调用。
- 平等、认同、互助的安慰有具体展开；不把穷人的苦难当风景，不强派互助任务，不以贡献、觉察、上进或疗愈能力取得平等资格。
- 小资病可深入分析，但理解为困境与业障，人是受害者、幸存者。用户新增的“批判认知不足或自我疗愈不足都是严重错误”在根护栏、三 skill、Web SYSTEM / scan / selfcheck 均覆盖。
- 下班样例完整保留全部思想环节及“参考思路，不参考长短”。同时区分示例与事实：外界攻击、历史经历、隐藏的改变或革命愿望不能代用户断言。
- 自检增加仅内在安慰、遗漏社会归因 / 共同处境 / 人民链接的复核；纯陪伴可合理不展开。无条件尊重是体系立场，不得误判为需要证明的事实。

## 文章原名与可达性

已按知识库实际文件核对，未改文章正文：

1. zhuangzi-series/普通人如何感受本自具足.md
2. link-series/我们身为小微资，如何链接无产阶级朴实真善美.md
3. link-series/拼多多评论区文学和菜市场疗愈.md

以上加入异化表前部；责任归位文章及 karma-series/小资病.md 也在实际可读的前六篇范围。跨系列路径精确命中，非法路径不回退同名文章。

## 工程接通与本地安装

Web 不能只改 skill：运行时不直接执行这些文档。本次同时改 SYSTEM、两版 scan、selfcheck、确定性 route、成文框架注入与知识覆盖合同。业障配对不能被模型 crossReference=false、选文失败或旧上下文开关撤销。原主维与两个次维保留，额外必需异化席位将上限增至四框架、48 候选；四框架时全文上限八篇，联合路由每框架至少两篇，预算不足明确失败，不静默丢异化。

AA 的 counseling 与根人格可由 Git 同步；alienation、karma-diagnosis 原本为私有 ignored 文件，保持不公开。四份私有文件已核对主工作区内容等于改造前基线后安装回原 AA。旧版备份位于原 AA 的 ignored project/backups/marx-counseling-20261020。program/scripts/verify_marx_skills.mjs 可验证两平台、跨两仓框架和文章路由；校验收据只记哈希，不公开私有正文。

## 自动验收

- 两仓 / 两平台 / 三 skill，共十二份 skill：quick_validate.py 全部通过。默认捆绑 Python 缺 PyYAML，实际使用原 AA 既有 diary-rag venv 的 Python，未安装新依赖。
- 十二份资产共同框架、根人格、文章存在性、框架不被 6000 字截断：通过。最终哈希收据保存在本地 tools/provider-eval/runs/marx-skill-assets.json。
- Web 相关集中回归：四文件 135 项通过；新增本轮用户原话隔离后 marx-integration 单独九项通过。覆盖配对、主次保留、去重、旧新成文、B 类、规范路径、模型拒绝交叉参照、选文失败、预算失败、四框架知识覆盖、自检原话边界。
- shared 全量：十二文件 149 项通过；知识资产 inventory 四项通过，212 篇与原 AA 同步；最终资产重新生成 227 文件。以下早期快照结果仅说明相应阶段；集成后的门禁以末节为准。
- pnpm -r build：最终版本通过，生产产物新鲜度校验通过。初始快照的 pnpm -r typecheck 与 lint 已通过，lint 零 error。合入最新 master 后的结果另见末节，不沿用早期 lint 通过结论。
- 全量 API 与浏览器回归的最终结果在下方追加；默认 E2E 在全新隔离库启动时因现有迁移多命令 prepared statement 报错，尚未开始页面测试。迁移文件和执行器未被本次修改。为继续验证运行时，仅在本 worktree 的可抛 .data/pg-e2e 用 PGlite.exec 执行原样 SQL，登记原 migration hash/timestamp 后重跑。此预置不等于默认迁移门禁通过，不接触生产 D1 或真实用户数据。

## 真实模型抽样与局限

模型为 deepseek-flash、thinking disabled、temperature 0.3；全部为合成场景，不含真实用户档案。Web 使用实际导出的 prompt builders、route、knowledge 与一次 selfcheck / revise；AA 为加载原 skill 的提示词评估器，不能冒充原生 Claude / Codex 客户端的工具调用验收。AA 原生客户端端到端仍未验证。

六场景轮覆盖：下班自责、失业无贡献、小资羞耻、家庭伤害、仅需陪伴、JavaScript 信息交流。执行及路由记录齐全。发现两类真实质量失败后已修正：一是“会提问所以没废”的条件式安慰；二是自检将无条件尊重误判为“没有实据”，AA 甚至修订成“无法判断你是否值得尊重”。后者已增加公理与经历因果的区分，并将本轮用户原话传入 Web 自检。

校准后三场景复测（下班 / 失业 / 小资羞耻）均完成：Web 失业回应明确“你值得被尊重，跟你现在能不能赚钱、有没有贡献，没有关系”；AA 明确“值得被尊重，不需要任何条件”。两份故意注入“认知不足 / 自我疗愈不足”的错误稿均被自检判 fail。它们证明样本有效，不能保证所有回答稳定合格。

残余偏差如实保留：部分回答仍把内化动机说得过满；AA 小资羞耻场景仍有解释性标签；自检存在漏判和误判。因此不宣称语义验收百分之百通过，也不把 HTTP 成功或字符串出现当作回答质量。最终版本六场景重跑被自动审批拒绝：评估需用现有模型密钥向 DeepSeek 发送内部 skill 与提示词，审批要求用户明确授权。该项等待用户选择，未绕过。已有本地报告 marx-integration-final.json 与 marx-integration-calibrated.json 保留初稿、自检及修订稿，不覆盖失败历史。

## 发布与交接

无生产部署、迁移、域名或密钥修改。上线需用户明确授权，再由唯一部署 owner 从最新 master 的干净 worktree 执行 tools/deploy.mjs，并核对版本、cron 与冒烟。未通过的全仓门禁不能写成“全部验收通过”；提交、集成与推送实际状态在最终结果中明确记录。

## 最新 master 集成后的最终本地结果

Web 实现提交 6fd6294，基于 origin/master 983d147；只重放本次提交，未重写原主 checkout 的旧监控提交。双方的文章归属、事实纠错、引用译文 / 拼音护栏均保留，新增自检条目顺延为 25–27。AA 实现已在本地 master 集成为 ad31174，原有两项修改的意图已吸收，旧内容仍在 stash（pre-marx-overhaul-user-persona-and-route-20261020）；私有 skill 及备份均留在原 AA，未强制加入 Git。

| 验收 | 最终结果 | 范围与说明 |
|---|---|---|
| 十二份 skill 与原 AA 实际安装哈希 | 通过 | 原 AA 主目录运行 verify_marx_skills，双平台、双仓共同框架 / 三篇文章 / 根人格 |
| 相关回归 | 175 / 175 通过 | 七文件，含 knowledge / scan / selfcheck / 路由 / 新旧成文 / 资料边界 / 语言护栏 |
| 全包构建 | 通过 | 最终算法资产重新生成，生产产物校验通过 |
| 全仓类型检查 | 通过 | 并发执行曾出现 Node 进程 3221225477 崩溃；降低 workspace concurrency 后顺序执行通过，非类型报错 |
| 默认上下文 E2E | 5 / 5 通过 | 多轮流式、危机中断、消息删除、会话管理、A/B 阶段保真；本地 mock、隔离库 |
| v2 上下文 E2E | 未通过 | 首轮报 history_context_unavailable，标题未回填；同样切到干净 origin/master 983d147 实测复现，非仅凭文件未改推断 |
| 全仓 lint | 未通过 | 最新 master 的 ChatPage.tsx:890 条件调用 useDailyAiDisclosure；干净 origin/master 实测同样失败，本次未改该文件 |
| Worker inventory | 知识资产等三项通过，一项失败 | 新增 referral_invites / referral_claims / crisis_referrals 未登记冻结表清单；干净 origin/master 同样失败 |
| 最新迁移日志复核 | 6 / 6 通过 | 最新 master 的 migration-journal.test.ts 已通过，旧快照的迁移错误不能沿用为当前结论 |

早期全量 API 诊断为 21 文件失败 / 133 通过 / 2 跳过，19 用例失败 / 1787 通过 / 157 跳过。该长跑期间加入了自检校准与新回归，部分变换缓存仍是旧 prompt，新增一项断言因此失败；它不是最终冻结快照的全量门禁结果，不能据此把所有失败归为旧基线。最终相关七文件 175 项已重新执行并全部通过。最新全量 API 门禁仍未取得通过结论，不以定向回归替代全量。

早期全量浏览器诊断在完成 15 项、失败 2 项后，为切换最新 master 对照而停止，亦不计作最终全量验收。最终仅默认路径相关五项通过；v2 已做独立基线对照。全新库默认启动迁移的早期失败和隔离 exec 预置过程保留在日志，未修改既有迁移 SQL。

本地证据位于 Web worktree 的 ignored tools/provider-eval/runs：build-marx-integrated.txt、typecheck-marx-integrated-sequential.txt、lint-marx-integrated.txt、lint-origin-baseline.txt、inventory-marx-integrated.txt、inventory-origin-baseline.txt、e2e-marx-integrated.txt、e2e-marx-integrated-v2.txt、e2e-origin-v2-baseline.txt、marx-aa-integrated-assets.json。Vitest 输出位于 apps/api/.vitest-marx-integrated.txt 和 .vitest-marx-baseline-journal.txt；旧完整输出 .vitest-marx-full.txt 保留诊断历史。它们均不入 Git，不公开模型初稿或私有技能正文。

剩余事项明确保留：最终六场景外发评估等待授权；AA 原生客户端调用未验证（当前只有真实 skill 的提示词评估与本地安装验证，现有客户端需重载才能读取新版）；Web 基线门禁需另行修复后再做完整冻结快照回归。Web 分支保持可审阅，不合并到 master，不部署。生产行为尚未改变。
