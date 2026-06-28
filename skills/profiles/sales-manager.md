# 销售经理角色配置

> 匹配规则见 core/role-engine.md
>
> 匹配关键词：经理、总监、主管、负责人、leader、部长、主任

## 意图路由

> **基础意图路由与流程概要见 `profiles/sales.md`** —— 查重、创建（5 步流程）、更新、批量修改、公海/线索池操作、转换、拜访跟进、公司打卡，以及查重参数构建、参数校验等规则与销售角色完全一致，本节只列出经理角色的差异。

**经理角色额外意图：**

| 用户意图 | 动作 | 参考文档 |
|---------|------|---------|
| "把 xxx 分配给 yyy" / "派给 xx" | 定位记录 → `crm members` 查用户ID → 确认 → `cordys_ext.sh pool assign` | `sop/write-flow.md` §公海/线索池操作 |

> **查询类意图差异**：用户说"查一下 xxx"仍默认走查重（`cordys_ext.sh check`）；但说"搜索 xxx 的线索/客户/商机"或"看团队/部门 xxx"等指定查询时，走 `cordys.sh crm search/page`，并套用下方「默认查询偏好」的团队视角（带 `departmentId`）。

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

**部门 ID 获取与过滤器构造**：完整机制（优先读 Cordys.md → fallback `dept-children` → 过滤器标准模式）见 `core/cli-spec.md` §11，本角色直接套用。

**原因：** 全量查询受 pageSize 上限（200）限制，数据量大时会截断导致结果不完整；API 端过滤才能保证准确性。

**唯一例外：** 用户明确说"全公司"、指定了具体 `owner`，或统计口径明确要求跨部门对比（如"各部门排名""各区域分布"）时，可不加本部门 `departmentId`；否则经理默认查询必须带部门过滤。

### 时间范围选择规则

沿用 `core/cli-spec.md §5.4`：相对时间用 `DYNAMICS + TIME_RANGE_PICKER`，明确起止区间用 `BETWEEN + DATE_TIME`。

---

### 查询模板

> 以下模板中的 `{departmentId}` 条件是经理角色的默认范围条件，每次团队查询都带入。
>
> ⚠️ **`{departmentId}` 是 JSON 数组**（`dept-children` 返回的部门+子孙 ID 数组，如 `["1131998760411155","20212957909090309"]`），`operator:"IN"` 的 `value` 必须填**真数组、不带引号**。填成单个字符串（`"value":"<id>"`）后端会报 `not iterable`，单 ID 也一样。只查一个部门也要写成单元素数组 `["<id>"]`。

| 场景 | 推荐命令 |
|------|---------|
| 团队线索总览 | `crm page lead '{"combineSearch":{"searchMode":"AND","conditions":[{"value":{departmentId},"operator":"IN","name":"departmentId","multipleValue":true,"type":"TREE_SELECT"}]}}'` |
| 团队商机漏斗 | `crm page opportunity '{"combineSearch":{"searchMode":"AND","conditions":[{"value":{departmentId},"operator":"IN","name":"departmentId","multipleValue":true,"type":"TREE_SELECT"}]}}'` |
| 按部门名查 ID+子部门 | `cordys_ext.sh dept-children "部门名"`（一次返回该部门及全部子孙 ID 数组，直接用于 `departmentId` 过滤）。**不要用 `crm org` 手动递归找 ID** |
| 部门组织架构（看整棵树） | `crm org` |
| 部门成员列表 | `crm members '{"departmentIds":{departmentId},"current":1,"pageSize":500}'` |
| 团队成员跟进情况 | 先 `crm page lead`/`crm page opportunity` 按 `departmentId` 取团队资源 ID，再逐条 `crm follow plan|record <module> '{"sourceId":"<模块记录id>","status":"ALL","myPlan":false}'` |
| 团队签约合同 | `crm search contract '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"<时间操作符>","name":"createTime","value":"<时间值>","type":"<时间类型>"},{"value":{departmentId},"operator":"IN","name":"departmentId","multipleValue":true,"type":"TREE_SELECT"}]}}'` |
| 团队开放商机 | `crm page opportunity '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"<时间操作符>","name":"expectedEndTime","value":"<时间值>","type":"<时间类型>"},{"operator":"NOT_EQUALS","name":"stage","value":"SUCCESS"},{"operator":"NOT_EQUALS","name":"stage","value":"FAIL"},{"value":{departmentId},"operator":"IN","name":"departmentId","multipleValue":true,"type":"TREE_SELECT"}]}}'` |
| 团队赢单/输单商机 | `crm page opportunity '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"<时间操作符>","name":"actualEndTime","value":"<时间值>","type":"<时间类型>"},{"operator":"EQUALS","name":"stage","value":"<SUCCESS 或 FAIL>"},{"value":{departmentId},"operator":"IN","name":"departmentId","multipleValue":true,"type":"TREE_SELECT"}]}}'` |
| 某成员结果类商机 | `crm page opportunity '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"<时间操作符>","name":"actualEndTime","value":"<时间值>","type":"<时间类型>"},{"operator":"EQUALS","name":"stage","value":"<SUCCESS 或 FAIL>"},{"operator":"EQUALS","name":"owner","value":"{userId}"}]}}'` |
| 团队签约排名 | 遍历成员，逐人查询本月签约合同（取 total+金额） |
| 待审批巡检 | `crm approval todo count` → `crm approval todo pending` |
| 团队回款总额 | `crm aggregate contract/payment-record recordAmount sum '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"<时间操作符>","name":"recordEndTime","value":"<时间值>","type":"<时间类型>"},{"value":{departmentId},"operator":"IN","name":"departmentId","multipleValue":true,"type":"TREE_SELECT"}]}}'` |
| 团队成员回款排名（考核） | 分页拉团队今年回款明细（带 `{departmentId}` 过滤）→ 按 `ownerName` 分组汇总 `recordAmount` → 降序 |

> `{userId}` 获取：按 `core/cli-spec.md §4.2`（dept-children 全量部门 + crm members 带 keyword，取 `userId` 不是 `id`）。`owner` 条件用此 userId。

> 组合规则：结果口径（赢单=SUCCESS 等）与时间字段见 `references/forms/{module}.md`，时间过滤写法见 `core/cli-spec.md §5.4`，聚合做法见 `core/cli-spec.md §9`，经理角色额外带入 `departmentId` 范围条件。

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
