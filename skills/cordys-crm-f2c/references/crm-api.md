# CORDYS CRM API 参考

> 查询语义与请求体规则见 `../core/cli-spec.md`，可执行命令语法以 CLI `help` 为准。本文件只维护原始 API 端点和请求/响应结构。
>
> **目录**
>
> 1. [模块概览](#1-模块概览)
> 2. [通用请求结构](#2-通用请求结构)
> 3. [常用 HTTP 端点](#3-常用-http-端点)
> 4. [请求示例](#4-请求示例)
> 5. [响应解析](#5-响应解析)
> 6. [错误处理建议](#6-错误处理建议)
> 7. [最佳实践](#7-最佳实践)
> 8. [附录：字段/filters 例子](#8-附录字段filters-例子)

---

## 1. 模块概览
| 模块 | 描述                             |
| --- |--------------------------------|
| `lead` | 潜在客户（线索）记录，用于销售团队初步跟进；业务所称“线索私海”仍是此普通模块。 |
| `account` | 客户/公司基础信息，包含行业、地点、负责人等；业务所称“客户私海”仍是此普通模块。 |
| `opportunity` | 商机（机会）记录，表示销售流程中的具体案子。         |
| `contract` | 合同及其回款、发票等子资源，用于追踪签署后的收款与交付状态。 |
| `lead-pool` | 线索池、线索公海，用于共享线索。API 路径为 `pool/lead`。 |
| `account-pool` | 客户公海，用于共享客户。API 路径为 `pool/account`。 |

你在自然语言中提到的模块名，转换成命令时就能直接定位到本文档中所列的模块。

> **池术语按业务对象消歧**：`线索池/线索公海/线索（含公海）`及明确线索上下文中的“公海” = `pool/lead`；`客户公海/客户池` = `pool/account`；裸“公海”无上下文时默认客户公海。两套 options 可以出现同名池，必须先锁定业务对象，再在对应 options 内匹配名称。

> **私海没有独立 API 端点**：`线索私海`及线索上下文中的“私海”使用普通 `lead` 的 page/search；`客户私海`及客户上下文中的“私海”使用普通 `account` 的 page/search。它们不使用 `/pool/...`、不请求 options、也不携带 `poolId`。裸“私海”无法判断业务对象时先询问；“我的/我名下的私海”再用 `viewId:SELF` 或当前 owner 缩小普通模块范围。

`contract` 模块还有几个常用的二级资源：`contract/payment-plan`（回款计划）、`invoice`、`contract/business-title`（工商抬头）、`contract/payment-record` 以及 `opportunity/quotation`，CLI 仍然沿用 `page`/json 的方式访问它们。

---

## 2. 通用请求结构

> 完整的 JSON Body 模板及字段说明见 `../core/cli-spec.md#2-分页默认结构`。本节仅补充 API 层面的注意事项。

关键字段简述：
- `current`：页码（从 1 开始）
- `pageSize`：每页条数，默认 30；普通 `crm page` 按任务选择，`crm page-summary` 内部固定为 500 并自动翻页聚合
- `sort`：排序对象，例如 `{"followTime":"desc"}`
- `combineSearch.conditions`：组合筛选条件。`conditions` / `searchMode` 禁止放在 payload 顶层，错误位置会被后端静默忽略并返回全量数据，CLI 会在联网前拒绝。
- `keyword`：全局关键词，模糊匹配名称/说明/电话等
- `viewId`：按模块选择，完整官方/自定义目录见 `references/forms/{module}.md` 的「视图目录」。常见值包括 ALL、SELF、DEPARTMENT；客户另有 CUSTOMER_COLLABORATION，商机另有 OPPORTUNITY_SUCCESS。
- `filters`：精细字段级过滤
- `poolId`: 目标池 id。`/pool/{module}/page` 查单个池时必传，必须是 payload 顶层非空 JSON 字符串，值来自同模块 `GET /pool/{module}/options`；不得放进 conditions、不得写错大小写、不得传 JSON 数字。CLI 会在联网前校验。跨池搜索用 `/global/search/clue_pool`（线索池/线索公海）或 `/global/search/customer_pool`（客户公海），必须传非空 `keyword` 且不使用 poolId。其它模块查询不得携带 poolId。

---

## 3. 常用 HTTP 端点
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/{module}/view/list` | 列出当前实例、当前用户可见的自定义视图（不返回官方内置视图，也不返回业务数据）。联系人为 `/account/contact/view/list`，跟进记录/计划为 `/follow/record/view/list`、`/follow/plan/view/list`；`contract/business-title` 无该端点，只使用内置视图。 |
| `GET` | `/{module}/get/{id}` | 获取单条记录详情。 |
| `POST` | `/{module}/page` | 发送上面模型的 JSON 进行分页查询（支持复杂过滤 + 关键词）。联系人使用 `/account/contact/page`。 |
| `POST` | `/global/search/{module}` | 全局搜索，JSON body 结构同上，额外在多个字段里查关键词。池模块端点名：线索池 `/global/search/clue_pool`、公海 `/global/search/customer_pool`（`crm search pool/lead`、`pool/account` 已自动映射）。 |
| `GET` | `/opportunity/quotation/get/{id}` | 获取报价单详情。 |

> 全局搜索（`crm search`）覆盖 `lead`/`account`/`opportunity` 及线索池/线索公海、客户公海；联系人由 CLI 特殊映射到 `/account/contact/page`。报价单没有 `/global/search`，`crm search opportunity/quotation` 会复用 `/opportunity/quotation/page`。其余签约后模块无全局搜索，按父 id 走取数器或使用 `crm page {module} '{"keyword":"…"}'`。详见 §7、§10.2。
| `GET` | `/{module}/contact/list/{id}` | 获取某条记录的联系人列表（仅 `opportunity`、`account` 模块）。 |
| `GET` | `/pool/{module}/options` | 获取当前用户可见的线索池/线索公海或客户公海列表（`module` 为 `lead`/`account`），返回各池的 `id`（即 poolId）与 `name`。 |
| `POST` | `/pool/{module}/page` | **单个**线索池/线索公海或客户公海记录分页。body 同标准分页结构，`poolId` 必传，取自同模块 `/pool/{module}/options`。跨池搜索用 `/global/search/clue_pool`、`/global/search/customer_pool`。 |

> `cordys raw {METHOD} {PATH} [JSON body]` 仅用于调用同一 `CORDYS_CRM_DOMAIN` 下的已知端点；认证 header 由脚本注入，调用方不得提供自定义 header 或任意 curl 参数。raw 当前只接受命令行中的一个 JSON body，不支持 `@-`/`-` stdin；大 body 不得把 raw 当作支持 stdin 的结构化命令。优先使用结构化 `crm ...` 命令。

### 字段数据源：订单服务与价格目录

订单中的“服务”不是产品字典，也不是订单子表行 ID。当前订单表单的三个服务子字段均为 `DATA_SOURCE` 且 `dataSourceType=PRICE`：

| 子表 | 服务字段 fieldId | 数据源类型 |
|---|---|---|
| 维保 | `178368304592200000` | `PRICE` |
| 专业服务 | `178368405249700001` | `PRICE` |
| 培训服务 | `178368413190600000` | `PRICE` |

#### 全量查询服务价格目录

调用价格数据源分页接口：

```text
POST /field/source/price
```

请求体使用标准分页结构，`pageSize` 最大 500：

```json
{
  "current": 1,
  "pageSize": 500,
  "sort": {},
  "combineSearch": {"searchMode": "AND", "conditions": []},
  "keyword": "",
  "viewId": "ALL",
  "filters": []
}
```

成功响应为 `code=100200`，核心结构为：

```text
data.total                 价格目录主表总数
data.list[].id             服务字段实际保存的价格目录主表 ID
data.list[].name           服务名称
data.list[].products[]     该价格目录下的价格子行
data.list[].products[].id  价格子行 ID
```

导出订单时必须连续分页到首个 `data.total`，建立两级索引：

```text
服务字段值 -> data.list[].id -> data.list[].name
price_sub  -> data.list[].products[].id（或 products[].price_sub）
```

服务字段值优先匹配价格目录主表 `id`；若服务 ID未命中，再用 `price_sub` 匹配 `products[]` 子行并取该子行所属主表 `name`。不得用产品字典的 `product` ID、价格子行 `id` 或订单子表行 `id` 直接代替服务字段。两种匹配都失败时，服务名称留白，保留原始服务 ID并标记未解析。

#### 价格目录子行字段定义

价格目录 `products[]` 的业务属性不是固定 JSON 键，而是当前价格表单的子字段 ID。导出前必须读取：

```text
GET /price/module/form
```

从 `data.fields[]` 中定位 `businessKey=products` 的 `SUB_PRODUCT` 字段，再用其 `subFields[]` 建立 `价格子字段 ID -> 中文字段名/类型/options` 映射。对价格子行，只能按该映射读取和转换字段；不得假定存在 `productSku`、`description`、`purchaseType` 等英文键，也不得拿订单子表 fieldId 去读取价格子行。

其中 `产品SKU`、`描述`、`购买方式`、`收入类型`、`单位`、`服务等级`、`币种`、`产品版本`等与订单导出固定列同名的字段，可在订单行该字段为空时回填；SELECT/RADIO 必须按价格表单自身 options 转成中文标签，`产品`仍按产品字典解析。价格表单或价格子行缺失时不得伪造值。

#### 已知服务 ID 的定向核验

当只需核对少量已出现的服务 ID时，可调用：

```text
POST /field/source/ref-detail
```

请求体：

```json
{
  "dataSourceType": "PRICE",
  "sourceIds": ["<服务字段值>"]
}
```

该接口成功时返回 `data[]`，不是分页 `data.list[]`。它只能用于已知 ID 的定向核验，不能替代全量导出所需的 `/field/source/price` 分页。返回 0 条、重复主表或缺少 `id/name` 时，必须报告服务价格目录未命中或无法唯一解析，不得猜名称。

产品类型仍单独调用 `POST /field/source/product`；价格目录里的 `products[].product` 只表示产品实体 ID，不能当作订单“服务”字段。

---

## 跟进计划与记录 API
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/follow/plan/page` | 全局分页查询跟进计划。body 使用标准分页结构，额外必填 `status`；结构化 CLI 未传时自动补 `ALL`。|
| `POST` | `/follow/record/page` | 全局分页查询跟进记录。body 使用标准分页结构，可按 `keyword`、`viewId` 或 `combineSearch.conditions` 筛选。|
| `GET` | `/{module}/follow/plan/get/{id}` | 获取单条跟进计划详情。走 `cordys.sh crm follow-get plan`，其中 `id` 是计划 ID。|
| `GET` | `/{module}/follow/record/get/{id}` | 获取单条跟进记录详情。走 `cordys.sh crm follow-get record`，其中 `id` 是记录 ID。|
| `POST` | `/{module}/follow/plan/add` | 新增跟进计划（后续要做的跟进）。走 `cordys_ext.sh follow-plan`。必填 `type`+`method`；字段见 `references/forms/follow-plan.md`。|
| `POST` | `/{module}/follow/record/add` | 新增跟进记录（已发生的跟进）。走 `cordys_ext.sh follow`。必填 `type`；字段见 `references/forms/follow.md`。|
| `POST` | `/{module}/follow/plan/update` | 更新跟进计划。走 `cordys_ext.sh follow-plan-update`；完整请求体必填 `id`、`content`、`method`、`owner`、`type`。|
| `POST` | `/{module}/follow/record/update` | 更新跟进记录。走 `cordys_ext.sh follow-update`；完整请求体必填 `id`、`content`、`followMethod`、`owner`、`type`。|

> **列表与详情/写入的路由不同**：列表固定走全局 `/follow/{plan|record}/page`，不带父模块前缀；现有详情、新增和更新命令仍走 `/{module}/follow/{plan|record}/...`，其中 `module` 为 `lead`、`account` 或 `opportunity`。禁止把两套路由互换。

全局分页请求不使用顶层 `sourceId`。按某条业务资源定位时，在 `combineSearch.conditions` 中使用真实数据源字段：线索用 `clueId`、客户用 `customerId`、商机用 `opportunityId`，统一采用 `type:"DATA_SOURCE"`、`operator:"IN"`、`value:["<资源ID>"]`。这些字段放在 payload 顶层会被后端忽略，CLI 会在联网前拦截。

跟进计划的 `status` 允许 `ALL`、`PREPARED`、`UNDERWAY`、`COMPLETED`、`CANCELLED`；CLI 缺省补 `ALL`。本人范围使用 `viewId:"SELF"`；旧 `myPlan:true` 仅作为 CLI 兼容输入转换为 SELF，不再发送给全局接口。

旧命令 `crm follow <kind> <module> '{"sourceId":"..."}'` 暂时兼容：CLI 会把 `sourceId` 安全转换为上述资源字段条件后再请求全局端点。新命令不得再带 `module`，也不得使用顶层 `sourceId`。

更新不是 PATCH。更新命令会先 GET 当前详情、保留未修改的必填字段与模块字段，再合并用户明确要求的变更并只 POST 一次。更新命令中的 `id` 是分页结果或新增响应返回的**跟进计划/记录条目 ID**，不是父资源 `sourceId`；执行更新前必须读取详情、展示当前值与目标值并取得确认。

`crm follow` 会补齐标准分页体：`current`、`pageSize`、`sort`、`combineSearch`、`keyword`、`viewId`、`filters`；计划查询还会补 `status:"ALL"`。


## 4. 请求示例
### 分页列出商机（默认结构）
```bash
cordys.sh crm page opportunity "{\"current\":1,\"pageSize\":20,\"keyword\":\"线索\"}"
```
会调用 `POST /opportunity/page`，body 同上。

### 二级模块支持
Cordys CRM 里有一些隐藏在 `contract`｜ `opportunity` 模块下的二级资源（比如回款计划、发票等），`cordys` CLI 通过接受包含斜杠路径的模块名来访问它们。

- `cordys crm page contract/payment-plan`：查询回款计划的分页列表，支持传入关键词/JSON body，实际上调用的是 `POST /contract/payment-plan/page`。
- `cordys crm page invoice`：查询发票的分页列表，通过 `POST /invoice/page` 获取，每个条件都可以通过 `filters` 精细控制。
- `cordys crm page contract/business-title`：检索工商抬头列表，同样支持关键词/filters。
- `cordys crm page contract/payment-record`：查看回款记录列表，可结合关键词、`filters` 或 `viewId` 进行精细筛选。
- `cordys crm page opportunity/quotation`：查看报价单列表，可结合关键词、`filters` 或 `viewId` 进行精细筛选。
- `cordys crm search opportunity/quotation`：自动复用 `POST /opportunity/quotation/page`。
- `cordys crm get opportunity/quotation <id>`：调用 `GET /opportunity/quotation/get/{id}` 获取详情。

这些业务模块沿用统一写入端点：

```text
GET  /{module}/module/form
POST /{module}/add
POST /{module}/update
```

`{module}` 可为 `contract`、`contract/payment-plan`、`contract/payment-record`、`invoice`、`contract/business-title`、`opportunity/quotation` 或 `order`。报价单业务必填为 `name`、`opportunityId`、`untilTime`、`products`、`moduleFields`；更新还必须保留 `id`、`approvalStatus`，由 `crm update` 先读详情并合并成完整对象。同步后的本地 schema 中只要模块含 `subFields`（当前为合同、发票、报价单、订单），`crm create/update` 就会在首次写请求前读取对应 `/module/form`，校验响应 `code=100200` 且 `data` 含 `fields + formProp`，再自动附加为 `moduleFormConfigDTO`。调用方不得手工携带旧配置；form 获取或校验失败时不会发送写请求。

创建、更新或批量更新前必须先执行 `sync-if-needed`，字段、必填项、fieldId 和选项值只读取同步后的本地 `references/forms/*.md`。`GET /{module}/module/form` 仅用于接口诊断，以及 CLI 为子表模块自动组装 `moduleFormConfigDTO`，不能替代本地表单流程。订单创建额外执行 `sop/order-operations.md` 的“创建订单 / 自动拆单”：调用方只传唯一 `contractId` 和可选公共默认字段。CLI 读取合同全部有效业务子表，按“具体产品/服务 ID + 收入类型中文标签”分组，同组合多行合并、不同组合顺序调用 `/order/add`；每张 `name` 仍按 `<合同编码>-<产品类型中文标签>-${订单编号}` 自动生成，不追加收入类型。合同源行全部有值的非公式业务字段按父/子表标签映射，SELECT/RADIO 经中文标签转换目标 option ID；合同子行 `id` 不复制，PRICE 源行 `price_sub` 保留，`*_ref_*` 投影在公式完成后剥离。每组独立计算全部公式，合同调整金额按原始金额比例分摊、末组吸收尾差；任一订单失败或状态不明立即停止并禁止整批重跑，全部订单成功后才调用 `/contract/update` 把“是否已拆订单”标记为“是”。`crm create/update` 都接受 `-`/`@-` UTF-8 stdin；子表或其他大 JSON 不得展开到 Windows 命令行。

对这些二级模块的查询依旧遵循 `page_payload` 结构（`current`/`pageSize`/`sort`/`filters`）和关键字补全，缺失的分页字段会用默认值补全。

需要更专业的筛选能力时，直接把完整 JSON body 传给 `cordys crm page contract/payment-plan '{…}'`。仅当没有结构化命令时才用 `cordys raw POST /contract/payment-record/page '{...}'`，且只传单个 JSON body。

### 高级 search（带 filters + sort）
```bash
cordys.sh crm search account '{
  "current":1,
  "pageSize":40,
  "keyword":"云",
  "sort":{"followTime":"desc"},
  "combineSearch":{
    "searchMode":"AND",
    "conditions":[
      {"name":"industry","operator":"EQUALS","value":"科技","type":"INPUT"},
      {"name":"province","operator":"EQUALS","value":"广东","type":"INPUT"}
    ]
  }
}'
```
CLI 会请求 `/global/search/account`，按关键词 + combineSearch 条件精确过滤。

### 高级 search（和时间相关的动态搜索）
```bash
cordys.sh crm search account '{
  "current":1,
  "pageSize":40,
  "keyword":"云",
  "sort":{},
  "combineSearch":{
    "searchMode":"AND",
    "conditions":[
      {"value": "WEEK","operator": "DYNAMICS","name": "createTime","multipleValue": false,"type": "TIME_RANGE_PICKER"}
    ]
  },
  "filters":[]
}'
```
在combineSearch.conditions参数结构中，operator为DYNAMICS时，value为时间常量。

> 完整时间常量表见 `../core/cli-spec.md#5-动态时间过滤`。

查询"n天前/早于n天"时，DYNAMICS **不支持**自定义天数（value 只收时间常量，传 `["CUSTOM",n,"BEFORE_DAY"]` 会报 `ClassCastException`）。改用 AI 算出 n 天前的毫秒级时间戳 `tsN`，写 `value: tsN`、`operator: LT`、`type: DATE_TIME`（等价 BETWEEN `[0, tsN]`）。"超过n天没跟进"还需另查 `EMPTY` 相加（LT/BETWEEN 不含 null）。
如果要查询两个时间段中间的数据，value可以写[较早的毫秒级时间戳，较晚的毫秒级时间戳]，同时operator为BETWEEN。

明确自然日区间不要手算，也不要使用歧义缩写 `CST`。先运行 `cordys.sh crm date-range <开始日> <结束日>`，把返回的 `value` 原样用于 `BETWEEN + DATE_TIME`；命令固定按 `Asia/Shanghai`（UTC+8）生成两端都包含的区间。例如 2026-07-01 至 2026-07-31 返回 `[1782835200000,1785513599999]`。

> ⚠️ `stageUpdateTime` 是展示字段，不能用于过滤条件（DYNAMICS 和 BETWEEN 都不行）。需要阶段变更时间请用 `updateTime`。商机时间过滤：结束时间（赢单/输单/成交/开放）一律用 `expectedEndTime`、新建用 `createTime`、修改用 `updateTime`。**`actualEndTime` 无统计意义，不要用。**

### 获取某条记录
```
cordys crm get lead 987654321
```
等价于 `GET /lead/get/987654321`。

---

### 跟进计划/记录请求示例
```bash
cordys.sh crm follow record '{"current":1,"pageSize":30,"combineSearch":{"searchMode":"AND","conditions":[]},"keyword":"","viewId":"ALL","filters":[]}'
cordys.sh crm follow plan '{"current":1,"pageSize":30,"combineSearch":{"searchMode":"AND","conditions":[]},"keyword":"","viewId":"ALL","status":"ALL","filters":[]}'
cordys.sh crm follow record '{"combineSearch":{"searchMode":"AND","conditions":[{"value":["927627065163785"],"operator":"IN","name":"clueId","type":"DATA_SOURCE"}]}}'
cordys.sh crm follow-get record lead '<跟进记录ID>'
cordys.sh crm follow-get plan account '<跟进计划ID>'
```

跟进计划**新增**（走扩展 CLI，中文方式/时间自动转换）：
```bash
cordys_ext.sh follow-plan '{"module":"lead","clueId":"398984062159048704","content":"下周电话回访采购进度","跟进方式":"电话","计划时间":"2026-07-15 10:00"}'
```
> ⚠️ 新增走 `/{module}/follow/plan/add`（带 module 前缀），字段用**存储态名**（`type`/`clueId`/`estimatedTime`/`method`/`content`），**不是**表单 `/follow/plan/module/form` 暴露的 `planXxx` 键。必填 `type`+`method`。计划的方式选项 ID 与记录不同，详见 `references/forms/follow-plan.md`。

跟进记录/计划**更新**（先用上方 `follow-get` 获取详情并向用户确认）：
```bash
cordys_ext.sh follow-update '{"module":"lead","id":"<跟进记录ID>","跟进内容":"【AI打卡】跟进\n补充沟通结果","跟进方式":"微信"}'
cordys_ext.sh follow-plan-update '{"module":"account","id":"<跟进计划ID>","计划时间":"2026-08-10 10:00","跟进方式":"电话"}'
```
> 更新命令内部完成“详情读取 → 完整字段合并 → 单次提交 → 失败时回读核验”。返回 `noOp:true` 时没有发起更新；返回 `verifiedAfterFailure:true` 时已通过回读确认成功；返回 `retryAllowed:false` 时禁止自动重试。
响应返回同样的分页结构，`data.list` 含 `planTime`、`status`、`ownerName`、`content` 等字段，例如：
```json
{
  "code":100200,
  "data":{
    "list":[
      {"id":"plan-1","planTime":"2026-02-28T14:00:00","status":"UNFINISHED","content":"跟进沟通需求"},
      {"id":"plan-2","planTime":"2026-02-26T10:00:00","status":"FINISHED","content":"确认资料"}
    ],
    "current":1,"pageSize":10,"total":2
  }
}

```

## 5. 响应解析
所有调用返回统一结构：
```json
{
  "code": 100200,
  "message": null,
  "messageDetail": null,
  "data": {
    "list": [ ... ],
    "total": 13,
    "pageSize": 30,
    "current": 1
  }
}
```
正常响应 `code=100200`。异常时会返回 `ACCESS_DENIED`、`INVALID_KEY`、`INVALID_REQUEST` 等，`message` 字段含具体原因。

---

## 6. 错误处理建议
1. **Token/密钥错误**：`INVALID_KEY`、`ACCESS_DENIED` → 检查 `CORDYS_ACCESS_KEY`/`CORDYS_SECRET_KEY`。
2. **参数问题**：`INVALID_REQUEST`、`INVALID_FILTER` → 检查 JSON 格式、字段名拼写。
3. **404/资源不存在**：要么 `id` 写错，要么没有访问权限。
4. **500+**：查询请求可记录脱敏后的 `messageDetail` 并稍后重试；写请求可能“假失败真成功”，必须先查询确认是否已写入，确认不存在后才能重试。

对于任何非 `100200` 响应，我会把 `code`+`message` 反馈给你。

---

## 7. 最佳实践
- **分页不要太大**：大于 200 会容易超时。
- **关键词 + filters 组合**：先用 `keyword` 粗筛，再在 `combineSearch.conditions` 中加精确字段。
- **签约后家族按父维度取数（两个对称取数器）**：`contract`、`invoice`、`order`、`contract/payment-record`、`contract/payment-plan`、`contract/business-title`、`opportunity/quotation` 用父 id 取，不要手搓 `/page` body。
  - **客户名下** → `crm acct-sub <子资源> <客户ID>`：`contract`/`opportunity`/`order`/`payment-record`/`payment-plan`/`invoice` 明细 + `*-stat` 统计（走 `/account/{module}/page`，自动带 `customerId`）。
  - **合同名下** → `crm contract-sub <子资源> <合同ID>`：`payment-record`/`payment-plan` 明细（走 `/contract/{sub}/page`，自动把 `contractId` 放 body 顶层）、`invoice-stat` 统计。
  - 两个取数器把"父 id 放对位置"的坑藏在命令内部。手搓 `/page` body 时的两条硬规则（脚本已 die 拦截并指回取数器）：① `customerId`/`accountId` 放在 body 任何位置（顶层或 `combineSearch.conditions`）都不行——顶层被静默忽略返回全表、条件会拼出非法 SQL 报 100500；② `contractId` 不能放进 `conditions`（`payment-plan`/`invoice`/`order` 会 100500），但放 body 顶层是合法过滤（`crm page contract/payment-record '{"contractId":"…"}'` 即 `contract-sub` 内部写法）。
  - 合同名下的**发票/订单明细**查不了（`/page` 不按 `contractId` 过滤），只能取统计 `contract-sub invoice-stat`；要明细走客户维度 `acct-sub invoice`。
  - 只有名称关键词时用 `crm page contract '{"keyword":"…"}'`。
- **排序字段稳定**：使用 `sort` 降序 `followTime` 或 `createTime`，避免每次结果顺序浮动。
- **多条件用 `combineSearch`**：传多个 `conditions` 会自动 AND（或 OR，取决于 `searchMode`）。
- **控制层级**：JSON body 里按模块字段命名（大小写敏感）。

---

## 8. 附录：常用过滤字段示例
| 字段 | 描述 | 示例值 |
| --- | --- | --- |
| `name` | 名称/标题 | `"Acme 商机"` |
| `stage` | 商机阶段 | `"Qualification"` |
| `owner` | 负责人 ID | `"user123"` |
| `industry` | 行业 | `"科技"` |
| `province` | 省份 | `"上海"` |

过滤示例（放入 `combineSearch.conditions`，`operator` 用大写枚举，键名为 `name` 非 `field`）：
```
{"name":"stage","operator":"IN","value":["SUCCESS"],"type":"SELECT"}
```
更多字段可以在 CLI 输出的 `moduleFields` 里查看或用 `cordys raw GET /settings/fields?module={module}` 查询。

> **字段类型与操作符映射**：构造 `combineSearch.conditions` 时，每个 condition 的 `type` 字段必须正确填写目标字段的字段类型，`operator` 必须为该字段类型支持的操作符。SELECT/RADIO/MEMBER/DEPARTMENT/DATA_SOURCE 等枚举类使用 `IN`/`NOT_IN` 且 `value` 为数组；详细映射见 `../core/cli-reference.md` §2。

---

## 9. 审批 API

审批模块是独立于 CRM 标准模块的专用 API，不走 `/module/page` 模式。

### 9.1 审批代办端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/approval-todo/pending/page` | POST | 待我审批分页 |
| `/approval-todo/processed/page` | POST | 我已处理的审批分页 |
| `/approval-todo/initiated/page` | POST | 我发起的审批分页 |
| `/approval-todo/cc/page` | POST | 抄送我的审批分页 |
| `/approval-todo/pending/count` | GET | 待审批统计 |

请求体（POST）使用标准 `page_payload` 结构（current/pageSize/sort/combineSearch/viewId/filters），外加 `resourceType` 字段（ALL/QUOTATION/CONTRACT/ORDER/INVOICE）。

### 9.2 审批操作端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/approval-action/approve` | POST | 同意 |
| `/approval-action/reject` | POST | 驳回 |
| `/approval-action/back` | POST | 退回 |
| `/approval-action/sign` | POST | 加签 |
| `/approval-action/revoke` | POST | 撤回 |
| `/approval-action/batch-approve` | POST | 批量同意 |
| `/approval-action/batch-reject` | POST | 批量驳回 |

### 9.3 审批资源端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/approval-resource/push` | POST | 提审 |
| `/approval-resource/revoke` | POST | 撤销 |
| `/approval-resource/simple-detail/{resourceId}` | GET | 列表详情 |
| `/approval-resource/detail/{resourceId}` | GET | 完整记录详情（含审批流进度） |

### 9.4 审批流设置端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/approval-flow/page` | POST | 审批流列表 |
| `/approval-flow/add` | POST | 新建审批流 |
| `/approval-flow/update` | POST | 更新审批流 |
| `/approval-flow/get/{id}` | GET | 审批流详情 |
| `/approval-flow/delete/{id}` | GET | 删除审批流 |
| `/approval-flow/enable/{id}` | GET | 启用/禁用（?enable=true\|false） |
| `/approval-flow/get-by-form-type/{formType}` | GET | 按表单类型获取审批流 |
| `/approval-flow/status-permission/setting/{formType}` | GET | 状态权限配置 |
| `/approval-flow/webhook/test` | POST | webhook 测试 |

### 9.5 完整命令示例

```bash
# 待我审批（只看合同类）
cordys.sh crm approval todo pending '{"current":1,"pageSize":30,"resourceType":"CONTRACT"}'

# 审批统计
cordys.sh crm approval todo count

# 同意审批
cordys.sh crm approval action approve '{"resourceId":"xxx","remark":"同意"}'

# 驳回
cordys.sh crm approval action reject '{"resourceId":"xxx","remark":"金额不符，请修改后重新提交"}'

# 退回（退回上一个节点）

cordys.sh crm approval action back '{"resourceId":"xxx","backNodeId":"node1","remark":"请补充附件"}'

# 加签
cordys.sh crm approval action sign '{"resourceId":"xxx","signUserIds":["user123"],"remark":"需要法务审核"}'

# 查看审批进度
cordys.sh crm approval resource detail RESOURCE_ID

# 提审
cordys.sh crm approval resource push '{"resourceId":"xxx"}'

# 撤销审批
cordys.sh crm approval resource revoke '{"resourceId":"xxx"}'

# 查看审批流配置
cordys.sh crm approval flow list '{"current":1,"pageSize":30}'

# 原始 API（等价）
cordys.sh raw POST /approval-todo/pending/page '{"current":1,"pageSize":30}'
cordys.sh raw GET /approval-todo/pending/count
```

### 9.6 审批响应结构

审批代办列表返回 `ApprovalTodoItemResponse` 对象，主要字段：

| 字段 | 说明 |
|------|------|
| `resourceId` | 审批资源ID |
| `resourceName` | 审批标题/名称 |
| `resourceType` | 资源类型（QUOTATION/CONTRACT/ORDER/INVOICE） |
| `status` | 审批状态 |
| `initiatorName` | 发起人 |
| `createTime` | 创建时间 |
| `currentApproverName` | 当前审批人 |

审批记录详情 `ApprovalInstanceDetail` 包含完整的审批流节点历史。

---

后续扩展，在 `references/` 下添加更多模块的字段列表（例如 `contacts.md`、`tasks.md`）或写出常用 JSON 模板。

---

## 10. L2C 链路 API 说明

### 10.1 历史统计 API（仅接口参考，统计禁用）

> 以下端点仅保留作后端接口参考。其范围、时间桶或服务端口径可能与业务 page 明细不一致，**不得用于生成统计结论**。所有统计统一走 `crm page` 的 `data.total` 或基于 page 全量分页的 `crm page-summary`，详见 `core/funnel-engine.md`。

#### 首页统计

| 端点 | 用途 | 请求体 |
|------|------|--------|
| `POST /home/statistic/lead` | 线索统计 | `HomeStatisticBaseSearchRequest` |
| `POST /home/statistic/opportunity` | 商机统计 | 同上 |
| `POST /home/statistic/opportunity/success` | 赢单统计 | 同上 |
| `POST /home/statistic/opportunity/underway` | 进行中商机统计 | 同上 |
| `GET /home/statistic/department/tree` | 用户部门权限树 | — |

`HomeStatisticBaseSearchRequest`：

```json
{
  "searchType": "SELF",
  "deptIds": ["dept_id"],
  "timeField": "CREATE_TIME",
  "userField": "OWNER",
  "priorPeriodEnable": true
}
```

字段说明：
- `searchType`：`ALL` / `SELF` / `DEPARTMENT`
- `deptIds`：`DEPARTMENT` 时必填
- `timeField`：`CREATE_TIME` / `EXPECTED_END_TIME` / `ACTUAL_END_TIME`
- `userField`：`CREATE_USER` / `OWNER`
- `priorPeriodEnable`：是否返回上期数据做环比

响应（线索统计）：

```json
{
  "todayClue": { "value": 3, "priorPeriodCompareRate": 0.5 },
  "thisWeekClue": { "value": 12, "priorPeriodCompareRate": 0.2 },
  "thisMonthClue": { "value": 45, "priorPeriodCompareRate": 0.18 },
  "thisYearClue": { "value": 120, "priorPeriodCompareRate": 0.26 }
}
```

响应（商机统计，含金额字段）：

```json
{
  "todayOpportunity": { "value": 1, "priorPeriodCompareRate": 0 },
  "thisWeekOpportunity": { "value": 5, "priorPeriodCompareRate": 0.25 },
  "thisMonthOpportunity": { "value": 18, "priorPeriodCompareRate": 0.12 },
  "thisYearOpportunity": { "value": 60, "priorPeriodCompareRate": 0.3 },
  "todayOpportunityAmount": { "value": 50000, "priorPeriodCompareRate": -1.0 },
  "thisWeekOpportunityAmount": { "value": 320000, "priorPeriodCompareRate": 0.4 },
  "thisMonthOpportunityAmount": { "value": 1200000, "priorPeriodCompareRate": 0.15 },
  "thisYearOpportunityAmount": { "value": 5000000, "priorPeriodCompareRate": 0.35 }
}
```

> `value` 为数值；金额单位按后端返回口径处理，展示前需要确认是否为分。`priorPeriodCompareRate` 是较上期变化率（0.2 = +20%，-0.1 = -10%）。

#### 模块级统计

| 端点 | 请求体 | 响应 |
|------|--------|------|
| `POST /contract/statistic` | `BaseCondition` | `{amount, averageAmount}` |
| `POST /contract/payment-record/statistic` | `ContractPaymentRecordStatisticRequest` | `{amount, averageAmount}` |
| `POST /opportunity/statistic` | `OpportunitySearchStatisticRequest` | `{amount, averageAmount}` |
| `POST /order/statistic` | `BaseCondition` | `{amount, averageAmount}` |

#### 客户子资源统计

| 端点 | 响应 |
|------|------|
| `GET /account/contract/statistic/{accountId}` | `{totalAmount}` |
| `GET /account/contract/payment-plan/statistic/{accountId}` | `{totalPlanAmount}` |
| `GET /account/contract/payment-record/statistic/{accountId}` | `{totalAmount, receivedAmount, pendingAmount}` |
| `GET /account/invoice/statistic/{accountId}` | `{contractAmount, uninvoicedAmount, invoicedAmount}` |
| `GET /contract/invoice/statistic/{contractId}` | 同上 |

### 10.2 客户子资源 API（Customer 360 核心）

| 端点 | 方法 | 用途 |
|------|------|------|
| `POST /account/contract/page` | POST | 客户名下合同列表 |
| `POST /account/opportunity/page` | POST | 客户名下商机列表 |
| `POST /account/order/page` | POST | 客户名下订单列表 |
| `POST /account/contract/payment-plan/page` | POST | 客户回款计划列表 |
| `POST /account/contract/payment-record/page` | POST | 客户回款记录列表 |
| `POST /account/invoice/page` | POST | 客户发票列表 |

以上分页端点的请求体必须带 `customerId`。`cordys.sh crm acct-sub ... <accountId>` 和 `cordys.py crm acct-sub ... <accountId>` 会自动把 `<accountId>` 写入 body；直接调用 API 时不要省略，尤其是 `/account/contract/payment-record/page`，缺少 `customerId` 时可能返回全公司回款记录。

### 10.3 全局搜索

| 端点 | 用途 |
|------|------|
| `POST /global/search/module/count?keyword=X` | 全局搜索各模块命中计数 |
| `POST /global/search/account` | 全局搜索客户 |
| `POST /global/search/lead` | 全局搜索线索 |
| `POST /global/search/opportunity` | 全局搜索商机 |
| `POST /account/contact/page` | 联系人列表/关键词搜索（CLI 的 `crm search contact` 和 `crm page contact` 使用此端点） |

> 不使用 `/search/{module}` 或 `/advanced/search/{module}`；CLI 的 `crm search` 对普通模块映射到 `/global/search/{module}`，联系人例外映射到 `/account/contact/page`。`/global/search/contact` 对姓名关键词不可靠，不作为联系人姓名查询入口。

### 10.4 订单模块

Cordys CRM 存在订单（Order）模块，L2C 链路可扩展为：

```
合同 → 订单 → 发票
```

| 端点 | 用途 |
|------|------|
| `POST /order/page` | 订单列表 |
| `POST /order/statistic` | 订单统计 |
| `POST /account/order/page` | 客户订单列表 |

### 10.5 仪表板

| 端点 | 用途 |
|------|------|
| `POST /dashboard/page` | 仪表板列表 |
| `GET /dashboard/detail/{id}` | 仪表板详情（含 resourceUrl） |
| `POST /dashboard/add` | 创建仪表板 |

> 仪表板可以在 Cordys CRM 前端创建 L2C 漏斗报表，然后通过 API 获取。

### 10.6 组织与成员

| 端点 | 用途 | 关键约束 |
|------|------|----------|
| `GET /department/tree` | 当前账号可见组织树 | 用于递归范围和 `org outline` 层级，不把扁平 ID 顺序当层级 |
| `POST /user/list` | 成员列表 | 顶层 `departmentIds` 只精确匹配，不自动包含子部门 |

`crm members` 接受一个或多个父部门 ID，并在内部先读取组织树、展开为“本部门 + 全部子孙部门”、去重后再调用 `/user/list`。只有明确只查直属成员时才使用 `--exact-departments` 跳过递归。在职名单加 `--active --compact`；禁止顶层单数 `departmentId`、顶层 `enable` 或顶层 `status`。
