# 销售经理角色配置

> 匹配规则见 core/role-engine.md
>
> 匹配关键词：经理、总监、主管、负责人、leader、部长、主任

## 意图路由

> 写操作（查重/创建/更新/转换/跟进/打卡）规则与销售角色一致；查询类意图按本角色「默认查询偏好」走团队视角。

| 用户意图 | 动作 | 参考文档 |
|---------|------|---------|
| "查一下 xxx" / "查重 xxx" / "有没有 xxx" | `cordys_ext.sh check '{"客户名":"xxx","产品":[...]}'` | `sop/duplicate-check.md` |
| "创建线索/客户/商机/联系人" | 执行创建 5 步流程 | `sop/write-flow.md` + `references/forms/{module}.md` |
| "更新/修改/改一下 xxx" / "把 xxx 改成 yyy" | 定位记录 → 展示原值→新值对比 → 确认后 `cordys_ext.sh update <module> <id> '<JSON>'` | `sop/write-flow.md` §更新 |
| "批量修改/把这几条都改成 xxx" | 圈定记录 → 确认范围+字段 → `cordys_ext.sh batch-update` 或循环 `update` | `sop/write-flow.md` §批量更新 |
| "领取线索/客户" / "从公海/线索池捞 xxx" | `pool page` 定位 → `pool options` 拿 poolId → 确认 → `cordys_ext.sh pool pick` | `sop/write-flow.md` §公海/线索池操作 |
| "把 xxx 分配给 yyy" / "派给 xx" | 定位记录 → `crm members` 查用户ID → 确认 → `cordys_ext.sh pool assign` | `sop/write-flow.md` §公海/线索池操作 |
| "把 xxx 退回公海/线索池" | 定位记录 → 确认 → `cordys_ext.sh pool to-pool` | `sop/write-flow.md` §公海/线索池操作 |
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
- **L2C 管道**：团队线索→签约全链路转化分析

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
| 团队签约排名 | 遍历成员，逐人查询本月签约合同（取 total+金额） |
| 待审批巡检 | `crm approval todo count` → `crm approval todo pending` |
| 团队回款总额 | `crm aggregate contract/payment-record recordAmount sum '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"<时间操作符>","name":"recordEndTime","value":"<时间值>","type":"<时间类型>"},{"value":"{departmentId}","operator":"IN","name":"departmentId","multipleValue":false,"type":"TREE_SELECT"}]}}'` |
| 团队成员回款排名（考核） | 分页拉团队今年回款明细（带 `{departmentId}` 过滤）→ 按 `ownerName` 分组汇总 `recordAmount` → 降序 |

> `{userId}` 获取方式：调 `crm members '{"departmentIds":{departmentId},"current":1,"pageSize":500}'`，将 `dept-children` 返回的部门 ID 数组原样嵌入 `departmentIds`，从返回列表中按 `userName` 匹配姓名，取 `userId` 字段值（**不是 `id`**，取错 `id` 会静默返回空结果）。`owner` 条件使用此 `userId`。

> 组合规则：结果口径沿用 `core/stats-engine.md` 的「结果口径映射」，时间口径沿用 `core/cli-spec.md` 的时间规则，经理角色额外同步带入 `departmentId` 范围条件。

---

### 查询构造检查清单

构造任何团队查询前，逐项确认：

1. ✅ 已从 Cordys.md 取到部门 ID 数组（无则调 `dept-children`）
2. ✅ `conditions` 中包含 `departmentId` IN 条件
3. ✅ 时间字段选择正确（赢单/输单用 `actualEndTime`，开放商机用 `expectedEndTime`，新建用 `createTime`）
4. ✅ 时间操作符选择正确（相对时间用 DYNAMICS，明确起止区间用 BETWEEN）
5. ✅ `pageSize` 合理（默认 30，需要统计全量时用 200 并检查是否需要翻页）

## L2C 典型工作流

> 详细流程见 `core/workflow-engine.md` §2

### 日常
1. **晨会看板**："团队今天" → 部门总量 + 今日新增 + 成员活跃度
2. **审批处理**："批一下" → 待审批列表 + 超期标注

### 周常
3. **周会数据**："团队这周" → L2C 漏斗快照 + 成员排名 + 周环比
4. **风险巡检**："有什么问题" → 低跟进率 + 低转化 + 链断裂

### 月常
5. **月度复盘**："本月复盘" → 漏斗全貌 + 排名 + 趋势 + 赢单/输单分析
6. **管道预测**："下月预测" → 当前商机阶段分布 + 金额预测

## KPI 基准线
| 指标 | 正常 | 警戒 | 严重 |
|------|------|------|------|
| 团队线索跟进率 | ≥ 70% | 60-70% ⚠️ | < 60% 🚨 |
| 个人跟进率最低值 | ≥ 50% | 40-50% ⚠️ | < 40% 🚨 |
| 线索→客户转化率 | ≥ 15% | 10-15% ⚠️ | < 10% 🚨 |
| 商机→合同转化率 | ≥ 25% | 15-25% ⚠️ | < 15% 🚨 |
| 人均周签约量 | ≥ 1 个 | 0.5-1 ⚠️ | < 0.5 🚨 |
| 审批超期（>3天） | ≤ 2 条 | 3-5 条 ⚠️ | > 5 条 🚨 |
| 目标时间进度差 | ≤ 10% | 10-20% ⚠️ | > 20% 🚨 |

## 跨角色协作
| 触发条件 | 动作 |
|---------|------|
| 成员连续 2 周跟进率 < 50% | 标记该成员需要 1v1，可能触发 **高管** 关注 |
| 团队目标进度落后 > 20% | 提醒 **高管** "部门{名称}业绩风险" |
| 大额商机（> ¥50万） | 主动关注 + 提醒 **销售** "需要支持吗" |
| 审批被驳回 ≥ 2 次 | 协调 **商务** "合同条款需要确认" |
| 线索池超过 100 条积压 | 提醒自己 "分配线索或转公共池" |

## 权限边界
| 能做 | 不能做 |
|------|--------|
| 查看本部门及子部门所有数据 | 查看其他部门数据（除非被授权） |
| 审批下属提交的合同/报价单 | 审批自己提交的申请 |
| 查看团队成员的跟进记录 | 代成员创建跟进记录 |
| 查看本部门回款和发票 | 查看全公司财务汇总 |

## 角色内子类型
| 子类型 | 关键词 | 差异 |
|--------|--------|------|
| 一线经理 | 经理、主管 | 关注 3-8 人团队、日常执行 |
| 区域总监 | 总监、区域经理 | 关注多团队、跨区域对比 |
| 事业部负责人 | 部长、总经理、BU | 关注完整 P&L、包括成本和利润 |

> "总监"默认走 manager，"总经理"走 executive（在 role-engine 中已分离）。可通过 `ROLE_MAP` 调整。

## 交互模式
- **默认输出**：团队层面统计优先，附个人排名，允许下钻到个人
- **数据深度**：团队全貌 → 个人详情，提供多层下钻路径
- **提醒风格**：关注结构性问题和团队整体风险
- **行动建议**：定位到具体成员和具体问题，给出管理决策建议
- **漏斗视角**：定期展示 L2C 各阶段数据，标记瓶颈

## 异常预警
详见核心引擎：
- [risk-engine.md §3 经理预警](../core/risk-engine.md#3-经理预警)
- [risk-engine.md §5 审批预警](../core/risk-engine.md#5-审批相关预警)
- [risk-engine.md §6 L2C 跨模块风险](../core/risk-engine.md#6-l2c-跨模块风险链断裂检测)
