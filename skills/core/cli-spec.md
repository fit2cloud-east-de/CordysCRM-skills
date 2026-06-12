# ⚙️ CLI 语义规范

本文件定义了 `cordys` CLI 的全部命令、参数规则和意图映射。
所有 AI 生成的命令必须遵循本规范。

> **目录**
>
> 1. [命令族总览](#1-命令族总览)
> 2. [分页默认结构](#2-分页默认结构)
> 3. [意图 → 命令映射](#3-意图--命令映射)
> 4. [模块推断](#4-模块推断)
> 5. [高级条件处理](#5-高级条件处理)
> 6. [动态参数替换](#6-动态参数替换)
> 7. [排序规则](#7-排序规则)
> 8. [异常处理](#8-异常处理)
> 9. [统计与聚合](#9-统计与聚合)
> 10. [内置视图与自定义视图](#10-内置视图与自定义视图)
> 11. [部门组织架构展开](#11-部门组织架构展开)
> 12. [全局模糊搜索](#12-全局模糊搜索多模块并行)
> 13. [审批操作](#13-审批操作)

> 📖 **完整参考**：字段类型→操作符映射表、详细 JSON 示例、审批 API 完整端点 → 见 `core/cli-reference.md`（仅在构造复杂 conditions 或处理审批时按需加载）。

---

## 1. 命令族总览

所有命令使用 `cordys.sh`（Shell CLI，推荐）执行，`cordys.py` 备用（已弃用）。

```text
cordys.sh crm page    <模块> [关键词|JSON]     分页查询
cordys.sh crm get     <模块> <ID>              获取详情
cordys.sh crm search  <模块> [关键词|JSON]     全局搜索
cordys.sh crm follow  plan|record <模块> <JSON>  跟进计划/记录
cordys.sh crm contact <模块> <ID>              联系人列表
cordys.sh crm product [关键词|JSON]            产品列表
cordys.sh crm aggregate <模块> <字段> <op> [JSON] 聚合计算（sum/avg/count/max/min）
cordys.sh crm org                             组织架构
cordys.sh crm members <JSON>                   部门成员
cordys.sh crm whoami                           当前用户信息
cordys.sh crm verify                           验证 API 密钥
cordys.sh raw          <METHOD> <PATH> [body]  原始 API 调用
```

**审批命令：**

```text
cordys.sh crm approval todo     <类型> [JSON]        审批代办列表
cordys.sh crm approval action   <操作> <JSON>        审批操作
cordys.sh crm approval resource <操作> [参数]         审批资源
cordys.sh crm approval flow     <操作> [参数]         审批流管理
```

> `cordys.sh` 前置路径为 `scripts/cordys.sh`，无需切换目录。

---

## 2. 分页默认结构

所有 page/search 命令使用统一的 JSON body 模板：

```json
{
  "current": 1,
  "pageSize": 30,
  "sort": {},
  "combineSearch": {
    "searchMode": "AND",
    "conditions": []
  },
  "keyword": "",
  "viewId": "ALL",
  "filters": []
}
```

### 自动补全规则
| 条件 | 动作 |
|------|------|
| 只给关键词 | 放入 `keyword`，其余字段填默认值 |
| 给部分 JSON | 补全缺失字段，保留已有字段；若未给 `viewId` 则按语义推断 |
| 给完整 JSON | 原样传递，不修改 |
| 没给任何参数 | 全部默认值 |

---

## 3. 意图 → 命令映射

| 用户说 | 映射命令 | 备注 |
|--------|---------|------|
| 列表、分页查看、看看、有哪些 | `crm page <module>` | 自动追加角色过滤 |
| 搜索、筛选、找一下、找 xxx | `crm search <module> <JSON>` | 关键词→keyword，条件→conditions |
| **模糊搜索（未指定模块）** | **同时搜索 lead, pool/lead, account, opportunity, pool/account, contact** | **见 §11** |
| 详情、查看、打开这个 | `crm get <module> <ID>` | 若有名称无 ID，先搜索 |
| 跟进、跟进计划/记录 | `crm follow <plan\|record> <module> <JSON>` | 需 sourceId |
| 全部、拉全量、查完所有页 | 执行 page，遍历所有页 | 每页后询问是否继续 |
| 原始、自定义 | `cordys raw <METHOD> <PATH>` | 仅限信任域名 |

---

## 4. 模块推断

### 4.1 模块消歧规则

当用户表达可能映射到多个模块时（如"签了多少单"可能是 opportunity 也可能是 contract），按以下优先级决策：

**优先走 `opportunity` 的信号：**
- 涉及赢/输/签单/成交/丢单（这些是商机阶段概念）
- 涉及金额统计但没有明确说"合同""回款""发票"
- 涉及"有效合同额"（这是 opportunity 的字段，不在 contract 模块上）
- 涉及阶段/漏斗/转化

**优先走 `contract` 的信号：**
- 明确说"合同"且语境是合同管理（待签署、已签署、合同到期）
- 涉及回款、收款、到账、欠款
- 涉及发票、开票

**判定口诀**：业绩统计（签了多少、赢了多少、金额排名）→ opportunity；财务管理（回款、发票、合同到期）→ contract/payment-record。

### 4.2 按人名查数据的通用步骤

当用户提到**具体人名**作为过滤条件（如"苗倩倩签了多少单"）时，需要先拿到该人的 `userId`：

```
1. cordys_ext.sh dept-children
   → 不传参数 = 返回全公司所有部门 ID 数组
2. crm members '{"departmentIds":<上一步数组>,"current":1,"pageSize":500,"keyword":"苗倩倩"}'
   → 按姓名搜索，返回匹配的成员
3. 取 userId 字段值
4. 在后续查询的 conditions 中用 {"operator":"EQUALS","name":"owner","value":"{userId}"}
```

> **注意**：`departmentIds` 不能为空数组（API 会报错），必须传 `dept-children` 返回的实际 ID 数组。
>
> **owner 字段规则**：过滤条件用 `owner`（非 `ownerId`），值填 `userId`（非 `id`）。返回记录中 `ownerName` 仅供展示，不可用于过滤。
>
> 如果用户说的是"我的"，直接从 User.md 取 userId，不需要查 members。

### 4.3 模块映射表

| 用户说 | 模块 | 常用命令 |
|--------|------|---------|
| 线索、潜客 | `lead` | page, get, search, follow |
| 客户、公司、厂商 | `account` | page, get, search, follow, contact |
| 商机、机会 | `opportunity` | page, get, search, follow |
| 合同 | `contract` | page, get, search |
| 回款、收款、到账 | `contract/payment-record` | page, aggregate |
| 回款计划、待回款 | `contract/payment-plan` | page（不支持 conditions 过滤，只能无条件查全量） |
| 发票 | `invoice` | page |
| 报价单 | `opportunity/quotation` | page |
| 工商抬头 | `contract/business-title` | page |
| 产品 | 使用 `product` 命令 | product |
| 组织、部门 | `org` | org |
| 成员、人员 | `members` | members |
| 联系人 | `contact` | contact |
| 线索池 | `pool/lead` | page（需 poolId） |
| 公海 | `pool/account` | page（需 poolId） |

---

## 5. 高级条件处理

### 5.1 两种过滤方式

| 方式 | 位置 | 适用场景 |
|------|------|---------|
| `combineSearch.conditions` | JSON body 内 | **推荐**。支持 AND/OR 组合、所有字段类型、所有操作符 |
| `filters` | JSON body 内下层数组 | 仅支持基础操作符（equals/contains/gte/lte），不建议复杂场景使用 |

> **最佳实践**：所有筛选条件统一放入 `combineSearch.conditions`，`filters` 保持为空数组。

### 5.2 conditions 结构

```json
{
  "value": "xxx",           // 条件值（字符串、数字、布尔、数组）
  "operator": "EQUALS",     // 操作符（大写枚举）
  "name": "fieldName",      // 字段名（查询字段参考中的 API 字段标识，大小写敏感）
  "multipleValue": false,   // 是否允许多值
  "type": "INPUT"           // 字段类型（决定哪些操作符可用）
}
```

**name 字段规则：** `name` 只能填查询字段参考中列出的字段标识（如 `stage`、`owner`、`departmentId`、`createTime`）。API 返回的展示字段（如 `ownerName`、`stageName`、`departmentName`、`customerName`）仅用于读取结果，不能作为过滤条件。

**value 与 operator 搭配规则：**

| operator | value 类型 | 示例 |
|----------|-----------|------|
| `EQUALS` / `NOT_EQUALS` | 标量（字符串或数字） | `"value": "SUCCESS"` |
| `IN` / `NOT_IN` | 数组 | `"value": ["SUCCESS", "FAIL"]` |
| `BETWEEN` | 二元数组 | `"value": [ts1, ts2]` |
| `CONTAINS` / `NOT_CONTAINS` | 字符串 | `"value": "科技"` |
| `GT` / `LT` / `GE` / `LE` | 标量 | `"value": 50000` |
| `EMPTY` / `NOT_EMPTY` | 不填或 null | |
| `DYNAMICS` | 时间常量字符串 | `"value": "MONTH"` |
```

### 5.3 常用操作符速查

| 场景 | 操作符 | 示例 |
|------|--------|------|
| 精确等于 | `EQUALS` | 名称等于"张三" |
| 模糊包含 | `CONTAINS` | 行业包含"科技" |
| 大于/小于 | `GT` / `LT` | 金额大于50000 |
| 大于等于/小于等于 | `GE` / `LE` | 数量≤10000 |
| 在集合中 | `IN` | 阶段在 [需求确认, 谈判] |
| 区间 | `BETWEEN` | 创建时间在 [ts1, ts2] |
| 动态时间 | `DYNAMICS` | 本月创建的（type=`TIME_RANGE_PICKER`） |
| 为空/不为空 | `EMPTY` / `NOT_EMPTY` | 电话不为空 |

> 📖 **完整操作符列表和字段类型→操作符映射表** → 见 `core/cli-reference.md`。仅在构造 conditions 且不确定 type 字段值时加载。

### 5.4 动态时间过滤

DYNAMICS 用于**相对时间范围**，例如今天、本周、本月、本季度、本年、上月、近 7 天、近 30 天。相对时间直接用 DYNAMICS 表达。

```json
{"value": "MONTH", "operator": "DYNAMICS", "name": "createTime", "type": "TIME_RANGE_PICKER"}
```

| 含义 | value 常量 | 用户说法举例 |
|------|------|-------------|
| 今天 | `TODAY` | 今天、今日、当天 |
| 昨天 | `YESTERDAY` | 昨天、昨日 |
| 本周 / 上周 | `WEEK` / `LAST_WEEK` | 这周、这个星期、上周 |
| 本月 / 上月 | `MONTH` / `LAST_MONTH` | 本月、这个月、上月、上个月 |
| 本季度 / 上季度 | `QUARTER` / `LAST_QUARTER` | 本季度、这个季度、上季度 |
| 本年 / 上年 | `YEAR` / `LAST_YEAR` | 今年、本年度、去年 |
| 近 7 天 / 近 30 天 | `LAST_SEVEN` / `LAST_THIRTY` | 最近一周、近7天、最近一个月、近30天 |

自定义天数：`["CUSTOM", 90, "BEFORE_DAY"]`

**字段与 type 规则：**

| 场景 | operator | type | value |
|------|----------|------|-------|
| 相对时间 | `DYNAMICS` | `TIME_RANGE_PICKER` | 时间常量字符串，如 `"MONTH"` |
| 明确起止区间 | `BETWEEN` | `DATE_TIME` | 毫秒时间戳数组，如 `[ts1, ts2]` |

**决策顺序：**

1. 用户说"今天/昨天/本周/上周/本月/上月/本季度/本年/近 7 天/近 30 天"等相对时间 → 用 `DYNAMICS`，value 填上方常量表对应的值。
2. 用户说"上半年/下半年/Q1-Q2/2026-01-01 到 2026-03-31"等明确起止区间（常量表中没有对应值时）→ 用 `BETWEEN` + 毫秒时间戳。
3. BETWEEN 的时间戳由 AI 直接给出，填入毫秒级 `[startTs, endTs]`（北京时间 UTC+8 对应的 Unix 毫秒戳）。
4. 时间字段按业务口径选择：赢单/输单/成交用 `actualEndTime`，开放商机/在跟商机用 `expectedEndTime`，新建用 `createTime`，合同用 `createTime`。

> 操作符与 type 固定搭配：区间用 `BETWEEN` + `DATE_TIME`，相对时间用 `DYNAMICS` + `TIME_RANGE_PICKER`。

**常用时间字段验证表：**

| 模块 | 字段 | DYNAMICS | BETWEEN | 业务口径 |
|------|------|----------|---------|----------|
| `opportunity` | `actualEndTime` | ✅ | ✅ | 赢单/输单/成交时间 |
| `opportunity` | `createTime` | ✅ | ✅ | 新建商机时间 |
| `opportunity` | `expectedEndTime` | ✅ | ✅ | 开放商机预计结束时间 |
| `opportunity` | `updateTime` | ✅ | ✅ | 记录最近修改时间（含阶段变更） |
| `lead` | `createTime` | ✅ | ✅ | 新建线索时间 |
| `lead` | `followTime` | ✅ | ✅ | 线索跟进时间 |
| `account` | `createTime` | ✅ | ✅ | 新建客户时间 |
| `account` | `followTime` | ✅ | ✅ | 客户跟进时间 |
| `contract` | `createTime` | ✅ | ✅ | 合同创建时间 |

### 5.5 组合条件

```json
{
  "combineSearch": {
    "searchMode": "AND",       // AND 或 OR
    "conditions": [
      { "value": "科技", "operator": "CONTAINS", "name": "industry", "type": "INPUT" },
      { "value": "MONTH", "operator": "DYNAMICS", "name": "createTime", "type": "TIME_RANGE_PICKER" }
    ]
  }
}
```

**获取字段类型的方法：**

```bash
cordys.sh raw GET /settings/fields?module=account
cordys.sh crm get account <id>
```

> 📖 `type` 字段决定可用的 `operator`。完整映射表 → `core/cli-reference.md` §2。

---

## 6. 动态参数替换（从 User.md 读取）

| 占位符 | 来源字段 | 示例值 |
|--------|---------|-------|
| `{userId}` | User.md 用户ID | `admin` |
| `{departmentId}` | User.md 部门ID（展开后为数组） | `["dept_a","dept_b"]` |

> 如果 User.md 中没有对应的 ID，则不追加该过滤条件。

---

## 7. 排序规则

```json
{"followTime": "desc"}
{"createTime": "asc"}
```

常用排序字段：`followTime`、`createTime`、`amount`、`stage`

---

## 8. 异常处理

| 响应 | 处理方式 |
|------|---------|
| HTTP 401/403 | 提示密钥可能失效，建议刷新身份 |
| code ≠ 100200 | 读取 message 字段并说明原因 |
| `INVALID_FILTER` | 检查字段名拼写和操作符是否匹配该字段类型 |
| 数据空列表 | 若查询格式正确（字段名存在、操作符匹配字段类型、模块正确）→ 结果为空即是真实结果，直接告知用户并解释可能原因（如角色无此类数据、时间范围内无记录等），**不要反复换格式重试**。仅当接口返回错误码或 INVALID_FILTER 时才排查格式问题 |
| CLI 报错 | 检查环境变量和 .env |
| 接口超时 | 提示稍后重试或减小 pageSize（≤200） |

---

## 9. 统计与聚合

统计不是独立查询路径，而是普通查询的结果处理方式。先按角色 profile 和字段参考构造查询条件，再选择计数、聚合或分组展示。

### 9.1 触发关键词

汇总、总计、合计、总金额、排名、TopN、分布、占比、趋势、环比、同比、漏斗、转化、对比。

### 9.2 执行规则

| 场景 | 做法 |
|------|------|
| 纯计数 | `crm page <module> '{"current":1,"pageSize":1,...}'`，直接读 `data.total` |
| 金额/数值汇总 | 用 `crm aggregate <module> <field> sum '<JSON>'` |
| 平均值/最大/最小 | 用 `crm aggregate <module> <field> avg|max|min '<JSON>'` |
| 分组/排名/趋势 | 若 API 无服务端 group by，按 `pageSize:200` 分页读取必要字段，本地聚合后输出 |

### 9.3 统计口径识别

| 口径 | 识别信号 | 处理方式 |
|------|----------|----------|
| 数量 | 数量、多少个、几条、几单 | `pageSize:1` 读取 `data.total` |
| 金额汇总 | 金额、总额、总金额、累计金额、合计 | `crm aggregate ... sum` |
| 平均值 | 平均、客单价、平均单笔 | `crm aggregate ... avg` 或 `sum/count` |
| 排名 | TopN、排名、前几 | 读取必要字段后排序 |
| 分布 | 分布、占比、各部门、各区域 | 读取必要字段后分组 |
| 趋势 | 趋势、按月、按周、环比、同比 | 按时间分桶后展示 |

### 9.4 本地聚合规则

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

### 9.5 结果口径映射

| 用户口径 | 结果条件 | 时间字段 |
|----------|----------|----------|
| 赢单 / 签单 / 成交 / 已下单 | `stage = SUCCESS` | `actualEndTime` |
| 输单 / 丢单 | `stage = FAIL` | `actualEndTime` |
| 新建商机 | `stage = CREATE` 或新建语义 | `createTime` |
| 开放商机 / 在跟商机 | `stage NOT_IN [SUCCESS, FAIL]` | `expectedEndTime` |
| 合同签约 | 合同模块 | `createTime` |
| 回款 | `contract/payment-record` 模块 | `recordEndTime` |
| 发票 / 开票 | `invoice` 模块 | `createTime` |

### 9.6 聚合字段

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

### 9.7 角色过滤

统计意图优先识别，profile 中的强制过滤条件同步带入。经理角色默认带 `departmentId`；销售角色默认带 `owner`（限定为当前用户）；财务角色默认不带范围限定（看全公司数据），用户指定部门/负责人时再加对应条件。用户明确说"全公司"、"全部"、指定具体 `owner`，或统计口径要求跨部门对比（如"各部门排名""各区域分布"）时，按用户口径构造范围条件。

---

## 10. 内置视图与自定义视图

### 10.1 内置系统视图（直接使用）

| viewId | 含义 | 适用模块 |
|--------|------|---------|
| `ALL` | 全部数据（默认） | 所有模块 |
| `SELF` | 我的数据 | `lead`, `account`, `opportunity`, `contract` |
| `CUSTOMER_COLLABORATION` | 协作客户 | `account` 仅 |

### 10.2 viewId 匹配流程

```
1. 匹配内置视图（"我的"→SELF, "全部"→ALL）
2. 未命中 → 调用 `cordys.sh crm view <module>` 获取自定义视图列表
```

### 10.3 典型语义映射

| 用户说 | viewId |
|--------|--------|
| "全部线索" / "所有线索" | `ALL` |
| "我的线索" / "我负责的线索" | `SELF` |
| "我的客户" | `SELF` |
| "协作客户" | `CUSTOMER_COLLABORATION` |

> 优先使用 viewId 而非自己构造 filters。

---

## 11. 部门组织架构展开（含子部门）

当用户按**部门范围**查询时，**必须自动包含该部门下的所有子部门**。

### 操作流程

```
1. 识别目标部门名称，通过 `cordys.sh crm org` 获取组织架构树
2. 在树中定位该部门节点，递归遍历其所有子节点
3. 收集该部门及所有子孙部门的 ID 列表
4. 构造 departmentId 数组过滤器
```

### 部门范围过滤器标准模式

```json
{
  "combineSearch": {
    "searchMode": "AND",
    "conditions": [
      {
        "value": "{departmentId}",
        "operator": "IN",
        "name": "departmentId",
        "multipleValue": false,
        "type": "TREE_SELECT"
      }
    ]
  }
}
```

执行示例（替换后）：
```json
{"value": ["dept_a", "dept_b", "dept_c"], "operator": "IN", "name": "departmentId", "multipleValue": false, "type": "TREE_SELECT"}
```

| 场景 | 行为 |
|------|------|
| "我部门"、不指定部门 | 使用 User.md 的 `{departmentId}`，展开子部门 |
| 指定具体部门名 | 通过 org 树查找该部门ID，展开子部门 |
| "全公司"、"全部" | 不使用部门过滤，viewId 用 `ALL` |
| 部门没有子部门 | `{departmentId}` = 该部门自己的ID数组 `["dept_x"]` |

---

## 12. 全局模糊搜索（多模块并行）

当用户**未明确指定模块**时，并行搜索 6 个模块：

| 中文名 | 模块名 | 优先级 |
|--------|--------|-------|
| 线索 | `lead` | 🔴 高 |
| 线索池 | `pool/lead` | 🔴 高 |
| 客户 | `account` | 🔴 高 |
| 商机 | `opportunity` | 🟡 中 |
| 公海 | `pool/account` | 🟡 中 |
| 联系人 | `contact` | 🟢 低 |

每个模块使用统一模板，`pageSize: 10`。用后台进程 `&` 并行发起，等待全部完成后合并输出。

### 12.1 模块明确性判定

- 输入含「线索/客户/商机/联系人/线索池/公海」→ 只搜指定模块
- 仅含公司名/人名/联系方式等 → 执行全局模糊搜索

### 12.2 响应处理流程

```
启动搜索
  │
  ├─→ 并行发起 6 个模块的 search 请求
  │
  ├─→ 等待所有请求完成（或超时 15s）
  │    ├─ 成功 → 解析列表数据
  │    └─ 失败 → 记录该模块为"查询失败"，继续处理其他模块
  │
  ├─→ 合并结果，按模块汇总
  │
  └─→ 输出跨模块概览（格式见 output-engine.md §6 多模块搜索输出格式）
```

> **超时处理**：单个模块请求超过 15 秒时放弃该模块，不影响其他模块继续搜索。最终输出中标注"XXX 模块查询超时"。

### 12.3 模块明确性判定规则

> **优先级**：当 `cordys_ext.sh` 可用时，"查一下 xxx"/"查查 xxx"/"有没有 xxx" 优先走 **查重**（`cordys_ext.sh check`），不走全局模糊搜索。仅当用户明确说"搜索"/"列表"/"看看 xxx 的线索/商机"等查询意图时才走本节逻辑。

当用户只说关键词但未显式指定模块时，按以下规则判定是否需要全模块搜索：

| 用户输入 | 判定 | 动作 |
|---------|------|------|
| "查一下 xxx 公司" / "查查 xxx" / "有没有 xxx" | ⚡ 查重优先 | `cordys_ext.sh check '{"客户名":"xxx"}'` |
| "搜索 xxx" / "搜一下 xxx" | ❌ 未指定模块 | **执行 §12 全局模糊搜索** |
| "查一下 xxx 公司的线索" | ✅ 明确指定模块 | 只搜 `lead` |
| "有没有 xxx 相关的联系人" | ✅ 明确指定模块 | 只搜 `contact` |
| "线索池里有没有 xxx" | ✅ 明确指定模块 | 只搜 `pool/lead` |
| "帮我查一下 xxx 这个人" | ⚡ 查重优先 | `cordys_ext.sh check '{"客户名":"xxx"}'` |
| "看看 xxx 项目的商机" | ✅ 明确指定模块 | 只搜 `opportunity` |
| "查手机号 138xxxx" / "搜邮箱" | ⚡ 查重优先 | `cordys_ext.sh check '{"手机":"138xxxx"}'` |

**核心判定原则：**
- "查一下"/"查查"/"有没有" + 公司名/人名/手机号 → **走查重**（cordys_ext.sh check）
- "搜索"/"搜一下" + 关键词 → 走全局模糊搜索
- 用户输入中包含「线索/客户/商机/联系人/线索池/公海」等模块关键词 → 明确指定模块
- 用户说"找找 xxx"但 xxx 后带明确模块词 → 明确指定模块（例："找找 xxx 公司的联系人" → 只搜 contact）

### 12.4 角色感知的搜索范围

| 角色 | 搜索范围偏好 | viewId 规则 |
|------|-------------|-------------|
| 销售 | 全部 6 个模块 | 默认 `ALL`；若含"我的"语义 → `SELF` |
| 销售经理 | 全部 6 个模块 | 默认 `ALL`；部门范围自动扩展 |
| 财务 | 仅 account, contract 相关 | 仅搜索客户 + 合同相关模块 |

> 角色配置在 profiles/{role}.md 中定义，修改角色的 globalSearchModules 即可。

### 12.5 实际执行示例

用户："查一下 华星科技"

```bash
# 查重优先
cordys_ext.sh check '{"客户名":"华星科技"}'
```

用户："搜索 华星科技"

```bash
# 全局模糊搜索 6 个模块
cordys.sh crm search lead '{"keyword":"华星科技","current":1,"pageSize":10}'
cordys.sh crm search account '{"keyword":"华星科技","current":1,"pageSize":10}'
cordys.sh crm search opportunity '{"keyword":"华星科技","current":1,"pageSize":10}'
```

---

## 13. 审批操作

### 13.1 审批意图映射

| 用户说 | 映射命令 |
|--------|---------|
| 我的待审批、看看谁需要我批 | `approval todo pending` |
| 我处理过的审批 | `approval todo processed` |
| 我发起的 | `approval todo initiated` |
| 抄送我的 | `approval todo cc` |
| 有多少待审批 | `approval todo count` |
| 同意/通过这个审批 | `approval action approve` + `resourceId` |
| 驳回/拒绝 | `approval action reject` + `resourceId` + `remark` |
| 退回/打回 | `approval action back` + `resourceId` + `backNodeId` |
| 加签 | `approval action sign` + `resourceId` + `signUserIds` |
| 撤回申请 | `approval action revoke` + `resourceId` |
| 批量同意 | `approval action batch-approve` + `resourceIds` |
| 提交审批/提审 | `approval resource push` + `resourceId` |
| 审批进度 | `approval resource detail <resourceId>` |
| 审批流设置 | `approval flow list` |

### 13.2 审批代办 JSON 结构

和 CRM page 参数结构一致，额外多一个字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `resourceType` | string | 可选：`ALL` / `QUOTATION` / `CONTRACT` / `ORDER` / `INVOICE` |

### 13.3 实际执行示例

```bash
cordys.sh crm approval todo pending '{"current":1,"pageSize":30,"resourceType":"CONTRACT"}'
cordys.sh crm approval todo count
cordys.sh crm approval action approve '{"resourceId":"xxx","remark":"同意"}'
cordys.sh crm approval resource detail RESOURCE_ID
```

> 📖 **审批操作完整 JSON body 结构、审批流管理端点** → 见 `core/cli-reference.md` §4。
