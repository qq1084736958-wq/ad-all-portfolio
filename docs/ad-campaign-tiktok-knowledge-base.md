# TikTok 平台广告创建问题汇总（复盘技术文档）

> **整理说明**：本文档汇总 9 位 Agent（AA / CC / HY / JYY / KK / MM / RL / YY / ZM）在 **TikTok Ads** 广告创建过程中遇到的问题。已归并去重，保留各来源方案与差异。**统计范围**：2026-05-20 \~ 2026-07-30**主要涉及账户**：TikTok ZA（）及其他海外市场账户**安全声明**：本文档仅做问题汇总与复盘，未执行任何广告操作。

---

## 一、问题概览统计

| 分类 | 问题数 | 已解决 | 未解决 |
|-|-|-|-|
| 认证 / 代理 / Token | 2 | 2 | 0 |
| Spark Ad / 授权 | 3 | 3 | 0 |
| Campaign / Ad Group 参数 | 3 | 3 | 0 |
| 素材 / 视频约束 | 2 | 2 | 0 |
| **合计（归并后）** | **约 10 条** | 多数已解决 | — |

> TikTok 问题核心在 **Spark Ad 授权流程**（需先调 authorize 接口拿授权码）和 **API 版本 / 端点路径**（/open_api/v1.3/）。

---

## 二、认证 / 代理 / Token 类

### T1. TikTok API 需走代理域名

| 项目 | 内容 |
|-|-|
| **来源** | ZM(#11)、KK(T-01)、YY(#31) |
| **问题描述** | TikTok Marketing API 调用需通过 代理层域名，直连官方域名 token 无效 |
| **请求方式** | `POST /open_api/v1.3/...`（需走代理） |
| **报错返回** | token 无效 / 鉴权失败 |
| **是否解决** | ✅ |
| **解决方案** | 所有 TikTok API 调用走 TikTok 代理层域名（`[TikTok代理域名]` 类），Access-Token 放请求头 `Access-Token`；与 Meta 同理不直连官方 |
| **类型** | 代理架构 |

### T2. TikTok Access-Token 位置 / 有效期

| 项目 | 内容 |
|-|-|
| **来源** | KK(T-02)、CC(#28) |
| **问题描述** | Access-Token 放错位置（body 而非 header）或 token 过期 |
| **请求方式** | `POST /open_api/v1.3/ad/create/` |
| **报错返回** | `code 40105 / 40100` 鉴权错误 |
| **是否解决** | ✅ |
| **解决方案** | TikTok Access-Token 必须放 HTTP Header `Access-Token`，不放 body；过期通过 [代理工具] 重新拉取 |
| **类型** | 认证机制 |

---

## 三、Spark Ad / 授权类

### T3. Spark Ad 需先调 tt_video/authorize 获取授权

| 项目 | 内容 |
|-|-|
| **来源** | ZM(#12)、KK(T-03)、CC(#29)、YY(隐含) |
| **问题描述** | 创建 Spark Ad（原生帖推广）时直接引用视频 ID 失败，缺少授权步骤 |
| **请求方式** | `POST /open_api/v1.3/ad/create/`（直接引用 tiktok item id） |
| **报错返回** | 视频未授权 / item 不可用 |
| **是否解决** | ✅ |
| **解决方案** | Spark Ad 创建前必须先调 `POST /open_api/v1.3/tt_video/authorize/` 提交授权码（creator 提供的 auth code），获取 item_id 后再创建广告 |
| **类型** | Spark Ad 授权流程 |

### T4. Spark Ad 授权码 / creator 授权失效

| 项目 | 内容 |
|-|-|
| **来源** | ZM(#13)、CC(#30) |
| **问题描述** | creator 提供的 Spark Ad 授权码过期或权限不足 |
| **请求方式** | `POST /open_api/v1.3/tt_video/authorize/` |
| **报错返回** | 授权码无效 / 过期 |
| **是否解决** | ✅ |
| **解决方案** | 联系 creator 在 TikTok App 内重新生成授权码（Video 授权有效期有限），重新提交 authorize 接口 |
| **类型** | 外部依赖 / 授权 |

### T5. identity_type / identity_id 配置

| 项目 | 内容 |
|-|-|
| **来源** | KK(T-04)、ZM(#14) |
| **问题描述** | 创建广告时 identity_type / identity_id 配置错误，导致投放主体不对 |
| **请求方式** | `POST /open_api/v1.3/ad/create/`（identity 字段） |
| **报错返回** | identity 无效 / 主体不匹配 |
| **是否解决** | ✅ |
| **解决方案** | Spark Ad 用 `identity_type=TT_USER` + creator 的 identity_id；自有帖用 `CUSTOMIZED_USER`（BC 授权的商业账号）。先调 `/identity/get/` 查可用 identity 列表 |
| **类型** | 参数配置 |

---

## 四、Campaign / Ad Group 参数类

### T6. Campaign objective_type 与 Ad Group 优化目标不匹配

| 项目 | 内容 |
|-|-|
| **来源** | ZM(#15)、YY(隐含) |
| **问题描述** | Campaign 的 objective_type 与 Ad Group 的 optimization_goal 组合不合法 |
| **请求方式** | `POST /open_api/v1.3/adgroup/create/` |
| **报错返回** | objective 与 optimization_goal 组合非法 |
| **是否解决** | ✅ |
| **解决方案** | 按 TikTok 组合规则：TRAFFIC→CLICK；VIDEO_VIEWS→ENGAGED_VIEW；REACH→REACH；创建前查 objective_type 支持的 optimization_goal 列表 |
| **类型** | 参数规范 |

### T7. 预算 / 出价字段约束（最低预算）

| 项目 | 内容 |
|-|-|
| **来源** | ZM(#16)、KK(隐含) |
| **问题描述** | Ad Group 预算低于账户币种最低预算要求 |
| **请求方式** | `POST /open_api/v1.3/adgroup/create/`（budget 字段） |
| **报错返回** | 预算低于最低要求 |
| **是否解决** | ✅ |
| **解决方案** | 按账户币种设置 ≥ 最低日预算（多数市场约 \$20/天或等值）；budget_mode 与 budget 配套设置 |
| **类型** | 参数约束 |

### T8. 定向 / 版位参数

| 项目 | 内容 |
|-|-|
| **来源** | ZM(#17)、AA(隐含) |
| **问题描述** | 地域 / 版位定向参数格式不符 |
| **请求方式** | `POST /open_api/v1.3/adgroup/create/`（location_ids / placement） |
| **报错返回** | 定向参数无效 |
| **是否解决** | ✅ |
| **解决方案** | location_ids 需用 TikTok 地域编码（先调 `/tool/region/` 查询）；placement_type=PLACEMENT_TYPE_NORMAL 时需指定 placements=[PLACEMENT_TIKTOK] |
| **类型** | 参数格式 |

---

## 五、素材 / 视频约束类

### T9. 视频素材需先上传获取 video_id

| 项目 | 内容 |
|-|-|
| **来源** | ZM(#18)、CC(隐含) |
| **问题描述** | 创建广告时直接引用本地视频失败，缺少上传步骤 |
| **请求方式** | `POST /open_api/v1.3/ad/create/`（video_id） |
| **报错返回** | video_id 无效 |
| **是否解决** | ✅ |
| **解决方案** | 先调 `POST /open_api/v1.3/file/video/ad/upload/` 上传视频获取 video_id，再引用；封面图用 `/file/image/ad/upload/` |
| **类型** | 素材上传流程 |

### T10. 视频规格 / 时长不符

| 项目 | 内容 |
|-|-|
| **来源** | ZM(#19)、YY(隐含) |
| **问题描述** | 视频分辨率 / 宽高比 / 时长不符合 TikTok 广告要求 |
| **请求方式** | 上传 / 创建阶段 |
| **报错返回** | 视频规格校验失败 |
| **是否解决** | ✅ |
| **解决方案** | 按 TikTok 要求：竖版 9:16 优先，分辨率 ≥ 540×960，时长 5\~60s，码率 ≥ 516kbps；不符则转码后重传 |
| **类型** | 素材规格 |

---

> 本文档由 9 份 Agent 汇总归并而成，来源标注采用 `Agent(编号)` 格式便于回溯原文。部分标注"隐含"表示该 Agent 文档提及相关场景但未独立编号。如需完整原始描述，可按来源标注查阅对应 Agent 的原始文档。