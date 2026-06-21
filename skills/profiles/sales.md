# 销售角色配置

> 匹配规则见 core/role-engine.md

## 意图路由

| 用户意图 | 动作 | 参考文档 |
|---------|------|---------|
| "查一下 xxx" / "查重 xxx" / "有没有 xxx" | `cordys_ext.sh check '{"客户名":"xxx","产品":[...]}'` | `sop/duplicate-check.md` |
| "创建线索/客户/商机/联系人" | 执行创建 5 步流程 | `sop/write-flow.md` + `references/forms/{module}.md` |
| "更新/修改/改一下 xxx" / "把 xxx 改成 yyy" | 定位记录 → 展示原值→新值对比 → 确认后 `cordys_ext.sh update <module> <id> '<JSON>'` | `sop/write-flow.md` §更新 |
| "批量修改/把这几条都改成 xxx" | 圈定记录 → 确认范围+字段 → `cordys_ext.sh batch-update` 或循环 `update` | `sop/write-flow.md` §批量更新 |
| "领取线索/客户" / "从公海/线索池捞 xxx" | `pool page` 定位 → `pool options` 拿 poolId → 确认 → `cordys_ext.sh pool pick` | `sop/write-flow.md` §公海/线索池操作 |
| "把 xxx 退回公海/线索池" | 定位记录 → 确认 → `cordys_ext.sh pool to-pool` | `sop/write-flow.md` §公海/线索池操作 |
| "转客户" / "转换线索" / "转商机" / "转客户并建商机" | `cordys_ext.sh transform '<JSON>'`（"转商机/并建商机"=同时建商机，"只转客户"=仅转客户，未提则问一次） | `sop/transform.md` |
| "拜访xx" / "跟进xx" / "记录一下xx" / "xx聊了产品" | 搜索 CRM → 写跟进 → 拜访打卡 | `sop/visit-flow.md` |
| "打卡" / "签到" / "上班" / "到公司" | 创建打卡链接 | `sop/company-checkin-flow.md` |

> **拜访/跟进意图细分**：含"拜访"→拜访打卡（走完整流程）；含"跟进""记录""聊了"但不含"拜访"→纯跟进（写完即结束）。详见 `sop/visit-flow.md` 开头。

> **查重参数构建**：用户输入中如果包含产品名或产品简称（JS/JMS=JumpServer、MK=MaxKB、MS=MeterSphere、DE=DataEase 等，完整映射见 `sop/inference-rules.md`），必须识别出来放入 `产品` 字段，不要当作客户名。示例："查一下赛摩智能和 JS" → `{"客户名":"赛摩智能","产品":["JumpServer 企业版"]}`
>
> **「的 + 产品」等价于查重**：「查一下 X 的 JS」「X 的 MK 情况」与「查一下 X 和 JS」**完全等价，都走查重**，把产品简称识别进 `产品` 字段。不要因为出现"的"就误判成 Customer-360 下钻。示例："查一下赛摩智能的 JS" → `cordys_ext.sh check '{"客户名":"赛摩智能","产品":["JumpServer 企业版"]}'`。
>
> **「的」后接什么决定走向（消歧关键）**：
> - 「的」后是**产品别名**（JS/JMS/MK/MS/DE…）→ **查重**（`cordys_ext.sh check`，产品进 `产品` 字段）
> - 「的」后是**业务对象模块词**（商机/合同/订单/联系人/回款/开票）→ **Customer-360 下钻**（定位 account → `cordys.sh crm acct-sub`，见 `core/linkage-engine.md`）
>
> **参数校验**：查重必须有明确的客户名或手机号。如果用户提供的信息中没有公司名称也没有手机号（如"未告知公司名称"），不得用城市名、产品名或其他信息替代，应直接告知用户"信息不足，无法查重，请补充公司名或联系电话"。

> **意图区分**：用户说"查一下 xxx"默认走查重（cordys_ext.sh check），而非 cli-spec.md §12 的全局模糊搜索。只有明确说"搜索 xxx 的线索/客户/商机"等指定模块查询时，才走 cordys.sh crm search/page。

## 流程概要

### 创建流程

创建线索/客户/商机/联系人统一遵循 5 步流程（详见 `sop/write-flow.md`）：

1. **提取 + 推断** — 从用户输入提取字段，应用 `sop/inference-rules.md` 自动补充
2. **查重** — 调用 `cordys_ext.sh check`，根据结果决定是否继续
3. **解析关联 ID** — 商机/联系人需解析所属客户/联系人 ID
4. **校验必填** — 对照 `references/forms/{module}.md` 检查必填字段
5. **创建** — 调用 `cordys_ext.sh create <module> '<JSON>'`

### 拜访跟进

用户提到"拜访""跟进"某公司时，执行拜访跟进流程（详见 `sop/visit-flow.md`）：

1. **提取信息** — 从用户输入提取 customer_name、checkin_type、followMethod、crm_type_hint、extracted_fields（AI 语义识别的联系人/产品等）、用户业务描述
2. **搜索定位** — `cordys.sh crm search` 并行搜 lead/account/opportunity，按商机>线索>客户优先级选取
3. **写跟进** — `cordys_ext.sh follow '<JSON>'`，字段定义见 `references/forms/follow.md`，跟进方式映射见 `references/mappings/follow-method.md`
4. **打卡卡片**（仅拜访意图）— 调打卡 API 发卡片，API 详情见 `references/checkin-api.md`；纯跟进意图写完即结束，不打卡

> **路径区分**：拜访意图走完整步骤1-4；纯跟进意图只走步骤1-3，写完跟进即结束。
>
> **企业微信限制**：打卡卡片仅在企业微信环境下发送（上下文有企业微信 userid 时）。非企业微信环境只写跟进，提示"请在企业微信中发起打卡"。

### 公司打卡

用户说"打卡""签到"时，执行公司打卡流程（详见 `sop/company-checkin-flow.md`）：直接调打卡 API 创建链接，不涉及 CRM。

## 核心关注
- **我的线索**：待跟进、今日新增、即将超时
- **我的商机**：推进中、即将赢单、卡住需要推动
- **我的客户**：近期活跃、需要回访、跟进记录
- **今日计划**：今日跟进计划提醒
- **我的业绩**：合同签约、目标进度

## 默认查询偏好
| 场景 | 推荐命令 |
|------|---------|
| 查看今天的跟进计划 | `crm follow plan lead '{"myPlan":true,"status":"UNFINISHED","sourceId":"..."}'` |
| 查看我的线索列表 | `crm page lead '{"viewId":"SELF"}'` |
| 查看我的待办商机 | `crm page opportunity '{"viewId":"SELF","combineSearch":{"searchMode":"AND","conditions":[{"operator":"NOT_IN","name":"stage","value":["SUCCESS","FAIL"],"type":"SELECT"}]}}'`（待办=未赢未输的开放商机） |
| 查看我的客户 | `crm page account '{"viewId":"SELF"}'`（按负责人 `owner` 判定归属，勿用 `follower`；owner/follower 区分见 `core/cli-spec.md` §4.2） |
| 查看协作客户 | `crm page account '{"viewId":"CUSTOMER_COLLABORATION"}'` |
| 查看今日新增线索 | `crm search lead '{"combineSearch":{"conditions":[{"operator":"DYNAMICS","name":"createTime","value":"TODAY","type":"TIME_RANGE_PICKER"}]}}'` |

### 统计查询模板

销售角色统计默认范围为"我的"数据，通过 `owner` 条件限定为当前用户。

> **查询范围边界（重要）**：销售角色只能查本人名下的线索/客户/商机/联系人。`owner` 条件一律填当前用户 userId（或用 `viewId:SELF`），**不要填他人 userId、也不要去 `crm members` 查别人**。
>
> 当用户要求查"别人/某同事/某成员/全部门/全公司"的数据（如"看看张三的客户""部门所有商机"）时，不要尝试构造查询，也不要编造"系统限制"之类的解释，而是直接回复：「我这边只能查询你本人名下的数据。查看团队或其他成员的数据需要销售经理权限，可以让对应的经理来查，或联系管理员调整权限。」

> `{userId}` 取自 Cordys.md 中的用户 ID（whoami 返回的 `data.userId`）。

| 场景 | 推荐命令 |
|------|---------|
| 我的赢单/输单商机 | `crm page opportunity '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"<时间操作符>","name":"actualEndTime","value":"<时间值>","type":"<时间类型>"},{"operator":"IN","name":"stage","value":["<SUCCESS 或 FAIL>"],"type":"SELECT"},{"operator":"EQUALS","name":"owner","value":"{userId}"}]}}'` |
| 我的开放商机 | `crm page opportunity '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"<时间操作符>","name":"expectedEndTime","value":"<时间值>","type":"<时间类型>"},{"operator":"NOT_IN","name":"stage","value":["SUCCESS","FAIL"],"type":"SELECT"},{"operator":"EQUALS","name":"owner","value":"{userId}"}]}}'` |
| 我的线索 | `crm page lead '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"<时间操作符>","name":"createTime","value":"<时间值>","type":"<时间类型>"},{"operator":"EQUALS","name":"owner","value":"{userId}"}]}}'` |

> 组合规则：结果口径沿用 `core/stats-engine.md` 的「结果口径映射」，时间口径沿用时间规则，统计处理方式沿用 `core/stats-engine.md`。销售角色额外同步带入 `owner` 范围条件。用户明确说"全部""所有人"时可去掉 `owner` 条件。

## 交互模式
- **默认输出**：列表优先，摘要展示，辅以关键状态 emoji
- **数据深度**：默认查看自己相关的数据，需要时再扩展到团队
- **提醒风格**：主动提醒跟进超时、线索积压、商机停滞
- **行动建议**：具体到"联系谁、做什么、优先级"

## 异常预警
详见核心引擎 [risk-engine.md §2 销售预警](../core/risk-engine.md)
