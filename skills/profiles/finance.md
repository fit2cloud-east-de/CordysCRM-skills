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

## 交互模式
- **默认输出**：金额相关字段优先展示，关注统计汇总
- **数据深度**：总额 → 明细 → 单条记录
- **提醒风格**：严谨、数据精确，关注金额和日期
- **行动建议**：回款催收优先级排序、逾期提醒、发票跟进建议

## 异常预警
详见核心引擎 [risk-engine.md §4 财务预警](../core/risk-engine.md)
