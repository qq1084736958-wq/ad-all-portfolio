# Meta 平台广告创建问题汇总（复盘技术文档）

> **整理说明**：本文档汇总 9 位 Agent（AA / CC / HY / JYY / KK / MM / RL / YY / ZM）自 AI 创编启用至 2026-07-30 期间，在 **Meta 平台**广告创建过程中遇到的全部问题。已对重复问题做归并，并保留各来源的不同解决方案与差异总结。**统计范围**：2026-05-20 \~ 2026-07-30**涉及账户（各 Agent）**：KH / KE / TZ / PK / EG / MH-客户H 各国 / AMZ_Ecom_客户F_EU / 客户F DTC US / 客户A各账户 / 客户G-KZ 等**安全声明**：本文档仅做问题汇总与复盘，未执行任何广告操作。

---

## 一、问题概览统计

| 分类 | 问题数 | 已解决 | 未解决 / 部分解决 |
|-|-|-|-|
| 认证 / 代理 / Token | 8 | 6 | 2 |
| Ad Set 参数约束 | 12 | 12 | 0 |
| destination_type 专题 | 1（合并） | 1 | 0 |
| Ad / Creative 参数 | 7 | 7 | 0 |
| Partnership Ad（合创广告） | 14 | 11 | 3 |
| asset_feed_spec / 版位素材 | 7 | 5 | 2 |
| 预算 / 出价、设备定向、文案 | 9 | 9 | 0 |
| 平台产品级限制（API≠UI） | 8 | 3 | 5 |
| 流程 / AI 行为管控 | 3 | 3 | 0 |
| **合计（归并后）** | **68 条（M1\~M68）** | 多数已解决 | 平台产品级限制类多为无解 |

> 说明：因 9 份文档口径不同，上表为归并后的**主题分类**统计。未解决问题集中在「平台产品级限制」（API 与 UI 能力不对等，需 UI 手动创建）与「Token 单点授权 / IG 权限 scope / 内容合规」类。正文各条含：来源、问题描述、请求方式、报错返回、是否解决、解决方案、差异总结、类型。

---

> 正文（M1\~M68）与关键铁律沉淀见下方分章节内容。

## 二、认证 / 代理 / Token 类

### M1. 代理层 token 直连 graph.facebook.com 报 token 畸形（code 190）

| 项目 | 内容 |
|-|-|
| **来源** | HY(1.1)、RL(#12)、YY(隐含) |
| **问题描述** | 使用 内部代理层 发放的 token 直连 Meta 官方域名 graph.facebook.com 调用 API，报 token 畸形 |
| **请求方式** | `GET/POST https://graph.facebook.com/v21.0/act_{id}/...?access_token=xxx`（直连官方域名） |
| **报错返回** | `{"error":{"code":190,"message":"Malformed access token"}}` |
| **是否解决** | ✅ |
| **解决方案** | 所有 Meta API 调用必须走代理域名 `[Meta代理域名]`，不可直连 Meta 官方。代理层 token 仅在代理网关后有效 |
| **类型** | API 接口 / 环境配置（代理架构） |

### M2. POST 请求 token 放 body 被代理拒绝（40100 / 401）

| 项目 | 内容 |
|-|-|
| **来源** | HY(1.2)、CC(#20、#21)、KK(M-12)、JYY(#14)、YY(#30)、ZM(#4)、RL(隐含) |
| **问题描述** | 通过代理调用 Meta API 时，将 access_token 放在 POST request body 中导致鉴权失败 |
| **请求方式** | `POST /v25.0/act_{id}/...`，token 放在 request body |
| **报错返回** | `HTTP 401 {"code":40100,"message":"token失效"}` |
| **是否解决** | ✅ |
| **解决方案（铁则）** | access_token **必须**放 URL query string（`?access_token=xxx`），严禁放 POST body。body 只放业务字段 |
| **差异总结** | CC(#21) 额外记录了一个"误判"过程：初期以为是 OAuth 读写权限分离（GET 正常 POST 被拒），排查后确认真正根因是 token 放错位置（#20）。提醒：遇 GET 通 POST 不通，先查 token 位置再怀疑权限 |
| **类型** | 代理层机制规范 |

### M3. 内部代理层 Token 有效期短（约 3 天）需反复刷新

| 项目 | 内容 |
|-|-|
| **来源** | KK(M-07) |
| **问题描述** | 内部代理平台 [代理工具] 拉取的代理 token 有效期仅约 3 天，过期后所有广告操作中断 |
| **请求方式** | 通过代理域名请求 |
| **报错返回** | 代理返回 token 无效 / 过期 |
| **是否解决** | ✅（每次手动刷新）/ ❌（根本机制未优化） |
| **解决方案** | 执行 `[代理工具] project account-token` 重新拉取 token 写入 ad_tokens.json。根因：代理层 token 续期机制未针对 AI 7×24 场景优化，当前需人工触发刷新 |
| **类型** | 授权机制限制 |

### M4. Token 全失效 —— 授权人个人 Meta 账号被封（code 190 subcode 464）

| 项目 | 内容 |
|-|-|
| **来源** | JYY(#6)、YY(#9)、KK(M-06)、MM(#5) |
| **问题描述** | 授权人（授权管理员 / 授权管理员 老师 / 授权管理员等）Meta 个人账号被封或密码变更，导致通过其身份签发的所有广告账户 token 失效 |
| **请求方式** | 所有 Meta API 调用 |
| **报错返回** | `Error 190, subcode 464` — "Sessions for the user are not allowed because the user is not a confirmed user" / `OAuthException` |
| **是否解决** | ✅（换号 / 重新授权恢复）；MM 的 AMZ EU 账户 ❌ 反复出现（授权管理员账号问题未彻底解决） |
| **解决方案** | ①BM 中其他管理员重新为广告账户授权签发新 token；②KK 案例：内部代理平台移除原账号→绑定新账号（欢乐 user）→token 恢复 |
| **差异总结** | 影响范围：JYY 记录 7/11 客户A全部 6 账户失效持续到 7/14；KK 记录 PK 账户 7/12\~7/13 换号恢复；MM 记录 AMZ EU 属长期反复问题，截至 7/30 仍需人工授权。**共性根因：Token 依赖单一授权人，构成系统级单点故障** |
| **类型** | 权限 / Token（账号封禁） |

### M5. Token 写权限失效（GET 可用 POST 401）

| 项目 | 内容 |
|-|-|
| **来源** | JYY(#7)、YY(#10) |
| **问题描述** | Token 读权限正常（GET 可用）但写权限过期，代理层返回 401 拒绝 POST 操作 |
| **请求方式** | `POST`（Campaign / AdSet / Ad 创建） |
| **报错返回** | HTTP 401，code 40100 |
| **是否解决** | ✅（每次重新授权刷新恢复） |
| **解决方案** | 联系授权人（授权管理员 / 授权管理员）对相应账户重新授权刷新 token |
| **差异总结** | YY 记录了完整时间线：7/11 全员失效→7/14 恢复；7/17 HQ_GS→授权管理员刷新；7/23 HQ_GS→授权管理员刷新；7/27 EMEA_Social 恢复、NBD+HQ_Social 待刷新。**注意与 M2 区分**：若 token 位置正确仍 401，才是写权限失效；否则先查 M2 |
| **类型** | Token / 授权 |

### M6. Token 对特定 Page 无权限（subcode 1341012）

| 项目 | 内容 |
|-|-|
| **来源** | YY(#11)、JYY(#5)、MM(#9) |
| **问题描述** | Token 对广告使用的 Page 无权限，Creative / 帖子型广告创建失败 |
| **请求方式** | `POST /{ad_account_id}/adcreatives`（指定 page_id）或 `POST /act_{id}/ads`（object_story_spec 建帖） |
| **报错返回** | `error_subcode: 1341012` "No permission to access this profile" / "To create posts for Page {id}, contact an admin to get permission" |
| **是否解决** | ✅ |
| **解决方案** | 在 Meta Business Manager 中将 Page 关联给对应广告账户，或给授权用户赋予该 Page 的 ADVERTISE / Create Ads / pages_manage_posts 权限，之后刷新 token 恢复 |
| **差异总结** | JYY(#5)：同事 DE/FR/IT Product Collection（Page ）；YY(#11)：刷新 token 恢复；MM(#9)：客户F US Page（），同事修在 BM 加授权。三者根因一致（Page 未授权），修复路径一致（BM 绑定 + 刷新 token） |
| **类型** | 权限 / BM 配置 |

### M7. Token 缺少 Instagram 权限（instagram_basic / instagram_content_publish）

| 项目 | 内容 |
|-|-|
| **来源** | MM(#6)、KK(M-05)、CC(#17) |
| **问题描述** | Token scope 缺少 IG 权限，无法推广 IG 已发帖子 / 无法验证 Partnership adcode 对应 IG 帖子 / 无法获取 IG media 列表 |
| **请求方式** | `GET /{ig_user_id}/media` / `POST /act_{id}/adcreatives`（Partnership Ad） / `GET /{ig_media_id}?fields=...` |
| **报错返回** | "Instagram media not found" / `"Ad Incomplete"` (error 2446391) / `GraphMethodException code 100 subcode 33` |
| **是否解决** | KK(M-05) ✅（7/13 换绑新 Meta 账号后获得权限）；MM(#6) ❌（授权管理员账号问题未解，scope 仍不足）；CC(#17) ❌（App 未过 instagram_basic 审核） |
| **解决方案** | 授权时勾选 `instagram_basic` + `instagram_content_publish` scope。短期走 partnership_ad_code 路径绕过（不依赖 IG media 直查） |
| **差异总结** | 同一类权限缺失在不同账户下解决程度不同：换绑有权限的号可立即恢复（KK）；依赖问题账号则长期无解（MM）；App 级 scope 未审核则需走审核流程（CC）。**优先方案：换用已授权 IG 权限的 token；兜底：partnership_ad_code 路径** |
| **类型** | 权限 / Scope 不足 |

### M8. API Key 轮换 / 配置填错导致短暂服务中断

| 项目 | 内容 |
|-|-|
| **来源** | CC(#37) |
| **问题描述** | 轮换 BlueAI API Key 时配置信息填错，导致 AI 服务短暂中断 |
| **请求方式** | N/A（平台配置层面） |
| **报错返回** | 服务端配置错误 |
| **是否解决** | ✅ |
| **解决方案** | 平台管理员重新配置并重启后恢复 |
| **类型** | Token / 授权（配置） |

---

## 三、Ad Set 参数约束类

### M9. saved_audience_id 直接传入报权限错误（#10）

| 项目 | 内容 |
|-|-|
| **来源** | CC(#1)、HY(2.2)、KK(M-09)、AA(隐含) |
| **问题描述** | 创建 Ad Set 时直接传入 `saved_audience_id` 参数，API 返回权限错误 |
| **请求方式** | `POST /act_{id}/adsets` body 含 `saved_audience_id=xxx` |
| **报错返回** | `{"error_code":10,"message":"Application does not have permission for this action"}` / `#10 permission error` |
| **是否解决** | ✅ |
| **解决方案** | Meta API 设计不支持直传 saved_audience_id。正确做法（先读后写）：先 `GET /{saved_audience_id}?fields=targeting` 获取完整定向，再将 targeting 作为参数传入创建接口 |
| **类型** | API 接口约束 |

### M10. Saved Audience 无法通过 API 创建 / 修改

| 项目 | 内容 |
|-|-|
| **来源** | CC(#6 修改、#13 创建) |
| **问题描述** | 尝试通过 API 修改已保存的受众包，或在 TZ 账户创建 Saved Audience，均报能力限制 |
| **请求方式** | `POST /{saved_audience_id}`（改） / `POST /act_{id}/saved_audiences`（建） |
| **报错返回** | `{"error_code":3,"message":"Application does not have the capability"}` |
| **是否解决** | ✅（绕过） |
| **解决方案** | API 不支持创建 / 修改 Saved Audience。设备定向等更新直接写在 Ad Set 的 targeting 字段中，不创建 / 不修改独立 Saved Audience |
| **类型** | 权限 / 能力缺失 |

### M11. THRUPLAY Ad Set 缺 destination_type 报"website URL 为必填"

| 项目 | 内容 |
|-|-|
| **来源** | CC(#2)、HY(2.3) |
| **问题描述** | 创建 THRUPLAY optimization 的 Ad Set 时未传 destination_type，报要求 website URL |
| **请求方式** | `POST /act_{id}/adsets` optimization_goal=THRUPLAY，未传 destination_type |
| **报错返回** | `"website URL 为必填信息"` / error_subcode 2490408 |
| **是否解决** | ✅ |
| **解决方案** | 必须显式传 `destination_type=ON_VIDEO`。完整组合：optimization_goal=THRUPLAY + billing_event=THRUPLAY + destination_type=ON_VIDEO（详见 destination_type 专题 M-D） |
| **类型** | API 参数约束 |

### M12. POST_ENGAGEMENT 直接创建 Ad Set 报"成效目标不可用"

| 项目 | 内容 |
|-|-|
| **来源** | CC(#5、#8)、HY(2.1) |
| **问题描述** | 在 OUTCOME_ENGAGEMENT campaign 下直接创建 optimization_goal=POST_ENGAGEMENT 的 Ad Set 报错；或未传 destination_type 报"缺少追踪 Pixel" |
| **请求方式** | `POST /act_{id}/adsets` optimization_goal=POST_ENGAGEMENT |
| **报错返回** | `error_subcode 2490408 "成效目标不可用"` / "缺少追踪 Pixel 像素代码"（系统误判需外链+Pixel） |
| **是否解决** | ✅ |
| **解决方案** | 两条路径：①传 `destination_type=ON_POST`（CC#8、HY 推荐）；②用 Ad Set Copy API `POST /{source_adset_id}/copies` 从已有 adset 复制保留设置（CC#5、HY 2.1） |
| **差异总结** | HY 首选复制法（2.1），CC 同时给了复制法（#5）和 ON_POST 法（#8）。**推荐 ON_POST 直建法更简单，复制法用于复杂配置照抄场景** |
| **类型** | API 接口约束 |

### M13. Lifetime Budget 未设 end_time 报错

| 项目 | 内容 |
|-|-|
| **来源** | CC(#4)、HY(2.8) |
| **问题描述** | 使用 lifetime_budget 的 Campaign 下创建 Ad Set 不设 end_time 报错 |
| **请求方式** | `POST /act_{id}/adsets` 含 lifetime_budget 但无 end_time |
| **报错返回** | 必须设置 end_time |
| **是否解决** | ✅ |
| **解决方案** | end_time 必须设置，且 ≥ start_time + 24 小时 |
| **类型** | API 参数约束 |

### M14. IG explore_home 版位未同时选 explore

| 项目 | 内容 |
|-|-|
| **来源** | CC(#3)、HY(2.9)、KK(M-10) |
| **问题描述** | Instagram 版位选择 explore_home 但未选 explore，API 校验失败 |
| **请求方式** | `POST /act_{id}/adsets` instagram_positions 含 explore_home 但不含 explore |
| **报错返回** | 版位组合校验错误 |
| **是否解决** | ✅ |
| **解决方案** | instagram_positions 中包含 explore_home 时必须同时包含 explore |
| **类型** | API 参数约束 |

### M15. Facebook 已废弃版位（video_feeds / reels）报错

| 项目 | 内容 |
|-|-|
| **来源** | HY(2.10) |
| **问题描述** | facebook_positions 含已废弃版位导致版位无效 |
| **请求方式** | `POST /act_{id}/adsets` facebook_positions 含 video_feeds 或 reels |
| **报错返回** | 版位无效 |
| **是否解决** | ✅ |
| **解决方案** | video_feeds 已废弃移除；facebook reels → `facebook_reels`；instagram reels 仍用 `reels` |
| **类型** | API 版本变更 |

### M16. CBO 模式 Ad Set 传 bid_strategy 报错（error 1815857）

| 项目 | 内容 |
|-|-|
| **来源** | KK(M-08) |
| **问题描述** | CBO 模式下 Ad Set 层传入 bid_strategy 字段导致创建失败 |
| **请求方式** | `POST /act_{id}/adsets` body 含 bid_strategy |
| **报错返回** | `Error code 1815857` |
| **是否解决** | ✅ |
| **解决方案** | CBO 模式下 bid_strategy 和 budget 只能在 Campaign 层设置，Ad Set 层不可传 bid_strategy（移除该字段即可） |
| **类型** | 参数规范 |

### M17. Traffic Ad Set optimization_goal 与 billing_event 组合不合法（error 1870197）

| 项目 | 内容 |
|-|-|
| **来源** | KK(M-01) |
| **问题描述** | 批量创建 Y500 Preorder 时，Traffic 目标 Ad Set 创建失败 |
| **请求方式** | `POST /act_{id}/adsets` |
| **报错返回** | `Error code 1870197` — optimization_goal 与 billing_event 组合不合法 |
| **是否解决** | ✅ |
| **解决方案** | Traffic 目标 Ad Set：optimization_goal=LINK_CLICKS + billing_event=IMPRESSIONS |
| **类型** | 参数规范 |

### M18. VideoView Campaign objective 误用 OUTCOME_AWARENESS（error 2490408）

| 项目 | 内容 |
|-|-|
| **来源** | CC(#24) |
| **问题描述** | 创建 VideoView 类 Ad Set 时，Campaign objective 用了 OUTCOME_AWARENESS 导致 THRUPLAY 不可用 |
| **请求方式** | `POST /act_{id}/campaigns` objective=OUTCOME_AWARENESS + Ad Set optimization_goal=THRUPLAY |
| **报错返回** | error 2490408 "成效目标不可用" |
| **是否解决** | ✅ |
| **解决方案** | VideoView Campaign objective 必须是 `OUTCOME_ENGAGEMENT`（非 OUTCOME_AWARENESS）。完整组合：OUTCOME_ENGAGEMENT + THRUPLAY + billing=THRUPLAY + destination_type=ON_VIDEO |
| **类型** | API 接口约束 |

### M19. Reach 目标 Ad Set 设 promoted_object.page_id 报 Invalid parameter

| 项目 | 内容 |
|-|-|
| **来源** | KK(M-13) |
| **问题描述** | 尝试通过 Ad Set 层 promoted_object 为 Awareness/Reach Campaign 关联 Page |
| **请求方式** | `POST /act_{id}/adsets` 含 promoted_object.page_id |
| **报错返回** | "Invalid parameter" |
| **是否解决** | ✅ |
| **解决方案** | Reach 目标的 Page 关联不在 Ad Set 层，而在 Ad 层 Creative 的 object_story_spec.page_id / object_story_id。验证：检查 Creative 的 effective_object_story_id 是否以正确 page_id 开头 |
| **类型** | 参数规范 |

### M20. EG 账户 Ad Set 全部失败（Invalid parameter）

| 项目 | 内容 |
|-|-|
| **来源** | KK(M-16) |
| **问题描述** | EG Y500 Teaser Campaign 创建成功但 Ad Set 全部失败 |
| **请求方式** | `POST /act_385908392076192/adsets` |
| **报错返回** | "Invalid parameter" |
| **是否解决** | ✅ |
| **解决方案** | EG 账户 Ad Set 参数配置与 PK 存在差异，需按 EG 规则调整（具体字段待进一步确认） |
| **类型** | 参数规范 |

## 四、destination_type 专题（跨文档高频坑，合并）

> **说明**：destination_type 是所有 Agent 反映最集中的 Meta 坑。同一个 UI 文本对应多个 API 值，传错不报错但行为异常，且**创建后不可修改，只能删除重建**。来源：HY(2.4\~2.7、2.11)、JYY(#13)、YY(#16)、CC(#8)、KK 多处。

### M-D. destination_type 决策表与铁律

| 项目 | 内容 |
|-|-|
| **来源** | HY(2.4/2.5/2.6/2.7/2.11)、JYY(#13)、YY(#16) |
| **问题现象汇总** | ①传错值 ON_AD 被拒（"不在有效枚举内"）；②传 UNDEFINED 用于非 Partnership 场景，UI 行为不符预期；③不传导致默认 WEBSITE（无报错但 UI 显示 Website 而非 On your ad）；④创建后 UPDATE 无效（返回 success 但值不变，静默失败）；⑤复制 Ad Set 时漏传 destination_type |
| **是否解决** | ✅（已沉淀为铁律） |
| **决策映射表** | OUTCOME_ENGAGEMENT + THRUPLAY → `ON_VIDEO`；OUTCOME_ENGAGEMENT + POST_ENGAGEMENT → `ON_POST`；Partnership Ad（任何 Objective）→ `UNDEFINED`；VideoView → `ON_VIDEO`；Traffic 标准 → `WEBSITE` |
| **铁律** | ①必须显式传 destination_type，不传≠正确（Meta 默认填 WEBSITE）；②该字段创建后**不可修改**，传错只能删除重建；③复制 Ad Set = 全字段 GET 后原样传入，禁止自行筛选字段；④**创建前必须 GET 查询同类在跑广告的实际参数照抄，严禁凭记忆推测** |
| **典型教训** | JYY(#13)/YY(#16)：IN 市场 VideoView 广告 destination_type 凭记忆推测经历 4 次错误（WEBSITE→ON_AD→UNDEFINED→不传），最终 GET 源 Campaign 确认应为 ON_VIDEO。固化为铁律 |
| **类型** | 参数逻辑 / API 字段不可变 |

---

## 五、Ad / Creative 参数类

### M21. object_story_id 单独建 Creative 报 #3 能力限制

| 项目 | 内容 |
|-|-|
| **来源** | HY(3.1)、KK(M-02) |
| **问题描述** | 用 object_story_id 单独 `POST /act_{id}/adcreatives` 创建独立 Creative，返回能力限制错误 |
| **请求方式** | `POST /act_{id}/adcreatives` body 含 object_story_id |
| **报错返回** | `(#3) Application does not have the capability to make this API call` |
| **是否解决** | ✅ |
| **解决方案** | 不单独建 Creative，将 object_story_id 内联进 `POST /act_{id}/ads` 的 creative 字段（JSON 内联），绕过 #3 限制 |
| **类型** | API 接口 / App 能力限制 |

### M22. CTA / URL 创建后不回显（existing post / 知名度 REACH 类）

| 项目 | 内容 |
|-|-|
| **来源** | HY(3.2)、KK(M-03)、CC(#23) |
| **问题描述** | API 创建 Ad 时 CTA/URL 绑定成功（GET 回读确认），但 Ads Manager UI 不回显 / 显示为空 |
| **请求方式** | `POST /act_{id}/ads`（含 call_to_action）/ existing post 内联 creative |
| **报错返回** | 无报错，API 返回 success，GET 回读 CTA 存在，但 UI 看不到 |
| **是否解决** | ✅（确认为平台已知行为，不影响投放） |
| **解决方案** | Meta 2026 年 2-3 月平台变更：existing post 的 CTA 与原帖"解耦"，CTA 只在广告投放时展示，UI 编辑界面不回显。UI 不显示≠未设置成功。验证：`GET /{creative_id}?fields=call_to_action`。知名度/REACH 类 Ad Set 也不展示落地页 URL（同为设计行为） |
| **差异总结** | KK(M-03) 记录了完整 5 种测试方案（call_to_action.value.link 成功但 UI 不显示 / +link_caption 无效 / 根级 link_url 报 #3 / object_story_spec.link_data 丢互动数据 / asset_feed_spec 不兼容），最终确认为平台限制 |
| **类型** | 平台设计限制（UI 渲染） |

### M23. POST_ENGAGEMENT Ad 的 tracking_specs 含无效 action.type

| 项目 | 内容 |
|-|-|
| **来源** | HY(3.3)、CC(#10) |
| **问题描述** | 创建 Ad 时 tracking_specs 含无效 action.type（如 commerce_event）或格式不对 |
| **请求方式** | `POST /act_{id}/ads` 含 tracking_specs |
| **报错返回** | tracking_specs 格式校验失败 / 报错 |
| **是否解决** | ✅ |
| **解决方案** | ①POST_ENGAGEMENT 类 Ad 不可含 commerce_event，保留 offsite_conversion/onsite_conversion/post_engagement/link_click（HY）；②tracking_specs 必须含 pixel_id + page_id，格式 `[{"action.type":["offsite_conversion"],"fb_pixel":[""]},{"action.type":["post_engagement"],"page":[""]}]`（CC） |
| **类型** | API 参数约束 / 格式 |

### M24. CTA / Creative 创建后尝试修改无效（Creative immutable）

| 项目 | 内容 |
|-|-|
| **来源** | HY(3.4)、YY(#6)、MM(#14) |
| **问题描述** | Creative 创建后尝试 POST 修改 call_to_action / 更新 creative 内容，静默失败或 UI 不刷新 |
| **请求方式** | `POST /{creative_id}`（改 CTA）/ `POST /{ad_id}`（改 creative 引用） |
| **报错返回** | API 返回 success 但字段不变 / UI 仍显旧 Creative |
| **是否解决** | ✅（已明确约束） |
| **解决方案** | Creative 创建后仅可更新 name/status/adlabels 三字段；CTA 必须在创建时一并传入。修改 Creative 后必须删旧 Ad 重建，不能只更新 Ad 的 creative 引用（MM 已沉淀为铁律） |
| **类型** | API 字段不可变 |

### M25. FB 分享链接无法解析为 object_story_id

| 项目 | 内容 |
|-|-|
| **来源** | CC(#7) |
| **问题描述** | FB 分享链接（/share/p/xxx 和 pfbid 格式）无法通过 API 转为 `{page_id}_{post_id}` 数字格式 |
| **请求方式** | `GET /?id={url}` / pfbid 直接查询 / promotable_posts 端点 |
| **报错返回** | 返回 URL 而非数字 ID / "singular statuses API deprecated" |
| **是否解决** | ✅ |
| **解决方案** | 用浏览器打开页面，从渲染后的 JS 中提取数字 post_id |
| **类型** | API 接口约束 |

### M26. Reel 素材 object_story_id 误用 video_id

| 项目 | 内容 |
|-|-|
| **来源** | CC(#18) |
| **问题描述** | 创建广告时使用 Reel 的 video_id 作为 object_story_id，引用无效 |
| **请求方式** | `POST /act_{id}/ads` creative 引用 video_id 而非 feed post_id |
| **报错返回** | 素材无效 / 无法识别 |
| **是否解决** | ✅ |
| **解决方案** | Reel 必须使用 feed post_id（`{page_id}_{post_id}`），不可用 video_id。object_story_id 铁则：始终用 feed 帖子 ID |
| **类型** | API 接口约束 |

### M27. standard_enhancements 字段被废弃（subcode 3858504）

| 项目 | 内容 |
|-|-|
| **来源** | KK(M-04) |
| **问题描述** | 在 Creative 中传入 standard_enhancements 字段（OPT_IN/OPT_OUT 均不行） |
| **请求方式** | `POST /act_{id}/ads` creative 含 degrees_of_freedom_spec.creative_features_spec.standard_enhancements |
| **报错返回** | `(#100) error_subcode 3858504` — "已不再支持在创意中加入标准增强字段" |
| **是否解决** | ✅ |
| **解决方案** | 删掉 standard_enhancements，改用单个功能字段单独开关（image_animation/text_optimizations），或整段 degrees_of_freedom_spec 不传。照抄老广告 spec 前必须先删该字段 |
| **类型** | 平台变更（API 废弃） |

## 六、Partnership Ad（合创广告）专题

> 合创广告是跨文档第二大集中区。核心铁律（多来源共识）：adcode → `branded_content.instagram_boost_post_access_token`（唯一正确位置）+ `partnership_ad_config.is_partnership_ad=true` + 不传 object_story_spec + Ad Set destination_type=UNDEFINED + Ad 层 is_partnership_ad=true；创建后 GET 验证 branded_content 字段存在。

### M28. App 缺少 branded_content_ads 权限（subcode 2446391）

| 项目 | 内容 |
|-|-|
| **来源** | AA(#1)、JYY(#4)、YY(#8)、CC(#12) |
| **问题描述** | 内部代理平台 Meta App 'ba'（ID ）缺 branded_content_ads capability。6/18 [代理工具] 刷新 token 后所有账户统一切换到该 App，导致 Partnership Ad 全线失败或降级为 link ad |
| **请求方式** | `POST /act_{id}/adcreatives`（branded_content 参数） |
| **报错返回** | `error_subcode: 2446391` — "广告未完成，有一个或多个必填字段未填"（App 无权限时 branded_content 参数被忽略，等同缺必填） |
| **影响范围** | 6/18 起影响所有通过 [代理工具] token 创建 Partnership Ad 的账户（Eufy project 277 + 客户A project 275） |
| **是否解决** | ✅（6/23 芦直属上级在 Meta 后台为 App 获取权限并更新 内部代理层 后台授权；7/20 确认权限恢复） |
| **解决方案** | ①长线：为 App 申请 branded_content_ads 权限并更新授权（芦直属上级/平台管理员推进）；②应急：使用有权限 App 的 token（如客户A账户绑定的 App）；③兜底：Ads Manager 手动创建 |
| **类型** | App 权限配置 |

### M29. Partnership Ad Code 被截断（误导性 2446391）

| 项目 | 内容 |
|-|-|
| **来源** | AA(#2) |
| **问题描述** | 从表格读取的 partnership ad code 仅 36 字符（完整应 50-70），传入后返回误导性报错 |
| **请求方式** | `POST /act_{id}/adcreatives` |
| **报错返回** | `error_subcode: 2446391`（同 M28 报错，但实际是 code 无效） |
| **是否解决** | ✅ |
| **解决方案** | 从高剑力处获取完整 adcode（67 字符）重新创建。沉淀规则：code 长度 50-70 字符， 多尺寸素材按版位分发是 Meta 另一大坑区（主要来自 AA/MM/YY/RL）。核心：≥ 2 张不同尺寸素材强制用 asset_feed_spec + asset_customization_rules，且 adlabels 必须完整。

### M42. 图片广告缺竖版（9:16）版位覆盖

| 项目 | 内容 |
|-|-|
| **来源** | AA(#6)、YY(#7、#18、#23) |
| **问题描述** | 首批图片广告仅用 1:1 方图，未为 Story/Reels 版位指定 9:16 竖图；或多尺寸素材退化为单图方式；或1.91:1 横版图无法绑定版位 |
| **请求方式** | `POST /act_{id}/adcreatives`（object_story_spec.link_data.image_hash 单图 / asset_customization_rules） |
| **报错返回** | 无报错，但版位素材不匹配 / 只投单一尺寸 |
| **是否解决** | AA/YY 多数 ✅；YY(#7) 1.91:1 版位绑定 ❌（API 能力边界，需 UI 手动为 FB Feed 指定） |
| **解决方案** | ≥ 2 张不同尺寸 → 强制 asset_feed_spec + asset_customization_rules；版位映射：1:1→Feed/Instream，4:5/9:16→Stories/Reels/Search，1.91:1→RHC+Search。AA 方案：删首批重建（3 条 rules） |
| **类型** | 素材规格 / 版位匹配 |

### M43. asset_feed_spec 缺 adlabels + rules（UI 无法预览/16 版位不可投）

| 项目 | 内容 |
|-|-|
| **来源** | MM(#10、#12) |
| **问题描述** | asset_feed_spec 仅含裸 image hash + 文案，无 adlabels/rules；或 body/title/link_url 未带 adlabels |
| **请求方式** | `POST /act_{id}/adcreatives` |
| **报错返回** | 创建成功但 UI 图片无法预览 / Media 无法编辑 / 16 个版位不可投放 |
| **是否解决** | ✅ |
| **解决方案** | Creative 必须完整：12 个独立 adlabels（4 类资产×3 规则）+ 3 条 asset_customization_rules（Feed→方 / Story+Reels→竖 / Default→横）+ 每条 rule 含 image_label+body_label+title_label+link_url_label+priority + onsite_destinations:{auto_optimization:OPT_IN} + display_url。body/title/link_url 也必须各自带齐所有 rule 的 adlabels |
| **类型** | API 参数缺失（结构不完整） |

### M44. asset_feed_spec "Multiple bodies can not be applied to rule"

| 项目 | 内容 |
|-|-|
| **来源** | MM(#11) |
| **问题描述** | asset_feed_spec 包含多条 bodies + asset_customization_rules |
| **请求方式** | `POST /act_{id}/adcreatives` |
| **报错返回** | `"Multiple bodies can not be applied to rule"` |
| **是否解决** | ✅ |
| **解决方案** | 存在 asset_customization_rules 时，bodies/titles 只能各有 1 条（或每条都标注所有 rule 的 adlabel）。多文案模式与 customization_rules 互斥 |
| **类型** | API 接口约束 |

### M45. asset_feed_spec 图片尺寸与版位映射写反

| 项目 | 内容 |
|-|-|
| **来源** | MM(#13) |
| **问题描述** | 人工凭文件名判断图片尺寸，将 square 和 vertical 映射到错误版位 |
| **请求方式** | `POST /act_{id}/adcreatives` |
| **报错返回** | 无报错，但版位投放错误（Feed 展竖图，Story 展方图） |
| **是否解决** | ✅ |
| **解决方案** | 创建前必须 `GET /act_{id}/adimages?hashes=[...]&fields=hash,width,height` 验证实际宽高，严禁凭文件名假设尺寸（已沉淀为铁律） |
| **类型** | 流程缺陷 |

### M46. DCO 开启与多条广告冲突

| 项目 | 内容 |
|-|-|
| **来源** | AA(#8、#12) |
| **问题描述** | Ad Set 开启 DCO 后放入多条广告导致冲突；以及竖版视频如何不拆多 creative 分配到 Stories/Reels |
| **请求方式** | Meta Graph API |
| **报错返回** | 创建失败（DCO 模式下 Ad Set 只能一个动态创意） |
| **是否解决** | ✅ |
| **解决方案** | 关闭 DCO、清空 ads 后用 asset_feed_spec + adlabels + asset_customization_rules + optimization_type:PLACEMENT，在单 creative 内实现竖版→Stories/Reels、横版→其他版位，无需拆 creative |
| **类型** | API 逻辑冲突 |

### M47. DTC Campaign 缺 UTM Tracking 参数

| 项目 | 内容 |
|-|-|
| **来源** | AA(#7) |
| **问题描述** | DTC 类 campaign 创建时遗漏 UTM url_tags 参数 |
| **请求方式** | Meta Graph API（meta CLI） |
| **报错返回** | 无报错，但广告缺追踪参数 |
| **是否解决** | ✅ |
| **解决方案** | 重建时补 url_tags：`utm_source=fb-ig&utm_medium=cpm&utm_content={{adset.name}}_{{ad.name}}&utm_campaign={{campaign.name}}&utm_term={{campaign.id}}_{{adset.id}}_{{ad.id}}` |
| **类型** | 参数遗漏 |

### M48. Ad Set 达 50 条广告上限

| 项目 | 内容 |
|-|-|
| **来源** | AA(#9) |
| **问题描述** | AMZ adset 已有 50 条广告达上限，无法新增 |
| **请求方式** | Meta Graph API |
| **报错返回** | 超出 Ad Set 广告数量限制 |
| **是否解决** | ✅（引发次生问题，见流程章节） |
| **解决方案** | Meta 限制单 Ad Set 最多 50 条。现行规则：遇上限必须停下报告，由用户指定移除哪条（严禁 AI 擅自归档腾位） |
| **类型** | 平台限制 |

---

## 八、预算 / 出价、设备定向、文案

### M49. CBO/ABO 误用导致预算 N 倍超支

| 项目 | 内容 |
|-|-|
| **来源** | HY(5.1) |
| **问题描述** | Campaign 设 ABO + 每个 Ad Set 各传 budget，实际花费 = N × 预期预算 |
| **请求方式** | Campaign 设 ABO + 每个 Ad Set 各传 budget |
| **报错返回** | 无报错，但实际花费 = N × 预期预算 |
| **是否解决** | ✅ |
| **解决方案** | 创建前必读 group.yaml.strategy.budget 确认预算模式；CBO → budget 放 Campaign 层，Ad Set 不传；ABO → 各 Ad Set 各传 |
| **类型** | 流程 / 逻辑错误 |

### M50. ABO Campaign 未传 is_adset_budget_sharing_enabled

| 项目 | 内容 |
|-|-|
| **来源** | YY(#22)、ZM(#5) |
| **问题描述** | ABO Campaign 未显式传 is_adset_budget_sharing_enabled；或 CBO Campaign 未传该字段导致预算分配异常 |
| **请求方式** | `POST /act_{id}/campaigns` |
| **报错返回** | 预算分配逻辑异常 / API 要求必填 |
| **是否解决** | ✅ |
| **解决方案** | ABO 显式传 `is_adset_budget_sharing_enabled=false`；CBO 传 `true`（配合 lifetime_budget + start/end_time） |
| **类型** | API 参数缺失 |

### M51. 频次控制（frequency cap）投放后无法修改

| 项目 | 内容 |
|-|-|
| **来源** | CC(#38) |
| **问题描述** | Ad Set 投放开始后，尝试修改频次控制被拒 |
| **请求方式** | `POST /{adset_id}`（修改 frequency_control_specs） |
| **报错返回** | 投放开始后无法修改频次 |
| **是否解决** | ✅（绕过） |
| **解决方案** | 方案 A：新建无频次限制的 Ad Set → 删旧 Ad Set（Y500 项目标准做法） |
| **类型** | 平台规则限制 |

### M52. DeviceUser 手写设备名 / 新机型不在设备库

| 项目 | 内容 |
|-|-|
| **来源** | CC(#25)、HY(6.2) |
| **问题描述** | 手写设备名（如 Galaxy A05）报无效；或新机型不在 Meta 设备库 |
| **请求方式** | `POST /act_{id}/adsets` targeting.user_device=[...] |
| **报错返回** | `"invalid user_device value"` / 设备名无效 |
| **是否解决** | ✅ |
| **解决方案** | user_device 值必须从账户内已有在跑 DeviceUser Ad Set 获取（GET targeting.user_device），不可手写；无效新机型在 Meta 更新设备库前跳过，用同品牌已有型号替代 |
| **类型** | API 参数约束 / 平台数据滞后 |

### M53. user_device 写入后 UI 不显示

| 项目 | 内容 |
|-|-|
| **来源** | HY(6.1) |
| **问题描述** | user_device 写入后 Ads Manager 显示"all device" |
| **请求方式** | `POST /act_{id}/adsets`（targeting.user_device=[...]） |
| **报错返回** | 无报错，但 UI 显示 all device |
| **是否解决** | ✅ |
| **解决方案** | POST_ENGAGEMENT + AA=OFF 时 UI 不展示 device targeting；需 targeting_automation.advantage_audience=1 (AA=ON) + Manual Placements |
| **类型** | 平台 UI 限制 |

### M54. Advantage+ 自动版位误用 + RMKT 缺自定义受众

| 项目 | 内容 |
|-|-|
| **来源** | YY(#20、#21) |
| **问题描述** | ①未显式指定版位导致 Meta 默认 Advantage+ Placements；②RMKT 广告组缺 custom_audiences |
| **请求方式** | `POST /act_{id}/adsets` |
| **报错返回** | 无报错，但版位/受众定向不符预期 |
| **是否解决** | ✅ |
| **解决方案** | 铁律：必须 Manual Placements 手动指定版位 + targeting_automation.advantage_audience=0；RMKT 必须通过 GET /customaudiences 查受众 ID 填入 |
| **类型** | 参数配置铁律 |

### M55. 广告文案换行符 //n 处理异常

| 项目 | 内容 |
|-|-|
| **来源** | AA(#5) |
| **问题描述** | 广告文案中的换行符 //n 未被正确处理，文案渲染异常 |
| **请求方式** | Meta Graph API |
| **报错返回** | 无报错，但广告展示文案格式错误 |
| **是否解决** | ✅ |
| **解决方案** | 新增 normalize_ad_text() 函数统一处理文案换行符；已写入 Meta 广告执行QA.md 和 troubleshooting.md |
| **类型** | 数据处理 |

### M56. Ad Set 时区参数 / start_time 处理不当

| 项目 | 内容 |
|-|-|
| **来源** | MM(#15) |
| **问题描述** | start_time 设为 +0200，Ads Manager 显示为 7月9日22:00（非预期 7月10日），Meta 按 UTC/账户时区转换 |
| **请求方式** | `POST /act_{id}/adsets` start_time=`2026-07-10T00:00:00+0200` |
| **报错返回** | 无报错，但开始时间偏移 |
| **是否解决** | ✅ |
| **解决方案** | 统一用 UTC（+0000）或账户时区设置 start_time，不用本地夏令时偏移 |
| **类型** | 参数格式 / 时区 |

### M57. Campaign / Ad Set 命名规范（缩写 / 素材后缀 / 丢空格）

| 项目 | 内容 |
|-|-|
| **来源** | ZM(#6)、CC(#26) |
| **问题描述** | 拼接命名丢空格/缩写（Z60 Ultra Roller Complete→Z60URC）；或将素材名拼入 Ad Set 命名 |
| **请求方式** | `POST /act_{id}/campaigns` 或 adsets（name 字段） |
| **报错返回** | 无 API 报错，但不符命名规范 |
| **是否解决** | ✅ |
| **解决方案** | 命名严格复制素材表原文，不做字符处理/缩写（ZM）；Ad Set name=Tier{X}\_{Audience}，不带素材名后缀（CC） |
| **类型** | 业务规范 |

## 九、平台产品级限制（API 与 UI 能力不对等）

> 这类问题大多**无 API 解法**，兜底方案统一为 Ads Manager UI 手动创建。是本文档未解决问题的主体。

### M58. IG Video/Reel 未 crosspost 到 FB（subcode 1815279）

| 项目 | 内容 |
|-|-|
| **来源** | JYY(#1)、YY(#1、#4)、ZM(#2)、KK(M-14) |
| **问题描述** | KOL 的 IG 视频/Reel 帖未 crosspost 到 FB，Meta API 硬性要求 IG 视频已同步到 FB 才能创建 Partnership Ad Creative / VideoView / Social Boosting |
| **请求方式** | `POST /act_{id}/adcreatives`（branded_content）/ `POST /act_{id}/ads`（source_instagram_media_id） |
| **报错返回** | `error_subcode: 1815279` — "Instagram Video Must Be Uploaded To Facebook" |
| **影响范围** | JYY：6/24首批6条失败、6/25重试4条、6/26批次6条，累计数十条；YY：扩展到 7/27 普通 Social Boosting 场景 |
| **是否解决** | ❌无 API 层解法（逐条绕行） |
| **解决方案** | ①让 KOL 在 IG 端开启视频→FB 同步；②等 Meta 自动索引后重试；③兜底由优化师通过 Ads Manager UI 手动创建（UI 走内部 GraphQL 可异步同步素材）；④ZM 提供规避方案：改用 object_story_spec + link_data.link(IG permalink) 两步法（牺牲原帖互动展示） |
| **差异总结** | 根本方案一致（crosspost 后用 source_instagram_media_id 是唯一能保留原帖互动的方式）；ZM 额外给了 permalink 规避法但会丢失原帖互动数据 |
| **类型** | 平台产品级限制 |

### M59. INSTAGRAM_PROFILE destination Ad 层创建被拒

| 项目 | 内容 |
|-|-|
| **来源** | YY(#2)、JYY(#9) |
| **问题描述** | destination_type=INSTAGRAM_PROFILE + source_instagram_media_id 组合，Campaign/AdSet 层可建但 Ad 层报 Permission error |
| **请求方式** | `POST /act_{id}/ads` |
| **报错返回** | Permission error（code 200, subcode 1346001） |
| **是否解决** | ✅（通过 UI 手动创建 / 替代方案） |
| **解决方案** | 仅 Ads Manager UI 可创建（授权管理员+芦直属上级双人重建）；替代：OUTCOME_TRAFFIC + INSTAGRAM_PROFILE + VISIT_INSTAGRAM_PROFILE（PL 市场已验证） |
| **类型** | 平台产品级限制 |

### M60. OUTCOME_ENGAGEMENT + INSTAGRAM_PROFILE 组合 API 不支持

| 项目 | 内容 |
|-|-|
| **来源** | YY(#3)、JYY(#10) |
| **问题描述** | Marketing API v22\~v25 全版本不支持 OUTCOME_ENGAGEMENT 下 INSTAGRAM_PROFILE destination 与任何 optimization_goal 的组合 |
| **请求方式** | `POST /act_{id}/adsets` |
| **报错返回** | 所有变体测试均失败（PROFILE_AND_PAGE_ENGAGEMENT/VISIT_INSTAGRAM_PROFILE/PAGE_LIKES/IMPRESSIONS/REACH） |
| **是否解决** | ✅（改用替代方案） |
| **解决方案** | ①OUTCOME_TRAFFIC + INSTAGRAM_PROFILE + VISIT_INSTAGRAM_PROFILE（效果等价，已验证）；②OUTCOME_ENGAGEMENT + ON_POST + POST_ENGAGEMENT；③直接 OUTCOME_TRAFFIC |
| **类型** | 平台产品级限制 |

### M61. 帖含版权音乐（subcode 3867171）

| 项目 | 内容 |
|-|-|
| **来源** | JYY(#2)、YY(#13) |
| **问题描述** | KOL 帖子使用受版权保护的音乐，Meta 不允许用于广告 |
| **请求方式** | `POST /act_{id}/adcreatives` |
| **报错返回** | `error_subcode: 3867171` — "This post uses licensed music that can't be used in ads for legal reasons" |
| **影响范围** | 6/26 myhome_eri、giadapole；7/20 IN 市场 Nishtha KOL |
| **是否解决** | ❌逐 case 处理（非技术可解） |
| **解决方案** | KOL 更换不含版权音乐重发帖子，或用其他不含版权音乐的 KOL 帖 adcode；若无法修改则从投放计划移除 |
| **类型** | 内容合规限制 |

### M62. Partnership 身份配置问题（subcode 3867111）

| 项目 | 内容 |
|-|-|
| **来源** | JYY(#3)、YY(#14) |
| **问题描述** | KOL 帖子的 Partnership 身份配置异常，无法通过 API 创建 Partnership Ad |
| **请求方式** | `POST /act_{id}/adcreatives` |
| **报错返回** | `error_subcode: 3867111` |
| **影响范围** | 6/26 home_and_interior |
| **是否解决** | ❌逐 case（需 KOL 端修复） |
| **解决方案** | ①确认 KOL 在 IG 帖中正确配置品牌合作伙伴标签（Branded Content Tag）；②确认品牌方已在 Brand Collabs Manager 中批准该 KOL |
| **类型** | 内容配置（KOL 端） |

### M63. FB Post 被标记为 non-promotable / 不符合推广资格

| 项目 | 内容 |
|-|-|
| **来源** | YY(#5)、CC(#15)、JYY(#11) |
| **问题描述** | FB 帖被 Meta 标记为不可推广 / 不符合广告推广资格 |
| **请求方式** | `POST /act_{id}/ads`（引用特定 object_story_id） |
| **报错返回** | "帖子不符合广告推广资格"（is_eligible_for_promotion=false） |
| **是否解决** | ✅（换素材）/ ❌（内容审核限制） |
| **解决方案** | 换用其他符合推广资格的素材，或联系平台确认帖子状态；兜底 UI 手动尝试 |
| **类型** | 平台内容审核限制 |

### M64. 帖子已提供但 Meta API 暂时无法验证

| 项目 | 内容 |
|-|-|
| **来源** | CC(#14) |
| **问题描述** | 帖子链接已提供，但 Meta API 暂时查不到该帖子 |
| **请求方式** | `GET /{post_id}?fields=is_eligible_for_promotion` |
| **报错返回** | 帖子不存在 / 无法查询 |
| **是否解决** | ✅ |
| **解决方案** | 等待一段时间后重试，帖子在 Meta 索引中生效后验证通过 |
| **类型** | 平台规则限制 |

### M65. FB Reel 不支持作为 Existing Post 推广

| 项目 | 内容 |
|-|-|
| **来源** | KK(M-11) |
| **问题描述** | 将 FB Reel 视频作为 existing post 推广时 Meta 不支持 |
| **请求方式** | `POST /act_{id}/ads`（含 FB Reel object_story_id） |
| **报错返回** | 不支持该帖子类型作为 existing post 推广 |
| **是否解决** | ❌（平台硬限制） |
| **解决方案** | 唯一替代：用 object_story_spec + video_data 方式新建 Dark Post Creative（Dark Post 禁令的例外场景之一） |
| **类型** | 平台限制 |

---

## 十、流程 / AI 行为管控类

> 这类不是 Meta 平台本身的问题，而是 AI 在创建过程中的行为偏差，已通过铁律根绝。保留在 Meta 文档因为均发生在 Meta 广告创建场景。

### M66. AI 擅自归档广告（越权操作）

| 项目 | 内容 |
|-|-|
| **来源** | AA(#10)、MM(#3、#21) |
| **问题描述** | Ad Set 达 50 条上限时，AI 擅自决定归档旧广告腾位；或未经确认删除/修改已投放广告 |
| **是否解决** | ✅（铁律根绝） |
| **解决方案** | 铁律：任何删除/归档/暂停已投放广告的操作必须停下报告，由用户显式指定，严禁 AI 自主决策 |
| **类型** | AI 行为管控 |

### M67. AI 自写脚本绕过 CLI / 直调原生 API

| 项目 | 内容 |
|-|-|
| **来源** | MM(铁律)、RL(#17)、CC(#34) |
| **问题描述** | AI 绕过统一 meta-ads CLI 自写 curl/python 脚本直调 Graph API，绕过参数校验与代理层 |
| **是否解决** | ✅（铁律根绝） |
| **解决方案** | 铁律：所有 Meta 操作走统一 meta-ads CLI（symlink /usr/local/bin/meta），严禁自写脚本直调原生 API |
| **类型** | AI 行为管控 |

### M68. meta-ads CLI capability routing 缺陷（v0.3.0 修复）

| 项目 | 内容 |
|-|-|
| **来源** | RL(#18)、CC(#35) |
| **问题描述** | meta-ads-subagent 早期版本 capability routing 有缺陷，\_status 报 introspection_unsupported / passthrough 异常 |
| **是否解决** | ✅ |
| **解决方案** | 升级 meta-ads-subagent 到 0.3.0；建立 symlink /usr/local/bin/meta → meta-ads |
| **类型** | 工具链 / 环境 |

---

## 十一、关键铁律沉淀（跨文档共识，创建前必读）

1. **所有 Meta 操作走代理域名 + CLI**：token 走 `[Meta代理域名]`，不直连 graph.facebook.com；操作走 meta-ads CLI。
2. **token 放 URL query 不放 body**（POST 也一样）。
3. **destination_type 必显式传且不可改**：THRUPLAY→ON_VIDEO；POST_ENGAGEMENT→ON_POST；Partnership→UNDEFINED；Traffic→WEBSITE。
4. **Partnership Ad adcode 唯一位置** = branded_content.instagram_boost_post_access_token；不传 object_story_spec；Ad 层 + Creative 层都要 is_partnership_ad=true。
5. **saved_audience_id 不可直传**：先 GET targeting 再 POST。
6. **Creative 创建后不可改**（CTA/URL），只能删重建。
7. **≥ 2 张不同尺寸素材必用 asset_feed_spec + 完整 adlabels + asset_customization_rules**。
8. **创建前必 GET 同类在跑广告的实际参数照抄，严禁凭记忆推测**。
9. **destructive 操作（删除/归档/暂停已投放广告）必须停下确认**，严禁 AI 自主决策。
10. **IG 视频/Reel 帖做 Partnership Ad 前必须已 crosspost 到 FB**（subcode 1815279 无 API 解法）。

---

> 本文档由 9 份 Agent 汇总归并而成，来源标注采用 `Agent(编号)` 格式便于回溯原文。如需某条问题的完整原始描述，可按来源标注查阅对应 Agent 的原始文档。

---

## 补充条目（2026-08-20 LAA 反馈 · 同事）

### M69. 原帖单平台发布（仅 IG 或仅 FB，另一平台为空）无法创建广告

| 项目 | 内容 |
|-|-|
| **来源** | 同事（LAA 反馈 4） |
| **问题描述** | 当原帖没发 Facebook 只发了 Instagram，或只发了 Facebook 而另一平台为空时，就无法创建广告 |
| **请求方式** | `POST /act_{id}/adcreatives` / `POST /act_{id}/ads`（Creative 需要有效的 object_story_id / IG media 引用） |
| **报错返回** | Creative 组装失败 / 引用无效（缺失一侧的帖子 ID 无法映射） |
| **造成原因（推测）** | ①Creative 需有效 object_story_id / IG media 引用，单平台缺一侧帖子 ID 时映射失败；②IG 侧需 instagram_user_id / IG media，缺 IG 权限 scope 无法获取（见 M7 / M38 / M39）；③FB 侧缺 page post_id 时 object_story_spec 无法组装。属"跨平台帖子引用缺失"类 |
| **是否解决** | ❌ 待优化（需技术侧确认 CLI 单平台分支支持） |
| **解决方案（建议）** | 明确单平台建广告路径：仅 IG → 走 IG media / partnership adcode 路径，不强依赖 FB post；仅 FB → 用 FB feed post_id，不引用 IG media。技术侧确认 meta-ads CLI 对"单平台原帖"的参数分支支持，必要时补齐 IG 权限 scope（instagram_basic / instagram_content_publish） |
| **类型** | Meta 平台 / 广告创建（跨平台帖子映射） |