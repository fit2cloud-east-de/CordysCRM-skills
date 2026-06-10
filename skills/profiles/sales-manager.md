# 销售经理角色配置

> 匹配规则见 core/role-engine.md

## 意图路由

> 写操作（查重/创建/转换/跟进/打卡）规则与销售角色一致；查询类意图按本角色「默认查询偏好」走团队视角。

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

> **意图区分**：用户说"查一下 xxx"默认走查重（cordys_ext.sh check），而非 cli-spec.md §12 的全局模糊搜索。只有明确说"搜索 xxx 的线索/客户/商机"或"看团队/部门 xxx"等指定查询时，才走 cordys.sh crm search/page（团队场景套用下方「默认查询偏好」）。

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
- **团队看板**：部门线索总量、商机漏斗、签约进度
- **成员执行力**：跟进覆盖率、转化率、排名
- **目标达成**：团队目标进度、个人排名对比
- **风险巡检**：长期未跟进客户、商机卡点、团队短板
- **数据下钻**：从团队概览 → 个人详情 → 具体记录
- **审批管理**：团队成员的待审批、审批效率、驳回情况

## 默认查询偏好

### ⚠️ 部门查询前置步骤（强制）

查询带 `{departmentId}` 的模板时，**必须用 `cordys_ext.sh dept-children` 获取部门 ID 数组**：

```bash
cordys_ext.sh dept-children 郝碧纯组
# → ["1131998760411186","8150336099852288","8151710489387008"]
```

将返回的数组直接作为 `departmentId` 条件的 `value`。**禁止自己调 `crm org` 手动解析树，禁止只传单个 ID。**

---

### 查询模板

除非用户明确说"全公司"或指定了 `ownerId`，经理角色的查询**默认带当前部门（含子部门）范围**。

| 场景 | 推荐命令 |
|------|---------|
| 团队线索总览 | `crm page lead '{"combineSearch":{"searchMode":"AND","conditions":[{"value":"{departmentId}","operator":"IN","name":"departmentId","multipleValue":false,"type":"TREE_SELECT"}]}}'` |
| 团队商机漏斗 | `crm page opportunity '{"combineSearch":{"searchMode":"AND","conditions":[{"value":"{departmentId}","operator":"IN","name":"departmentId","multipleValue":false,"type":"TREE_SELECT"}]}}'` |
| 部门组织架构 | `crm org` |
| 部门成员列表 | `crm members '{"departmentId":"{departmentId}"}'` |
| 团队成员跟进情况 | `crm follow plan lead '{"status":"ALL","myPlan":false}'` + 遍历成员 |
| 本月签约合同 | `crm search contract '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"DYNAMICS","name":"signTime","value":"MONTH","type":"TIME_RANGE_PICKER"},{"value":"{departmentId}","operator":"IN","name":"departmentId","multipleValue":false,"type":"TREE_SELECT"}]}}'` |
| 本月开放商机（结束日期在本月，未赢单未输单） | `crm page opportunity '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"DYNAMICS","name":"expectedEndTime","value":"MONTH","type":"TIME_RANGE_PICKER"},{"operator":"NOT_EQUALS","name":"stage","value":"SUCCESS"},{"operator":"NOT_EQUALS","name":"stage","value":"FAIL"},{"value":"{departmentId}","operator":"IN","name":"departmentId","multipleValue":false,"type":"TREE_SELECT"}]}}'` |
| 本月赢单商机（实际成交时间在本月） | `crm page opportunity '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"DYNAMICS","name":"actualEndTime","value":"MONTH","type":"TIME_RANGE_PICKER"},{"operator":"EQUALS","name":"stage","value":"SUCCESS"},{"value":"{departmentId}","operator":"IN","name":"departmentId","multipleValue":false,"type":"TREE_SELECT"}]}}'` |
| 某成员今年赢单（替换 ownerId） | `crm page opportunity '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"DYNAMICS","name":"actualEndTime","value":"YEAR","type":"TIME_RANGE_PICKER"},{"operator":"EQUALS","name":"stage","value":"SUCCESS"},{"operator":"EQUALS","name":"ownerId","value":"{userId}"}]}}'` |

> `{userId}` 获取方式：调 `crm members '{"departmentIds":["{departmentId}"]}'` 从返回列表中匹配姓名取 `id` 字段值。

## 交互模式
- **默认输出**：团队层面统计优先，附个人排名，允许下钻到个人
- **数据深度**：团队全貌 → 个人详情，提供多层下钻路径
- **提醒风格**：关注结构性问题和团队整体风险
- **行动建议**：定位到具体成员和具体问题，给出管理决策建议

## 异常预警
详见核心引擎 [risk-engine.md §3 经理预警](../core/risk-engine.md)、[risk-engine.md §5 审批预警](../core/risk-engine.md#5-审批相关预警)
