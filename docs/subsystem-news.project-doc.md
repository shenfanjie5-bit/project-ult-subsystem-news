# subsystem-news 完整项目文档

> **文档状态**：Draft v1
> **版本**：v0.1.1
> **作者**：Codex
> **创建日期**：2026-04-15
> **最后更新**：2026-04-15
> **文档目的**：把 `subsystem-news` 子项目从“抓新闻做舆情分析”的宽泛理解收束为可立项、可拆分、可实现、可验收的正式项目，使其成为主项目中唯一负责合规新闻源接入、纯非结构化新闻理解、新闻事件/情绪/影响信号抽取，并以 `Ex-1`、`Ex-2` 为主、`Ex-3` 为辅输出候选对象的参考子系统。

---

## 变更记录

| 版本 | 日期 | 变更内容 | 作者 |
|------|------|----------|------|
| v0.1 | 2026-04-15 | 初稿 | Codex |
| v0.1.1 | 2026-04-15 | 补充 `reasoner-runtime.generate_structured()` 调用路径、实体解析分工和 Full 适配约束 | Codex |

---

## 1. 一句话定义

`subsystem-news` 是主项目中**唯一负责面向已批准新闻源接入纯非结构化新闻文本，完成正文清洗、去重聚类、实体提及识别、事件抽取、情绪与影响判断，并将结果以带证据链和来源追溯的 `Ex-1` / `Ex-2` / 少量高门槛 `Ex-3` 候选对象输出**的新闻理解子系统，它以“来源合规可追溯”“语义判断必须发生在子系统 S0 而非 Flink CEP”“不直接写 formal object”为不可协商约束。

它不是通用爬虫平台，也不是流式 CEP 引擎。  
它不拥有 formal 发布、不拥有实体主数据、不拥有 Kafka/Flink/Temporal 编排，也不替代公告、研报、社交媒体等其他信息子系统。

---

## 2. 文档定位与核心问题

本文解决的问题不是“怎么抓网页”，而是：

1. **纯非结构化新闻理解问题**：新闻正文属于主文档定义的纯非结构化来源，必须在子系统内部完成语义理解、事件抽取和方向判断，不能把语义责任推给 Layer B 或 CEP。
2. **新闻去重与证据可信度问题**：同一条新闻常被多家媒体转载、改写或快讯化，如果不做 fingerprint、聚类和证据锚定，会把同一事件误算成多条独立信号。
3. **实体歧义与影响映射问题**：新闻中的简称、口语别名、上下游公司、行业指代和主题概念高度混杂，必须明确“哪些由本模块识别，哪些交给 `entity-registry` 解析”。
4. **面向未来事件驱动的接口稳定问题**：新闻是最有可能进入 P11 事件驱动路径的信息源之一，但 `subsystem-news` 当前只能负责产出稳定的结构化 Ex 候选，不应提前吞并 Kafka/Flink/CEP 或 interim 发布职责。

---

## 3. 术语表

| 术语 | 定义 | 备注 |
|------|------|------|
| Approved News Source | 经过人工确认允许接入的新闻来源 | 必须有来源策略、访问方式和合规说明 |
| News Article | 单篇新闻正文及其元数据 | 可来自 RSS、API、付费终端或站点正文 |
| Source Reference | 指向原始新闻来源的可追溯引用 | 至少包含 source_id、url 或 provider article key |
| Article Fingerprint | 用于去重和聚类的新闻内容指纹 | 不等于原始 content hash |
| Dedupe Cluster | 多篇高度相似新闻组成的聚类集合 | 一个事件可对应一个 cluster |
| Entity Mention | 新闻正文中的实体提及片段 | 可能尚未解析为 canonical entity |
| Evidence Span | 支撑候选结论的文本片段定位 | 审计必需字段 |
| News Fact Candidate | 从新闻中抽出的候选事实 | 对应 `Ex-1` |
| News Signal Candidate | 从新闻语义中抽出的候选信号 | 对应 `Ex-2` |
| News Graph Delta Candidate | 由新闻明确支持的候选图谱变更 | 对应 `Ex-3` |
| Impact Scope | 新闻影响范围 | 如 company / sector / supply_chain / market_theme |
| Source Reliability Tier | 来源可靠性等级 | 由来源配置和历史表现共同决定 |

**规则**：

- 只允许 Approved News Source 进入主处理链，禁止临时抓取不在 allowlist 内的站点正文。
- 同一新闻事件跨站点转载后，默认先进入 Dedupe Cluster，再决定是否产生多个候选对象。
- 新闻语义判断必须在 `subsystem-news` 内完成，尤其是 `Ex-2.direction`、`magnitude`、`impact_scope` 等字段不能留给 Flink CEP 推断。
- 实体提及可以由本模块发现，但 canonical entity ID 必须来自 `entity-registry` 的解析结果，禁止本模块自造 ID。
- `Ex-3` 只允许基于明确关系表述生成，禁止根据共现、标题联想或情绪倾向推导图谱关系。
- 每个 Ex 候选对象必须带 `source_reference` 和 `evidence_spans`，只给摘要不给出处视为无效输出。

---

## 4. 目标与非目标

### 4.1 项目目标

1. **接入合规新闻源**：消费已批准 RSS / API / 站点正文入口，把新闻发现流收束为可重放、可追溯的输入。
2. **规范化新闻正文**：抽取标题、发布时间、正文、作者、语言、栏目等核心字段，形成统一的 `NewsArticle` 处理对象。
3. **去重并聚类转载新闻**：在正文轻度改写、转载、快讯/长文并存的情况下，把同一事件的重复报道折叠到同一 cluster。
4. **抽取新闻候选事实**：针对事件类新闻产出高质量 `Ex-1` 候选事实，为后续主系统和审计提供结构化入口。
5. **生成新闻候选信号**：在证据充分时，输出 `sentiment`、`event_impact`、`sector_rotation` 等 `Ex-2` 候选信号。
6. **谨慎生成图谱变更候选**：仅在收购、合作、制裁、核心供应关系变更等强证据场景输出少量 `Ex-3`。
7. **压测实体解析边界**：以新闻场景验证 `entity-registry` 对简称、模糊主体、跨语言别名和主题实体的解析能力。
8. **为未来事件驱动做好接口准备**：把新闻产出塑造成 Full 模式可消费的结构化信号，但不在本模块内实现事件驱动编排。

### 4.2 非目标

- **不做通用互联网爬虫**：本模块只接入已批准来源，不承担全网采集、反爬绕过和海量站点治理职责。
- **不做来源采购与法务判定**：新闻源是否可买、是否可接、是否合规由人和部署配置决定，本模块只消费已批准结果。
- **不替代公告/研报/社交媒体子系统**：新闻、公告、研报、社交媒体的证据结构和噪声特征不同，不能混成一个“内容理解总系统”。
- **不拥有 Kafka/Flink/CEP**：流式校验、事件模式检测和事件驱动局部 cycle 属于 `stream-layer` / P11 范围，不在本模块内实现。
- **不生成 formal object**：新闻子系统只能产出候选对象，正式状态和正式建议归 `main-core`。
- **不拥有实体真相层**：实体命名空间、别名库、解析 case 和冲突裁决归 `entity-registry`。
- **不把共现当作关系写图**：没有明确关系证据时不产出 `Ex-3`，避免污染图谱层。
- **不拥有 Layer B / Iceberg canonical 落地**：本模块只负责本地 artifact 与 Ex 输出，正式入湖由 Layer B 和 `data-platform` 接管。
- **不直连 provider SDK**：复杂抽取、分类、方向判断统一通过 `reasoner-runtime.generate_structured()` 或等价公开结构化接口完成。

---

## 5. 与现有工具的关系定位

### 5.1 架构位置

```text
approved news sources + assembly config + contracts + subsystem-sdk
  + entity-registry + reasoner-runtime
    -> subsystem-news
        ├── source fetch / article normalize
        ├── fingerprint / dedupe cluster
        ├── entity mention detect
        ├── event extraction
        ├── Ex-1 fact candidates
        ├── Ex-2 signal candidates
        └── limited Ex-3 graph delta candidates
    -> Layer B
        -> data-platform canonical
        -> main-core
        -> graph-engine
        -> audit-eval
        -> future stream-layer consumers
```

### 5.2 上游输入

| 来源 | 提供内容 | 说明 |
|------|----------|------|
| 外部新闻源 | 新闻正文、标题、时间、来源、URL | 必须在 approved source allowlist 内 |
| `assembly` | source config、凭据、运行模式、backend 配置 | 环境注入和部署参数不归本模块定义 |
| `contracts` | `Ex-0`~`Ex-3` schema、错误码、字段约束 | 本模块只消费正式合同 |
| `subsystem-sdk` | base class、validator、submit、heartbeat、fixtures 支撑 | 公共子系统框架 |
| `entity-registry` | 实体别名查询、解析、冲突返回 | 新闻场景高度依赖 |
| `reasoner-runtime` | 复杂抽取、分类、判向、结构化输出调用 | 不在本模块里直连 provider |

### 5.3 下游输出

| 目标 | 输出内容 | 消费方式 |
|------|----------|----------|
| Layer B / `data-platform` | `Ex-1` / `Ex-2` / `Ex-3` payload | 通过 `subsystem-sdk.submit()` |
| `main-core` | 经校验接纳的新闻事实与信号 | 间接消费 |
| `graph-engine` | 经接纳的少量新闻图谱变更候选 | 间接消费 |
| `audit-eval` | 候选对象的证据片段、来源追溯、重放 trace | 间接消费 |
| 未来 `stream-layer` | 稳定结构化新闻信号 | 未来 Full 模式下间接消费 |

### 5.4 核心边界

- **新闻正文语义理解归 `subsystem-news`，Flink CEP 只消费结构化信号，不接触原始新闻文本**
- **只通过 Ex 合同输出，不直接写 formal object、running state 或 interim publish**
- **来源 allowlist 和证据追溯是强约束，未批准来源或无出处新闻不得进入主输出链**
- **实体解析结果以 `entity-registry` 为准，本模块不自造 canonical entity**
- **`Ex-3` 只允许在明确关系证据下少量输出，绝不因新闻共现批量造边**
- **S0 的复杂结构化抽取统一调用 `reasoner-runtime.generate_structured()`；backend adapter / provider 切换只能发生在 runtime 配置层，不得要求改写 news 域代码或 Ex schema**

---

## 6. 设计哲学

### 6.1 设计原则

#### 原则 1：Provenance First

新闻最容易出问题的不是模型能力，而是来源不清、转载混淆、标题党和摘要失真。  
因此在新闻域里，来源、URL、发布时间、原文证据片段和聚类关系必须先于“观点”存在。

#### 原则 2：Dedupe Before Signal

同一事件被 5 家媒体转载，不应该被算成 5 条独立信号。  
必须先收敛到 cluster，再决定事实数和信号数，否则后续主系统会被重复信息放大。

#### 原则 3：Facts Before Sentiment

新闻首先应回答“发生了什么”，其次才是“偏利多还是利空”。  
如果没有事实层，信号层会失去可审计支撑，回放时也无法判断模型为什么得出方向。

#### 原则 4：Semantic Judgment Lives in S0

主文档已经冻结：Flink CEP 只做结构化模式匹配，不做文本语义理解。  
所以诸如“这条新闻是否偏利空、影响范围是公司还是行业、时间窗口是短期还是中期”等判断，必须在 `subsystem-news` 内完成。

#### 原则 5：Uncertainty Must Stay Visible

新闻天生噪声大、措辞模糊、引用二手消息多。  
不确定时应降低置信度、显式 unresolved 或拒绝输出，而不是为追求覆盖率硬填结构化字段。

#### 原则 6：Event-Driven Ready, Not Event-Driven Coupled

新闻是未来局部 cycle 的高价值输入，但当前项目阶段不能因为“将来要实时”而把 Kafka/Flink/CEP 等重组件耦合进来。  
本模块只负责输出稳定字段和明确语义，为未来接口留好空间即可。

### 6.2 反模式清单

| 反模式 | 为什么危险 |
|--------|-----------|
| 临时抓取 allowlist 之外的网站 | 破坏来源合规边界，后续无法审计 |
| 把转载新闻按多条独立事件处理 | 同一事件被重复放大，污染排序与传播 |
| 让 CEP 或下游系统推断文本情绪 | 责任边界错位，后续无法回放 S0 语义判断 |
| 未解析实体也强行填 canonical ID | 会把实体层错误固化到全链路 |
| 仅凭共现或标题联想生成 `Ex-3` | 图谱被猜测关系污染，后续传播严重失真 |
| 为追求时效跳过证据片段 | 审计与回放不可用，难以纠错 |
| 直接把新闻结论写成 formal 结果 | 破坏主系统对正式判断的唯一责任边界 |

---

## 7. 用户与消费方

### 7.1 直接消费方

| 消费方 | 消费内容 | 用途 |
|--------|----------|------|
| Layer B | 新闻域 Ex payload | 校验、去重、冲突处理、入湖 |
| `main-core` | 经接纳的新闻事实 / 新闻信号 | 参与状态判断、排序与建议 |
| `graph-engine` | 明确关系类 `Ex-3` | 形成候选图谱变更 |
| `audit-eval` | source reference、evidence、trace | 事后复盘与质量评估 |
| 开发 / reviewer | fixtures、cluster 样本、回放结果 | 开发与验收 |

### 7.2 间接用户

| 角色 | 关注点 |
|------|--------|
| 系统 owner | 新闻是否真正形成可复用的参考子系统，而不是脚本堆 |
| 实体 owner | 新闻场景对 alias / disambiguation 的压力是否暴露清楚 |
| 研究/审计人员 | 每条信号能否回到具体新闻和具体证据片段 |

---

## 8. 总体系统结构

### 8.1 新闻发现主线

```text
approved source feed / api / page
  -> discover article refs
  -> fetch article body + metadata
  -> normalize title / body / time / source fields
  -> persist local article artifact
```

### 8.2 新闻理解主线

```text
normalized article
  -> fingerprint / dedupe cluster
  -> entity mention detect
  -> entity resolution with entity-registry
  -> event extraction
  -> Ex-1 fact candidates
  -> Ex-2 signal candidates
  -> limited Ex-3 graph delta candidates
  -> submit through subsystem-sdk
```

### 8.3 面向未来事件驱动的接口主线

```text
news signal candidates
  -> stable structured fields
  -> Layer B validation
  -> future Full-mode stream consumer reads Ex-2
```

这里的重点不是“现在就做实时”，而是**保证 `Ex-2` 字段语义足够稳定，让未来 Kafka/Flink 只处理结构化模式，不再回头理解原文**。

---

## 9. 领域对象设计

### 9.1 持久层对象

| 对象名 | 职责 | 归属 |
|--------|------|------|
| NewsSourceConfig | 记录批准来源、访问方式、可靠性等级、抓取策略 | 部署配置 / 本地读取视图 |
| NewsArticleArtifact | 存放原始正文、标准化元数据和来源追溯 | 本地 artifact store |
| NewsDedupeCluster | 记录重复新闻聚类结果 | 本地 state / trace |
| NewsExtractionRun | 记录一次文章或 cluster 的抽取运行 | 本地 trace / optional analytical ref |

### 9.2 运行时对象

| 对象名 | 职责 | 生命周期 |
|--------|------|----------|
| NewsIngestContext | 单篇新闻从发现到归档的上下文 | 单次 ingest 期间 |
| ParsedNewsArticle | 标准化后的正文与元数据对象 | 单次处理期间 |
| EntityMention | 文本中的实体提及 | 单次解析期间 |
| NewsFactCandidate | 候选事实对象 | 单次抽取期间 |
| NewsSignalCandidate | 候选信号对象 | 单次抽取期间 |
| NewsGraphDeltaCandidate | 候选图谱变更对象 | 单次抽取期间 |
| EvidenceSpan | 证据片段定位 | 单次抽取期间 |

### 9.3 核心对象详细设计

#### NewsArticleArtifact

**角色**：系统处理新闻时的本地权威文章副本，承载来源追溯、正文、正文指纹和聚类前后状态。

| 字段 | 类型 | 含义 |
|------|------|------|
| `article_id` | string | 本地唯一文章 ID |
| `source_id` | string | 来源配置 ID |
| `source_reference` | object | URL / provider key / fetch cursor 等原始引用 |
| `title` | string | 标题 |
| `body_text` | string | 清洗后的正文文本 |
| `published_at` | datetime | 来源发布时间 |
| `fetched_at` | datetime | 系统抓取时间 |
| `language` | string | 语言标记 |
| `author_or_channel` | string | 作者、栏目或终端频道 |
| `content_hash` | string | 原始正文 hash |
| `article_fingerprint` | string | 用于语义去重的标准化指纹 |
| `license_tag` | string | 来源许可标签 |
| `reliability_tier` | string | 来源可靠性等级 |
| `cluster_id` | string nullable | 所属去重聚类 ID |

#### NewsDedupeCluster

**角色**：把同一事件的多篇新闻收敛到一个可追溯集合，避免多次放大。

| 字段 | 类型 | 含义 |
|------|------|------|
| `cluster_id` | string | 聚类 ID |
| `representative_article_id` | string | 代表文章 ID |
| `member_article_ids` | string[] | 成员文章列表 |
| `canonical_headline` | string | 聚类标准标题 |
| `first_published_at` | datetime | 最早发布时间 |
| `source_count` | int | 覆盖来源数 |
| `fingerprint_family` | string | 指纹族标记 |
| `cluster_confidence` | float | 聚类可信度 |

#### NewsFactCandidate

**角色**：对新闻中“发生了什么”做结构化表达，是本模块的基础输出。

| 字段 | 类型 | 含义 |
|------|------|------|
| `candidate_id` | string | 候选 ID |
| `article_id` | string | 来源文章 ID |
| `cluster_id` | string nullable | 所属聚类 |
| `fact_type` | string | 事实类型，如 accident / contract / product / regulation_impact |
| `summary` | string | 事实摘要 |
| `involved_entities` | object[] | 涉及实体及其解析状态 |
| `event_time` | datetime nullable | 事件发生时间 |
| `evidence_spans` | object[] | 支撑该事实的证据片段 |
| `confidence` | float | 候选置信度 |
| `source_reliability_tier` | string | 来源可靠性 |
| `export_contract` | string | 固定为 `Ex-1` |

#### NewsSignalCandidate

**角色**：把新闻理解映射为方向性、可组合的候选信号，为 Layer B、主系统和未来 CEP 提供结构化输入。

| 字段 | 类型 | 含义 |
|------|------|------|
| `candidate_id` | string | 候选 ID |
| `article_id` | string | 来源文章 ID |
| `cluster_id` | string nullable | 所属聚类 |
| `signal_type` | string | 如 `sentiment` / `event_impact` / `sector_rotation` |
| `direction` | string | `positive` / `negative` / `neutral` / `mixed` |
| `magnitude` | string or float | 影响强度 |
| `affected_entities` | object[] | 受影响实体 |
| `impact_scope` | string | company / sector / supply_chain / market_theme |
| `time_horizon` | string | short / medium / long |
| `rationale` | string | 结构化解释 |
| `evidence_spans` | object[] | 支撑信号判断的证据 |
| `confidence` | float | 候选置信度 |
| `export_contract` | string | 固定为 `Ex-2` |

#### NewsGraphDeltaCandidate

**角色**：仅在新闻中出现明确关系变化且证据足够强时，输出给图谱系统的候选变更。

| 字段 | 类型 | 含义 |
|------|------|------|
| `candidate_id` | string | 候选 ID |
| `article_id` | string | 来源文章 ID |
| `subject_entity` | object | 主体实体 |
| `relation_type` | string | 如 supplier_of / acquired / sanctioned_by |
| `object_entity` | object | 客体实体 |
| `delta_action` | string | add / update / deactivate |
| `valid_from` | datetime nullable | 生效时间 |
| `evidence_spans` | object[] | 明确关系证据 |
| `confidence` | float | 候选置信度 |
| `requires_manual_review` | bool | 是否要求人工审查 |
| `export_contract` | string | 固定为 `Ex-3` |

---

## 10. 数据模型设计

### 10.1 本地存储分层

`subsystem-news` 只维护**本地处理所需的 artifact 和 trace**，不拥有 Layer A 的 canonical / formal 真相层。

| 分层 | 内容 | 说明 |
|------|------|------|
| Source Config Layer | 批准来源配置、访问策略、可靠性等级 | 由部署配置注入，本模块只读 |
| Artifact Layer | 原始 HTML / 文本、标准化正文、元数据 | 便于回放与排错 |
| Dedupe State Layer | cluster 状态、fingerprint 结果 | 便于增量处理 |
| Trace Layer | 抽取运行记录、错误、置信度、提交回执 | 便于回归与审计 |

### 10.2 与主系统数据平台的边界

- 本模块**不拥有** Raw Zone / Canonical Zone / Formal Zone 的 schema 定义和入湖流程。
- 新闻原文本地 artifact 仅服务于本模块回放、排错和证据追溯，**不是 Layer A Raw Zone 的替代品**。
- 经 `subsystem-sdk.submit()` 提交后的 Ex payload，只有在 Layer B 接纳后才进入主系统 canonical 真相链。
- 本模块不建立 formal 表，不提供 `latest` / `by_id` / `by_snapshot` 读取语义。

### 10.3 数据留痕要求

- 每篇文章必须可回到 `source_reference`
- 每个 cluster 必须能追溯成员文章
- 每个候选对象必须能追溯到文章和具体 evidence spans
- 每次回放必须保留运行版本、模型版本和规则版本

---

## 11. 核心计算/算法设计

### 11.1 新闻发现与来源校验

第一步不是“抓到越多越好”，而是“只抓允许接入的来源”。  
输入必须通过 `NewsSourceConfig` 校验，包含：

1. 来源是否在 allowlist 中
2. 当前凭据或访问方式是否有效
3. 来源正文是否可稳定获取
4. 来源级可靠性和优先级是否已配置

未通过校验的来源直接拒绝进入主链，只记录错误 trace。

### 11.2 正文规范化

规范化目标是得到一个稳定的 `ParsedNewsArticle`：

1. 清洗标题、正文、发布时间、作者/频道字段
2. 剥离导航、广告、免责声明和模板化站点噪声
3. 统一时间格式、语言标记和空白字符
4. 生成 `content_hash` 与 `article_fingerprint`

**约束**：

- 优先使用来源直接提供的正文文本，其次才做 HTML 正文抽取
- 新闻正文主路径不依赖 Docling；Docling 是文档解析主线的工具，不应成为新闻 HTML 解析的默认依赖
- 缺少正文时，只有标题+摘要的快讯可进入低置信路径，默认不直接生成 `Ex-3`

### 11.3 去重与聚类

新闻处理的默认单位不是单篇文章，而是**cluster 视角下的事件组**。

去重策略分两层：

1. **强去重**：同一 provider article key、同一 URL、同一 content hash 直接归并
2. **弱去重**：标题相似、正文核心句相似、发布时间接近时进入 cluster 候选

聚类完成后：

- 对相同事件只保留一个 representative article 进入主抽取链
- 其他 member article 只作为补充来源证据
- 如果不同来源给出互相冲突的关键信息，则提升为 conflict trace，不自动合并成单一事实

### 11.4 实体提及识别与解析

实体识别分为两个责任层次：

1. **本模块负责发现 mention**：公司名、简称、产品、人物、行业主题、地缘/监管主体等
2. **`entity-registry` 负责给 canonical 解释**：alias 匹配、歧义消解、case 记录、失败返回

处理规则：

- 本模块负责 mention 检测、span 定位、上下文打包和类型初判，不负责最终 canonical 裁决
- 股票代码、正式公司名、标准简称优先通过 `entity-registry.lookup_alias()` 走确定性快路径
- 确定性未命中、候选大于 1、集团/子公司口语称谓、跨语言别名和主题概念统一进入 `entity-registry.resolve_mentions()`
- 解析失败时保留 unresolved mention，不得伪造 canonical entity

### 11.5 事件与事实抽取

`Ex-1` 是新闻域最基础也最稳的输出。  
本模块应优先从新闻中提炼出“发生了什么”，再考虑是否提升为方向性信号。

重点事实类型包括但不限于：

- 重大经营事件
- 产品/订单/合作/停产/事故
- 监管、诉讼、制裁、调查
- 并购、资产重组、股权交易相关新闻
- 行业与供应链扰动

涉及复杂事件类型归并、方向判断、`impact_scope` 归类或多句证据融合时，统一通过 `reasoner-runtime.generate_structured()` 执行结构化抽取，并固定 schema 与 version pin。

每条 `NewsFactCandidate` 至少要求：

- 可定位的 Evidence Span
- 已知或 unresolved 的 involved entities
- 事件类型与摘要
- 基础置信度

### 11.6 信号生成

`Ex-2` 不是情绪分数随便打一分，而是对未来可消费的结构化判断。

信号生成流程：

1. 从事实候选中确定是否值得提升为信号
2. 判断 `signal_type`
3. 判断 `direction`
4. 估计 `magnitude`
5. 标记 `impact_scope` 和 `time_horizon`
6. 绑定 evidence、affected_entities 和 rationale

关键约束：

- `direction`、`magnitude`、`impact_scope` 必须在本模块完成，不能留给 CEP 或下游推断
- 同一个 cluster 下多篇转载新闻不能机械叠加成多条同向信号
- 没有足够证据时宁可只保留 `Ex-1`，也不强行提升为 `Ex-2`

### 11.7 图谱变更候选生成

新闻域允许输出 `Ex-3`，但门槛必须高于 `Ex-1` / `Ex-2`。

只有以下类型才考虑 `Ex-3`：

- 明确收购 / 出售 / 控股关系变化
- 明确供应、合作、制裁、代理等关系建立或终止
- 新闻正文中直接给出可支持关系边的表述

明确禁止：

- 仅凭同一文章中提到两家公司就生成边
- 仅凭情绪方向推断合作或竞争关系
- 用摘要站、二手转载站作为唯一证据生成 `Ex-3`

### 11.8 置信度、来源等级与拒绝输出

新闻域必须允许“拒绝输出”。  
候选对象的形成应综合：

- 来源可靠性
- 文本质量
- 证据是否明确
- 实体解析是否稳定
- 聚类是否冲突

当以下情况出现时，应拒绝生成对应候选：

- 来源不可靠或来源策略不允许
- 正文不完整或证据片段无法定位
- 实体解析高度不确定
- cluster 内冲突信息未处理
- 关系证据不足却试图生成 `Ex-3`

### 11.9 面向 Full 模式的字段稳定性

本模块当前不实现 Kafka/Flink/CEP，但需要保证未来 `stream-layer` 消费时不需要重新解释原文。  
因此 `Ex-2` 至少要稳定提供：

- `signal_type`
- `direction`
- `magnitude`
- `affected_entities`
- `impact_scope`
- `time_horizon`
- `source_reference`
- `evidence_spans`

未来 CEP 只负责模式组合，例如“连续负面供应链新闻 + 行业扩散”，而不是回头判断“这条新闻是不是负面”。
因此 Lite -> Full 的 backend / provider / fallback 切换只能发生在 `reasoner-runtime` 配置层，不得要求改写 news 域 prompt 组装、字段命名或 Ex schema。

---

## 12. 触发/驱动引擎设计

### 12.1 常规批处理触发

常规模式下，`subsystem-news` 由外部调度或 `subsystem-sdk` heartbeat 触发：

```text
schedule / heartbeat
  -> pull approved source updates
  -> ingest new articles
  -> run normalize + dedupe + extract
  -> submit Ex payloads
```

调度策略本身不归本模块拥有，本模块只保证幂等处理。

### 12.2 回放与修复触发

当规则、模型或实体词典变更后，必须支持按文章或 cluster 回放：

```text
manual replay request
  -> load article artifact / cluster state
  -> rerun extraction with pinned version
  -> compare old/new candidate outputs
```

这条路径对新闻域尤其重要，因为新闻误判的排查通常来自“为什么这条新闻当时判成了利空/利多”。

### 12.3 Full 模式接口约束

P11 以后，新闻可能成为事件驱动局部 cycle 的高频输入，但本模块只承担**快速稳定地产出 Ex 候选对象**。  
以下职责仍不在本模块内：

- Kafka topic 管理
- Flink 流式校验
- Flink CEP 规则
- interim publish

### 12.4 启动前置条件

本模块启动前至少需要：

1. `contracts` 可用
2. `subsystem-sdk` 可用
3. Approved source config 已冻结
4. `entity-registry` 基础解析接口可用
5. `reasoner-runtime.generate_structured()` 基础结构化抽取接口可用

---

## 13. 输出产物设计

### 13.1 `Ex-1` 新闻候选事实

| 字段 | 说明 |
|------|------|
| `fact_type` | 事件类型 |
| `source_reference` | 来源追溯 |
| `evidence_spans` | 证据片段 |
| `involved_entities` | 涉及实体 |
| `event_time` | 事件时间 |
| `confidence` | 置信度 |

### 13.2 `Ex-2` 新闻候选信号

| 字段 | 说明 |
|------|------|
| `signal_type` | `sentiment` / `event_impact` / `sector_rotation` 等 |
| `direction` | 正向 / 负向 / 中性 / 混合 |
| `magnitude` | 强度 |
| `affected_entities` | 受影响实体 |
| `impact_scope` | 公司 / 行业 / 供应链 / 主题 |
| `time_horizon` | 影响时间窗 |
| `source_reference` | 来源追溯 |
| `evidence_spans` | 证据片段 |

### 13.3 `Ex-3` 新闻候选图谱变更

| 字段 | 说明 |
|------|------|
| `subject_entity` | 主体实体 |
| `relation_type` | 关系类型 |
| `object_entity` | 客体实体 |
| `delta_action` | add / update / deactivate |
| `source_reference` | 来源追溯 |
| `evidence_spans` | 明确关系证据 |
| `confidence` | 置信度 |

### 13.4 辅助产物

除 Ex 合同外，本模块还应产出以下辅助对象：

- 新闻文章 artifact
- cluster 去重结果
- 抽取运行 trace
- 回放差异报告

这些对象主要服务于开发、审计和回归，不直接进入 formal 主线。

---

## 14. 系统模块拆分

| 模块 | 责任 |
|------|------|
| `subsystem_news.sources` | 来源发现、拉取、访问策略校验 |
| `subsystem_news.normalize` | 标题/正文/时间规范化 |
| `subsystem_news.dedupe` | 指纹计算、转载去重、cluster 管理 |
| `subsystem_news.entities` | mention 抽取、实体解析协同 |
| `subsystem_news.extract` | 事实抽取、事件分类 |
| `subsystem_news.signals` | `Ex-2` 信号生成与约束检查 |
| `subsystem_news.graph` | 高门槛 `Ex-3` 生成 |
| `subsystem_news.runtime` | pipeline 组装、submit、replay |
| `subsystem_news.fixtures` | 夹具、标注样本、回归样本 |

模块边界要求：

- `sources` 只负责拿到文章，不负责解释语义
- `dedupe` 先于 `signals`
- `graph` 只消费已过实体解析和证据校验的对象
- `runtime` 负责流程编排，但不拥有外部调度器

---

## 15. 存储与技术路线

### 15.1 语言与运行时

- Python 作为主实现语言
- 复用 `subsystem-sdk` 的公共子系统框架
- 复杂抽取与分类通过 `reasoner-runtime` 访问模型能力

### 15.2 正文处理路线

- 优先消费来源原生正文字段
- 次选轻量 HTML 正文抽取
- 新闻主路径不引入重型文档解析栈作为默认依赖

### 15.3 实体与语言处理

- 轻量 NER / mention 抽取可以复用 Lite 模式已有 NLP 包
- canonical entity 解析统一走 `entity-registry`
- 不在本模块内单独维护另一套 alias 真相表

### 15.4 存储策略

- 本地 artifact / trace 可采用 JSON / Parquet / 轻量状态表
- canonical / formal 真相入湖仍归 Layer B + `data-platform`
- 不引入独立向量数据库或流式基础设施作为首版依赖

### 15.5 明确不引入的技术

- Kafka / Flink / CEP：归 P11 `stream-layer`
- Temporal：归 `orchestrator` 的 Full 可选路径
- Neo4j 直写：归 `graph-engine`
- 独立爬虫平台：超出新闻子系统边界

---

## 16. API 与接口合同

### 16.1 对外接口

| 接口 | 输入 | 输出 | 约束 |
|------|------|------|------|
| `discover_articles(cursor)` | source cursor / schedule window | `NewsArticleRef[]` | 只返回 approved sources |
| `ingest_article(article_ref)` | 来源文章引用 | `NewsArticleArtifact` | 必须带 source reference |
| `process_article(article_id)` | 本地文章 ID | `ProcessResult` | 内含 dedupe / entities / Ex candidates |
| `replay_article(article_id, version_pin)` | 文章 ID + 版本钉住信息 | `ReplayResult` | 结果必须可比较旧版输出 |
| `submit_candidates(batch)` | `Ex` payload batch | `SubmitReceipt` | 统一走 `subsystem-sdk.submit()` |

### 16.2 对依赖模块的接口

| 依赖模块 | 接口 | 目的 |
|----------|------|------|
| `entity-registry` | `lookup_alias(name)` | 对股票代码、正式公司名、标准简称做确定性快路径命中 |
| `entity-registry` | `resolve_mentions(mentions)` | 把复杂 mention 解析到 canonical entity 或 unresolved |
| `entity-registry` | `record_resolution_case(case)` | 对复杂新闻场景沉淀解析案例 |
| `reasoner-runtime` | `generate_structured(request)` | 执行复杂事件/事实/方向/影响的结构化抽取 |

### 16.3 接口硬约束

- `submit_candidates()` 前必须完成本地 schema 校验
- 所有模型调用必须经由 `reasoner-runtime.generate_structured()`，不得私接 provider SDK
- backend / provider / fallback 切换只能在 `reasoner-runtime` 配置层发生，不得要求改写 news 域代码或 Ex schema
- `Ex-2` 不允许缺少 `direction`、`magnitude`、`affected_entities`
- `Ex-3` 不允许缺少双边实体和明确 evidence spans
- 任一输出缺少 `source_reference` 视为接口错误

---

## 18. 测试与验证策略

### 18.1 Fixture 结构

至少要有以下夹具集合：

1. 单源标准新闻样本
2. 多源转载样本
3. 模糊实体样本
4. 明确关系样本
5. 只适合 `Ex-1` 不适合 `Ex-2` 的边界样本
6. 不应生成 `Ex-3` 的负样本

### 18.2 核心测试类型

| 测试类型 | 验证内容 |
|----------|----------|
| 规范化测试 | 标题、正文、发布时间、来源字段是否正确落位 |
| 去重测试 | 转载新闻是否正确聚类 |
| 实体解析测试 | 模糊简称是否正确 unresolved 或正确解析 |
| 合同测试 | `Ex-1` / `Ex-2` / `Ex-3` schema 是否满足合同 |
| 证据测试 | 每个候选对象是否带 evidence spans |
| 回放回归测试 | 规则升级后旧样本结果是否可比较 |
| 负样本测试 | 共现新闻是否被错误提升为 `Ex-3` |

### 18.3 验证策略

- 每次改动先跑 fixture 回归，再允许扩大来源范围
- `Ex-3` 需要单独 review 样本集，不与普通新闻信号混测
- 转载聚类错误视为高优先级问题，因为它会系统性放大噪声

---

## 19. 关键评价指标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| Approved source ingestion success rate | >= 95% | 在已配置样本源上的成功接入率 |
| Evidence coverage | 100% | 所有提交的 Ex 候选都必须带 evidence spans |
| Dedupe precision on curated fixtures | >= 95% | 精选转载样本上的去重准确率 |
| Unresolved entity explicitness | 100% | 解析失败必须显式 unresolved，不允许静默伪造 |
| `Ex-2` contract completeness | 100% | 提交的信号必须字段完整 |
| `Ex-3` false positive rate on reviewed set | <= 1% | 关系边误报必须极低 |
| Fetch-to-candidate p95 latency | <= 5 分钟 | 常规来源从发现到生成候选的处理延迟 |

---

## 20. 项目交付物清单

| 交付物 | 内容 | 验收方式 |
|--------|------|----------|
| 来源配置规范 | approved source schema、示例配置、访问要求 | 配置评审 |
| 新闻 ingest + normalize 管线 | 来源接入、正文规范化、本地 artifact 落地 | 真实样本跑通 |
| 去重聚类能力 | fingerprint、cluster、冲突记录 | 转载样本验证 |
| `Ex-1` / `Ex-2` 生成能力 | 事实与信号输出 | schema + fixture 验证 |
| 高门槛 `Ex-3` 能力 | 少量强证据关系变更输出 | 人审样本验证 |
| 回放与回归资产 | fixtures、trace、回放脚本、差异报告 | 回归测试通过 |
| 运行文档 | 接口说明、边界、故障处理、已知限制 | 文档审查 |

---

## 21. 实施路线图

### 阶段 0：来源与边界冻结

- 冻结 approved source allowlist
- 冻结新闻事实/信号的首批 taxonomy
- 确认 `subsystem-news` 与公告、研报、流式层的边界

### 阶段 1：来源接入与规范化

- 实现 article discovery
- 实现正文抽取与标准化
- 落地本地 article artifact

### 阶段 2：去重与实体解析协同

- 实现 fingerprint 与 cluster
- 接通 `entity-registry`
- 建立 unresolved 处理路径

### 阶段 3：`Ex-1` / `Ex-2` 成型

- 优先产出稳定 `Ex-1`
- 再补 `Ex-2` 的 `direction` / `magnitude` / `impact_scope`
- 接通 `subsystem-sdk.submit()`

### 阶段 4：高门槛 `Ex-3` 与回放

- 仅对强证据关系场景开放 `Ex-3`
- 建立回放与回归基线
- 固定 metrics 与验收口径

### 阶段 5：面向 Full 模式接口对齐

- 保证输出字段能被未来 `stream-layer` 直接消费
- 不在此阶段内引入 Kafka / Flink / CEP 实现

---

## 22. 主要风险

| 风险 | 描述 | 应对 |
|------|------|------|
| 来源策略变化 | 付费 API、站点结构或访问策略变化 | 来源配置解耦，按 source adapter 隔离 |
| 转载与改写噪声 | 同一事件多版本传播 | 强化 cluster 与 conflict trace |
| 实体歧义 | 简称、子公司、主题词冲突 | unresolved 显式化，依赖 `entity-registry` |
| 过度信号化 | 把事实层错误提升为信号层 | 保持 facts-first，拒绝低证据 `Ex-2` |
| 图谱污染 | 弱证据关系误入 `Ex-3` | 高门槛 + 单独 review 样本集 |
| 时效预期失真 | 用户误以为本模块就是实时事件引擎 | 文档明确不拥有 P11 流式职责 |

---

## 23. 验收标准

1. 能从 approved sources 稳定发现并接入新闻文章，且每篇文章都能追溯回原始来源。
2. 对精选转载样本，能正确完成去重聚类，不把同一事件机械放大为多条独立信号。
3. `Ex-1` 和 `Ex-2` 能通过合同校验，且所有输出都带 evidence spans。
4. 模糊实体场景下，系统能显式 unresolved 或正确解析，不出现自造 canonical entity。
5. `Ex-3` 仅在强证据关系场景产出，并通过单独 review 样本集验证。
6. 模块不直接依赖 Kafka / Flink / CEP / formal publish，也不越权写图谱或正式对象。
7. 回放同一篇文章时，能输出可比较的差异结果，并保留版本钉住信息。

---

## 24. 一句话结论

`subsystem-news` 应被定义为一个**以来源追溯、转载去重、实体协同和语义判断为核心，把纯非结构化新闻稳定转成 Ex 候选对象、但坚决不越界吞并流式层和正式发布职责**的参考子项目。

---

## 25. 自动化开发对接

### 25.1 自动化输入契约

| 项 | 规则 |
|----|------|
| `module_id` | `subsystem-news` |
| 脚本先读章节 | `§1` `§4` `§5.2` `§5.4` `§8` `§11` `§14` `§16` `§18` `§21` `§23` |
| 默认 issue 粒度 | 一次只实现一个子链路：sources / normalize / dedupe / entities / extract / signals / graph / runtime / fixtures |
| 默认写入范围 | 当前 repo 的新闻源接入、正文规范化、抽取、提交、测试、fixture、文档和版本配置 |
| 内部命名基线 | 以 `§14` 的内部模块名和 `§9` / `§13` 的对象名为准 |
| 禁止越界 | 不接未批准来源、不私接 provider SDK、不写 formal object、不把 CEP 语义拉回本项目 |
| 完成判定 | 同时满足 `§18`、`§21` 当前阶段退出条件和 `§23` 对应条目 |

### 25.2 推荐自动化任务顺序

1. 先落 approved sources、normalize、dedupe / cluster 主干
2. 再落 `entity-registry` 协同和 `reasoner-runtime.generate_structured()` 抽取主线
3. 再落 `Ex-2`、高门槛 `Ex-3` 和 replay / repair
4. Full 模式 transport 适配只通过 backend 配置后置推进

补充规则：

- 单个 issue 默认只改一个子链路；去重、实体、语义抽取不要混成超大 PR
- 在 `source_reference`、cluster 和实体解析未稳定前，不进入 `Ex-3` 或 Full 适配类 issue

### 25.3 Blocker 升级条件

- 来源 allowlist、版权 / 合规边界或 `source_reference` 语义不清
- 需要私接 provider SDK 或把语义判断下放给 CEP / 下游系统
- 需要把新闻结果直接写成 formal object、图谱正式更新或运行时状态
- 无法给出去重、实体解析和结构化抽取的最小样本闭环
