# 统计查询流程

用户意图为统计/汇总/排名/趋势/分布时执行本流程，不走普通查询路径。

触发关键词：汇总、总计、合计、总金额、排名、TopN、分布、占比、趋势、环比、同比、漏斗、转化、对比

---

## 步骤 1：提取统计意图

从用户输入提取：统计类型、目标模块、时间范围、分组维度。

| 用户说 | 统计类型 | 模块 | 时间字段 |
|--------|---------|------|---------|
| "本月赢单金额" | 金额汇总 | opportunity | actualEndTime |
| "本月赢单数量" | 纯计数 | opportunity | actualEndTime |
| "各部门赢单金额" | 分组统计 | opportunity | actualEndTime |
| "赢单 Top5" | 排名 | opportunity | actualEndTime |
| "近3个月赢单趋势" | 趋势 | opportunity | actualEndTime |
| "本月新建线索数" | 纯计数 | lead | createTime |

> 统计字段选择见 `references/forms/opportunity.md`「统计字段速查」。

未明确时间范围时追问："您要看哪个时间段的？本月/本季度/本年？"

---

## 步骤 2：构造查询条件

### 2.1 时间过滤

首选 DYNAMICS（有对应常量时）：

```json
{"operator":"DYNAMICS","name":"actualEndTime","value":"MONTH","type":"TIME_RANGE_PICKER"}
```

DYNAMICS 报错或无对应常量时，直接用 BETWEEN + 时间戳值：

```json
{"operator":"BETWEEN","name":"actualEndTime","value":[1748707200000,1751299199000],"type":"DATE_TIME"}
```

> 时间戳值由 AI 直接给出，不需要写代码计算。DYNAMICS 覆盖了大部分场景（MONTH/YEAR/QUARTER/LAST_MONTH/LAST_SEVEN/LAST_THIRTY），仅上半年/下半年等少数场景需要 BETWEEN。

> ⚠️ 常见错误：`RANGE` 不是合法操作符（用 `BETWEEN`）；`DATETIME` 不是合法 type（用 `DATE_TIME`）

### 2.2 时间字段选择

| 查询场景 | 时间字段 |
|---------|---------|
| 赢单/输单/成交 | actualEndTime |
| 新建商机/线索 | createTime |
| 合同签约 | signTime |

> 详见 `references/forms/opportunity.md`「时间维度筛选规则」。

### 2.3 部门过滤

| 用户说法 | 部门过滤 |
|---------|---------|
| "本月赢单"（默认） | 本部门 departmentId（经理强制） |
| "全公司本月赢单" | 无 departmentId |
| "各部门本月赢单" | 无 departmentId，拉全量后按 departmentId 分组 |

> 部门 ID 获取：`cordys_ext.sh dept-children <部门名>`

---

## 步骤 3：获取数据

### 纯计数

```bash
cordys.sh crm page opportunity '{"current":1,"pageSize":1,"combineSearch":{"conditions":[...]},"viewId":"ALL"}'
```

→ 读 `data.total` 即为计数，**不需要拉明细**

- total = 0 → 告知用户"该时间段无数据"，结束
- total > 0 → 输出计数结果

### 金额汇总 / 分组统计

先查 total：

```bash
cordys.sh crm page opportunity '{"current":1,"pageSize":1,"combineSearch":{"conditions":[...]},"viewId":"ALL"}'
```

- total = 0 → 告知用户"该时间段无数据"，结束
- total ≤ 200 → 单页拉取明细（pageSize:200），AI 本地聚合
- total > 200 → 用 aggregate 命令：

```bash
cordys.sh crm aggregate opportunity 1751888184000041 sum '{"combineSearch":{"conditions":[...]}}'
# → {"op":"sum","field":"1751888184000041","value":3200000,"count":47}
```

---

## 步骤 4：聚合计算 + 值映射

### 纯计数 → 直接用 total

### 金额汇总 → aggregate 返回结果，或 AI 累加明细

### 分组统计 → AI 按指定字段分组

分组字段优先用 API 返回的语义化顶层字段名：

| 分组字段 | 顶层字段名 | 需要额外映射吗 |
|---------|-----------|--------------|
| 负责人 | ownerName | ❌ 直接用 |
| 部门 | departmentName | ❌ 直接用 |
| 阶段 | stageName | ❌ 直接用 |
| 区域/行业 | moduleFields 中的 fieldId | 从 optionMap 提取映射 |

---

## 步骤 5：格式化输出

| 统计类型 | 展示方式 |
|---------|---------|
| 纯计数 | 单行数字 + 同比/环比（如有） |
| 金额汇总 | 金额 + 计数 + 平均值 |
| 排名 | 表格 ≤5 列，≤10 条 |
| 分组汇总 | 表格：分组列 + 指标列 + 合计行 |
| 趋势 | 按时间排列的表格 |

> 统计场景下允许表格超过 5 列，但不超过 8 列。

---

## 完整示例

**用户**："本月我部门赢单金额汇总"

**步骤 1** — 提取：金额汇总，opportunity，本月，本部门

**步骤 2** — 构造条件：

```bash
cordys_ext.sh dept-children 苏皖线下团队
# → ["1131998760411191"]
```

**步骤 3** — 获取数据：

```bash
cordys.sh crm page opportunity '{"current":1,"pageSize":1,"combineSearch":{"searchMode":"AND","conditions":[{"operator":"DYNAMICS","name":"actualEndTime","value":"MONTH","type":"TIME_RANGE_PICKER"},{"operator":"IN","name":"stage","value":["SUCCESS"],"type":"SELECT"},{"value":["1131998760411191"],"operator":"IN","name":"departmentId","multipleValue":false,"type":"TREE_SELECT"}]},"viewId":"ALL"}'
```

→ total=47，需要拉明细

```bash
cordys.sh crm aggregate opportunity 1751888184000041 sum '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"DYNAMICS","name":"actualEndTime","value":"MONTH","type":"TIME_RANGE_PICKER"},{"operator":"IN","name":"stage","value":["SUCCESS"],"type":"SELECT"},{"value":["1131998760411191"],"operator":"IN","name":"departmentId","multipleValue":false,"type":"TREE_SELECT"}]}}'
```

→ {"op":"sum","field":"1751888184000041","value":3200000,"count":47}

**步骤 4** — 聚合：aggregate 已返回结果

**步骤 5** — 输出：

```
本月苏皖线下团队赢单汇总：
- 赢单金额：320万元
- 赢单数量：47笔
- 平均单笔：6.8万元
```
