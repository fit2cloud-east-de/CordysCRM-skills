# ⚙️ CLI 语义规范

本文件只定义查询/统计的业务语义、请求体规则、模块能力和意图映射。可执行命令语法以 CLI `help` 为准；condition 合法组合以 `core/cli-reference.md` 为准；写入流程以 `core/write-engine.md` 为准。

## 按需阅读（禁止整文件通读）

本文件很长。**只读与当前意图相关的章节**；不要从 §1 扫到文末。

| 意图 | 最少阅读 | 可选加读 |
|------|----------|----------|
| 列表/搜索/详情（page/search/get） | §1 命令族 + §2 分页与强制规则（2.1–2.5） | §3 意图映射、§4 模块、§5 条件、§7 排序、§9 视图 |
| 人名 → userId / 部门范围 | §2.2、§2.4、§11 | — |
| 线索池 / 公海查询 | §2.5 | §1 写入侧 pool 命令速览 |
| 构造 conditions / 时间过滤 | §5（+ 必要时 `cli-reference.md`） | §6 |
| 统计/汇总/排名/趋势/分布 | `funnel-engine.md` + §2「page 统计」 | 角色 profile 强制条件；纯计数用 `crm page` 的 `data.total`，需遍历时用 `crm page-summary` |
| 全局模糊（未指定模块） | §12 | §3、§4 |
| 审批 | §13（细节 body → `cli-reference.md` §4） | — |
| L2C 链路 / 漏斗 | `linkage-engine.md` / `funnel-engine.md` | 本文件只在需要构造查询条件时按节读取 |
| 模糊工作指令 | `intent-engine.md` | 按路由结果加载目标 engine/profile |
| 写入 create/update/… | **不要靠本文件** → `write-engine.md`；§1 仅命令入口对照 | — |

> **目录**（跳转用，不等于要全读）
>
> 1. [命令族总览](#1-命令族总览)
> 2. [分页默认结构](#2-分页默认结构)
> 3. [意图 → 命令映射](#3-意图--命令映射)
> 4. [模块推断](#4-模块推断)
> 5. [高级条件处理](#5-高级条件处理)
> 6. [动态参数替换](#6-动态参数替换)
> 7. [排序规则](#7-排序规则)
> 8. [异常处理](#8-异常处理)
> 9. [内置视图与自定义视图](#9-内置视图与自定义视图)
> 10. [部门组织架构展开](#11-部门组织架构展开)
> 11. [全局模糊搜索](#12-全局模糊搜索多模块并行)
> 12. [审批操作](#13-审批操作)

```
启动时必加载：
  core/role-engine.md        角色匹配

查询/统计（按上表分节读 cli-spec，勿整篇加载）：
  core/cli-spec.md           仅相关 §
  core/output-engine.md      格式化输出（有数据要展示时）
  core/risk-engine.md        扫描风险（展示数据后）
  core/cli-reference.md      operator/type（构造 conditions 时）
  core/linkage-engine.md     跨模块链路
  core/funnel-engine.md      漏斗/管道
  core/intent-engine.md      模糊指令

写入：
  core/write-engine.md       创建/查重/更新/批量/转化/公海池（唯一权威）
```

---

## 1. 命令族总览

命令语法只以 CLI 自带帮助为准：查询 CLI 运行 `scripts/cordys.sh help`，扩展/写入辅助 CLI 运行 `scripts/cordys_ext.sh help`。本节只区分能力族，不复制完整参数表：

| 能力族 | 入口 | 本文语义章节 |
|--------|------|--------------|
| 列表、详情、搜索、视图、跟进查询 | `cordys.sh crm` | §2–§9、§12 |
| 统计、分布、客户/合同子资源 | `cordys.sh crm` | 跨模块链路读 `core/linkage-engine.md` |
| 用户、组织、审批、受限 raw | `cordys.sh crm/raw` | §2、§11、§13 |
| 创建、更新、批量更新 | `cordys.sh crm` | 仅入口；流程读 `core/write-engine.md` |
| 查重、转化、公海、字段同步 | `cordys_ext.sh` | 仅入口；流程读 `core/write-engine.md` |
| 跟进记录、跟进计划 | `cordys_ext.sh` | 仅入口；流程读 `sop/visit-flow.md` |

> 联系人模块名、owner/SELECT 写法、写入安全和具体参数均由 `core/write-engine.md` 与 CLI help 维护，本文件不重复定义。
> JSON 入参两种传法**：① inline 单引号包裹 `crm page opportunity '{...}'`；② 管道经 stdin `echo '{...}' | crm page opportunity @-`（`@-` 或 `-` 表示从标准输入读，page/search 均支持）。inline 的 JSON **必须以 `{` 开头**，否则会被当成关键词去搜（静默返回空，不是查无数据）。
>
> **管道只允许把请求 JSON 送入 `-`/`@-`，不得处理 CLI 输出。** 禁止在命令后接 `| head`、`| python`、`| grep`，禁止 `2>&1`、`2>/dev/null` 和 `/tmp`/Windows 临时文件二次解析。`head` 会用自己的成功码掩盖上游失败；合并 stderr 会污染 JSON；跨 MSYS/Windows 的临时路径和默认编码不一致。直接读取 CLI 原始 stdout、stderr 和退出码。查询只使用 `page` 或 `page-summary`：看记录/数量用 `page`，跨全量记录计算用 `page-summary`。

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

### page 与 page-summary 二选一

- 看记录、搜索、最近 N 条、分页查看：`crm page <模块> [查询JSON]`。
- 纯计数：仍用 `crm page`，固定传 `pageSize:1`，只读 `data.total`。
- 金额、平均、分组、排名、分布、漏斗、跨期比较：`crm page-summary <模块> <统计JSON> [查询JSON]`。脚本每页 500 条自动翻至 `data.total`，在本地流式聚合，仅返回固定大小摘要。
- 完整全量倾倒或本地文件导出不属于技能能力。用户要求全部明细时，用 `page` 分页展示并建议增加筛选条件，不得临时编写管道或脚本绕过边界。

统计不再使用 `crm stat`、`stat-home`、`aggregate`、`dist` 或各类 statistic 子资源；历史命令仅为兼容保留，不作为统计结论来源。完整规则见 `core/funnel-engine.md`。

**权限上限与查询范围优先级（强制）**：角色 profile 先规定权限上限；在权限内，用户明确指定的本人、具体人、团队/部门或公司范围优先；仅在未指定范围时使用角色默认值。明确范围可以缩小、不能越权扩大：经理问“我的 / 我负责的 / 我名下的”业务记录或“我有哪些 / 我有多少”时必须使用 `viewId:SELF`（无 SELF 时追加当前 owner），不得替换成部门范围；“我的团队 / 我的部门 / 我的下属 / 我们部门”才按部门范围。销售角色查询 lead/account/opportunity/contact 时必须把默认 `viewId:ALL` 覆盖为 `SELF`（或追加当前 owner）。销售要求“全部/所有人/全公司/全部门/某同事”时拒绝扩大范围，不构造 ALL、部门或他人 owner 查询。

> **联系人例外**：联系人列表实际端点是 `/account/contact/page`。CLI 的 `crm search contact` 和 `crm page contact` 已自动映射到该端点；未显式传 `viewId` 时默认 `SELF`，可直接按 `keyword` 搜姓名/手机号。已知客户 ID、需要枚举该客户全部联系人时，才使用 `crm contact account <客户ID>`。

### 2.1 成员查询的 status 过滤规则

`crm members` 的 `status=true`（仅在职）过滤**按场景决定，默认不加**——无脑追加会把停用账号挡在结果外，导致按人名找人时误答"查无此人"（停用账号 `enable=false` 仍在册）。

```json
{"value": true, "operator": "IN", "name": "status", "multipleValue": false, "type": "SELECT"}
```

| 场景 | 行为 |
|------|------|
| **按人名找人 / 取 userId（见 §2.4）** | **不加** status——停用账号也要能查到 |
| 明确要「在职/活跃成员名单」「派单候选人」 | 追加 `status=true` |
| 用户主动指定状态（如"禁用的""离职的"） | 用用户指定的值 |
| 用户给的完整 JSON 已有 `status` 条件 | 原样保留，不覆盖 |

> 此规则**仅适用于 `crm members`**。`status` 是在职过滤；找人是判断"此人在不在册"，必须含停用账号。

### 2.2 ⚠️ 组织查询强制规则

**要拿某部门（含子部门）的全部成员/记录、得到名单或总数时（"有多少人/多少商机"、团队漏斗、部门业绩、成员名单），必须递归展开——取该部门及其所有子孙部门，用 `departmentIds` 数组过滤，不可仅查一级。**

| 场景 | 行为 |
|------|------|
| 统计指定部门（如"销售一部有多少人"） | 从 org 树定位该部门 → 递归收集所有子部门 ID → 用 `departmentIds` 数组过滤 |
| 统计多个部门（如"一部、二部、三部各有多少人"） | **每个部门分别递归展开**，各自收集完整子部门 ID → 按部门维度分别统计 |
| 多个部门汇总（如"一部+二部一共多少人"） | 每个部门递归展开 → 所有 ID 合并为一个数组 → 一次查询汇总 |
| 用户说"我部门" | 从 Cordys.md 取 `departmentId` → 递归展开所有子部门 |
| 用户说"全公司"、"全部" | 仅经理/高管等 profile 明确允许时不追加部门过滤；销售角色拒绝扩大范围 |

**例外**：用户明确说"只看一级"、"不要子部门"时跳过递归。

> 📖 递归展开流程见 §11。**本规则用于"拿某部门（含子部门）的全部成员/记录，得到名单或总数"。**

### 2.3 ⚠️ 模块消歧强制规则

**「签单/金额」类无模块名的表达可能落到多个模块，必须按口径判定，不可凭感觉选：**

| 口径 | 落点 | 触发信号 |
|------|------|---------|
| 业绩 | `opportunity` | 签了/赢了/丢单/成交、金额排名、阶段/漏斗/转化、"有效合同额"（商机字段） |
| 财务 | `contract` / `payment-record` | 明确说"合同"且语境是合同管理（待签/到期）、回款/收款/欠款、发票/开票 |

> **判定口诀**：业绩统计（签了多少、赢了多少、金额排名）→ `opportunity`；财务管理（回款、发票、合同到期）→ `contract`/`payment-record`。

### 2.4 ⚠️ 人名 → userId 解析强制规则

**凡涉及"具体人"（有没有叫 X 的、X 是谁、按人名查、分配派单、改 owner）都必须先在此拿 `userId`。** 用户说"我的"则直接取 Cordys.md 的 userId，不必查 members。

**一条命令，脚本内部搞定部门范围与过滤：**

```
crm members --name <姓名>
   → 服务端按 userName 过滤，直接返回匹配记录，取 userId 字段（不是 id）
   → owner 过滤用 {"operator":"IN","name":"owner","value":["<userId>"],"multipleValue":false,"type":"MEMBER"}
```

`--name` 会自动把姓名下推成服务端条件（`userName CONTAINS`），并在你没指定部门时自动补全公司部门范围（带缓存，全公司 90 部门实测 <2s）。已知对方部门时可加 `'{"departmentIds":["<id>"]}'` 缩小范围、更快。

获取团队名单时优先直接消费精简响应：`crm members '{"departmentIds":["<完整部门及子部门ID>"]}' --compact`。`--compact` 只保留 `userName/userId/departmentName/enable` 和 `total`；已有完整 `departmentIds` 时整条链路只 POST `/user/list` 一次，不再拉部门树。

> **要点：**
> - 查用户的唯一入口是 `crm members --name`；`crm page member`、`crm search user`、`crm fuzzy user`、`crm page org`、`raw .../member/*` 均不存在，遇到空结果时用 `crm members --name` 重试。
> - 姓名过滤交给 `--name`（服务端过滤，又快又准）。
> - 取 `userId` 字段（不是 `id`）；过滤用 `owner` + `userId`，`ownerName` 仅供展示。
> - 真·查无此人的信号：`--name` 返回 `{"list":[],"total":0}` 且 code 100200——公司里有此人（含停用账号）就一定会被命中。
> - `code=100200` 是成功终态：直接解析 stdout，不得重跑同一请求，不得写 `/tmp`、合并 stderr、用正则抠 JSON 或另起 Python 二次解析。无 JSON/非 100200 时只按原始错误报错，不得伪装成空名单。
> - 查询契约会对语义唯一的常见形状错误做联网前归一化，例如删除 `EMPTY/NOT_EMPTY` 的空占位 value，或把 `DATE_TIME + GT/LT` 的单元素毫秒值外层数组/数字字符串还原为整数标量。命令成功且 stderr 标明“已自动归一化/无需重试”时直接使用 stdout，禁止为消除提示重跑。无法无歧义修复时，错误会说明当前值形状和要求的形状；只改被指出的层级一次，不得改字段、换端点或先发无条件查询试探。

> **owner ≠ follower**：`owner`=负责人（记录归属），`follower`=跟进人（当前在跟的人），二者可不同。「我的线索/客户/商机」按归属算，用 `owner`（或 `viewId:SELF`）；`follower` 用于写跟进记录的场景（详见 `references/forms/follow.md`）。

### 2.5 ⚠️ 线索池 / 公海查询强制规则

**术语硬映射：`线索池` = `pool/lead`；`公海` = `pool/account`。** 线索池保存共享线索，公海保存共享客户，两者不是同义词。必须先按用户名词锁定模块，再在该模块中选查询路径和匹配池名。

| 用户明确名词 | 记录类型 | 查询模块 | options 端点 | 跨池搜索端点 |
|------------|---------|---------|-------------|---------------|
| 线索池 | 线索 | `pool/lead` | `/pool/lead/options` | `/global/search/clue_pool` |
| 公海、客户公海 | 客户 | `pool/account` | `/pool/account/options` | `/global/search/customer_pool` |

每个模块都有**两条查询路径**，按目的选，poolId 要求不同：

| 目的 | 命令 | 命中端点 | poolId |
|------|------|---------|--------|
| 看**某个具体池**的记录 | `crm page pool/lead` 或 `crm page pool/account` | `/pool/{module}/page` | **必传**，值为已锁定模块 options 中的目标池 id |
| **跨池按关键词搜** | `crm search pool/lead` 或 `crm search pool/account` | `/global/search/clue_pool` 或 `/global/search/customer_pool` | **不需要**，但需要 `keyword` |

**怎么拿 poolId / 怎么查全部：**

| 场景 | 做法 |
|------|------|
| “东区线索池” | `raw GET /pool/lead/options` → 仅在线索池 options 中按 name 匹配“东区” → `crm page pool/lead`；最新 N 条用 `pageSize:N` + `sort.createTime:desc` |
| “东区公海” | `raw GET /pool/account/options` → 仅在公海 options 中按 name 匹配“东区” → `crm page pool/account`；最新 N 条用 `pageSize:N` + `sort.createTime:desc` |
| “看看线索池” / “公海有哪些” | 前者只使用 `pool/lead`，后者只使用 `pool/account`；可逐池 page，或有 keyword 时用各自的跨池 search |

> **先模块、后池名（强制）**：不同模块可以有同名池，例如线索池和公海都可能叫“东区”。池名只在已经锁定的模块内匹配；目标模块匹配不到或池为空时，列出该模块候选或如实报告空结果，**禁止改查另一模块兜底**。
>
> **池名 vs 字段条件**：“东区公海”中“东区”直接修饰“公海”，默认是池名；“公海里区域是东区”才把“东区”作为记录字段条件。无法判断时询问，不得同时尝试两个模块。
>
> **输出标签（强制）**：查询 `pool/lead` 只能称“线索池”，查询 `pool/account` 只能称“公海”；禁止“线索池（公海）”“公海线索”等混合称呼。
> **工具区分**：查询用 `crm page` / `crm search pool/...`；`cordys_ext.sh pool` 只做 pick / assign / to-pool 等**写**操作，不用于查询。

---

## 3. 意图 → 命令映射

| 用户说 | 映射命令 | 备注 |
|--------|---------|------|
| 列表、分页查看、看看、有哪些、有多少、几个 | `crm page <module>` | 自动追加角色过滤；计数场景加 `"pageSize":1` 只读 `data.total` |
| 总额、金额汇总、合计金额 | `crm page-summary <module> <统计JSON> <查询JSON>` | 基于 page 全量分页，本地对真实数字字段求和；不输出原始明细 |
| 周期对比、环比、同比、趋势 | 对每个互斥区间分别执行 `crm page` 或 `crm page-summary` | 数量读各区间 `data.total`；金额读各区间 `sums`；业务时间字段必须一致 |
| 明确自然日区间转毫秒戳 | `crm date-range <开始日> <结束日>` | 纯本地、无需凭证；两端日期均包含，固定按 `Asia/Shanghai`（UTC+8）生成可直接用于 BETWEEN 的 `value` |
| 搜索、筛选、找一下、找 xxx | `crm search <module> <JSON>` | 关键词→keyword，条件→conditions |
| **模糊搜索（未指定模块）** | **同时搜索 lead, pool/lead, account, opportunity, pool/account, contact** | **见 §12** |
| 详情、查看、打开这个 | `crm get <module> <ID>` | 若有名称无 ID，先搜索 |
| 跟进、跟进计划/记录 | `crm follow <plan\|record> <module> <JSON>` | 需 sourceId（取模块主键），详见 crm-api.md |
| 原始、自定义 | `cordys raw <METHOD> <PATH>` | 仅限信任域名 |
| **创建、新建、添加 + 模块名** | `cordys.sh crm create <module>` | **见 core/write-engine.md** |
| **修改、更新、编辑 + 模块名** | `cordys.sh crm update <module>` | **见 core/write-engine.md** |
| **批量修改** | `cordys.sh crm batch-update <module>` | **见 core/write-engine.md** |
| **线索转客户/商机** | `cordys_ext.sh transform` | **见 core/write-engine.md** |
| **L2C 链路追踪 / Customer 360** | 由链路引擎编排跨模块查询 | **见 `core/linkage-engine.md`** |
| **漏斗分析** | 由漏斗引擎编排统计与明细汇总 | **见 `core/funnel-engine.md`** |

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
| 订单 | `order` | page, page-summary | 统计只走 page 数据源 |
| 工商抬头 | `contract/business-title` | page | |
| 产品 | 使用 `product` 命令 | product | |
| 组织、部门 | `org` | org | 见 §2.2 |
| 成员、人员 | `members` | members | 见 §2.1 + §2.2 + §2.4 |
| 联系人 | `contact`（统一别名）/ `account/contact`（真实路径） | page, search, get, contact, add, update | 读写都自动映射到 `/account/contact/*`；写入归属客户，见下方注 |
| 线索池 | `pool/lead` | page | 见 §2.5 |
| 公海 | `pool/account` | page | 见 §2.5 |

> ⚠️ **联系人**：查询和写入均可使用 `contact` 别名，CLI 会自动映射到 `/account/contact/*`；`account/contact` 仍可作为显式真实模块路径。已知客户 ID 枚举联系人使用 `crm contact account <客户ID>`。

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
  "value": "<按 operator 填标量或数组>", // 条件值（字符串、数字、布尔、数组）
  "operator": "<按 type 选择>",          // 操作符（大写枚举，必须与真实 type 匹配；SELECT/RADIO/CHECKBOX/MEMBER/DEPARTMENT/TREE_SELECT/DATA_SOURCE 只能用 IN/NOT_IN，且 value 必须是数组）
  "name": "fieldName",      // 字段名（查询字段参考中的 API 字段标识，大小写敏感）
  "multipleValue": false,   // 是否允许多值
  "type": "<真实字段类型>"   // 字段类型（从 forms/schema 获取，决定哪些操作符可用）
}
```

> ⚠️ 不得根据“等于”的字面直接填写 `EQUALS`。必须先从 forms/schema 确认字段真实 `type`，再选择合法的 `operator`；选择类字段即使只有一个值也必须使用 `IN` / `NOT_IN` 和数组，例如 `{"value":["SUCCESS"],"operator":"IN","name":"stage","type":"SELECT"}`。

**name 字段规则：** `name` 只能填查询字段参考中列出的字段标识（如 `stage`、`owner`、`departmentId`、`createTime`）。API 返回的展示字段（如 `ownerName`、`stageName`、`departmentName`、`customerName`）仅用于读取结果，不能作为过滤条件。

> ⚠️ **禁止用中文字段名作为 conditions 的 `name`。** 部分字段的 API 标识是数字 ID（如 `1751888184000009`），必须从 `references/forms/{module}.md` 查询字段表的"name（条件用）"列获取，不能用"区域""行业"等中文名称替代。

**SELECT / RADIO 字段的 value 规则（创建和查询都传选项 ID）：**

> 创建（`cordys.sh crm create/update`）时，SELECT 字段在 `moduleFields` 里的 `fieldValue` 传**选项 value/ID**（从 `references/forms/{module}.md`「SELECT 字段可选值」表取，如「高科技和互联网」→ `175188976309600000`；部分选项 value 与中文一致，如「东区」→ `东区`）。
> 查询条件 `combineSearch.conditions` 的 `value` 同样要传**选项 ID**——部分 SELECT 字段（如「行业」）的选项 value 是雪花 ID（如 `银行` = `175188949491200001`），**填中文标签会静默返回空结果，不报错**（这正是"查到 0 条但其实有数据"的常见原因）。
>
> 中文标签 → 选项 ID 的对照见 `references/forms/{module}.md` 的「SELECT 字段可选值」段：标注「查询用 ID」的字段按 `=` 右侧的 ID 填；未标注的字段中文即 ID，直接传中文。若该文档尚未同步出 ID（旧版），可临时查一次 `crm page <module> '{"pageSize":1}'`，从返回的 `optionMap` 里读对照，并提醒用户重新执行表单同步。

**value 与 operator 搭配规则：**

| operator | value 类型 | 示例 |
|----------|-----------|------|
| `EQUALS` / `NOT_EQUALS` | 文本类字段的标量（字符串或数字） | `"value": "张三"` |
| `IN` / `NOT_IN` | 数组；SELECT/RADIO 等选择字段必须使用 | `"value": ["SUCCESS", "FAIL"]` |
| `BETWEEN` | 二元数组 | `"value": [ts1, ts2]` |
| `CONTAINS` / `NOT_CONTAINS` | 字符串 | `"value": "科技"` |
| `GT` / `LT` / `GE` / `LE` | 标量 | `"value": 50000` |
| `EMPTY` / `NOT_EMPTY` | 不填或 null | |
| `DYNAMICS` | 时间常量字符串 | `"value": "MONTH"` |
```

> `value` 是数组不代表字段是多选类型。字段 type 永远取 forms/schema 的真实类型：商机 `stage` 是 `SELECT`，所以 `NOT_IN ["SUCCESS","FAIL"]` 仍使用 `type:"SELECT"`；只有字段定义本身为 `SELECT_MULTIPLE` 时才使用该 type。

### 5.3 常用操作符速查

| 场景 | 操作符 | 示例 |
|------|--------|------|
| 文本字段精确等于 | `EQUALS` | 名称等于"张三" |
| 模糊包含 | `CONTAINS` | 行业包含"科技" |
| 大于/小于 | `GT` / `LT` | 金额大于50000 |
| 大于等于/小于等于 | `GE` / `LE` | 数量≤10000 |
| 选择类字段（含单值） | `IN` / `NOT_IN` | 阶段为成功：`["SUCCESS"]` |
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

1. AI 直接算出"N 天前同一时刻"的毫秒戳 `tsN`（now − N×86400×1000）；这是相对时长，不使用自然日边界。
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
2. 用户说"上半年/下半年/Q1-Q2/2026-01-01 到 2026-03-31"等明确自然日起止区间（常量表中没有对应值时）→ 先执行 `cordys.sh crm date-range <开始日> <结束日>`，再把返回的 `value` 原样用于 `BETWEEN + DATE_TIME`。
3. 自然日边界固定按 `Asia/Shanghai`（UTC+8）解释，开始为首日 `00:00:00.000`，结束为末日 `23:59:59.999`。**禁止使用 `CST` 缩写，也禁止依赖机器本地时区**；GNU `date` 会把 `CST` 当成北美 UTC-6，造成 14 小时偏移。
4. 时间字段按业务口径选择（商机结束时间——赢单/输单/成交/开放——**一律用 `expectedEndTime`**、新建/合同用 `createTime` 等）——完整口径见 `references/forms/{module}.md`，避免在此重复维护。

```bash
# 2026 年 7 月（两端日期均包含）
cordys.sh crm date-range 2026-07-01 2026-07-31
# value = [1782835200000,1785513599999]
```

`1782835200000` 表示 `2026-07-01 00:00 Asia/Shanghai`，换算成 UTC 是 `2026-06-30 16:00Z`，**不是 UTC 午夜**。Unix 毫秒戳本身没有时区；时区只参与日期文本到时间戳的转换。

> 操作符与 type 固定搭配：区间用 `BETWEEN` + `DATE_TIME`，相对时间用 `DYNAMICS` + `TIME_RANGE_PICKER`。

> ⚠️ **时间区间查询结果异常时的排错纪律**：赢单/时间类查询结果为空或明显偏少时，先检查 `BETWEEN` 的 value：字符串日期会查不到；合法但按 `CST`/主机时区算出的毫秒戳会漏掉首日边界。明确自然日区间必须重新执行 `crm date-range`，例如 2026 年 7 月应为 `[1782835200000,1785513599999]`。**不要因为结果不对就去换时间字段**（尤其别换成 `actualEndTime`，见下方验证表）。

**常用时间字段验证表：**

| 模块 | 字段 | DYNAMICS | BETWEEN | 业务口径 |
|------|------|----------|---------|----------|
| `opportunity` | `expectedEndTime` | ✅ | ✅ | 商机结束时间（赢单/输单/成交/开放统一用它） |
| `opportunity` | `createTime` | ✅ | ✅ | 新建商机时间 |
| `opportunity` | `actualEndTime` | ✅ | ✅ | ⚠️ **该字段本库大量为空**，`BETWEEN`/`LT` 不含 null 记录（见本节决策顺序末尾），用它筛赢单会漏掉大批记录导致**少算、结果偏低**。**赢单/输单/成交/开放的时间过滤一律用 `expectedEndTime`，禁用 `actualEndTime`** |
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

### 9.1 模块视图目录

每个模块的官方内置视图与实例自定义视图都维护在 `references/forms/{module}.md` 的「视图目录」中。官方项由 Skill 静态维护，自定义项由 `cordys_ext.sh sync` 从该模块 `/view/list` 自动刷新；不同模块不得共用一张假定一致的视图表。

### 9.2 viewId 匹配流程

```
1. 读取目标模块 forms 的「视图目录」
2. 应用角色 profile 的权限上限，禁止越权扩大
3. 解析用户明确范围：本人→SELF/当前 owner，具体人→该 owner，团队/部门→部门及子部门；“我的团队/我的部门”不是 SELF
4. 用户未指定范围时，才应用角色默认范围；经理默认部门不能覆盖明确的 SELF
5. 官方视图语义直接匹配该模块内置项
6. 只有用户明确引用已有视图时，才精确匹配实例自定义视图；多项同名或未命中时不得猜 ID
7. 普通业务短语可转换成字段条件时，默认构造 conditions，不因名称相似而套用自定义视图
```

### 9.3 典型语义映射

| 用户说 | viewId |
|--------|--------|
| "全部线索" / "所有线索" | profile 允许全量时才用 `ALL`；销售角色仍为 `SELF` 并说明范围 |
| "我的线索" / "我负责的线索" | `SELF` |
| "我有哪些超过 7 天没跟进的线索"（经理也一样） | `SELF`；时间条件另行构造，不加 `departmentId` |
| "我的客户" | `SELF` |
| "我的团队 / 我的部门有哪些线索" | 不是 SELF；经理使用 `ALL` + 部门及子部门条件 |
| "协作客户" | `CUSTOMER_COLLABORATION` |
| "成交商机" | `OPPORTUNITY_SUCCESS` |
| "打开‘本月新线索’视图" | 精确匹配 lead forms 的实例自定义视图名称 |
| "看本月新线索" | 默认按线索创建时间构造本月条件，不自动匹配同名自定义视图 |

> 用户明确指定视图时优先使用 `viewId`；普通业务筛选使用 `combineSearch.conditions`。自定义视图不能取消当前 profile 的 SELF/owner/部门强制范围。

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
| "全公司"、"全部" | 仅当前 profile 允许全公司范围时不使用部门过滤并用 `ALL`；销售角色拒绝扩大范围 |
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
| 联系人 | `contact`（CLI 自动走 `/account/contact/page`） | 🟢 低 |

每个模块使用统一模板，`pageSize: 10`。用后台进程 `&` 并行发起，等待全部完成后合并输出。

### 模块明确性判定

- 输入含「线索/客户/商机/联系人/线索池/公海」→ 只搜指定模块
- 仅含公司名/人名/联系方式（手机号）等、**无明确"搜索/列出"动词** → **默认走查重（所有角色），不是全局搜索**。首次直接执行标准 JSON：公司名/人名用 `cordys_ext.sh check '{"客户名":"<名称>"}'`，仅手机号用 `cordys_ext.sh check '{"手机":"<手机号>"}'`，不得先传裸字符串试错。查重内部并行搜索 6 个模块，任一分类命中即统一提示“可能存在冲突”，见 `sop/duplicate-check.md`
- 明确说"**搜索/列出** …（不指定模块）"或明确要求全局搜索 → 才执行本节全局模糊搜索

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
