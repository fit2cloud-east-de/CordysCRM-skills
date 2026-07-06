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

> **回款计划查询**：`contract/payment-plan` 支持 `combineSearch.conditions` 过滤，也支持 `crm aggregate`。查未回款用 `planStatus=PENDING`（PENDING=未回款）。应收账款总额一条命令即可，见下方「未回款应收账款」。
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
| 未回款应收账款（"还没回款的钱""应收总额"） | `crm aggregate contract/payment-plan planAmount sum '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"EQUALS","name":"planStatus","value":"PENDING","type":"SELECT"}]}}'`（PENDING=未回款，一条命令直接出总额，勿拉全量本地筛） |
| 回款完成率 | 读取合同列表（含 `amount` 和 `alreadyPayAmount`），计算 `sum(alreadyPayAmount) / sum(amount)` |
| 各部门合同金额排名 | `crm pageall contract '{...}'` → 按 `departmentName` 分组汇总 `amount` |
| 各负责人回款排名 | `crm pageall contract/payment-record '{...}'` → 按 `ownerName` 分组汇总 `recordAmount` |
| 合同签约趋势（按月） | `crm pageall contract '{...}'` → 按 `createTime` 月份分桶，统计数量和金额 |
| 回款趋势（按月） | `crm pageall contract/payment-record '{...}'` → 按 `recordEndTime` 月份分桶 |

> 组合规则：结果口径与时间字段见 `references/forms/{module}.md`（回款见 `references/forms/payment-record.md`），时间过滤写法见 `core/cli-spec.md §5.4`，聚合做法见 `core/cli-spec.md §10`。

---

### 年度回款业绩考核

> 用于"今年大家回款多少""年度回款排名""回款业绩考核"等场景。回款考核按 `recordEndTime`（实际回款日期）口径，年度用 `DYNAMICS` + `YEAR`。

**后端能力边界**：回款无官方「按人/按部门分组」统计接口（`contract/payment-record/statistic` 只返回总额与均值）。按人/按部门排名用 `crm aggregate ... --by`（脚本内拉全量+分组+排序，见 `core/cli-spec.md §10.4`）。

| 场景 | 做法 |
|------|------|
| 今年回款总额 | `crm aggregate contract/payment-record recordAmount sum '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"DYNAMICS","name":"recordEndTime","value":"YEAR","type":"TIME_RANGE_PICKER"}]}}'` |
| 今年各负责人/各部门回款排名（考核） | 在上一行命令末尾加 `--by ownerName`（或 `--by departmentName`），直接返回按 `recordAmount` 降序的排名表 |
| 某人今年回款 | 加 `owner` 条件（userId 查法见 `core/cli-spec.md §2.4`）或本地按 `ownerName` 过滤 |

**考核口径**（按 `core/cli-spec.md §10.4` 分组聚合执行）：范围用 `recordEndTime`+`DYNAMICS`+`YEAR`（实际到账日期，非录入时间 `createTime`）；指标 `recordAmount`（单笔回款额，非合同额 `amount`）；模块 `contract/payment-record`；分组键 `--by ownerName`（按人）或 `--by departmentName`（按部门）。

---

### 查询构造检查清单

构造财务统计查询前，逐项确认：

1. ✅ 时间字段选择正确（合同用 `createTime`，回款用 `recordEndTime`）
2. ✅ 时间操作符选择正确（相对时间用 DYNAMICS，明确起止区间用 BETWEEN）
3. ✅ 需要金额汇总时用 `crm aggregate`（纯计数用 pageSize:1 读 total）
4. ✅ 排名/分布场景用 `crm aggregate ... --by <分组字段>`（脚本内拉全量分组排序，不要自己分页拉明细再聚合）
5. ✅ 用户指定部门/负责人时，额外加 `departmentId` 或 `owner` 条件

---

## L2C 典型工作流

### 日常

#### 回款日报（"今天回款情况"）
```
执行流程：
  1. cordys.sh crm page contract/payment-record '{
       "combineSearch":{"conditions":[
         {"value":"TODAY","operator":"DYNAMICS","name":"paymentTime","type":"TIME_RANGE_PICKER"}
       ]}
     }'
     → 今日回款记录
  2. 今日到期回款计划
  3. 逾期回款汇总
输出：今日回款 + 到期提醒 + 逾期汇总
```

### 周常

#### 应收账款全景（"欠款情况"）
```
执行流程：
  1. cordys.sh crm page contract/payment-plan → 全部回款计划
  2. 筛选状态为"未回款"或"部分回款"
  3. 按到期日排序，逾期优先
  4. 汇总：总应收、已逾期、即将到期（7天内）、正常
输出：AR 全景 + 逾期列表 + 催收优先级
```

#### 开票检查（"开票情况"）
```
执行流程：
  1. cordys.sh crm page invoice
  2. 筛选已签约未开票的合同
  3. 汇总开票缺口金额
输出：已开票列表 + 未开票合同 + 缺口汇总
```

### 月常

#### 合同→现金全链路（"合同回款进度"）
```
执行流程（对指定合同）：
  1. cordys.sh crm get contract {id} → 合同详情
  2. cordys.sh crm page contract/payment-plan → 回款计划
  3. cordys.sh crm page contract/payment-record → 实际回款
  4. cordys.sh crm page invoice → 开票记录
  5. 对比：计划金额 vs 实际回款 vs 开票金额
输出：合同→现金链路图 + 缺口分析
```

#### 月度财报数据
```
执行流程：
  1. 本月签约合同数 + 总金额
  2. 本月回款总额
  3. 本月开票总额
  4. 应收账款余额
  5. 环比数据（本月 vs 上月）
输出：月度财报摘要
```

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
