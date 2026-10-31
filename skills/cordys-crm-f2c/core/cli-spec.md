# ⚙️ CLI 语义规范（查询入口）

本文件只定义查询/统计的业务语义、请求体规则、模块能力和意图映射。可执行命令语法以 CLI `help` 为准；condition 构造以 `core/query-conditions.md` 为准，operator/type 合法组合以 `core/cli-reference.md` 为准；写入流程以 `core/write-engine.md` 为准。

> **前置**：查询统一先读 `core/query-engine.md`（生成顺序、`sync-if-needed`、结果核验）。平台/编码/临时文件问题读 `references/platform-notes.md`。

## 按需阅读

本文件只保留所有查询共用的部分。专题按需加载，不要为了一个条件把所有专题都读一遍：

| 意图 | 读哪个文件 |
|------|-----------|
| 列表 / 搜索 / 详情（page / search / get） | 本文件 §1–§4 |
| 构造 conditions、时间过滤、SELECT 过滤 | `core/query-conditions.md`（+ 必要时 `core/cli-reference.md`） |
| 人名 → userId、在职名单、部门范围、层级汇总 | `core/query-members-org.md` |
| 私海 / 线索池 / 线索公海 / 客户公海 | `core/query-pools.md` |
| 视图（viewId）选择 | `core/query-views.md` |
| 全局模糊搜索（未指定模块） | `core/query-global-search.md` |
| 审批 | `core/approval.md` |
| 价格目录 / SKU | `core/price-catalog.md` |
| 统计 / 汇总 / 排名 / 趋势 / 分布 | `core/funnel-engine.md` + 本文件 §2「page 与 page-summary」 |
| L2C 链路 / Customer 360 | `core/linkage-engine.md` |
| 模糊工作指令 | `core/intent-engine.md` |
| 写入 create / update / … | `core/write-engine.md`；本文件 §1 仅命令入口对照 |

---

## 1. 命令族总览

命令语法只以 CLI 自带帮助为准：查询 CLI 运行 `scripts/cordys.sh help`，扩展/写入辅助 CLI 运行 `scripts/cordys_ext.sh help`。本节只区分能力族，不复制完整参数表：

| 能力族 | 入口 | 语义来源 |
|--------|------|----------|
| 列表、详情、搜索、视图、跟进查询 | `cordys.sh crm` | 本文件 §2–§4、`query-views.md`、`query-global-search.md` |
| 统计（纯计数 / 本地聚合） | `cordys.sh crm page` / `page-summary` | `funnel-engine.md` |
| 客户/合同父记录下钻（Customer 360、合同链路） | `cordys.sh crm acct-sub` / `contract-sub` | `linkage-engine.md` |
| 价格目录 | `cordys.sh crm price-form/price/price-sku/price-detail` | `price-catalog.md` |
| 报价关联上下文（客户、商机、联系人、工商抬头、线索一次返回） | `cordys.sh crm quote-context` | `sop/quote-linking.md` §1 |
| 用户、组织、成员 | `cordys.sh crm whoami/org/members` | `query-members-org.md` |
| 审批 | `cordys.sh crm approval` | `approval.md` |
| 受限 raw | `cordys.sh raw` | 仅同域已知端点；见下方注 |
| 创建、更新、批量更新、附件 | `cordys.sh crm create/update/batch-update/upload` | `write-engine.md` |
| 查重、转化、公海写操作、字段同步 | `cordys_ext.sh check/transform/pool/sync` | `write-engine.md`、`sop/duplicate-check.md` |
| 跟进记录 / 计划新增与更新 | `cordys_ext.sh follow/follow-plan/follow-update/follow-plan-update` | `sop/visit-flow.md` |

> **JSON 入参两种传法**：① inline 单引号包裹 `crm page opportunity '{...}'`；② 经 stdin `printf '%s' '{...}' | crm page opportunity @-`（`@-` 或 `-`，page/search 均支持）。inline 的 JSON **必须以 `{` 开头**，否则会被当成关键词去搜（静默返回空，不是查无数据）。
> **`crm raw` 例外**：raw 只接受命令行中的一个 JSON body，不支持 stdin；只用于同一 `CORDYS_CRM_DOMAIN` 下的已知端点，认证 header 由脚本注入。优先使用结构化 `crm ...` 命令。
> **管道只用于送入请求 JSON，不得处理 CLI 输出**（`| head`、`2>&1`、临时文件二次解析均禁止），原因见 `references/platform-notes.md` §3。
> **已弃用命令**：`crm stat`、`stat-home`、`dist`、`glocount` 仅为兼容保留，调用时会在 stderr 打印弃用警告，不作为任何统计结论来源。

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

`conditions` / `searchMode` 只能位于 `combineSearch` 内；顶层写法会被后端静默忽略并返回全量数据，CLI 会在联网前拒绝。

### 自动补全规则

| 条件 | 动作 |
|------|------|
| 只给关键词 | 放入 `keyword`，其余字段填默认值 |
| 给部分 JSON | 补全缺失字段，保留已有字段；若未给 `viewId` 则按语义推断 |
| 给完整 JSON | 原样传递，不修改 |
| 没给任何参数 | 全部默认值 |

### page 与 page-summary 二选一

- 看记录、搜索、最近 N 条、分页查看：`crm page <模块> [查询JSON]`，默认 `pageSize` 30，只返回一页。
- 纯计数：仍用 `crm page`，固定传 `pageSize:1`，只读 `data.total`。
- 金额、平均、分组、排名、分布、漏斗、跨期比较：`crm page-summary <模块> <统计JSON> [查询JSON]`。脚本每页 500 条自动翻至 `data.total`，本地流式聚合，仅返回固定大小摘要。完整规则见 `core/funnel-engine.md`。
- 完整全量倾倒或本地文件导出不属于常规查询能力；用户要求全部明细时，用 `page` 分页展示并建议增加筛选条件。**唯一例外**是 `sop/order-operations.md`「完整订单导出」，按该 SOP 执行。

### 查询范围

权限上限与本次范围的判定以 `core/role-engine.md` §2.4 为唯一权威：先遵守 profile 权限上限，再采用用户明确指定的本人/具体人/团队/公司范围，只在用户未指定时用角色默认值。销售角色查询 lead/account/opportunity/contact 时必须把默认 `viewId:ALL` 覆盖为 `SELF`（或追加当前 owner），任何措辞都不能扩大。

> **联系人例外**：联系人列表实际端点是 `/account/contact/page`。`crm search contact` / `crm page contact` 已自动映射；未显式传 `viewId` 时默认 `SELF`，可直接按 `keyword` 搜姓名/手机号。已知客户 ID、需要枚举该客户全部联系人时才用 `crm contact account <客户ID>`。

### 模块消歧：「签单 / 金额」类无模块名的表达

| 口径 | 落点 | 触发信号 |
|------|------|---------|
| 业绩 | `opportunity` | 签了/赢了/丢单/成交、金额排名、阶段/漏斗/转化、"有效合同额"（商机字段） |
| 财务 | `contract` / `contract/payment-record` | 明确说"合同"且语境是合同管理（待签/到期）、回款/收款/欠款、发票/开票 |

判定口诀：业绩统计 → `opportunity`；财务管理 → `contract`/`payment-record`。不可凭感觉选。

---

## 3. 意图 → 命令映射

| 用户说 | 映射命令 | 备注 |
|--------|---------|------|
| 列表、分页查看、看看、有哪些、有多少、几个 | `crm page <module>` | 自动追加角色过滤；计数场景加 `"pageSize":1` 只读 `data.total` |
| 总额、金额汇总、合计金额、排名、分布 | `crm page-summary <module> <统计JSON> <查询JSON>` | 基于 page 全量分页本地聚合；见 `funnel-engine.md` |
| 周期对比、环比、同比、趋势 | 对每个互斥区间分别执行 `crm page` 或 `page-summary` | 数量读各区间 `data.total`；金额读各区间 `sums`；业务时间字段一致 |
| 明确自然日区间转毫秒戳 | `crm date-range <开始日> <结束日>` | 纯本地；两端包含；固定 `Asia/Shanghai` |
| 搜索、筛选、找一下、找 xxx（指定模块） | `crm search <module> <JSON>` | 关键词→keyword，条件→conditions |
| 搜索 / 列出（未指定模块） | 6 模块并行 | `core/query-global-search.md` |
| 查一下 / 有没有 XX、直接给公司名·手机号·人名 | `cordys_ext.sh check` | 查重，`sop/duplicate-check.md` |
| 详情、查看、打开这个 | `crm get <module> <ID>` | 若有名称无 ID，先搜索 |
| 跟进记录 / 计划列表 | `crm follow <plan\|record> [JSON\|-]` | 全局端点，不带父模块；按资源缩小用 `clueId` / `customerId` / `opportunityId` condition |
| 产品价格、价格目录、SKU | `crm price-form` / `crm price` / `crm price-sku` | `core/price-catalog.md` |
| 原始、自定义 | `cordys raw <METHOD> <PATH>` | 仅限信任域名 |
| 创建、新建、添加 + 模块名 | `cordys.sh crm create <module> <JSON\|->` | `core/write-engine.md` |
| 创建前预检（确认表之前） | `cordys.sh crm create <module> <JSON\|-> --dry-run` | `core/write-engine.md` §2.1 步骤 4 |
| 修改、更新、编辑 + 模块名 | `cordys.sh crm update <module>` | `core/write-engine.md` |
| 批量修改 | `cordys.sh crm batch-update <module>` | `core/write-engine.md` |
| 附件、上传文件、报价文件 | create/update JSON 带 `attachments`；确认前 `crm upload --check <文件>` | `core/write-engine.md` §2.4 |
| 线索转客户/商机 | `cordys_ext.sh transform` | `core/write-engine.md` §5 |
| L2C 链路追踪 / Customer 360 | 链路引擎编排跨模块查询 | `core/linkage-engine.md` |
| 漏斗分析 | 漏斗引擎编排统计 | `core/funnel-engine.md` |

---

## 4. 模块推断

| 用户说 | 模块 | 常用命令 | 强制规则 |
|--------|------|---------|------------|
| 线索、潜客 | `lead` | page, get, search, follow, create, update | 按人名查/分配/改负责人见 `query-members-org.md` |
| 客户、公司、厂商 | `account` | page, get, search, follow, contact, create, update | 同上 |
| 商机、机会 | `opportunity` | page, get, search, follow, create, update | 业绩/财务消歧见 §2 |
| 合同 | `contract` | page, get, form, create, update, batch-update | 消歧见 §2；无全局搜索端点，关键词用 `crm page contract '{"keyword":"…"}'` |
| 回款、回款计划 | `contract/payment-plan` | page, get, form, create, update | 消歧见 §2 |
| 回款记录 | `contract/payment-record` | page, get, form, create, update | 实际回款统计固定用 `recordEndTime` |
| 发票 | `invoice` | page, get, form, create, update | |
| 报价单 | `opportunity/quotation` | page, search, get, form, create, update | `search` 复用 page；更新先读回合并完整对象 |
| 订单 | `order` | page, page-summary, get, form, create, update, batch-update | 创建/拆单和完整导出读 `sop/order-operations.md` |
| 工商抬头 | `contract/business-title` | page, get, form, create, update | 无 `/view/list`，只有内置视图 |
| 产品 | `product` | product | |
| 组织、部门 | `org` | org ids / outline / tree | `query-members-org.md` |
| 成员、人员 | `members` | members | `query-members-org.md` |
| 联系人 | `contact`（别名）/ `account/contact`（真实路径） | page, search, get, contact, create, update | 读写都自动映射到 `/account/contact/*` |
| 线索池 / 线索公海 | `pool/lead` | page, search | `query-pools.md`；具体池顶层 `poolId` 必传 |
| 客户公海 | `pool/account` | page, search | 同上 |

> **联系人**：查询和写入均可使用 `contact` 别名，CLI 自动映射到 `/account/contact/*`。已知客户 ID 枚举联系人用 `crm contact account <客户ID>`。
> **报价单**：列表与关键词搜索都走 `/opportunity/quotation/page`，详情走 `/opportunity/quotation/get/{id}`；更新端点不是 PATCH，由 `crm update` 先取详情、合并旧值后完整提交。
> **父记录下钻**：客户名下的合同/商机/订单/回款/发票用 `crm acct-sub <子资源> <客户ID>`，合同名下的回款记录/计划用 `crm contract-sub <子资源> <合同ID>`；`customerId` 放进普通 `page` 的 body 任何位置都不行（顶层被忽略返回全表、条件会 100500），`contractId` 只能放顶层。详见 `references/crm-api.md` §7。

---

## 5. 排序规则

```json
{"followTime": "desc"}
{"createTime": "asc"}
```

常用排序字段：`followTime`、`createTime`、`amount`、`stage`。

---

## 6. 异常处理

| 响应 | 处理方式 |
|------|---------|
| HTTP 401/403 | 提示密钥可能失效，建议刷新身份 |
| code ≠ 100200 | 读取 message 字段并说明原因 |
| `INVALID_FILTER` | 检查字段名拼写和操作符是否匹配该字段类型 |
| 数据空列表 | 先排除**假空**：SELECT/RADIO 条件的 `value` 填了中文标签 → 改用选项 ID 重试一次（`query-conditions.md` §2）。排除后若查询格式正确（字段名存在、操作符匹配类型、模块正确、SELECT 值已用 ID），空就是真实结果，直接告知并解释可能原因，**不要再反复换格式重试** |
| 退出码 0 且 `code=100200`，stderr 提示"已自动归一化/无需重试" | 直接使用结果，禁止重跑 |
| 查询契约真正拒绝请求 | 只按错误指出的当前值形状与目标形状修改一次；不得读脚本追实现、先发无条件探测查询或更换业务字段试到有数据 |
| 查询接口超时 | 提示稍后重试或减小 pageSize（≤200） |
| 写命令的各种状态（`verifiedAfterTransportError`、`writeState:unknown` 等） | 以 `core/write-engine.md` §8 为准，不在此重复 |

---

## 7. 动态参数替换（从 Cordys.md 读取）

Cordys.md 中的值是可信缓存，直接使用，不要调接口二次验证。

| 占位符 | 来源 | 示例值 |
|--------|------|-------|
| `{userId}` | Cordys.md「用户ID」 | `admin` |
| `{departmentId}` | Cordys.md「部门ID」 | `1131998760411000` |
| `{departmentIds}` | Cordys.md「部门范围」（经理初始化时由 `crm org ids` 展开） | `["dept_a","dept_b"]` |

Cordys.md 中没有对应值时，不追加该过滤条件；经理缺「部门范围」时按 `core/query-members-org.md` §3.2 运行时展开。
