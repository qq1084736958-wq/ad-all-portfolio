# AI 广告投放中台・实习作品集

> **AI 产品经理视角的广告代理业务智能化实践**
> 本仓库是实习期间参与项目的
>
> **脱敏展示版**
>
> ：客户名、账户信息、人名、内部链接均已匿名化。所有内容基于实习期间的业务实践整理，平台字段 / API / 规则以各平台官方文档为准。



***

## 我在做什么・一句话

> 在广告代理公司，把媒介策划（Media Planning）和平台广告创编（Campaign Setup）从
>
> **手工 Excel 作业**
>
> 升级为
>
> **表格驱动 + Agent 自动化**
>
> ，并沉淀成可复用的问题知识库与策略引擎。



***

## 仓库内容总览



| 目录 / 文件                                       | 内容                              | 价值点                                                  |
| --------------------------------------------- | ------------------------------- | ---------------------------------------------------- |
| **docs/ad-campaign-full-lifecycle.md**        | 广告投放全链路业务拆解（投前 / 投中 / 投后）       | 业务全景：从 Brief 到数据报告的 9 阶段、角色分工、决策依据、校验标准              |
| **docs/ad-campaign-infra-knowledge-base.md**  | 跨平台基础设施问题复盘（15 条）               | Agent 运行底座：代理架构、Token 授权体系、运行环境、AI 行为管控              |
| **docs/ad-campaign-meta-knowledge-base.md**   | Meta 平台广告创建问题复盘（68 条 + 10 条铁律）  | 平台 API 深度实践：认证 / 参数约束 / Partnership Ad / 版位素材 / 平台限制 |
| **docs/ad-campaign-google-knowledge-base.md** | Google 平台广告创建问题复盘（8 条）          | Google Ads / GDN / Demand Gen 实践，含 API 能力边界          |
| **docs/ad-campaign-tiktok-knowledge-base.md** | TikTok 平台广告创建问题复盘（10 条）         | Spark Ad 授权流程、API 端点、素材规格                            |
| **docs/amazon-dsp-campaign-creation.md**      | Amazon DSP（DVA）创编拆解及 Agent 解决方案 | 账户体系、手动 / 自动化双路径、字段级映射、新旧版对比（209 张截图）                |
| **docs/ad-media-plan-skill-design.md**        | ad-media-plan Skill 设计方案        | 下一代 Media Plan 策略生成 Skill 的产品设计                      |
| **docs/media-plan-strategy-flow.md**          | Media Plan 策略生成流程               | 投前策略生成：需求接入 → 维度拆解 → 数据检索 → 策略 / 预算 / KPI 计算         |
| **skills/media-planner/**                     | media-planner 技能包（可运行）          | 策略手册 + 确定性计算脚本 + Excel / Word 模板生成引擎                 |
| **assets/images/**                            | DSP 后台界面示意图（190 张）              | 创编全流程操作界面可视化                                         |
| **assets/whiteboards/**                       | 字段映射 / 流程拆解 / 投递逻辑白板（7 张）       | 多维表格字段对应关系、TikTok/DSP 投递逻辑                           |



***

## 项目叙事・我做了什么

### 背景：广告代理业务的 "手工之痛"

广告投放业务有两条最耗时、最易错的人工链路：



| 环节                       | 人工痛点                                                                                                |
| ------------------------ | --------------------------------------------------------------------------------------------------- |
| **媒介计划（Media Plan）**     | 客户 Brief → 人群分层 → 平台策略 → 预算分配 → 排期 → KPI 体系，每步都有大量计算与多轮确认，Excel 来回改                                 |
| **平台创编（Campaign Setup）** | 把 Media Plan 表格映射到 Meta / Google / TikTok / Amazon DSP 后台，手工逐层创建 Campaign / Ad Set / Ad，字段多、强关联、易出错 |

我的工作围绕这两条链路展开，完整经历了 **问题发现 → 方案设计 → 落地 → 复盘沉淀** 的闭环。

### 工作线一：广告创编 Agent・问题知识库建设（核心）

**背景**：团队已上线 AI 广告创编 Agent（9 位 Agent 并行运营，覆盖 Meta / Google / TikTok 三平台）。Agent 在 2026-05-20 至 2026-07-30 期间持续遇到各类创建问题，但问题散落在各 Agent 的日报里，没有统一沉淀 ——**同一个坑反复踩**。

**我做的事**：



1. **问题归集与结构化**：汇总 9 位 Agent 的问题记录，按平台（Meta / Google / TikTok）+ 跨平台基础设施两类归并去重，形成 **Meta 68 条、Google 8 条、TikTok 10 条、基础设施 15 条** 的结构化知识库；

2. **每条问题的标准结构**：来源 → 问题描述 → 请求方式 → 报错返回 → 是否解决 → 解决方案 → 差异总结 → 类型，确保**可回溯、可复用**；

3. **提炼 "铁律"**：从高频问题中沉淀 10 条创建前必读铁律（如 token 位置、destination\_type 显式传参、Creative 创建后不可改、≥2 张素材必用 asset\_feed\_spec、destructive 操作必须停下确认），把经验固化为**防错机制**；

4. **识别平台能力边界**：梳理 "平台产品级限制"（API 与 UI 能力不对等）—— 如 Google VIDEO Campaign 无法 API 创建、Meta 部分能力仅 UI 支持，为产品路线提供依据（哪些能自动化、哪些必须人工兜底）。

**体现的产品思维**：



* **问题闭环**：不是记录问题，而是 "归并 → 结构化 → 提炼规则 → 防复发"；

* **边界认知**：区分 "能解决的问题" 与 "平台硬限制"，不硬碰平台能力边界，而是设计人工兜底路径；

* **AI 行为管控**：沉淀 "删除 / 归档 / 暂停已投放广告必须停下确认，严禁 AI 自主决策" 等行为铁律 —— 这是 AI 产品安全设计的第一课。

### 工作线二：Amazon DSP 创编拆解与 Agent 解决方案

**背景**：DSP 广告创建链路复杂（Entity → Advertiser → Order → Line Item → Creative 五层结构），且平台正在**新旧版界面迁移**（Orders→Campaigns、Line items→Ad groups、Creatives→Ads），业务方急需一份完整的创编拆解。

**我做的事**：产出《亚马逊 DSP 创编拆解及 Agent 解决方案》（209 张截图全流程可视化）：



* **账户体系拆解**：五层结构、权限模型、"一个 Advertiser 关联一个店铺" 等关键约束；

* **双路径设计**：手动创建路径（后台逐步操作）与自动化路径（多维表格驱动 API），并明确各自适用场景（如 Audience 因规模审核问题倾向手动）；

* **字段级映射表**：六大板块（Creatives / Orders / Line / Audience / Order 调整 / Line 调整）逐字段对应 "填写方式 → 平台字段 → 官方 API 接口 → MP 表格字段"；

* **新旧版差异对照**：平台命名变动全景表 + 业务侧创建确认要点（强关联、预设范式、命名规则、预算逻辑等）。

**体现的产品思维**：**把 "后台经验" 翻译成 "结构化规则"**—— 表格到后台的映射、字段强关联、审核限制，全部沉淀为可执行规则，为 Agent 自动化奠定基础。

### 工作线三：Media Plan 策略生成 Skill

**背景**：Media Plan 是全链路起点，但完全依赖人工 —— 客户 Brief 进来后，从拆解到策略到排期全是 Excel 手工活。

**我做的事**：



1. **梳理 P0 主链路**：多来源输入解析 → 维度拆解与字段标准化 → 完整性 / 冲突检查 → 数据检索与证据评分 → 策略 / 预算 / KPI 计算 → 自检 → 表格交付；

2. **设计并实现 media-planner Skill**：策略层（`strategy-playbook.md`，LLM 判断）+ 计算层（`scripts/`，确定性算术）分离；预算守恒自动校验、树状排期、三级汇总自动回读；对客数字强制实时联网检索（URL + 日期 + 原文）；

3. **迭代演进**：新增新建 MP / 已有 MP 调整 / 单模块任务路由；字段状态 / 来源 / 置信度保护；生成前 Preflight；版本、审计包、风险与待确认项输出；

4. **真实 Brief 试跑验证**：用客户 Brief 试跑，验证字段提取、风险 Sheet、审计包和 Excel 输出，并**发现 "Skill 仍主要按 Meta 链路生成，Google 等平台没有完整执行计划" 的缺口** → 下一步是全平台泛化架构（通用 Media Plan 引擎 + 平台规则配置包）。

**体现的产品思维**：



* **怎么想与怎么算分离**：策略判断交给 LLM（可解释、可迭代），算术交给确定性代码（零幻觉）；

* **非线性的业务容忍度**：业务使用通常从任意环节介入，Skill 设计保证灵活性（参考开源项目架构）；

* **证据纪律**：对客数字必须有来源，缺证据标 `insufficient_evidence`——AI 产品对 "数字真实性" 的责任设计。

### 工作线四：广告投放全链路梳理

**背景**：广告投放的完整业务链（投前 / 投中 / 投后）此前没有一份全局文档，新人上手靠口口相传。

**我做的事**：梳理 9 阶段全链路（需求接入 → 客户确认 → 广告授权 → 新建广告 → 表格回填 → 修改广告 → 暂停广告 → 删除广告 → 监测广告 → 检查广告 → 数据报告），每阶段明确**角色、输入、动作 / 能力、依据 / 逻辑、数据来源、校验 / 标准、输出**。

**体现的产品思维**：**业务全局视图**—— 任何自动化方案都建立在对全链路的理解之上，知道每一环的决策依据和数据来源，才能设计合理的 Agent 能力边界。



***

## 方法论沉淀・我在实习中学到的



1. **先理解业务，再设计产品**：所有自动化方案都从 "业务全链路拆解" 开始，而不是直接写代码；

2. **问题知识库是 AI 产品的护城河**：Agent 的能力提升 = 平台知识（API 规则）+ 业务规则（命名 / 预算 / 排期）+ 防错铁律（行为管控）的持续积累；

3. **区分能力边界**：能自动化的（规则清晰、API 支持）优先自动化；平台硬限制（API≠UI）设计人工兜底；这是产品路线图的判断依据；

4. **策略与工具解耦**：判断（LLM）与计算（代码）分离，让 "能解释" 与 "算得准" 各司其职；

5. **AI 行为安全是产品设计的一部分**：destructive 操作必须停下确认、参数必须显式传递、创建前必须照抄在跑广告参数 ——AI 产品不是 "能做事" 而是 "可靠做事"；

6. **证据纪律**：对客数字必须有来源 URL、检索日期、原文摘录；缺证据就标注，不凭记忆写数。



***

## 快速上手

### 浏览文档



```
# 从全链路业务图开始，理解业务全景
docs/ad-campaign-full-lifecycle.md

# 然后按平台看问题知识库（体现 Agent 能力积累）
docs/ad-campaign-meta-knowledge-base.md
docs/ad-campaign-infra-knowledge-base.md

# 再看 DSP 创编拆解（209 张截图全流程）
docs/amazon-dsp-campaign-creation.md

# 最后看 Media Plan 策略生成（从策略到落地）
docs/media-plan-strategy-flow.md
docs/ad-media-plan-skill-design.md
```

### 运行 media-planner Skill



```
cd skills/media-planner
pip install -r requirements.txt
python scripts/selfcheck.py              # 环境自检，全绿再开始

# 生成 Media Plan Excel
python scripts/generate_mediaplan.py \
  --data /path/to/data.json \
  --out /path/to/output.xlsx \
  --template references/MediaPlan_Template_Standard.xlsx
```

策略判断走 `references/strategy-playbook.md`（LLM 决策），算术与 Excel 生成走 `scripts/`（确定性代码），两部分解耦。



***

## 免责声明



* 本仓库为**脱敏展示版**：客户名、账户 ID、人名、内部链接均已匿名化；

* 问题知识库中的**报错码、API 端点、参数规则**为平台真实实践记录，但请以各平台官方文档为准；

* 截图来自脱敏后的操作界面示意图，仅用于说明流程；

* 文中涉及的 "客户 A\~J" 等代号均为匿名映射，不指向任何真实品牌。