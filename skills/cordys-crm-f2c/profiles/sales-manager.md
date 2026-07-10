# 销售经理角色配置

> 匹配规则见 core/role-engine.md
>
> 匹配关键词：经理、总监、主管、负责人、leader、部长、主任

## 意图路由

> **基础意图路由与流程概要见 `profiles/sales.md`** —— 查重、创建（5 步流程）、更新、批量修改、公海/线索池操作、转换、拜访跟进、**跟进记录/跟进计划录入**、公司打卡，以及查重参数构建、参数校验等规则与销售角色完全一致，本节只列出经理角色的差异。

**经理角色额外意图：**

| 用户意图 | 动作 | 参考文档 |
|---------|------|---------|
| "把 xxx 分配给 yyy" / "派给 xx" | 定位记录 → `crm members` 查用户ID → 确认 → `cordys_ext.sh pool assign` | `core/write-engine.md` §公海/线索池操作 |
| "给 xx 排个跟进计划" / "下周跟进 xx" / "记录一下拜访 xx" | `crm search` 定位记录取 id → `cordys_ext.sh follow-plan`（计划）/ `follow`（记录） | `references/forms/follow-plan.md`、`sop/visit-flow.md` |

> **跟进/计划录入**：经理写跟进记录/跟进计划与销售一致，直接执行。既可给自己排，也可代团队成员排（跟进人 `跟进人`/owner 传目标成员，缺省为当前用户）。
| "查查这笔单子" / "XX公司全景" / "团队某单全链路" | 定位 account/合同 → 跨模块关联追踪（带 `departmentId` 团队范围） | `core/linkage-engine.md`（§3.2 Customer 360 / §3.3 合同全线追踪） |

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
| 团队签约合同 | `crm page contract '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"<时间操作符>","name":"createTime","value":"<时间值>","type":"<时间类型>"},{"value":{departmentId},"operator":"IN","name":"departmentId","multipleValue":true,"type":"TREE_SELECT"}]}}'` |
| 团队开放商机 | `crm page opportunity '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"<时间操作符>","name":"expectedEndTime","value":"<时间值>","type":"<时间类型>"},{"operator":"NOT_IN","name":"stage","value":["SUCCESS","FAIL"],"type":"SELECT"},{"value":{departmentId},"operator":"IN","name":"departmentId","multipleValue":true,"type":"TREE_SELECT"}]}}'` |
| 团队赢单/输单商机 | `crm page opportunity '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"<时间操作符>","name":"expectedEndTime","value":"<时间值>","type":"<时间类型>"},{"operator":"IN","name":"stage","value":["<SUCCESS 或 FAIL>"],"type":"SELECT"},{"value":{departmentId},"operator":"IN","name":"departmentId","multipleValue":true,"type":"TREE_SELECT"}]}}'` |
| 某成员结果类商机 | `crm page opportunity '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"<时间操作符>","name":"expectedEndTime","value":"<时间值>","type":"<时间类型>"},{"operator":"IN","name":"stage","value":["<SUCCESS 或 FAIL>"],"type":"SELECT"},{"operator":"IN","name":"owner","value":["{userId}"],"type":"MEMBER"}]}}'` |
| 团队签约排名 | `crm aggregate contract amount sum '{...带 {departmentId} 过滤...}' --by ownerName`（按签约额降序，每人带合同数 count） |
| 待审批巡检 | `crm approval todo count` → `crm approval todo pending` |
| 团队回款总额 | `crm aggregate contract/payment-record recordAmount sum '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"<时间操作符>","name":"recordEndTime","value":"<时间值>","type":"<时间类型>"},{"value":{departmentId},"operator":"IN","name":"departmentId","multipleValue":true,"type":"TREE_SELECT"}]}}'` |
| 团队成员回款排名（考核） | 在"团队回款总额"命令末尾加 `--by ownerName`，直接返回按 `recordAmount` 降序的成员排名（见 `core/cli-spec.md §10.4`） |

> `{userId}` 获取：`crm members --name 姓名`（服务端过滤，取 `userId` 不是 `id`，详见 `core/cli-spec.md §2.4`）。`owner` 条件用此 userId。

> 组合规则：结果口径（赢单=SUCCESS 等）与时间字段见 `references/forms/{module}.md`，聚合做法见 `core/cli-spec.md §10`。

---

### 团队本周跟进情况 —— 别去 page「follow」

「本周团队跟进了什么/谁跟得多」有两种口径，都**不要** `crm page follow`（follow 不是可 page 的顶层模块，端点不存在会静默返回空，脚本已加 guard 拦截报错）：

- **口径 A：本周被跟进的业务记录 + 跟进人**（最常用、最省事）——直接查业务模块，按 `followTime` 过滤：
  ```
  crm page opportunity '{combineSearch: departmentId IN [...] + followTime DYNAMICS WEEK}' --sort followTime desc
  crm page account     '{同上}'
  crm page lead        '{同上}'      ← 三个模块都要查，别漏 lead
  ```
  结果里 `follower`/`owner` 就是跟进人，按人汇总即得"谁本周跟进多少条"。
- **口径 B：跟进记录明细（内容/方式/时间）**——用 `crm follow record <lead|account|opportunity> '{...}'`（POST `/{module}/follow/record/page`，**必须带父模块**）。⚠️ 跟进记录本身**没有 departmentId 字段**，团队范围只能按 `owner` IN 成员 userId 或 `followTime` 过滤，需先拿成员 userId 列表。

> 默认按口径 A 出"团队本周跟进概览"；用户要具体聊了什么才下钻口径 B。

---

### 赢单分析 —— 标准三步配方（勿现场拼、勿反复试）

「团队某时段赢单情况」是高频诉求，固定走以下最短链路，不要再逐条 page/dist 试错：

```
1. dept-children "<部门名>"                     → 拿部门ID数组（不需要 crm org）
2. crm aggregate opportunity amount sum '{
     "combineSearch":{"searchMode":"AND","conditions":[
       {"value":{departmentId},"operator":"IN","name":"departmentId","multipleValue":true,"type":"TREE_SELECT"},
       {"operator":"IN","name":"stage","value":["SUCCESS"],"type":"SELECT"},
       {"operator":"BETWEEN","name":"expectedEndTime","value":[<毫秒戳起>,<毫秒戳止>],"type":"DATE_TIME"}
     ]}}' --by ownerName                         → 一条出：赢单总额 + 每人排名 + 每人单数 + 合计
3.（可选，要明细清单时才查）crm page opportunity 同条件
```

**三条铁律**（对应踩过的坑）：
1. 时间字段用 **`expectedEndTime`**，**绝不用 `actualEndTime`**（本库大量为空，会少算）。
2. `BETWEEN` 传**毫秒时间戳**，不是字符串日期。上半年=`[1767225600000, 1780127999999]`（2026-01-01 ~ 2026-06-30）。
3. `aggregate --by ownerName` 一条已含合计 + 排名 + 单数，**不要**再补 `dist`/第二次 aggregate；已过滤 `stage=SUCCESS` 后再按 stage 做分布是无意义的。

---

### 查询构造检查清单

构造任何团队查询前，逐项确认：

1. ✅ 已从 Cordys.md 取到部门 ID 数组（无则调 `dept-children`）
2. ✅ `conditions` 中包含 `departmentId` IN 条件
3. ✅ 时间字段选择正确（商机结束时间——赢单/输单/成交/开放——一律用 `expectedEndTime`，新建用 `createTime`；**不用 `actualEndTime`**）
4. ✅ 时间操作符选择正确（相对时间用 DYNAMICS，明确起止区间用 BETWEEN）
5. ✅ `pageSize` 合理（默认 30，需要统计全量时用 200 并检查是否需要翻页）

## L2C 典型工作流

### 日常

#### 团队晨会（"团队今天"）
```
执行流程：
  1. cordys_ext.sh dept-children "<部门名>" → 部门及子部门 ID 数组（或直接读 Cordys.md 的 departmentId 数组）
  2. cordys.sh crm members '{"departmentIds":{departmentId},"pageSize":500}' → 成员列表
  3. 部门线索总量 + 今日新增
  4. 部门商机总量 + 本月新增
  5. 成员跟进率（需遍历成员）
输出：团队看板 + 关键指标 + 异常成员标记
```

#### 审批巡检（"批一下"）
```
执行：
  1. cordys.sh crm approval todo count → 待审批数量
  2. cordys.sh crm approval todo pending → 待审批列表
  3. 对超过 3 天未处理的审批标 ⚠️
输出：待审批列表 + 超期提醒
```

### 周常

#### 周会数据（"团队这周"）
```
执行流程：
  1. 本周 L2C 漏斗快照（见 funnel-engine.md §3.2）
  2. 成员排名表（线索量、签约量、签约金额）
  3. 周环比（本周 vs 上周）
  4. 风险巡检（低跟进率、低转化、长期未跟）
输出：周报数据 + 排名 + 风险列表
```

#### 风险巡检（"有什么问题"）
```
自动扫描（每次查部门数据时触发）：
  1. 团队跟进率 < 60% → 🚨 标记
  2. 某成员连续 2 周期转化偏低 → ⚠️ 标记
  3. 部门目标进度 < 时间进度 → 📊 标记
  4. 长期未跟进客户集中 → 🚨 标记
> 完整风险规则见 core/risk-engine.md §3
```

### 月常

#### 月度复盘（"本月复盘"）
```
执行流程：
  1. 本月漏斗（线索→客户→商机→合同→回款）
  2. 团队成员月度排名
  3. 本月 vs 上月对比
  4. 赢单/输单分析（各阶段商机数量分布）
  5. 签约金额汇总 + 回款预测
输出：月度报告 + 趋势分析 + 改进建议
```

#### 管道预测（"下月预测"）
```
执行：
  1. cordys.sh crm stat-home opportunity/underway '{"searchType":"DEPARTMENT",...}'
     → 进行中商机总金额
  2. 按阶段分组，每个阶段 × 历史转化率
  3. 汇总预计下月签约金额
输出：管道金额 + 阶段分布 + 预测签约额
```

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
| 查看团队成员的跟进记录、代成员创建跟进记录/跟进计划 | — |
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
