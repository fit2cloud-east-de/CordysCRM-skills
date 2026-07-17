# 📊 L2C 漏斗分析引擎

本文件定义 L2C 统计、排名、分布和漏斗的统一口径：**所有统计均以各业务模块的 `page` 端点为数据源**。本文件过去使用的 `stat-home`、`stat`、`aggregate`、`dist`、客户级/合同级 statistic 等统计方法全部弃用，不得用于生成统计结论。

弃用原因：这些统计入口的范围、时间桶、过滤条件或服务端预设口径可能与业务明细不一致，曾出现统计数据不全。`page` 返回的业务记录最完整，统计必须建立在相同角色范围和业务条件下的 page 结果上。

---

## 1. 唯一统计路径

### 1.1 只统计数量

只需要记录数时，不拉全量明细。执行普通 `crm page`，强制 `pageSize:1`，读取 `data.total`：

```bash
cordys.sh crm page lead '{"current":1,"pageSize":1,"viewId":"SELF","combineSearch":{"searchMode":"AND","conditions":[]}}'
```

`data.list` 中的一条示例记录不参与计数；最终数量只取 `data.total`。不得用首屏 `data.list` 长度代替总数。

### 1.2 金额、分组、排名和分布

需要遍历记录才能计算时，使用 `crm page-summary`。它仍然逐页调用模块的 `/{module}/page`，每页 500 条，但在本地进程内流式聚合，只向 stdout 返回小型摘要，不输出完整 `data.list`：

```bash
cordys.sh crm page-summary opportunity \
  '{"sum":["amount"],"groupBy":["stage"],"topN":20,"orderBy":"count"}' \
  '{"viewId":"SELF","combineSearch":{"searchMode":"AND","conditions":[]}}'
```

统计 JSON 支持：

| 字段 | 含义 | 约束 |
|------|------|------|
| `sum` | 求和字段数组 | 字段必须在目标模块 schema 中且类型为 `INPUT_NUMBER` |
| `groupBy` | 独立分组字段数组 | 最多 5 个；只允许枚举、成员、部门、数据源、地区等有限维度；每个字段独立分组 |
| `topN` | 每个分组最多返回多少桶 | 默认 20，范围 1–100 |
| `orderBy` | 分组排序 | `count` 或 `sum:<sum 中的字段>` |

响应中的关键字段：

```json
{
  "code": 100200,
  "data": {
    "count": 1200,
    "reportedTotal": 1200,
    "pages": 3,
    "sums": {"amount": 8300000},
    "numericCounts": {"amount": 1200},
    "averages": {"amount": 6916.666666666667},
    "groups": {"stage": [{"key":"SUCCESS","label":"赢单","count":320,"sums":{"amount":4100000}}]},
    "truncatedGroups": {"stage": false},
    "invalidNumeric": {"amount": 0}
  }
}
```

命令只在同时满足 `count=reportedTotal` 且全部求和字段均可解析时返回 `code=100200`，否则直接非零退出。`averages` 的分母是该字段实际存在数值的 `numericCounts`，不是全部记录数；没有数值时返回 `null`。`truncatedGroups=true` 表示只返回了 Top N 桶，不能把可见桶误称为完整分布。

### 1.3 两类命令的唯一分工

运行时查询只在 `page` 和 `page-summary` 之间选择：

| 用户最终要什么 | 命令 |
|---|---|
| 看记录、搜索、最近 N 条、翻页查看、只问记录数量 | `crm page` |
| 对命中范围内的全部记录做总和、平均、分组、分布、排名、漏斗或跨期比较 | `crm page-summary` |

完整全量倾倒、全量 JSON 进入对话或生成运行机器本地导出文件均不属于本技能能力。用户要求“全部列出来/导出所有明细”时，应说明当前只能分页查看，并请其增加筛选条件或按页继续查看；不得临时拼接脚本绕过输出边界。

---

## 2. 统计前的强制规则

1. 先加载目标模块的 `references/forms/{module}.md`，确认真实字段、字段类型、枚举 value 和业务时间字段。
2. 合并查询范围：先遵守角色权限上限，再采用用户明确范围；“我的 / 我负责的 / 我名下的”或“我有多少”使用 SELF/本人 owner，即使当前角色是经理也不加部门条件；“我的团队 / 我的部门 / 团队 / 部门”才让经理使用目标部门及全部子部门。用户未指定范围时才应用角色默认值，用户说“全部”不能扩大角色权限。
3. 当前存量与期间事件分开：当前开放管道通常不加创建时间；本月新增按 `createTime`；赢单按 `opportunity.expectedEndTime`；实际回款按 `contract/payment-record.recordEndTime`。
4. 明确自然日区间先执行 `crm date-range`，再把返回的 UTC+8 毫秒闭区间写入 `BETWEEN`。
5. SELECT 条件必须使用表单选项 value；`IN/NOT_IN` 即使传数组，字段 `type` 仍是字段真实类型。
6. 每个模块分别调用自己的 page；不得用一个模块的 total 推断另一个模块，也不得把独立阶段数量伪装成已关联的 cohort 转化率。

---

## 3. 常用场景

### 3.1 当前开放商机管道

以截至当前的商机明细为准，不自动追加 `createTime`：

```bash
cordys.sh crm page-summary opportunity \
  '{"sum":["amount"],"groupBy":["stage","owner"],"topN":50,"orderBy":"sum:amount"}' \
  '{"viewId":"ALL","combineSearch":{"searchMode":"AND","conditions":[{"name":"stage","operator":"NOT_IN","value":["SUCCESS","FAIL"],"type":"SELECT"}]}}'
```

输出数量、管道金额、阶段分布和负责人排名。用户明确查询团队/部门或未指定范围而采用经理默认值时，必须再加入完整子部门 ID 条件；经理明确查询“我的”时改为 `SELF` 且不加部门条件。销售场景将范围改为 `SELF`。

### 3.2 本期赢单

对 `opportunity` 使用 `stage=SUCCESS`，时间条件落在 `expectedEndTime`，数量和金额来自同一批 page 明细：

```bash
cordys.sh crm page-summary opportunity \
  '{"sum":["amount"],"groupBy":["owner"],"topN":50,"orderBy":"sum:amount"}' \
  '{"viewId":"ALL","combineSearch":{"searchMode":"AND","conditions":[{"name":"stage","operator":"IN","value":["SUCCESS"],"type":"SELECT"},{"name":"expectedEndTime","operator":"BETWEEN","value":[<开始毫秒>,<结束毫秒>],"type":"DATE_TIME"}]}}'
```

### 3.3 实际回款

实际回款只使用 `contract/payment-record.recordEndTime`；金额字段为 `recordAmount`：

```bash
cordys.sh crm page-summary contract/payment-record \
  '{"sum":["recordAmount"],"groupBy":["owner"],"topN":50,"orderBy":"sum:recordAmount"}' \
  '{"viewId":"ALL","combineSearch":{"searchMode":"AND","conditions":[{"name":"recordEndTime","operator":"BETWEEN","value":[<开始毫秒>,<结束毫秒>],"type":"DATE_TIME"}]}}'
```

用户明确问“本期录入的回款记录”时才改用 `createTime`，并在输出中标注这是录入口径而非实际到账口径。

### 3.4 L2C 漏斗快照

线索、客户、商机、合同、回款分别构造 page 查询：

- 只要数量：每个模块用 `crm page ... pageSize:1` 读取 `data.total`。
- 同时要金额或分组：对应模块用 `crm page-summary`。
- 每层必须使用该业务事件自己的时间字段；不要把同一个 `createTime` 条件机械套到所有层。
- 若各层只是独立记录数，输出“阶段快照/独立统计”，不得声称严格转化率。
- 只有通过关联字段建立同一批 cohort（例如线索转化后关联客户/商机）时，才能计算 `下一层关联记录数 ÷ 上一层 cohort 数`；分母为 0 时显示 `—`。

### 3.5 同比、环比和趋势

不再调用首页统计时间桶。为本期、上期或每个趋势时间桶分别构造互斥的 page 条件：

- 只比较数量：每个区间用 `pageSize:1` 的 `data.total`。
- 比较金额：每个区间用 `page-summary` 的 `sums`。
- 增长率：`(本期 - 上期) / 上期`；上期为 0 时显示 `—`，不得显示无穷大。
- 趋势桶边界必须连续、互斥，并使用同一角色范围与同一业务字段。

---

## 4. 大数据量与上下文保护

按以下优先级处理：

1. **能读 total 就不拉明细**：纯计数固定 `pageSize:1`。
2. **能本地聚合就不输出明细**：金额、分布、排名统一使用 `page-summary`。
3. **先过滤再分页**：尽量下推时间、角色、部门、状态等条件，减少网络传输与计算时间；但不得为了变小而改变用户口径。
4. **限制分组输出**：使用 `topN`；必须同时报告总数/总额和“仅展示 Top N”，不能把截断列表当完整结果。
5. **明细只分页展示**：完整名单或大量明细不做全量倾倒；用 `page` 展示当前页，并通过 `data.total` 说明总数，用户需要时继续下一页或增加筛选条件。
6. **失败关闭**：任一分页失败、出现空页但未达到 total、`count != reportedTotal` 或数字字段解析异常时停止统计，不得用已取得的部分页冒充全量结果。

该方案使模型上下文大小由“随记录数增长”变为“随当前页大小或分组 Top N 增长”。`page-summary` 仍需访问全部分页，网络请求量随页数增长；若 CRM 数据在翻页过程中变化，CLI 会在 `total` 变化时失败关闭，但无法替代后端事务快照。

---

## 5. 输出要求

输出格式见 `core/output-engine.md` §9，并至少标注：

- 模块和角色/组织范围；
- 截至当前或明确业务期间；
- 使用的业务时间字段；
- 总数、金额口径和是否 Top N 截断；
- 各层是否为独立快照，还是基于关联 cohort 的真实转化。

统计结果只采信 CLI stdout 中的 `code=100200` 完整摘要。只有“运行成功”而没有响应 JSON，不得生成数字。
