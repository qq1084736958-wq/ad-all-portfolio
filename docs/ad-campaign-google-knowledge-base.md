# Google 平台广告创建问题汇总（复盘技术文档）

> **整理说明**：本文档汇总 9 位 Agent（AA / CC / HY / JYY / KK / MM / RL / YY / ZM）在 **Google Ads / GDN / Demand Gen** 广告创建过程中遇到的问题。已归并去重，保留各来源方案与差异。**统计范围**：2026-05-20 \~ 2026-07-30**安全声明**：本文档仅做问题汇总与复盘，未执行任何广告操作。

---

## 一、问题概览统计

| 分类 | 问题数 | 已解决 | 未解决 / 无 API 解法 |
|-|-|-|-|
| 认证 / OAuth / 权限 | 3 | 2 | 1 |
| Campaign 类型限制（API≠UI） | 2 | 0 | 2 |
| 素材 / 资源约束 | 2 | 2 | 0 |
| 数据源 / Sheet 权限 | 1 | 1 | 0 |
| **合计（归并后）** | **约 8 条** | 多数已解决 | VIDEO Campaign 无 API 解法 |

> Google 平台问题总量远小于 Meta。核心难点集中在 **VIDEO/YouTube Campaign 无法通过 API 创建**（Google Ads API 硬限制），需改用 Demand Gen 或 UI 手动。

---

## 二、认证 / OAuth / 权限类

### G1. Google Ads API OAuth 授权失效 / 刷新

| 项目 | 内容 |
|-|-|
| **来源** | JYY(#15)、YY(#25)、RL(#13) |
| **问题描述** | Google Ads API OAuth token（[授权账号] 授权）过期或失效，无法调用 API |
| **请求方式** | Google Ads API（google-ads CLI / API client） |
| **报错返回** | `AuthenticationError` / `invalid_grant` / OAuth token expired |
| **是否解决** | ✅ |
| **解决方案** | 通过授权账号 [授权账号] 重新走 OAuth 流程刷新 refresh_token；确认 developer_token + client_id + client_secret + refresh_token 四要素齐全 |
| **类型** | OAuth / 授权 |

### G2. Sheet 数据源 403（服务账号无权限）

| 项目 | 内容 |
|-|-|
| **来源** | MM(#16)、YY(#26)、CC(#31) |
| **问题描述** | 读取投放计划 Google Sheet 时返回 403，服务账号 / 授权账号无该表访问权限 |
| **请求方式** | Google Sheets API `GET /v4/spreadsheets/{id}/values/...` |
| **报错返回** | `HTTP 403 The caller does not have permission` |
| **是否解决** | ✅ |
| **解决方案** | 将数据拉取所用账号 `[邮箱]`（或对应服务账号邮箱）加为该 Sheet 的协作者（至少查看权限）后恢复 |
| **类型** | 数据源权限 |

### G3. Demand Gen Campaign CID 权限 / 账户层级

| 项目 | 内容 |
|-|-|
| **来源** | YY(#27)、RL(#14) |
| **问题描述** | 在 Demand Gen Campaign（CID ）下创建广告时，账户层级 / MCC 关联权限不足 |
| **请求方式** | Google Ads API（Demand Gen campaign 创建） |
| **报错返回** | 权限 / 账户层级错误 |
| **是否解决** | ✅（确认 CID 后正常）/ 部分 |
| **解决方案** | 确认操作 CID 正确、MCC 下已关联该客户账户、login-customer-id 头正确设置 |
| **类型** | 权限 / 账户配置 |

---

## 三、Campaign 类型限制（API 与 UI 能力不对等）

### G4. VIDEO / YouTube Campaign 无法通过 API 创建（MUTATE_NOT_ALLOWED）

| 项目 | 内容 |
|-|-|
| **来源** | AA(#11)、YY(#24)、RL(#15)、CC(#32) |
| **问题描述** | 尝试通过 Google Ads API 创建 VIDEO（YouTube）类型 Campaign 被拒 |
| **请求方式** | Google Ads API `CampaignService.MutateCampaigns`（advertising_channel_type=VIDEO） |
| **报错返回** | `MUTATE_NOT_ALLOWED` / `CampaignError.CANNOT_CREATE_CAMPAIGN_OF_TYPE` |
| **是否解决** | ❌（Google Ads API 硬限制，无 API 解法） |
| **解决方案** | ①VIDEO Campaign 只能通过 Google Ads UI 手动创建；②改用 **Demand Gen Campaign**（支持 API 创建，可投 YouTube 版位）作为替代方案 |
| **类型** | 平台产品级限制 |

### G5. GDN Campaign 素材 / 资源组约束

| 项目 | 内容 |
|-|-|
| **来源** | AA(#12)、YY(#28)、CC(#33) |
| **问题描述** | GDN（账户 ）Campaign 创建时，响应式展示广告的图片 / 标题 / 描述资源数量或规格不满足要求 |
| **请求方式** | Google Ads API（AssetService / AdGroupAd 创建） |
| **报错返回** | 资源数量不足 / 图片规格不符（如缺少横版 landscape / 方形 square logo） |
| **是否解决** | ✅ |
| **解决方案** | 按响应式展示广告要求补齐资源：≥1 张 landscape(1.91:1) + ≥1 张 square(1:1) 营销图、≥1 个 landscape logo + ≥1 个 square logo、≥1\~5 条短标题、1 条长标题、≥1\~5 条描述；图片先上传为 Asset 再引用 |
| **类型** | 素材 / 资源约束 |

---

## 四、其他

### G6. Demand Gen 广告格式 / 版位映射

| 项目 | 内容 |
|-|-|
| **来源** | RL(#16)、YY(#29) |
| **问题描述** | Demand Gen Campaign 下广告格式（图片 / 视频 / 轮播）与目标版位（YouTube / Discover / Gmail）映射配置不当 |
| **请求方式** | Google Ads API（Demand Gen ad 创建） |
| **报错返回** | 格式 / 版位不匹配 |
| **是否解决** | ✅ |
| **解决方案** | 按 Demand Gen 规范配置 asset group，确保每种格式所需资源齐全；作为 VIDEO Campaign 的 API 替代路径时，用 Demand Gen 承载 YouTube 版位投放 |
| **类型** | 参数配置 |

---

> 本文档由 9 份 Agent 汇总归并而成，来源标注采用 `Agent(编号)` 格式便于回溯原文。如需某条问题的完整原始描述，可按来源标注查阅对应 Agent 的原始文档。