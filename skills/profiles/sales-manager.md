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

### 部门过滤条件（强制）

经理角色查询线索、商机、合同等列表时，**必须在 `combineSearch.conditions` 中包含 `departmentId` 条件**。

**执行方式：**
- 从 Cordys.md 读取 `departmentId` 数组（已含子部门），直接使用
- 若 Cordys.md 无此字段，再用 `cordys_ext.sh dept-children <部门名>` 获取
- 将数组放入 `departmentId` 的 `IN` 条件
- 在 API 端完成部门范围过滤

**原因：** 全量查询受 pageSize 上限（200）限制，数据量大时会截断导致结果不完整；API 端过滤才能保证准确性。

**唯一例外：** 用户明确说"全公司"、指定了具体 `owner`，或统计口径明确要求跨部门对比（如"各部门排名""各区域分布"）时，可不加本部门 `departmentId`；否则经理默认查询必须带部门过滤。

---

### 部门 ID 获取步骤（强制前置）

> ⚠️ **优先读 Cordys.md**：若 Cordys.md 中已有 `departmentId` 数组，直接使用，不要调 `dept-children`。

```
Cordys.md 有 departmentId？
├─ 有 → 直接用，跳过接口调用
└─ 无 → cordys_ext.sh dept-children <部门名>
```

将数组直接作为 `departmentId` 条件的 `value`。

---

### 时间范围选择规则

经理角色沿用 `core/cli-spec.md` 的时间规则：相对时间填 `DYNAMICS + TIME_RANGE_PICKER`，明确起止区间填 `BETWEEN + DATE_TIME`。

---

### 查询模板

> 以下模板中的 `{departmentId}` 条件是经理角色的默认范围条件，每次团队查询都带入。

| 场景 | 推荐命令 |
|------|---------|
| 团队线索总览 | `crm page lead '{"combineSearch":{"searchMode":"AND","conditions":[{"value":"{departmentId}","operator":"IN","name":"departmentId","multipleValue":false,"type":"TREE_SELECT"}]}}'` |
| 团队商机漏斗 | `crm page opportunity '{"combineSearch":{"searchMode":"AND","conditions":[{"value":"{departmentId}","operator":"IN","name":"departmentId","multipleValue":false,"type":"TREE_SELECT"}]}}'` |
| 部门组织架构 | `crm org` |
| 部门成员列表 | `crm members '{"departmentIds":{departmentId},"current":1,"pageSize":500}'` |
| 团队成员跟进情况 | `crm follow plan lead '{"status":"ALL","myPlan":false}'` + 遍历成员 |
| 团队签约合同 | `crm search contract '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"<时间操作符>","name":"createTime","value":"<时间值>","type":"<时间类型>"},{"value":"{departmentId}","operator":"IN","name":"departmentId","multipleValue":false,"type":"TREE_SELECT"}]}}'` |
| 团队开放商机 | `crm page opportunity '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"<时间操作符>","name":"expectedEndTime","value":"<时间值>","type":"<时间类型>"},{"operator":"NOT_EQUALS","name":"stage","value":"SUCCESS"},{"operator":"NOT_EQUALS","name":"stage","value":"FAIL"},{"value":"{departmentId}","operator":"IN","name":"departmentId","multipleValue":false,"type":"TREE_SELECT"}]}}'` |
| 团队赢单/输单商机 | `crm page opportunity '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"<时间操作符>","name":"actualEndTime","value":"<时间值>","type":"<时间类型>"},{"operator":"EQUALS","name":"stage","value":"<SUCCESS 或 FAIL>"},{"value":"{departmentId}","operator":"IN","name":"departmentId","multipleValue":false,"type":"TREE_SELECT"}]}}'` |
| 某成员结果类商机 | `crm page opportunity '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"<时间操作符>","name":"actualEndTime","value":"<时间值>","type":"<时间类型>"},{"operator":"EQUALS","name":"stage","value":"<SUCCESS 或 FAIL>"},{"operator":"EQUALS","name":"owner","value":"{userId}"}]}}'` |

> `{userId}` 获取方式：调 `crm members '{"departmentIds":{departmentId},"current":1,"pageSize":500}'`，将 `dept-children` 返回的部门 ID 数组原样嵌入 `departmentIds`，从返回列表中按 `userName` 匹配姓名，取 `userId` 字段值（非 `id`）。`owner` 条件使用此 `userId`。

> 组合规则：结果口径沿用 `core/stats-engine.md` 的「结果口径映射」，时间口径沿用 `core/cli-spec.md` 的时间规则，经理角色额外同步带入 `departmentId` 范围条件。

---

### 查询构造检查清单

构造任何团队查询前，逐项确认：

1. ✅ 已从 Cordys.md 取到部门 ID 数组（无则调 `dept-children`）
2. ✅ `conditions` 中包含 `departmentId` IN 条件
3. ✅ 时间字段选择正确（赢单/输单用 `actualEndTime`，开放商机用 `expectedEndTime`，新建用 `createTime`）
4. ✅ 时间操作符选择正确（相对时间用 DYNAMICS，明确起止区间用 BETWEEN）
5. ✅ `pageSize` 合理（默认 30，需要统计全量时用 200 并检查是否需要翻页）

## 交互模式
- **默认输出**：团队层面统计优先，附个人排名，允许下钻到个人
- **数据深度**：团队全貌 → 个人详情，提供多层下钻路径
- **提醒风格**：关注结构性问题和团队整体风险
- **行动建议**：定位到具体成员和具体问题，给出管理决策建议

## 异常预警
详见核心引擎 [risk-engine.md §3 经理预警](../core/risk-engine.md)、[risk-engine.md §5 审批预警](../core/risk-engine.md#5-审批相关预警)
