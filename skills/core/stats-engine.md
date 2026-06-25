# 📊 统计与聚合引擎

> **加载时机**：用户意图为统计/汇总/排名/趋势/分布/对比时加载。普通查询不加载此文件。
>
> **前置依赖**：本文件中的查询条件构造规则（conditions、时间过滤、operator）遵循 `core/cli-spec.md`。聚合字段和业务术语参考 `references/forms/{module}.md`。

---

统计不是独立查询路径，而是普通查询的结果处理方式。先按角色 profile 和字段参考构造查询条件，再选择计数、聚合或分组展示。

## 1. 触发关键词

汇总、总计、合计、总金额、排名、TopN、分布、占比、趋势、环比、同比、漏斗、转化、对比。

## 2. 执行规则（口径识别 → 做法）

| 口径 | 识别信号 | 做法 |
|------|----------|------|
| 数量 | 数量、多少个、几条、几单 | `crm page <module> '{"pageSize":1,...}'` 读 `data.total` |
| 金额汇总 | 金额、总额、总金额、累计、合计 | `crm aggregate <module> <field> sum '<JSON>'` |
| 平均值 | 平均、客单价、平均单笔 | `crm aggregate ... avg`（或 `sum/count`） |
| 排名 | TopN、排名、前几 | 分页读必要字段，本地汇总后降序 |
| 分布 | 分布、占比、各部门、各区域 | 有限枚举（stage/来源/行业/区域）用 `crm dist`（见 §3.2）；无限分组键才分页读本地分组 |
| 趋势 | 趋势、按月/周、环比、同比 | 分页读必要字段，按时间分桶 |

> 排名/分布/趋势：分组键是**有限枚举**（如 stage/来源/行业）用 `crm dist`（§3.2，脚本内逐桶服务端聚合）；分组键**无限/未知**（如 `ownerName`/`departmentName`）才走 §3.1 本地聚合（`pageSize:200` 分页拉全量）。

## 3. 本地聚合规则

| 统计类型 | 每条记录保留字段 | 聚合动作 | 输出顺序 |
|----------|------------------|----------|----------|
| 排名 | 排名键 + 指标字段 | 先汇总指标，再按指标降序排序 | 取 TopN 或前 10 条 |
| 分布 | 分组键 + 指标字段 | 按分组键累计 count / amount | 按指标降序或名称顺序 |
| 趋势 | 时间字段 + 指标字段 | 按时间桶累计 count / amount | 按时间升序 |

**排序规则：**

| 用户口径 | 排序字段 |
|----------|----------|
| 赢单金额排名 / 部门金额排名 | 汇总金额降序 |
| 赢单数量排名 / 成交数量排名 | 汇总数量降序 |
| 最近跟进 / 最近成交 | 时间字段降序 |
| 趋势图表 / 趋势表 | 时间桶升序 |

**分组键选择：**

| 用户口径 | 分组键 |
|----------|--------|
| 按负责人 / 个人排名 | `ownerName` |
| 按部门 / 各部门 | `departmentName` |
| 按阶段 | `stageName` |
| 按客户 | `customerName` 或 `name` |
| 按区域 / 行业 | 对应字段值；优先取语义化顶层字段，没有时再读 `moduleFields` |

**时间分桶规则：**

| 用户口径 | 时间桶 | 桶键示例 |
|----------|--------|----------|
| 按天 / 近 7 天趋势 | 天 | `2026-06-12` |
| 按周 / 近 8 周趋势 | 周 | `2026-W24` |
| 按月 / 本年趋势 | 月 | `2026-06` |
| 按季度 | 季度 | `2026-Q2` |

时间分桶使用查询条件中的业务时间字段：赢单/输单/成交用 `actualEndTime`，开放商机用 `expectedEndTime`，新建用 `createTime`，合同用 `createTime`。

### 3.1 通用分页本地聚合流程

当分组键取值无限/未知（如回款按人 `ownerName`、按部门 `departmentName`），服务端无逐桶接口时，分组/排名/分布走"分页拉全量 → 本地聚合"标准流程：

```
1. 分页拉取明细（pageSize 200，遍历所有页）：
   crm page <module> '{"current":<页码>,"pageSize":200,"combineSearch":{...范围与时间条件...}}'
   → 先读 data.total 决定页数（total/200 向上取整），逐页拉全
2. 每条提取：分组键（ownerName / departmentName / stageName 等）+ 指标字段（金额或计数）
3. 按分组键聚合：sum(指标) 或 count，并记录每组笔数
4. 按指标降序排列，输出排名/分布表（排名 / 分组 / 指标 / 笔数）
5. 大结果集只展示 Top 10 + 合计，其余按 output-engine 规则处理
```

> 分组键见上方「分组键选择」，时间分桶见「时间分桶规则」，指标字段见 §5 聚合字段。各角色的具体口径（时间字段、金额字段、范围条件）在对应 profile 中按本流程套用。

### 3.2 枚举字段分布：用 `crm dist`

当分组键是**有限枚举**（SELECT 字段，如 opportunity 的 `stage`/`来源`/`行业`/`区域`/`签约类型`）时，**不要手工逐桶拼 JSON、也不必拉全量本地分组**——用 `crm dist`，脚本内部完成"读枚举值 → 逐桶服务端聚合 → 汇总"，你只需传一段范围条件 JSON。

```
cordys.sh crm dist <module> <field> [baseJSON|-] [值列表]
```

  - **内联 JSON 字符串**——常规用法。条件含中文（如区域"东区"、行业名）也直接内联即可，WB 的 `bash.exe -c` 链路按 UTF-8 构造，中文不会损坏。
  - `-`——从 stdin 读（管道场景）。
  - `值列表`——逗号分隔，仅当字段不在 optionMap（如系统码值 `stage`）时需要。

> **返回**：`{"data":[{value,name,count,amount}...],"total":{count,amount}}`。name 是实时中文标签（fieldId 型来自 optionMap，码值型来自记录的 `<field>Name`），不依赖文档里可能漂移的标签。amount 走服务端 `/statistic`（opportunity/contract/contract-payment-record/order），其余模块只出 count。
> 排查用：设 `CORDYS_DIST_DEBUG=1`，stderr 会打 `[dist] raw_bytes=.. conds=..`，`conds` 即送达的条件数（应等于传入的条件个数），`conds=0` 表示条件没送达。
> 📌 **阶段分布/卡点**：`crm dist opportunity stage <baseJSON> <stage值列表>`。"卡在哪个阶段"= count 最大的桶 = 卡点阶段。

**示例：**

```bash
# 商机阶段分布（东区本月）——条件含中文"东区"，直接内联即可
cordys.sh crm dist opportunity stage '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"DYNAMICS","name":"createTime","value":"MONTH","type":"TIME_RANGE_PICKER"},{"operator":"EQUALS","name":"1751888184000030","value":"东区","type":"SELECT"}]}}' 'CREATE,CLEAR_REQUIREMENTS,SCHEME_VALIDATION,PROJECT_PROPOSAL_REPORT,BUSINESS_PROCUREMENT,SUCCESS,FAIL'
```

## 4. 结果口径映射

| 用户口径 | 结果条件 | 时间字段 |
|----------|----------|----------|
| 赢单 / 签单 / 成交 / 已下单 | `stage = SUCCESS` | `actualEndTime` |
| 输单 / 丢单 | `stage = FAIL` | `actualEndTime` |
| 新建商机 | `stage = CREATE` 或新建语义 | `createTime` |
| 开放商机 / 在跟商机 | `stage NOT_IN [SUCCESS, FAIL]` | `expectedEndTime` |
| 合同签约 | 合同模块 | `createTime` |
| 回款 | `contract/payment-record` 模块 | `recordEndTime` |
| 发票 / 开票 | `invoice` 模块 | `createTime` |

## 5. 聚合字段

聚合字段优先使用 API 返回的语义化顶层字段：

| 语义 | 模块 | 字段 |
|------|------|------|
| 商机金额 | `opportunity` | `amount` |
| 合同金额 | `contract` | `amount` |
| 已回款金额 | `contract` | `alreadyPayAmount` |
| 回款记录金额 | `contract/payment-record` | `recordAmount` |
| 发票金额 | `invoice` | `amount` |
| 负责人 | 所有模块 | `ownerName` |
| 部门 | 所有模块 | `departmentName` |
| 阶段 | `opportunity`/`contract` | `stageName` |

示例：

```bash
cordys.sh crm aggregate opportunity amount sum '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"DYNAMICS","name":"actualEndTime","value":"MONTH","type":"TIME_RANGE_PICKER"},{"operator":"IN","name":"stage","value":["SUCCESS"],"type":"SELECT"}]}}'

cordys.sh crm aggregate contract/payment-record recordAmount sum '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"DYNAMICS","name":"recordEndTime","value":"MONTH","type":"TIME_RANGE_PICKER"}]}}'
```

需要数值聚合时优先使用 `crm aggregate`。

## 6. 角色过滤

profile 中标记「强制」的过滤条件同步带入：经理带 `departmentId`、销售带 `owner`（当前用户）、财务不带范围（看全公司）。用户说"全公司/全部"、指定 `owner`、或跨部门对比口径（各部门排名/各区域分布）时按用户口径构造范围。详见各 profile。
