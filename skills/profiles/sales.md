# 销售角色配置

> 匹配规则见 core/role-engine.md

## 意图路由

| 用户意图 | 动作 | 参考文档 |
|---------|------|---------|
| "查一下 xxx" / "查重 xxx" / "有没有 xxx" | `cordys_ext.sh check '{"客户名":"xxx","产品":[...]}'` | `sop/duplicate-check.md` |
| "创建线索/客户/商机/联系人" | 执行创建 5 步流程 | `sop/write-flow.md` + `references/forms/{module}.md` |
| "转客户" / "转换线索" | `cordys_ext.sh transform '<JSON>'` | `sop/transform.md` |
| "拜访xx" / "跟进xx" / "记录一下xx" / "xx聊了产品" | 搜索 CRM → 写跟进 → 拜访打卡 | `sop/visit-flow.md` |
| "打卡" / "签到" / "上班" / "到公司" | 创建打卡链接 | `sop/company-checkin-flow.md` |

> **拜访/跟进意图细分**：含"拜访"→拜访打卡（走完整流程）；含"跟进""记录""聊了"但不含"拜访"→纯跟进（写完即结束）。详见 `sop/visit-flow.md` 开头。

> **查重参数构建**：用户输入中如果包含产品名或产品简称（JS/JMS=JumpServer、MK=MaxKB、MS=MeterSphere、DE=DataEase 等，完整映射见 `sop/inference-rules.md`），必须识别出来放入 `产品` 字段，不要当作客户名。示例："查一下赛摩智能和 JS" → `{"客户名":"赛摩智能","产品":["JumpServer 企业版"]}`
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
| 查看我的线索列表 | `crm page lead '{"viewId":"SELF"}'` （也可用 `{"filters":[{"field":"ownerId","operator":"equals","value":"{userId}"}]}`，但 SELF 更简洁高效） |
| 查看我的待办商机 | `crm page opportunity '{"viewId":"SELF","filters":[{"field":"stage","operator":"not equals","value":"Closed Lost"}]}'` |
| 查看我的客户 | `crm page account '{"viewId":"SELF"}'` |
| 查看协作客户 | `crm page account '{"viewId":"CUSTOMER_COLLABORATION"}'` |
| 查看今日新增线索 | `crm search lead '{"combineSearch":{"conditions":[{"operator":"DYNAMICS","name":"createTime","value":"TODAY","type":"TIME_RANGE_PICKER"}]}}'` |

### 统计查询模板

销售角色统计默认范围为"我的"数据，通过 `owner` 条件限定为当前用户。

> `{userId}` 取自 User.md 中的用户 ID（whoami 返回的 `data.userId`）。

| 场景 | 推荐命令 |
|------|---------|
| 我的赢单/输单商机 | `crm page opportunity '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"<时间操作符>","name":"actualEndTime","value":"<时间值>","type":"<时间类型>"},{"operator":"IN","name":"stage","value":["<SUCCESS 或 FAIL>"],"type":"SELECT"},{"operator":"EQUALS","name":"owner","value":"{userId}"}]}}'` |
| 我的开放商机 | `crm page opportunity '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"NOT_IN","name":"stage","value":["SUCCESS","FAIL"],"type":"SELECT"},{"operator":"EQUALS","name":"owner","value":"{userId}"}]}}'` |
| 我的线索 | `crm page lead '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"<时间操作符>","name":"createTime","value":"<时间值>","type":"<时间类型>"},{"operator":"EQUALS","name":"owner","value":"{userId}"}]}}'` |

> 组合规则：结果口径沿用 `core/cli-spec.md` 的「结果口径映射」，时间口径沿用时间规则，统计处理方式沿用 §9「统计与聚合」。销售角色额外同步带入 `owner` 范围条件。用户明确说"全部""所有人"时可去掉 `owner` 条件。

## 交互模式
- **默认输出**：列表优先，摘要展示，辅以关键状态 emoji
- **数据深度**：默认查看自己相关的数据，需要时再扩展到团队
- **提醒风格**：主动提醒跟进超时、线索积压、商机停滞
- **行动建议**：具体到"联系谁、做什么、优先级"

## 异常预警
详见核心引擎 [risk-engine.md §2 销售预警](../core/risk-engine.md)
