# subsystem-news 项目进度总览

> **项目**：subsystem-news — 合规新闻源接入与 Ex-1 / Ex-2 / Ex-3 候选产出
> **参考文档**：`docs/subsystem-news.project-doc.md`
> **任务明细**：`docs/TASK_BREAKDOWN.md`
> **最后更新**：2026-04-18

---

## 里程碑状态

| 阶段 | Milestone | 标题 | Issues | 状态 | 关键退出条件 |
|------|-----------|------|--------|------|--------------|
| 0 | milestone-0 | 来源与边界冻结 | ISSUE-001, ISSUE-002 | ☐ 未开始 | 包骨架 + Ex schema + approved allowlist 全部冻结 |
| 1 | milestone-1 | 来源接入与规范化 | ISSUE-003, ISSUE-004 | ☐ 未开始 | `NewsArticleArtifact` 可落地，approved source 接入率 ≥ 95% |
| 2 | milestone-2 | 去重与实体解析协同 | ISSUE-005, ISSUE-006 | ☐ 未开始 | Dedupe precision ≥ 95%；unresolved 显式化 100% |
| 3 | milestone-3 | Ex-1 / Ex-2 成型 | ISSUE-007, ISSUE-008, ISSUE-009 | ☐ 未开始 | Evidence coverage 100%；`Ex-2` 合同完整率 100%；端到端 submit 跑通 |
| 4 | milestone-4 | 高门槛 Ex-3 与回放 | ISSUE-010, ISSUE-011 | ☐ 未开始 | `Ex-3` FP ≤ 1%；replay 差异报告可生成 |
| 5 | milestone-5 | Full 模式接口对齐 | ISSUE-012 | ☐ 未开始 | `Ex-2` 字段冻结；backend 切换零代码改动通过 |

状态图例：☐ 未开始 / ▶ 进行中 / ✅ 完成 / ⛔ 阻塞

---

## Issue 列表

| Issue | 标题 | Milestone | Labels | 状态 | 依赖 |
|-------|------|-----------|--------|------|------|
| ISSUE-001 | 项目脚手架与包结构初始化 | milestone-0 | P0, infrastructure | ☐ | — |
| ISSUE-002 | 来源配置与 Ex 合同 schema 冻结 | milestone-0 | P0, infrastructure | ☐ | #ISSUE-001 |
| ISSUE-003 | sources 模块 — 发现与抓取 | milestone-1 | P0, feature | ☐ | #ISSUE-002 |
| ISSUE-004 | normalize 模块 — 正文规范化 | milestone-1 | P0, feature | ☐ | #ISSUE-003 |
| ISSUE-005 | dedupe 模块 — fingerprint 与 cluster | milestone-2 | P0, algorithm | ☐ | #ISSUE-004 |
| ISSUE-006 | entities 模块 — mention 与 registry 协同 | milestone-2 | P0, integration | ☐ | #ISSUE-004 |
| ISSUE-007 | extract 模块 — Ex-1 事实抽取 | milestone-3 | P0, model | ☐ | #ISSUE-005, #ISSUE-006 |
| ISSUE-008 | signals 模块 — Ex-2 信号生成 | milestone-3 | P0, model | ☐ | #ISSUE-007 |
| ISSUE-009 | runtime 模块 — pipeline 与 submit | milestone-3 | P0, integration | ☐ | #ISSUE-008 |
| ISSUE-010 | graph 模块 — 高门槛 Ex-3 | milestone-4 | P1, model | ☐ | #ISSUE-009 |
| ISSUE-011 | fixtures + replay 与回归基线 | milestone-4 | P1, testing | ☐ | #ISSUE-010 |
| ISSUE-012 | Full 模式接口稳定性与 backend 切换 | milestone-5 | P1, integration | ☐ | #ISSUE-011 |

---

## 关键指标基线（来自项目文档 §19）

| 指标 | 目标 | 当前 | 负责 issue |
|------|------|------|-----------|
| Approved source ingestion success rate | ≥ 95% | — | ISSUE-003 |
| Evidence coverage | 100% | — | ISSUE-007 / ISSUE-008 / ISSUE-010 |
| Dedupe precision on curated fixtures | ≥ 95% | — | ISSUE-005 |
| Unresolved entity explicitness | 100% | — | ISSUE-006 |
| `Ex-2` contract completeness | 100% | — | ISSUE-008 |
| `Ex-3` false positive rate | ≤ 1% | — | ISSUE-010 |
| Fetch-to-candidate p95 latency | ≤ 5 min | — | ISSUE-009 |

---

## 边界提醒（不可越界）

- ❌ 不私接 provider SDK —— 所有模型调用统一 `reasoner-runtime.generate_structured()`
- ❌ 不写 formal object / interim publish —— 仅输出 Ex-1 / Ex-2 / Ex-3 候选
- ❌ 不自造 canonical entity ID —— 全部走 `entity-registry`
- ❌ 不接 Kafka / Flink / CEP / Temporal / Neo4j 直写
- ❌ 不接受未在 allowlist 的来源
- ❌ 不基于共现 / 情绪 / 标题联想生成 `Ex-3`
