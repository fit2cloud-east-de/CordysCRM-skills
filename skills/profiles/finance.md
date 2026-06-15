# 财务角色配置

> 匹配规则见 core/role-engine.md

## 意图路由

| 用户意图 | 动作 | 参考文档 |
|---------|------|---------|
| "本月合同" / "签了多少合同" | 合同列表/统计 | `references/forms/contract.md` |
| "回款多少" / "回款总额" / "回款排名" | 回款记录统计 | `references/forms/payment-record.md` |
| "回款完成率" / "还有多少没收" | 合同金额 vs 已回款对比 | `references/forms/contract.md` |
| "发票" / "开票" | 发票列表 | — |
| "回款计划" / "待回款" | 回款计划列表 | — |
| "各部门合同" / "部门回款排名" | 按部门分组统计 | — |

## 核心关注
- **合同签约**：本月/本季新签合同数量及金额
- **回款跟踪**：实际回款金额、回款完成率（已回/合同额）、逾期未回
- **部门对比**：各部门/负责人的合同额和回款排名
- **发票管理**：开票状态、未开票合同
- **趋势分析**：按月/季度的签约和回款趋势
- **审批关注**：合同/发票/报价单的审批状态、待审批、审批逾期
- **L2C 现金链路**：合同→回款计划→回款记录→发票 全链路追踪

## 默认查询偏好

| 场景 | 推荐命令 |
|------|---------|
| 本月合同列表 | `crm page contract '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"DYNAMICS","name":"createTime","value":"MONTH","type":"TIME_RANGE_PICKER"}]}}'` |
| 本月回款记录 | `crm page contract/payment-record '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"DYNAMICS","name":"recordEndTime","value":"MONTH","type":"TIME_RANGE_PICKER"}]}}'` |
| 回款计划列表 | `crm page contract/payment-plan` |
| 发票列表 | `crm page invoice` |
| 工商抬头 | `crm page contract/business-title` |

> **⚠️ 回款计划限制**：`contract/payment-plan` 不支持 `combineSearch.conditions` 过滤，只能无条件查全量。当前数据量极少（2 条），直接查全量即可。
>
> **⚠️ "回款"语义**：用户说"回款多少""本月回款"指的是**已发生的回款记录**（`contract/payment-record`），不是回款计划（`contract/payment-plan`）。

---

### 统计查询模板

财务角色默认看**全公司**数据，不带部门/负责人限定。用户指定"某部门""某人"时再加对应条件。

| 场景 | 推荐命令 |
|------|---------|
| 本月合同总金额 | `crm aggregate contract amount sum '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"DYNAMICS","name":"createTime","value":"MONTH","type":"TIME_RANGE_PICKER"}]}}'` |
| 本季度合同总金额 | `crm aggregate contract amount sum '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"DYNAMICS","name":"createTime","value":"QUARTER","type":"TIME_RANGE_PICKER"}]}}'` |
| 本月回款总额 | `crm aggregate contract/payment-record recordAmount sum '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"DYNAMICS","name":"recordEndTime","value":"MONTH","type":"TIME_RANGE_PICKER"}]}}'` |
| 本季度回款总额 | `crm aggregate contract/payment-record recordAmount sum '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"DYNAMICS","name":"recordEndTime","value":"QUARTER","type":"TIME_RANGE_PICKER"}]}}'` |
| 回款完成率 | 读取合同列表（含 `amount` 和 `alreadyPayAmount`），计算 `sum(alreadyPayAmount) / sum(amount)` |
| 各部门合同金额排名 | `crm page contract '{"pageSize":200,...}'` → 按 `departmentName` 分组汇总 `amount` |
| 各负责人回款排名 | `crm page contract/payment-record '{"pageSize":200,...}'` → 按 `ownerName` 分组汇总 `recordAmount` |
| 合同签约趋势（按月） | `crm page contract '{"pageSize":200,...}'` → 按 `createTime` 月份分桶，统计数量和金额 |
| 回款趋势（按月） | `crm page contract/payment-record '{"pageSize":200,...}'` → 按 `recordEndTime` 月份分桶 |

> 组合规则：结果口径沿用 `core/stats-engine.md` 的「结果口径映射」，时间口径沿用时间规则，统计处理方式沿用 `core/stats-engine.md`。

---

### 查询构造检查清单

构造财务统计查询前，逐项确认：

1. ✅ 时间字段选择正确（合同用 `createTime`，回款用 `recordEndTime`）
2. ✅ 时间操作符选择正确（相对时间用 DYNAMICS，明确起止区间用 BETWEEN）
3. ✅ 需要金额汇总时用 `crm aggregate`（纯计数用 pageSize:1 读 total）
4. ✅ 排名/分布场景用 `pageSize:200` 分页读取后本地聚合
5. ✅ 用户指定部门/负责人时，额外加 `departmentId` 或 `owner` 条件

---

## L2C 典型工作流

> 详细流程见 `core/workflow-engine.md` §3。

### 日常
1. **回款日报**："今天回款情况" → 今日回款到账 + 今日到期计划 + 逾期汇总
2. **审批处理**："批一下" → 合同/发票待审批列表

### 周常
3. **应收全景**："欠款情况" → 总应收/已逾期/即将到期/正常 分层展示
4. **开票检查**："开票情况" → 已签约未开票合同列表

### 月常
5. **月度财报**："本月财报" → 签约/回款/开票汇总 + 环比
6. **合同→现金链**："某合同回款进度" → 合同→计划→实际回款→发票 四维对照

## KPI 基准线

| 指标 | 正常 | 警戒 | 严重 |
|------|------|------|------|
| 回款率（已回/到期应收） | ≥ 90% | 80-90% ⚠️ | < 80% 🚨 |
| 单笔逾期天数 | ≤ 15 天 | 15-30 天 ⚠️ | > 30 天 🚨 |
| 签约→开票周期 | ≤ 7 天 | 7-15 天 ⚠️ | > 15 天 🚨 |
| 回款计划覆盖率 | ≥ 95% | 85-95% ⚠️ | < 85% 🚨 |
| 单笔逾期金额 | ≤ ¥10 万 | ¥10-50 万 ⚠️ | > ¥50 万 🚨 |
| 应收账款/月签约额比 | ≤ 2x | 2-3x ⚠️ | > 3x 🚨 |

## 跨角色协作

| 触发条件 | 动作 |
|---------|------|
| 合同签约（商务推送） | 自动创建回款计划，提醒 **商务** "开票流程启动" |
| 回款逾期 > 15 天 | 提醒 **销售** "联系客户{名称}确认回款" + 抄送 **经理** |
| 回款逾期 > 30 天，金额 > ¥50 万 | 升级提醒 **高管** "大额逾期需要决策" |
| 发票已开 7 天未回款 | 提醒 **商务** "发票已送达，追踪回款" |
| 签约合同未创建回款计划 | 提醒自己 "补建回款计划" + 提醒 **商务** "合同管理跟进" |
| 季度回款率 < 80% | 提醒 **高管** "公司回款恶化" |

## 权限边界

| 能做 | 不能做 |
|------|--------|
| 查看所有合同和回款数据 | 修改线索/商机数据 |
| 查看所有发票和开票状态 | 审批非财务类审批（如报价审批） |
| 审批财务相关审批（金额、付款） | 查看销售跟进记录和客户沟通内容 |
| 查看工商抬头 | 创建/修改合同条款 |

## 角色内子类型

| 子类型 | 关键词 | 差异 |
|--------|--------|------|
| 应收会计 | 应收、出纳、会计 | 关注回款执行、对账、日常操作 |
| 财务经理 | 财务经理 | 关注回款率趋势、现金流预测、团队管理 |
| 财务总监 | 财务总监、CFO | 关注公司级财务健康、融资决策 |

> 财务总监可能更适合走 `executive` 角色（因为 CFO 在高管匹配关键词中）。可通过 `ROLE_MAP` 精确控制。

## 交互模式
- **默认输出**：金额相关字段优先展示，关注统计汇总
- **数据深度**：总额 → 明细 → 单条记录
- **提醒风格**：严谨、数据精确，关注金额和日期
- **行动建议**：回款催收优先级排序、逾期提醒、发票跟进建议
- **链路视角**：查看合同时自动检查回款计划和发票状态

## 异常预警
详见核心引擎：
- [risk-engine.md §4 财务预警](../core/risk-engine.md#4-财务预警)
- [risk-engine.md §6 L2C 跨模块风险](../core/risk-engine.md#6-l2c-跨模块风险链断裂检测)
