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
> 9. [统计与聚合](#9-统计与聚合)（口径→做法、取数路径、`crm dist`、分页聚合）
> 10. [视图过滤](#10-视图过滤viewid)
> 11. [部门组织架构展开](#11-部门组织架构展开)
> 12. [全局模糊搜索](#12-全局模糊搜索多模块并行)
> 13. [审批操作](#13-审批操作)

```
启动时必加载：
  core/role-engine.md        角色匹配

L2C 场景按需加载：
  core/cli-spec.md           构造命令（每次必用）
  core/output-engine.md      格式化输出（每次必用）
  core/risk-engine.md        扫描风险（展示数据后）
  core/cli-reference.md      字段类型映射（构造 conditions 时）
  core/linkage-engine.md     跨模块关联追踪（追踪链路时）
  core/funnel-engine.md      漏斗分析（看转化/管道时）
  core/intent-engine.md      意图路由（模糊指令时）

写入场景按需加载：
  core/write-engine.md        创建/更新/转化操作
  rules/form-rules/{module}.md  自定义表单校验规则（存在则加载）
  rules/field-mapping/{场景}.md 自定义字段映射（存在则加载）
  rules/business-rules/{模块}.md 自定义业务规则（存在则加载）
```

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
cordys.sh crm dist <模块> <枚举字段> [JSON|-] [值列表] 枚举字段分布（脚本内逐桶聚合；条件 JSON 可直接内联，含中文亦可；optionMap 自动取值，stage 等系统码值传逗号值列表）
cordys.sh crm view     <模块>                   列出可用视图定义（不返回业务数据，仅返回 viewId 列表）
cordys.sh crm org                             组织架构
cordys.sh crm members <JSON>                   部门成员
cordys.sh crm whoami                           当前用户信息
cordys.sh crm verify                           验证 API 密钥
cordys.sh raw          <METHOD> <PATH> [body]  原始 API 调用
```

**写入命令（创建/更新/转化）：**

```text
cordys.sh crm form         <模块>              获取模块表单定义
cordys.sh crm add          <模块> <JSON>        创建记录
cordys.sh crm update       <模块> <JSON>        更新记录（JSON 须含 id）
cordys.sh crm batch-update <模块> <JSON>        按字段批量更新
cordys.sh crm transition   <JSON>               线索转客户
cordys.sh crm transform    <JSON>               线索转换（客户+可选商机）
```

> 联系人通过 `account/contact` 模块名访问（如 `crm add account/contact`）。
> 写入操作完整规范见 `core/write-engine.md`。
> JSON 入参两种传法**：① inline 单引号包裹 `crm page opportunity '{...}'`；② 管道经 stdin `echo '{...}' | crm page opportunity @-`（`@-` 或 `-` 表示从标准输入读，page/search/aggregate 均支持）。inline 的 JSON **必须以 `{` 开头**，否则会被当成关键词去搜（静默返回空，不是查无数据）。

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

### 2.1 ⚠️ 成员查询强制规则

**构造 `crm members` 的 JSON 时，必须默认追加 `status=true`（启用状态）条件。**

```json
{"value": true, "operator": "IN", "name": "status", "multipleValue": false, "type": "SELECT"}
```

| 场景 | 行为 |
|------|------|
| 用户未提及状态 | `combineSearch.conditions` 中自动追加 `status=true` |
| 用户主动指定了状态（如"禁用的"） | 使用用户指定的值，不追加默认条件 |
| 用户给了完整 JSON 且已有 `status` 条件 | 原样保留，不覆盖 |

> 此规则**仅适用于 `crm members`**，不影响其他模块。

### 2.2 ⚠️ 组织查询强制规则

**所有涉及部门/组织的查询，必须递归展开——获取该部门及其所有子孙部门的成员/数据，不可仅查一级。**

| 场景 | 行为 |
|------|------|
| 查询指定部门（如"销售一部有多少人"） | 从 org 树定位该部门 → 递归收集其下所有子部门 ID → 用 `departmentIds` 数组过滤 |
| 查询多个部门（如"一部、二部、三部各有多少人"） | **每个部门分别递归展开**，各自收集完整子部门 ID → 按部门维度分别统计 |
| 查多个部门汇总（如"一部+二部一共多少人"） | 每个部门递归展开 → 所有 ID 合并为一个数组 → 一次查询汇总 |
| 用户说"我部门" | 从 Cordys.md 取 `departmentId` → 递归展开所有子部门 |
| 用户说"全公司"、"全部" | 不追加部门过滤，直接查全量 |

**例外**：仅当用户**明确**说"只看一级"、"不要子部门"时才跳过递归。

> 📖 递归展开的详细执行流程 → 见 §10。此规则适用于所有模块的部门过滤，尤其是 `crm members` 和 `crm page`。

### 2.3 ⚠️ 模块消歧强制规则

**「签单/金额」类无模块名的表达可能落到多个模块，必须按口径判定，不可凭感觉选：**

| 口径 | 落点 | 触发信号 |
|------|------|---------|
| 业绩 | `opportunity` | 签了/赢了/丢单/成交、金额排名、阶段/漏斗/转化、"有效合同额"（商机字段） |
| 财务 | `contract` / `payment-record` | 明确说"合同"且语境是合同管理（待签/到期）、回款/收款/欠款、发票/开票 |

> **判定口诀**：业绩统计（签了多少、赢了多少、金额排名）→ `opportunity`；财务管理（回款、发票、合同到期）→ `contract`/`payment-record`。

### 2.4 ⚠️ 人名 → userId 解析强制规则

**凡涉及"具体人"（按人名查、分配派单、改 owner）都必须先在此拿 `userId`。** 用户说"我的"则直接取 Cordys.md 的 userId，不必查 members。

**唯一正确路径，严格两步，不要自行发挥：**

```
1. 取全公司部门 ID 数组：Cordys.md 有 departmentId 数组 → 直接用；
   没有 → cordys_ext.sh dept-children（不传  ）
2. crm members '{"departmentIds":<完整数组>,1,"pageSize":500}'
   → 取返回的 userId 字段（不是 id）
   → conditions 用 {"operator":"EQUALS","nam,"type":"MEMBER"}
```

> ⚠️ **查不到人 99% 是下列错误，不是"查无此
> - ❌ 只传部分部门 ID（`members` 只返回所传部门的人）→ 必须用 dept-children 不传参的完整返回，别自己挑/拼
> - ❌ 编造端点：查用户**只有 `crm members`*arch user`、`crm fuzzy user`、`raw
    .../member/*` 等全部静默返回空
> - ❌ 不带 keyword 拉全量本地筛（慢且漏人）
> - ❌ 取 `id` 而非 `userId`、用 `ownerName` ；过滤恒用 `owner` + `userId`
> - 报错 `getDepartmentIds() is null` = 漏传

> **owner ≠follower**：owner=负责人（归属），follower= 同一人。「我的线索/客户/商机」按归属算，用`owner`（或 `viewId:SELF`），别用 follower； `references/forms/follow.md`）。

### 2.5 ⚠️ 线索池 / 公海查询强制规则

**查询走 `cordys.sh crm page pool/lead`（或 `pool/account`），命中 `/pool/{module}/page`。poolId 按需带，不是每次必走：**

| 场景 | 做法 |
|------|------|
| 没指定具体池子（"看看线索池""公海有哪些"） | 直接 `crm page pool/lead`，不带 poolId，返回可见的全部池子记录 |
| 指定了池子名（"东区线索池""华南公海"） | 先 `raw GET /pool/lead/options` 拿池子列表（含 id、name）→ 按 name 匹配取 id → 作为 `poolId` 放进 body：`crm page pool/lead '{"poolId":"<id>","current":1,"pageSize":10,"sort":{"createTime":"desc"}}'`；匹配不到或多个同名时才列 name 让用户选 |

> ⚠️ **池子名是拿去和 options 的 `name` 匹配段塞进 conditions。**
「区域=东区的记录」与「东区这个池子里的记录
> **工具区分**：options / page 用 `cordys.shext.sh pool` 只做 pick / assign / to-pool等**写**操作，不用于查询。

---

## 3. 意图 → 命令映射

| 用户说 | 映射命令 | 备注 |
|--------|---------|------|
| 列表、分页查看、看看、有哪些 | `crm page <module>` | 自动追加角色过滤 |
| 搜索、筛选、找一下、找 xxx | `crm search <module> <JSON>` | 关键词→keyword，条件→conditions |
| **模糊搜索（未指定模块）** | **同时搜索 lead, pool/lead, account, opportunity, pool/account, contact** | **见 §11** |
| 详情、查看、打开这个 | `crm get <module> <ID>` | 若有名称无 ID，先搜索 |
| 跟进、跟进计划/记录 | `crm follow <plan\|record> <module> <JSON>` | 需 sourceId（取模块主键），详见 crm-api.md |
| 全部、拉全量、查完所有页 | 执行 page，遍历所有页 | 每页后询问是否继续 |
| 原始、自定义 | `cordys raw <METHOD> <PATH>` | 仅限信任域名 |
| **创建、新建、添加 + 模块名** | `crm add <module>` | **见 write-engine.md** |
| **修改、更新、编辑 + 模块名** | `crm update <module>` | **见 write-engine.md** |
| **批量修改** | `crm batch-update <module>` | **见 write-engine.md** |
| **线索转客户/商机** | `crm transition` / `crm transform` | **见 write-engine.md** |
| **L2C 链路追踪** | `crm get` 起点 → `crm page` 上下游模块 | **见 §13** |
| **漏斗分析** | 多模块并行 `crm page` → 聚合 | **见 §14** |
| **Customer 360** | 全局搜索 + 多模块 page | **见 §15** |

---

## 4. 模块推断

| 用户说 | 模块 | 常用命令 | ⚠️ 强制规则 |
|--------|------|---------|------------|
| 线索、潜客 | `lead` | page, get, search, follow, add, update | 按人名查/分配/改负责人见 §2.4 |
| 客户、公司、厂商 | `account` | page, get, search, follow, contact, add, update | 按人名查/分配/改负责人见 §2.4 |
| 商机、机会 | `opportunity` | page, get, search, follow, add, update | 业绩/财务消歧见 §2.3 |
| 合同 | `contract` | page, get, search | 消歧见 §2.3 |
| 回款、回款计划 | `contract/payment-plan` | page | 消歧见 §2.3 |
| 回款记录 | `contract/payment-record` | page | 消歧见 §2.3 |
| 发票 | `invoice` | page | |
| 报价单 | `opportunity/quotation` | page | |
| 订单 | `order` | page, statistic | |
| 工商抬头 | `contract/business-title` | page | |
| 产品 | 使用 `product` 命令 | product | |
| 组织、部门 | `org` | org | 见 §2.2 |
| 成员、人员 | `members` | members | 见 §2.1 + §2.2 + §2.4 |
| 联系人 | `contact`（查询）/ `account/contact`（写入） | contact, add, update | 写入归属客户，见下方注 |
| 线索池 | `pool/lead` | page | 见 §2.5 |
| 公海 | `pool/account` | page | 见 §2.5 |

> ⚠️ **联系人**：查询使用 `contact` 模块，写入使用 `account/contact`（因联系人归属客户）。

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

> ⚠️ **禁止用中文字段名作为 conditions 的 `name`。** 部分字段的 API 标识是数字 ID（如 `1751888184000009`），必须从 `references/forms/{module}.md` 查询字段表的"name（条件用）"列获取，不能用"区域""行业"等中文名称替代。

**SELECT / RADIO 字段的 value 规则（创建传中文、查询传 ID）：**

> 创建（`cordys_ext.sh create/update`）时，SELECT 字段传**中文标签**即可（CLI 自动匹配）。
> 但查询条件 `combineSearch.conditions` 的 `value` 要传**选项 ID**——部分 SELECT 字段（如「行业」）的选项 value 是雪花 ID（如 `银行` = `175188949491200001`），**填中文标签会静默返回空结果，不报错**（这正是"查到 0 条但其实有数据"的常见原因）。
>
> 中文标签 → 选项 ID 的对照见 `references/forms/{module}.md` 的「SELECT 字段可选值」段：标注「查询用 ID」的字段按 `=` 右侧的 ID 填；未标注的字段中文即 ID，直接传中文。若该文档尚未同步出 ID（旧版），可临时查一次 `crm page <module> '{"pageSize":1}'`，从返回的 `optionMap` 里读对照，并提醒用户重新执行表单同步。

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

> ⚠️ DYNAMICS 的 value **只能是上表的字符串常量**。后端把它当字符串解析，传数组（如 `["CUSTOM",90,"BEFORE_DAY"]`）会报 `ClassCastException: ArrayList cannot be cast to String`。**没有"自定义天数"的 DYNAMICS 写法。**

**"早于N天 / N天未更新 / 超过N天没跟进"怎么查**（DYNAMICS 常量表里没有的自定义天数）：

1. AI 直接算出"N 天前"的北京时间毫秒戳 `tsN`（now − N×86400×1000）。
2. 用 `LT` + 标量 `tsN` + `DATE_TIME` 查"该时间字段早于 tsN"，例如 90 天未跟进：
   `{"value":<ts90>,"operator":"LT","name":"followTime","type":"DATE_TIME"}`（等价写法 `BETWEEN [0, ts90]`）。
3. ⚠️ **语义补全**：`LT`/`BETWEEN` **不包含该字段为 null 的记录**。"超过N天没跟进"业务上应含"从未跟进"，需**另查一次 `EMPTY` 再相加**：`早于N天数 = LT(tsN) + EMPTY(followTime)`。
4. 计数时各条件分别查 `total` 相加，或本地分页判定，**不要靠排序翻页肉眼估**（漏数、且不含 null）。

**字段与 type 规则：**

| 场景 | operator | type | value |
|------|----------|------|-------|
| 相对时间 | `DYNAMICS` | `TIME_RANGE_PICKER` | 时间常量字符串，如 `"MONTH"` |
| 明确起止区间 | `BETWEEN` | `DATE_TIME` | 毫秒时间戳数组，如 `[ts1, ts2]` |

**决策顺序：**

1. 用户说"今天/昨天/本周/上周/本月/上月/本季度/本年/近 7 天/近 30 天"等相对时间 → 用 `DYNAMICS`，value 填上方常量表对应的值。
2. 用户说"上半年/下半年/Q1-Q2/2026-01-01 到 2026-03-31"等明确起止区间（常量表中没有对应值时）→ 用 `BETWEEN` + 毫秒时间戳。
3. BETWEEN 的时间戳由 AI 直接给出，填入毫秒级 `[startTs, endTs]`（北京时间 UTC+8 对应的 Unix 毫秒戳）。
4. 时间字段按业务口径选择（赢单/输单用 `actualEndTime`、开放商机用 `expectedEndTime`、新建/合同用 `createTime` 等）——完整口径见 `references/forms/{module}.md`，避免在此重复维护。

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

## 6. 动态参数替换（从 Cordys.md 读取）

> ⚠️ Cordys.md 中的值是可信的缓存，**直接使用即可，不要调接口二次验证**。

| 占位符 | 来源字段 | 示例值 |
|--------|---------|-------|
| `{userId}` | Cordys.md 用户ID | `admin` |
| `{departmentId}` | Cordys.md 部门ID（展开后为数组） | `["dept_a","dept_b"]` |

> 如果 Cordys.md 中没有对应的 ID，则不追加该过滤条件。

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
| 数据空列表 | 先排除一类**假空**：条件里有 SELECT/RADIO 字段且 `value` 填的是**中文标签**（如行业填"银行"）→ 改用选项 ID 重试一次（见 §5.2 SELECT value 规则）。排除后，若查询格式正确（字段名存在、操作符匹配字段类型、模块正确、SELECT 值已用 ID）→ 结果为空即是真实结果，直接告知用户并解释可能原因（如角色无此类数据、时间范围内无记录等），**不要再反复换格式重试**。 |
| CLI 报错 | 检查环境变量和 .env |
| 接口超时 | 提示稍后重试或减小 pageSize（≤200） |

---

## 9. 内置视图与自定义视图

### 9.1 内置系统视图（直接使用）

| viewId | 含义 | 适用模块 |
|--------|------|---------|
| `ALL` | 全部数据（默认） | 所有模块 |
| `SELF` | 我的数据 | `lead`, `account`, `opportunity`, `contract` |
| `CUSTOMER_COLLABORATION` | 协作客户 | `account` 仅 |

### 9.2 viewId 匹配流程

```
1. 匹配内置视图（"我的"→SELF, "全部"→ALL）
2. 未命中 → 调用 `cordys.sh crm view <module>` 获取自定义视图列表
```

### 9.3 典型语义映射

| 用户说 | viewId |
|--------|--------|
| "全部线索" / "所有线索" | `ALL` |
| "我的线索" / "我负责的线索" | `SELF` |
| "我的客户" | `SELF` |
| "协作客户" | `CUSTOMER_COLLABORATION` |

> 优先使用 viewId 而非自己构造 filters。

---

## 10. 统计与聚合

> **触发关键词**：汇总、总计、合计、总金额、排名、TopN、分布、占比、趋势、环比、同比、漏斗、转化、对比。

统计不是独立命令，而是普通查询的结果处理方式：先按角色 profile 和 `references/forms/{module}.md` 构造查询条件，再按口径选计数、聚合或分组。各模块的结果口径（赢单=SUCCESS 等）、时间字段、聚合字段一律见 `references/forms/{module}.md`，不在此重复。

### 10.1 口径 → 做法

- **数量**（多少个/几条/几单）：`crm page <module> '{"pageSize":1,...}'` 读 `data.total`。
- **金额/均值**（总额/累计/客单价）：`crm aggregate <module> <field> sum|avg|count|max|min '<JSON>'`。
- **排名/分布/趋势**（TopN/占比/各部门/按月）：按 §9.2 选取数路径。

### 10.2 分组取数路径（拉全量前先选对路径）

按分组键的取值范围决定路径，**本地聚合是兜底、不是默认**：

```
分组键取值范围？
├─ 无分组（纯计数/金额/均值） → crm page 读 total，或 crm aggregate
├─ 有限枚举（stage / 来源 / 行业 / 区域 / 签约类型） → crm dist（§9.3，服务端逐桶）
└─ 无限/未知（ownerName / departmentName / customerName） → 分页本地聚合（§9.4）
```

> 📌 阶段分布/漏斗/卡点走 `crm dist opportunity stage`。"卡在哪个阶段"= count 最大的桶 = 卡点阶段。

### 10.3 枚举字段分布：`crm dist`

分组键是**有限枚举**（SELECT 字段）时，不手工逐桶拼 JSON、也不拉全量本地分组——用 `crm dist`，脚本内部"读枚举值 → 逐桶服务端聚合 → 汇总"，只需传一段范围条件 JSON。

```
cordys.sh crm dist <module> <field> [baseJSON|-] [值列表]
```

- **内联 JSON**：常规用法，条件含中文（区域"东区"、行业名）也直接内联。
- `-`：从 stdin 读（管道场景）。
- `值列表`：逗号分隔，仅当字段不在 optionMap（如系统码值 `stage`）时需要。

> **返回**：`{"data":[{value,name,count,amount}...],"total":{count,amount}}`。amount 走服务端 `/statistic`（opportunity/contract/contract-payment-record/order），其余模块只出 count。排查用 `CORDYS_DIST_DEBUG=1`，stderr 打 `[dist] conds=` 即送达条件数。

```bash
# 商机阶段分布（东区本月）——条件含中文"东区"直接内联
cordys.sh crm dist opportunity stage '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"DYNAMICS","name":"createTime","value":"MONTH","type":"TIME_RANGE_PICKER"},{"operator":"EQUALS","name":"1751888184000030","value":"东区","type":"SELECT"}]}}' 'CREATE,CLEAR_REQUIREMENTS,SCHEME_VALIDATION,PROJECT_PROPOSAL_REPORT,BUSINESS_PROCUREMENT,SUCCESS,FAIL'
```

### 10.4 分页本地聚合流程

分组键取值无限/未知（如回款按 `ownerName`、`departmentName`）、无服务端逐桶接口时，分页拉全量后本地按分组键 sum/count（标准 group-by）。系统约定：

- **`crm pageall`** 一次拉全量（内部读 `total` 逐页翻页，pageSize 200），不要用 `crm page` 自己翻页——`crm page` 只返回一页，total>200 时会被悄悄截断。
- 分组键、指标字段见 §9.5 与 `references/forms/{module}.md`。
- 大结果集只展示 Top 10 + 合计，余按 output-engine 处理。

### 10.5 分组键与时间分桶

- **分组键**：按人→`ownerName`、按部门→`departmentName`、按客户→`customerName`/`name`；按阶段用 §9.3 `crm dist`（不拉全量）；按区域/行业取顶层字段，无则读 `moduleFields`。
- **趋势分桶格式**：天 `2026-06-12`、周 `2026-W24`、月 `2026-06`、季 `2026-Q2`。
- 时间字段（赢单用 `actualEndTime` 等）见 `references/forms/{module}.md`。

---

## 10. 部门组织架构展开（含子部门）⚠️ 强制规则 → §2.2

**所有涉及部门/组织的查询，必须递归展开子部门。仅当用户明确说"只看一级"时才跳过。**

### 核心原则

部门查询 ≠ 查一级。部门是树形结构，"销售一部有多少人" 问的是销售一部**体系内**的所有人。

### 操作流程

> ⚠️ **优先读 Cordys.md**：若 Cordys.md 中已有 `departmentId` 数组（含子部门，已展开），直接使用，**不要调 `dept-children` 或 `crm org`**。仅当 Cordys.md 无此字段、或用户指定了其他部门名称时，才走接口查询。

```
1. Cordys.md 中有 departmentId？
   ├─ 有 → 直接用，跳到步骤 4
   └─ 无 / 用户指定了其他部门名 → 继续
2. 通过 `cordys_ext.sh dept-children [部门名称]` 获取部门及子部门 ID 数组
3. 若 dept-children 权限不足，fallback 到 `cordys.sh crm org` 手动递归
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
| "我部门"、不指定部门 | 使用 Cordys.md 的 `{departmentId}`，递归展开所有子部门 |
| 指定具体部门名（如"销售一部"） | 通过 org 树定位该部门ID，递归展开所有子部门 |
| 指定多个部门（如"一部、二部各多少人"） | 每个部门**分别**递归展开，构造各自的完整 departmentIds |
| "全公司"、"全部" | 不使用部门过滤，viewId 用 `ALL` |
| 部门没有子部门 | `departmentIds` = 该部门自己的ID数组 `["dept_x"]` |

---

## 11. 全局模糊搜索（多模块并行）

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

### 模块明确性判定

- 输入含「线索/客户/商机/联系人/线索池/公海」→ 只搜指定模块
- 仅含公司名/人名/联系方式等 → 执行全局模糊搜索

---

## 12. 审批操作

### 12.1 审批意图映射

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

### 12.2 审批代办 JSON 结构

和 CRM page 参数结构一致，额外多一个字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `resourceType` | string | 可选：`ALL` / `QUOTATION` / `CONTRACT` / `ORDER` / `INVOICE` |

### 12.3 实际执行示例

```bash
cordys.sh crm approval todo pending '{"current":1,"pageSize":30,"resourceType":"CONTRACT"}'
cordys.sh crm approval todo count
cordys.sh crm approval action approve '{"resourceId":"xxx","remark":"同意"}'
cordys.sh crm approval resource detail RESOURCE_ID
```

> 📖 **审批操作完整 JSON body 结构、审批流管理端点** → 见 `core/cli-reference.md` §4。

---

## 13. L2C 链路追踪

> 完整规范见 `core/linkage-engine.md`。本节仅提供命令级摘要。

### 13.1 正向追踪（顺藤摸瓜）

```
1. cordys.sh crm get <module> <id>       获取起点记录（提取关联字段）
2. cordys.sh crm page <target_module>    用关联字段筛选下游数据
3. 逐级向下追踪直到回款/发票
```

### 13.2 反向溯源（追根究底）

```
1. cordys.sh crm get <module> <id>       获取起点记录
2. 提取关联的上游模块字段
3. cordys.sh crm get <upstream_module>   获取上游记录
4. 逐级向上溯源直到线索
```

### 13.3 Customer 360

```
1. 全局搜索公司名（6 模块并行）
2. 锁定 account ID
3. 以 account ID（或公司名）搜索：opportunity, contact, contract
4. 以合同 ID 搜索：payment-plan, invoice
5. 合并输出 360 视图
```

> 完整规范见 `core/linkage-engine.md`。

---

## 14. L2C 漏斗分析

> 完整规范见 `core/funnel-engine.md`。本节仅提供命令级摘要。

### 14.1 漏斗快照

```bash
# 并行查询各阶段本月数据
cordys.sh crm page lead       '{"pageSize":1,"combineSearch":{"conditions":[{"value":"MONTH","operator":"DYNAMICS","name":"createTime","type":"TIME_RANGE_PICKER"}]}}' &
cordys.sh crm page account    '{"pageSize":1,"combineSearch":{"conditions":[{"value":"MONTH","operator":"DYNAMICS","name":"createTime","type":"TIME_RANGE_PICKER"}]}}' &
cordys.sh crm page opportunity '{"pageSize":1,"combineSearch":{"conditions":[{"value":"MONTH","operator":"DYNAMICS","name":"createTime","type":"TIME_RANGE_PICKER"}]}}' &
cordys.sh crm page contract   '{"pageSize":1,"combineSearch":{"conditions":[{"value":"MONTH","operator":"DYNAMICS","name":"signTime","type":"TIME_RANGE_PICKER"}]}}' &
wait
```

> 从各模块响应的 `data.total` 获取计数。

### 14.2 金额汇总

合同/商机金额汇总 → 遍历分页数据，AI 端求和。超过 100 条提示缩小范围。

### 14.3 管道预测

```bash
# 未来 7 天到期回款
cordys.sh crm page contract/payment-plan '{"combineSearch":{"conditions":[
  {"value": [now_ts, now_ts+604800000], "operator": "BETWEEN", "name": "planPayTime", "type": "DATE_TIME"}
]}}'
```

---

## 15. 意图路由与工作流

> 完整规范见 `core/intent-engine.md`。

当用户使用模糊指令（"今天做什么"、"这周怎么样"、"团队情况"）时，AI 自动匹配并路由到对应角色 profile 中的工作流章节。

意图→工作流映射表见 `core/intent-engine.md` §3。写操作（创建/更新/转化）路由到 `core/write-engine.md`。
