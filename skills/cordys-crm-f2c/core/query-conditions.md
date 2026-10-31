# 🔎 查询条件构造（combineSearch.conditions）

构造任何非空 `conditions`、时间过滤或 SELECT/成员/部门过滤前读本文件。

- operator 与字段类型的完整合法组合表 → `core/cli-reference.md` §1–§2
- 字段真实 `name`、`type`、选项 ID、业务时间口径 → `references/forms/{module}.md`（先执行 `cordys_ext.sh sync-if-needed`，见 `core/query-engine.md`）
- 成员/部门条件的取值方式 → `core/query-members-org.md`

## 1. 两种过滤方式

| 方式 | 位置 | 适用场景 |
|------|------|---------|
| `combineSearch.conditions` | JSON body 内 | **推荐**。支持 AND/OR 组合、所有字段类型、所有操作符 |
| `filters` | JSON body 内下层数组 | 仅支持基础操作符（equals/contains/gte/lte），不建议复杂场景使用 |

所有筛选条件统一放入 `combineSearch.conditions`，`filters` 保持为空数组。`conditions` 和 `searchMode` 只能位于 `combineSearch` 内；放在 payload 顶层会被后端静默忽略并返回全量数据，CLI 会在联网前拒绝。

## 2. conditions 结构

```json
{
  "value": "<按 operator 填标量或数组>",
  "operator": "<按 type 选择，大写枚举>",
  "name": "fieldName",
  "multipleValue": false,
  "type": "<字段真实类型，来自 forms/schema>"
}
```

**name 规则**：只能填 forms「查询字段参考」中列出的字段标识（如 `stage`、`owner`、`departmentId`、`createTime`，或数字 fieldId 如 `1751888184000009`）。API 返回的展示字段（`ownerName`、`stageName`、`departmentName`、`customerName`）只用于读结果，不能作为过滤条件。禁止用"区域""行业"等中文名作为 `name`。

**type 规则**：永远取 forms/schema 的真实类型，不根据 value 形状改写。`stage` 是 `SELECT`，`NOT_IN ["SUCCESS","FAIL"]` 仍写 `type:"SELECT"`；只有字段定义本身为 `SELECT_MULTIPLE` 才用该 type。

**operator 规则**：不得根据"等于"的字面直接填 `EQUALS`。选择类字段（SELECT/RADIO/CHECKBOX/MEMBER/DEPARTMENT/TREE_SELECT/DATA_SOURCE）即使只有一个值也必须用 `IN`/`NOT_IN` 且 value 为数组，例如 `{"value":["SUCCESS"],"operator":"IN","name":"stage","type":"SELECT"}`。

**SELECT/RADIO 的 value**（创建和查询都传选项 ID）：部分字段的选项 value 是雪花 ID（如行业「银行」= `175188949491200001`），填中文标签会**静默返回空结果，不报错**，这是"查到 0 条但其实有数据"的最常见原因。对照见 forms「SELECT 字段可选值」：标注「传 ID」的按 `=` 右侧填，未标注的中文即 ID。forms 尚未同步出 ID 时，临时执行一次 `crm page <module> '{"pageSize":1}'` 从 `optionMap` 读对照，并提醒用户重新同步表单。

**value 与 operator 搭配**：

| operator | value 类型 | 示例 |
|----------|-----------|------|
| `EQUALS` / `NOT_EQUALS` | 文本类字段的标量 | `"value": "张三"` |
| `IN` / `NOT_IN` | 数组；选择类字段必须使用 | `"value": ["SUCCESS", "FAIL"]` |
| `BETWEEN` | 二元数组 | `"value": [ts1, ts2]` |
| `CONTAINS` / `NOT_CONTAINS` | 字符串 | `"value": "科技"` |
| `GT` / `LT` / `GE` / `LE` | 标量 | `"value": 50000` |
| `EMPTY` / `NOT_EMPTY` | 不填或 null | |
| `DYNAMICS` | 时间常量字符串 | `"value": "MONTH"` |

## 3. 常用操作符速查

| 场景 | 操作符 | 示例 |
|------|--------|------|
| 文本字段精确等于 | `EQUALS` | 名称等于"张三" |
| 模糊包含 | `CONTAINS` | 行业包含"科技" |
| 大于/小于 | `GT` / `LT` | 金额大于 50000 |
| 大于等于/小于等于 | `GE` / `LE` | 数量 ≤ 10000 |
| 选择类字段（含单值） | `IN` / `NOT_IN` | 阶段为成功：`["SUCCESS"]` |
| 区间 | `BETWEEN` | 创建时间在 [ts1, ts2] |
| 动态时间 | `DYNAMICS` | 本月创建的（type=`TIME_RANGE_PICKER`） |
| 为空/不为空 | `EMPTY` / `NOT_EMPTY` | 电话不为空 |

## 4. 时间过滤

固定搭配：相对时间用 `DYNAMICS` + `TIME_RANGE_PICKER`；明确起止区间用 `BETWEEN` + `DATE_TIME`（毫秒戳数组）。

### 4.1 相对时间（DYNAMICS）

```json
{"value": "MONTH", "operator": "DYNAMICS", "name": "createTime", "type": "TIME_RANGE_PICKER"}
```

| 含义 | value 常量 | 用户说法举例 |
|------|------|-------------|
| 今天 / 昨天 | `TODAY` / `YESTERDAY` | 今天、今日、当天、昨天 |
| 本周 / 上周 | `WEEK` / `LAST_WEEK` | 这周、这个星期、上周 |
| 本月 / 上月 | `MONTH` / `LAST_MONTH` | 本月、这个月、上月、上个月 |
| 本季度 / 上季度 | `QUARTER` / `LAST_QUARTER` | 本季度、这个季度、上季度 |
| 本年 / 上年 | `YEAR` / `LAST_YEAR` | 今年、本年度、去年 |
| 近 7 天 / 近 30 天 | `LAST_SEVEN` / `LAST_THIRTY` | 最近一周、近 7 天、最近一个月、近 30 天 |

DYNAMICS 的 value **只能是上表字符串常量**。后端把它当字符串解析，传数组（如 `["CUSTOM",90,"BEFORE_DAY"]`）会报 `ClassCastException`。**没有"自定义天数"的 DYNAMICS 写法。**

### 4.2 明确自然日区间（BETWEEN）

"上半年 / Q1–Q2 / 2026-01-01 到 2026-03-31"等常量表没有的区间：先执行 `cordys.sh crm date-range <开始日> <结束日>`，把返回的 `value` 原样放进 `BETWEEN`。

```bash
cordys.sh crm date-range 2026-07-01 2026-07-31
# value = [1782835200000,1785513599999]
```

自然日边界固定按 `Asia/Shanghai`（UTC+8）解释：开始为首日 `00:00:00.000`，结束为末日 `23:59:59.999`。`1782835200000` 是上海时区 `2026-07-01 00:00`，对应 UTC `2026-06-30 16:00Z`，不是 UTC 午夜。**禁止写 `CST`、禁止依赖机器本地时区手算**：GNU `date` 会把 `CST` 当成北美 UTC-6，造成 14 小时偏移。

### 4.3 "早于 N 天 / N 天未更新 / 超过 N 天没跟进"

1. 算出"N 天前同一时刻"的毫秒戳 `tsN`（now − N×86400×1000）；这是相对时长，不使用自然日边界。
2. 用 `LT` + 标量 `tsN` + `DATE_TIME`：`{"value":<ts90>,"operator":"LT","name":"followTime","type":"DATE_TIME"}`（等价 `BETWEEN [0, ts90]`）。
3. **语义补全**：`LT`/`BETWEEN` 不包含字段为 null 的记录。"超过 N 天没跟进"业务上应含"从未跟进"，需**另查一次 `EMPTY` 再相加**：`早于 N 天数 = LT(tsN) + EMPTY(followTime)`。
4. 计数时各条件分别读 `total` 相加，不要靠排序翻页肉眼估。

### 4.4 时间字段按业务口径选择

完整口径只在 `references/forms/{module}.md` 维护；这里只列最常踩的坑：

| 模块 | 字段 | 业务口径 |
|------|------|----------|
| `opportunity` | `expectedEndTime` | 商机结束时间，赢单/输单/成交/开放**一律用它** |
| `opportunity` | `actualEndTime` | ⚠️ 本库大量为空，`BETWEEN`/`LT` 不含 null，用它筛赢单会**少算**。禁用 |
| `opportunity` | `createTime` / `updateTime` | 新建商机 / 最近修改（含阶段变更） |
| `lead` / `account` | `createTime` / `followTime` | 新建 / 跟进时间 |
| `contract` | `createTime` | 合同创建时间 |
| `contract/payment-record` | `recordEndTime` | 实际回款时间；`createTime` 只回答"录入了哪些回款记录" |

### 4.5 排错纪律

时间类查询结果为空或明显偏少时，先检查 `BETWEEN` 的 value：字符串日期查不到；按 `CST`/主机时区算出的毫秒戳会漏掉首日边界。明确自然日区间重新执行 `crm date-range`。**不要因为结果不对就去换时间字段**，尤其别换成 `actualEndTime`。

## 5. 组合条件

```json
{
  "combineSearch": {
    "searchMode": "AND",
    "conditions": [
      { "value": "科技", "operator": "CONTAINS", "name": "industry", "type": "INPUT" },
      { "value": "MONTH", "operator": "DYNAMICS", "name": "createTime", "type": "TIME_RANGE_PICKER" }
    ]
  }
}
```

`searchMode` 为 `AND` 或 `OR`。字段类型来自 forms「查询字段参考」的 `type` 列，或 `crm get <module> <id>` 返回的 `moduleFields`。
