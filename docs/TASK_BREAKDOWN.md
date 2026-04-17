# 项目任务拆解

## 阶段 0：来源与边界冻结

**目标**：冻结 approved source allowlist、新闻事实/信号首批 taxonomy，搭建 `subsystem_news` 包骨架与配置层，使后续阶段有稳定边界与 schema 基线。
**前置依赖**：无

### ISSUE-001: 项目脚手架与包结构初始化
**labels**: P0, infrastructure, milestone-0, ready

#### 背景与目标
项目仅有 `pyproject.toml` 与文档，尚无任何 Python 包骨架。根据项目文档 §14 与 §25.1，`subsystem-news` 必须按 `sources / normalize / dedupe / entities / extract / signals / graph / runtime / fixtures` 九个子模块组织代码。本 issue 负责一次性落地包目录、测试脚手架、依赖声明与最小运行入口，使后续每个阶段都在已有结构上增量开发。此 issue 是所有后续 issue 的物理前置，不涉及任何业务语义。

#### 所属模块
- 写入范围：
  - `pyproject.toml`（补充依赖与包声明）
  - `src/subsystem_news/__init__.py`
  - `src/subsystem_news/sources/__init__.py`
  - `src/subsystem_news/normalize/__init__.py`
  - `src/subsystem_news/dedupe/__init__.py`
  - `src/subsystem_news/entities/__init__.py`
  - `src/subsystem_news/extract/__init__.py`
  - `src/subsystem_news/signals/__init__.py`
  - `src/subsystem_news/graph/__init__.py`
  - `src/subsystem_news/runtime/__init__.py`
  - `src/subsystem_news/fixtures/__init__.py`
  - `src/subsystem_news/errors.py`
  - `src/subsystem_news/version.py`
  - `tests/__init__.py`
  - `tests/test_package_layout.py`
  - `README.md`（补充模块导航）
- 只读/集成边界：无（尚未接入外部依赖）
- 禁止写入：`docs/` 下除 README 外其他文件、`CLAUDE.md`、`AGENTS.md`

#### 实现范围
- 包骨架：
  - `src/subsystem_news/__init__.py`：导出 `__version__`、九个子模块命名空间
  - `src/subsystem_news/version.py`：常量 `__version__: str = "0.1.0"`
  - 每个子包 `__init__.py`：提供模块 docstring（说明该模块职责），不写业务逻辑
- 错误定义：
  - `src/subsystem_news/errors.py`：基类 `class SubsystemNewsError(Exception)`；子类 `SourceNotApprovedError`、`EvidenceMissingError`、`EntityResolutionError`、`ContractViolationError`，每个子类带 `code: str` 属性
- 构建配置：
  - `pyproject.toml`：将 `packages = []` 改为 `packages = ["subsystem_news"]` 并添加 `[tool.setuptools.packages.find] where = ["src"]`；`dependencies` 追加 `pydantic>=2.6`；新增 `[project.optional-dependencies] dev = ["pytest>=8", "pytest-cov>=5"]`
- 测试脚手架：
  - `tests/test_package_layout.py`：`test_all_submodules_importable()` 遍历九个子模块并 `importlib.import_module`
  - `tests/test_package_layout.py`：`test_errors_have_codes()` 验证每个异常子类都有非空 `code`
- 文档：
  - `README.md` 追加「模块导航」章节，列出九个子模块对应职责（不重复 CLAUDE.md 内容）

#### 不在本次范围
- 不实现任何业务逻辑（discover/ingest/normalize/dedupe/extract 等一律留空壳）
- 不引入 `reasoner-runtime` / `subsystem-sdk` / `entity-registry` 具体依赖包（这些属于阶段 1 集成）
- 不定义任何 `Ex-1` / `Ex-2` / `Ex-3` schema（属于 ISSUE-002）
- 不设置 CI workflow（.github/ 在另一 issue 考虑）
- 不要把 `errors.py` 扩展为通用结果类型（保持异常层即可）
- 如发现需要修改 `contracts/` 仓外 schema，应升级为 blocker 而非扩大本 issue

#### 关键交付物
- Python 包 `subsystem_news` 可通过 `pip install -e .` 安装
- 子模块导入：`from subsystem_news import sources, normalize, dedupe, entities, extract, signals, graph, runtime, fixtures` 全部成功
- 异常层级：`SubsystemNewsError` 及 4 个子类，均暴露 `code: str`
- `pyproject.toml` 声明包位置 `src/subsystem_news`，并支持 `pytest` 发现 `tests/`
- `tests/test_package_layout.py` 提供至少 2 个测试用例
- `README.md` 包含模块导航表格，列出 9 个子模块与 CLAUDE.md 中职责对齐的一句话描述

#### 验收标准
**Core functionality:**
- [ ] `python -c "import subsystem_news; print(subsystem_news.__version__)"` 输出 `0.1.0`
- [ ] 九个子模块全部可 import，无 `ImportError`
- [ ] `SubsystemNewsError` 及 4 个子类均可实例化，且 `err.code` 为非空字符串
**Error handling:**
- [ ] 异常子类继承关系正确：`isinstance(SourceNotApprovedError("x"), SubsystemNewsError) is True`
**Integration:**
- [ ] `pip install -e .[dev]` 在干净 venv 中成功
**Tests:**
- [ ] 至少 2 个单测：`test_all_submodules_importable`、`test_errors_have_codes`
- [ ] `pytest` 全部通过
- [ ] `README.md` 模块导航表格覆盖全部 9 个子模块

#### 验证命令
```bash
# Install
pip install -e ".[dev]"
# Unit tests
pytest tests/test_package_layout.py -v
# Integration check
python -c "from subsystem_news import sources, normalize, dedupe, entities, extract, signals, graph, runtime, fixtures; from subsystem_news.errors import SubsystemNewsError, SourceNotApprovedError, EvidenceMissingError, EntityResolutionError, ContractViolationError; print('ok')"
# Regression
pytest -q
```

#### 依赖
无前置依赖

---

### ISSUE-002: 来源配置与 Ex 合同 schema 冻结
**labels**: P0, infrastructure, milestone-0, ready

#### 背景与目标
根据项目文档 §3、§9、§11.1、§13、§16 与 §25.1 指定的“先读章节”，阶段 0 必须冻结三类数据契约：(1) approved source 配置 schema；(2) 新闻事实/信号/图谱变更 Ex-1/Ex-2/Ex-3 的本地 Pydantic schema；(3) 事件/信号 taxonomy 的枚举首批值。冻结后后续阶段只做填充，不再修改字段命名。此 issue 不实现抽取逻辑，仅落 schema + validator + 枚举 + 单测。

#### 所属模块
- 写入范围：
  - `src/subsystem_news/contracts/__init__.py`
  - `src/subsystem_news/contracts/sources.py`
  - `src/subsystem_news/contracts/article.py`
  - `src/subsystem_news/contracts/cluster.py`
  - `src/subsystem_news/contracts/candidates.py`
  - `src/subsystem_news/contracts/taxonomy.py`
  - `src/subsystem_news/contracts/evidence.py`
  - `tests/contracts/test_sources_schema.py`
  - `tests/contracts/test_candidate_schema.py`
  - `tests/contracts/test_taxonomy.py`
  - `src/subsystem_news/fixtures/approved_sources.sample.json`
- 只读/集成边界：ISSUE-001 产出的包骨架、`errors.py`
- 禁止写入：`sources/`、`normalize/`、`extract/` 等业务模块（仅允许 `import` contracts）；不得修改 `pyproject.toml` 依赖（Pydantic 已在 ISSUE-001 中加入）

#### 实现范围
- Source 配置层（`contracts/sources.py`）：
  - `class NewsSourceConfig(BaseModel)`：字段 `source_id: str`、`display_name: str`、`access_mode: Literal["rss","api","site_html"]`、`base_url: HttpUrl`、`approved: bool`、`reliability_tier: Literal["A","B","C"]`、`license_tag: str`、`language: str`、`credential_ref: str | None`
  - `def load_allowlist(path: Path) -> list[NewsSourceConfig]`：读取 JSON，拒绝 `approved=False` 条目并抛 `SourceNotApprovedError`
- Article artifact schema（`contracts/article.py`）：`class NewsArticleArtifact(BaseModel)` — 完整覆盖 §9.3 字段（`article_id` … `cluster_id`）
- Dedupe cluster schema（`contracts/cluster.py`）：`class NewsDedupeCluster(BaseModel)` — 覆盖 §9.3
- Evidence schema（`contracts/evidence.py`）：`class EvidenceSpan(BaseModel)`：`article_id: str`、`start_char: int`、`end_char: int`、`quote: str`、`locator: Literal["title","body"]`；validator 要求 `end_char > start_char`
- 候选对象 schema（`contracts/candidates.py`）：
  - `class InvolvedEntity(BaseModel)`：`mention_text: str`、`canonical_id: str | None`、`resolution_status: Literal["resolved","unresolved","ambiguous"]`、`type_hint: str`
  - `class NewsFactCandidate(BaseModel)`：覆盖 §9.3，`export_contract: Literal["Ex-1"] = "Ex-1"`，`evidence_spans: list[EvidenceSpan]` 最少 1 条
  - `class NewsSignalCandidate(BaseModel)`：覆盖 §9.3 / §13.2，`export_contract: Literal["Ex-2"] = "Ex-2"`，必填 `direction` / `magnitude` / `affected_entities` / `impact_scope` / `time_horizon`
  - `class NewsGraphDeltaCandidate(BaseModel)`：覆盖 §9.3 / §13.3，`export_contract: Literal["Ex-3"] = "Ex-3"`，必填双边实体 + evidence
  - 每个候选类均提供 `model_config = ConfigDict(frozen=True, extra="forbid")`
- Taxonomy 枚举（`contracts/taxonomy.py`）：
  - `FactType = Literal["accident","contract","product","regulation_impact","m_and_a","supply_chain","litigation"]`
  - `SignalType = Literal["sentiment","event_impact","sector_rotation"]`
  - `Direction = Literal["positive","negative","neutral","mixed"]`
  - `ImpactScope = Literal["company","sector","supply_chain","market_theme"]`
  - `TimeHorizon = Literal["short","medium","long"]`
  - `RelationType = Literal["supplier_of","acquired","sanctioned_by","partner_of","divested"]`
  - `DeltaAction = Literal["add","update","deactivate"]`
- Fixture：`approved_sources.sample.json` — 2 条 approved、1 条 `approved=False` 的示例
- 单测：每个 schema 至少覆盖「合法样例通过」「缺失必填字段被拒绝」「枚举外值被拒绝」三类

#### 不在本次范围
- 不实现 `discover_articles` / `ingest_article` 等运行时函数（留给阶段 1）
- 不实现 fingerprint / cluster 算法（属于 ISSUE-006）
- 不接入 `reasoner-runtime` / `entity-registry` 真实客户端
- 不扩展 taxonomy 枚举为动态配置（冻结就是最小枚举集合）
- 不定义 `submit()` 回执 schema（属于阶段 3 的 runtime issue）
- 任何跨项目 `contracts/` 共享 schema 变更升级为 blocker

#### 关键交付物
- Pydantic v2 模型：`NewsSourceConfig`、`NewsArticleArtifact`、`NewsDedupeCluster`、`EvidenceSpan`、`InvolvedEntity`、`NewsFactCandidate`、`NewsSignalCandidate`、`NewsGraphDeltaCandidate`
- Literal/Enum 约束：`FactType`、`SignalType`、`Direction`、`ImpactScope`、`TimeHorizon`、`RelationType`、`DeltaAction`
- 函数：`load_allowlist(path: Path) -> list[NewsSourceConfig]`
- 异常路径：未 approved 抛 `SourceNotApprovedError`；evidence 为空抛 `EvidenceMissingError`；字段违约抛 `ContractViolationError`（通过 Pydantic 的 `ValidationError` 外包装）
- Fixture 文件：`fixtures/approved_sources.sample.json`
- 单测：≥ 12 个（4 个 schema × 3 个场景）

#### 验收标准
**Core functionality:**
- [ ] `NewsFactCandidate(export_contract="Ex-1")` 合法实例可构造，缺 `evidence_spans` 立即抛异常
- [ ] `NewsSignalCandidate` 缺 `direction` / `magnitude` / `affected_entities` 任一时抛 ValidationError
- [ ] `NewsGraphDeltaCandidate` 缺 `subject_entity` 或 `object_entity` 时抛异常
- [ ] `load_allowlist()` 对 `approved=False` 条目抛 `SourceNotApprovedError`
**Error handling:**
- [ ] 枚举字段传入未列值时报错信息包含可选值列表
- [ ] `EvidenceSpan` 中 `end_char <= start_char` 时报错
**Integration:**
- [ ] 所有候选 schema 可 `model_dump_json()` 序列化并 `model_validate_json()` 还原，字段完全一致
- [ ] Taxonomy 枚举在 candidate schema 内被正确引用（pyright/mypy 可选，运行时等价）
**Tests:**
- [ ] 单测数量 ≥ 12
- [ ] `pytest tests/contracts/ -q` 全绿
- [ ] ISSUE-001 的 `test_package_layout.py` 继续通过（无回归）

#### 验证命令
```bash
# Unit tests
pytest tests/contracts/ -v
# Integration check
python -c "from subsystem_news.contracts.candidates import NewsFactCandidate, NewsSignalCandidate, NewsGraphDeltaCandidate; from subsystem_news.contracts.sources import load_allowlist; from pathlib import Path; print(load_allowlist(Path('src/subsystem_news/fixtures/approved_sources.sample.json')))"
# Regression
pytest -q
```

#### 依赖
依赖 #ISSUE-001（需要包骨架与 errors 模块）

---

## 阶段 1：来源接入与规范化

**目标**：实现 article discovery、正文抽取与标准化，落地本地 `NewsArticleArtifact`，使后续 dedupe/实体/抽取能读取稳定 artifact。
**前置依赖**：阶段 0 完成

### ISSUE-003: sources 模块 — 发现与抓取
**labels**: P0, feature, milestone-1, ready
**摘要**: 实现 `subsystem_news.sources`：基于 approved allowlist 的 RSS/API/站点正文 adapter 接口、`discover_articles(cursor)` 与 `fetch_article_body()`，并写入抓取 trace。
**所属模块**: 主写入 `src/subsystem_news/sources/`（`base.py`、`rss.py`、`api.py`、`site_html.py`、`discover.py`、`registry.py`）+ `tests/sources/`；只读引用 `contracts/sources.py`、`contracts/article.py`、`errors.py`
**写入边界**: 允许修改 `sources/` 与对应测试 + `fixtures/` 下的抓取样本；禁止修改 `contracts/`、`normalize/`、`dedupe/`；禁止直连 Kafka/Flink 或任何未 approved 来源
**实现顺序**: (1) `SourceAdapter` 协议与 `AdapterRegistry`；(2) 三类 adapter 实现（RSS/API/HTML），统一返回 `NewsArticleRef`；(3) `discover_articles(cursor)` 汇聚与 allowlist 校验；(4) `fetch_article_body()` 落盘原始 HTML/text 与 content_hash；(5) fixture + 单测（含拒绝未 approved 来源与凭据缺失场景）
**依赖**: #ISSUE-002（需 `NewsSourceConfig` 与 `NewsArticleArtifact` schema）

---

### ISSUE-004: normalize 模块 — 正文规范化与 artifact 落地
**labels**: P0, feature, milestone-1, ready
**摘要**: 从原始 fetch 结果产出 `ParsedNewsArticle` 与持久化 `NewsArticleArtifact`，统一标题/正文/时间/语言/作者字段，生成 `content_hash` 与 `article_fingerprint` 雏形。
**所属模块**: 主写入 `src/subsystem_news/normalize/`（`html_strip.py`、`text_clean.py`、`time_parse.py`、`fingerprint_seed.py`、`pipeline.py`）+ `src/subsystem_news/runtime/artifact_store.py` + `tests/normalize/`；只读引用 `sources/`、`contracts/`
**写入边界**: 允许修改 `normalize/` 与 `runtime/artifact_store.py`；禁止写入 `dedupe/`（真正聚类逻辑在 ISSUE-006）；禁止引入 Docling 等重型文档解析依赖
**实现顺序**: (1) `strip_boilerplate(html) -> str`；(2) `clean_text` / `parse_published_at` / `detect_language`；(3) `fingerprint_seed(title, body) -> str`（SHA256 of normalized sentences）；(4) `normalize_article(raw) -> NewsArticleArtifact`；(5) `artifact_store.save/load`；(6) fixture（中/英文、RSS 摘要 vs 站点正文）+ 单测
**依赖**: #ISSUE-003（需 fetch 出的 raw 数据结构）

---

## 阶段 2：去重与实体解析协同

**目标**：实现 fingerprint/cluster 与实体 mention 抽取，接通 `entity-registry`，建立 unresolved 显式化路径。
**前置依赖**：阶段 1 完成

### ISSUE-005: dedupe 模块 — fingerprint 与 cluster
**labels**: P0, algorithm, milestone-2, ready
**摘要**: 在 artifact 之上实现强/弱两层去重：URL/hash 强去重 + 标题+核心句相似度弱去重，产出 `NewsDedupeCluster` 并记录 conflict trace。
**所属模块**: 主写入 `src/subsystem_news/dedupe/`（`fingerprint.py`、`cluster.py`、`conflict.py`、`store.py`）+ `tests/dedupe/` + `fixtures/repost_pairs/`；只读引用 `normalize/`、`contracts/cluster.py`
**写入边界**: 允许修改 `dedupe/` 与对应测试/fixture；禁止回改 `normalize/` 的 fingerprint seed（升级为 blocker）；禁止调用 `reasoner-runtime`（本阶段保持确定性算法）
**实现顺序**: (1) `article_fingerprint(artifact) -> str`（在 seed 之上做 minhash/shingle 家族）；(2) 强去重 `exact_match(artifact, store)`；(3) 弱去重 `cluster_candidates(artifact, store, threshold)` 采用 cosine/Jaccard；(4) `merge_into_cluster` + representative 选择（最早发布 + 最高 reliability）；(5) conflict trace（成员之间关键字段冲突）；(6) 精选转载夹具 ≥ 20 对，目标 precision ≥ 95%
**依赖**: #ISSUE-004（需 `NewsArticleArtifact`）

---

### ISSUE-006: entities 模块 — mention 抽取与 registry 协同
**labels**: P0, integration, milestone-2, ready
**摘要**: 实现 mention 发现、span 定位、确定性快路径（股票代码/正式名/标准简称 → `lookup_alias`），不确定/多候选/跨语言走 `resolve_mentions`，保留 unresolved。
**所属模块**: 主写入 `src/subsystem_news/entities/`（`mention.py`、`quick_path.py`、`resolver_client.py`、`fallback.py`）+ `tests/entities/`（含 fake registry）；只读引用 `contracts/candidates.InvolvedEntity`、`normalize/`
**写入边界**: 允许修改 `entities/` 与其测试；禁止在本模块维护 alias 真相表（违反 §5.4 与 §6 原则 4）；禁止在 resolution 失败时自造 canonical_id
**实现顺序**: (1) `EntityRegistryClient` 协议 + HTTP/stub 两实现；(2) `detect_mentions(article) -> list[Mention]`（正则 + 轻量 NER）；(3) quick path `lookup_alias`；(4) batch `resolve_mentions` + case recording；(5) 输出 `InvolvedEntity` 列表含 `resolution_status`；(6) 单测覆盖 unresolved explicit、ambiguous > 1 候选、跨语言别名
**依赖**: #ISSUE-004（需 artifact 正文与 span 偏移），可与 #ISSUE-005 并行但建议顺序执行以便 fixture 复用

---

## 阶段 3：Ex-1 / Ex-2 成型

**目标**：通过 `reasoner-runtime.generate_structured()` 产出稳定 `Ex-1` 事实与 `Ex-2` 信号，接通 `subsystem-sdk.submit()`，完成 pipeline 组装。
**前置依赖**：阶段 2 完成

### ISSUE-007: extract 模块 — Ex-1 事实抽取
**labels**: P0, model, milestone-3, ready
**摘要**: 基于 cluster representative + entities，通过 `reasoner-runtime.generate_structured()` 抽取 `NewsFactCandidate`（fact_type、summary、involved_entities、event_time、evidence_spans、confidence），拒绝无证据输出。
**所属模块**: 主写入 `src/subsystem_news/extract/`（`prompt.py`、`schema_pin.py`、`runtime_client.py`、`fact_extractor.py`）+ `tests/extract/`（含 fake runtime stub）；只读引用 `contracts/candidates.NewsFactCandidate`、`entities/`、`dedupe/`
**写入边界**: 允许修改 `extract/` 与其测试；禁止直连 provider SDK（必须通过 `ReasonerRuntimeClient` 抽象）；禁止修改 taxonomy 枚举（如需新增 fact_type 升级为合同变更 issue）
**实现顺序**: (1) `ReasonerRuntimeClient.generate_structured(request, schema)`；(2) prompt assembly + schema pin（含 version）；(3) `extract_facts(cluster) -> list[NewsFactCandidate]`；(4) evidence span 回填与 bounds 校验；(5) 拒绝输出路径（证据不足/实体全部 unresolved）；(6) 单测覆盖 happy path、证据缺失被拒、schema pin 版本回退
**依赖**: #ISSUE-005（cluster）, #ISSUE-006（entities）

---

### ISSUE-008: signals 模块 — Ex-2 信号生成
**labels**: P0, model, milestone-3, ready
**摘要**: 在 Ex-1 基础上决定是否提升为 `NewsSignalCandidate`，强制本模块完成 `direction`/`magnitude`/`impact_scope`/`time_horizon`，cluster 内不机械叠加同向信号。
**所属模块**: 主写入 `src/subsystem_news/signals/`（`promotion_rules.py`、`direction_judge.py`、`magnitude.py`、`aggregator.py`）+ `tests/signals/`；只读引用 `extract/`、`contracts/candidates.NewsSignalCandidate`
**写入边界**: 允许修改 `signals/` 与其测试；禁止把方向判断下放给下游/CEP（违反 §6 原则 4）；禁止复制 `extract/` prompt（复用 runtime client）
**实现顺序**: (1) promotion 规则（fact_type × reliability × evidence 强度）；(2) `judge_direction` via runtime structured call；(3) `estimate_magnitude` + `impact_scope` 分类；(4) cluster 去叠加（一个 cluster 最多 N 条同 signal_type）；(5) 拒绝低置信路径；(6) 单测含负样本（不应提升、不应叠加）
**依赖**: #ISSUE-007

---

### ISSUE-009: runtime 模块 — pipeline 组装与 submit
**labels**: P0, integration, milestone-3, ready
**摘要**: 串联 discover → ingest → normalize → dedupe → entities → extract → signals → submit；实现 `subsystem-sdk` 接入、batch submit、heartbeat、trace 落地。
**所属模块**: 主写入 `src/subsystem_news/runtime/`（`pipeline.py`、`submit.py`、`trace.py`、`orchestrator.py`、`cli.py`）+ `tests/runtime/`；只读引用所有上游子模块
**写入边界**: 允许修改 `runtime/` 与其测试；禁止在 pipeline 里内联实现业务语义（必须调用上游模块）；禁止引入 Kafka/Flink/Temporal
**实现顺序**: (1) `Pipeline.run(source_cursor)` 顶层循环；(2) `SubsystemSdkClient` 抽象 + submit batch；(3) 幂等与 trace；(4) CLI 入口 `python -m subsystem_news.runtime.cli ingest`；(5) 端到端 fixture 跑通（≥ 3 篇真实样例）；(6) submit 失败重试与错误上报
**依赖**: #ISSUE-008

---

## 阶段 4：高门槛 Ex-3 与回放

**目标**：在强证据关系场景下输出少量 `Ex-3`，建立 replay/regression 基线，固化 metrics。
**前置依赖**：阶段 3 完成

### ISSUE-010: graph 模块 — 高门槛 Ex-3 生成
**labels**: P1, model, milestone-4, ready
**摘要**: 仅在收购/合作/制裁/供应等明确关系表述下产出 `NewsGraphDeltaCandidate`，禁止共现/情绪推导；单独 review 样本集，误报率 ≤ 1%。
**所属模块**: 主写入 `src/subsystem_news/graph/`（`relation_extract.py`、`evidence_guard.py`、`candidate_builder.py`）+ `tests/graph/` + `fixtures/graph_positive/` + `fixtures/graph_negative/`；只读引用 `extract/`、`entities/`、`contracts/candidates.NewsGraphDeltaCandidate`
**写入边界**: 允许修改 `graph/` 与其测试/fixture；禁止在 `signals/` 中调用 graph（方向单向）；禁止直写 Neo4j
**实现顺序**: (1) relation prompt + schema pin（限定 `RelationType` 枚举）；(2) evidence guard（必须双边 canonical_id 解析成功 + 显式关系动词）；(3) `requires_manual_review` 策略；(4) 共现/情绪负样本集（≥ 30 条）；(5) FP rate 测量脚本；(6) 单测覆盖 positive + 强制拒绝负样本
**依赖**: #ISSUE-009

---

### ISSUE-011: fixtures + replay 与回归基线
**labels**: P1, testing, milestone-4, ready
**摘要**: 建立 fixtures 集合（单源、多源转载、模糊实体、明确关系、Ex-1-only、Ex-3 负样本）与 replay 脚本，跑 §19 指标基线并输出差异报告。
**所属模块**: 主写入 `src/subsystem_news/fixtures/` + `src/subsystem_news/runtime/replay.py` + `scripts/replay_diff.py` + `tests/regression/`；只读引用全链路模块
**写入边界**: 允许新增 fixture 与 replay 工具；禁止修改业务模块（发现问题必须回到对应 issue 修复，不得在 fixtures 内 patch）
**实现顺序**: (1) 六类 fixture 集合定义与样本准备；(2) `replay_article(article_id, version_pin)` 实现；(3) `replay_diff.py` 产差异报告（JSON + markdown 摘要）；(4) metrics runner：evidence coverage / dedupe precision / unresolved explicitness / Ex-3 FP；(5) 全量回归基线快照；(6) CI 友好退出码
**依赖**: #ISSUE-010

---

## 阶段 5：面向 Full 模式接口对齐

**目标**：固化 `Ex-2` 字段稳定性，验证未来 `stream-layer` 可直接消费；backend/provider 切换只在 `reasoner-runtime` 配置层发生。
**前置依赖**：阶段 4 完成

### ISSUE-012: Full 模式接口字段稳定性与 backend 切换验证
**labels**: P1, integration, milestone-5, ready
**摘要**: 编写 stream-layer 消费合约测试与 runtime backend 切换测试，验证 `Ex-2` 必填字段 / 序列化 / 向后兼容；任何 news 域代码无需改动即可切换 backend。
**所属模块**: 主写入 `tests/contract_stability/`、`src/subsystem_news/runtime/backend_config.py`、`docs/INTERFACE_STABILITY.md`；只读引用 `contracts/`、`extract/`、`signals/`
**写入边界**: 允许新增 `backend_config.py` 与接口稳定性测试；禁止修改已冻结的 Ex schema 字段命名（如需变更升级为合同变更 issue）；禁止在本 issue 引入 Kafka/Flink 实际实现
**实现顺序**: (1) golden JSON 合约样例（Ex-2 的 6 个版本样本）；(2) backend switch stub（两个 fake runtime backend，同 prompt 同输入）；(3) contract stability test：字段集合、枚举可选值、序列化兼容性；(4) 文档 `INTERFACE_STABILITY.md` 列出冻结字段清单；(5) §19 指标复跑验证无回退
**依赖**: #ISSUE-011
