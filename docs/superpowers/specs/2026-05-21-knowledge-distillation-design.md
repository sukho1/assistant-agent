# Knowledge Distillation: Optimize CLAUDE.md and Skills

## Goal

Distill insights from ~201 knowledge articles (5 series) into CLAUDE.md and 9 skill SKILL.md files, filling gaps and strengthening each component without diluting the framework's philosophical core.

## Constraints

- **No external tools** — external distillation tools don't understand the Marx+Zhuangzi+psychology framework and would produce generic output.
- **Framework fidelity** — all edits must stay within the framework's axioms (本自具足, 四维模型, 五个综合体, 减法疗愈).
- **Article-grounded** — only add what articles actually contain; never fabricate.
- **User approval gate** — no file is modified until the user explicitly approves the proposed changes.

## Process

For each skill, in order:

1. Read current SKILL.md to understand existing content
2. Load 3-4 core articles from the skill's knowledge routing table
3. Compare article insights against current skill content — identify gaps and strengthenable areas
4. Present concrete edit proposals to user
5. After user approval, apply changes and commit (one commit per skill)

## Processing Order

Dependency-aware ordering — foundational components first:

| # | Target | Role |
|---|--------|------|
| 1 | CLAUDE.md | Global axioms and role definition |
| 2 | counseling | Top-level router, conversation flow |
| 3 | deep-psychology | Core analytical framework (five complexes) |
| 4 | alienation | Marx's alienation theory |
| 5 | karma-diagnosis | Karma, family-of-origin wounds |
| 6 | link-rebuild | Link reconstruction |
| 7 | innate-wholeness | Zhuangzi — innate completeness |
| 8 | self-healing | Self psychology (Kohut, Winnicott) |
| 9 | response-check | Output quality gate |
| 10 | trace | Analysis trajectory logging |

## Output

Each skill produces a concrete edit proposal shown to the user. After approval, the SKILL.md is updated and committed. One commit per skill.
