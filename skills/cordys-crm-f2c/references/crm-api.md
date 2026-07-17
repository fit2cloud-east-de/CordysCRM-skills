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
| `lead` | 潜在客户（线索）记录，用于销售团队初步跟进。         |
| `account` | 客户/公司基础信息，包含行业、地点、负责人等。        |
| `opportunity` | 商机（机会）记录，表示销售流程中的具体案子。         |
| `contract` | 合同及其回款、发票等子资源，用于追踪签署后的收款与交付状态。 |
| `lead-pool` | 线索池，用于共享线索。API 路径为 `pool/lead`。 |
| `account-pool` | 公海，用于共享客户。API 路径为 `pool/account`。 |

你在自然语言中提到的模块名，转换成命令时就能直接定位到本文档中所列的模块。

> **术语硬映射：`线索池` = `pool/lead`；`公海` = `pool/account`。** 两套 options 可以出现同名池，必须先按用户名词选择模块，再在对应 options 内匹配名称；不得因为另一模块存在同名池而切换端点。

`contract` 模块还有几个常用的二级资源：`contract/payment-plan`（回款计划）、`invoice`、`contract/business-title`（工商抬头）、`contract/payment-record` 以及 `opportunity/quotation`，CLI 仍然沿用 `page`/json 的方式访问它们。

---

## 2. 通用请求结构

> 完整的 JSON Body 模板及字段说明见 `../core/cli-spec.md#2-分页默认结构`。本节仅补充 API 层面的注意事项。

关键字段简述：
- `current`：页码（从 1 开始）
- `pageSize`：每页条数，默认 30；普通 `crm page` 按任务选择，`crm page-summary` 内部固定为 500 并自动翻页聚合
- `sort`：排序对象，例如 `{"followTime":"desc"}`
- `combineSearch.conditions`：组合筛选条件
- `keyword`：全局关键词，模糊匹配名称/说明/电话等
- `viewId`：按模块选择，完整官方/自定义目录见 `references/forms/{module}.md` 的「视图目录」。常见值包括 ALL、SELF、DEPARTMENT；客户另有 CUSTOMER_COLLABORATION，商机另有 OPPORTUNITY_SUCCESS。
- `filters`：精细字段级过滤
- `poolId`: 目标池 id。`/pool/{module}/page` 查单个池时必传，值来自 `GET /pool/{module}/options`。跨池搜索用 `/global/search/clue_pool`（线索池）或 `/global/search/customer_pool`（公海），传 keyword 即可。其它模块查询无需该参数。

---

## 3. 常用 HTTP 端点
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/{module}/view/list` | 列出当前实例、当前用户可见的自定义视图（不返回官方内置视图，也不返回业务数据）。联系人为 `/account/contact/view/list`，跟进记录/计划为 `/follow/record/view/list`、`/follow/plan/view/list`。 |
| `GET` | `/{module}/get/{id}` | 获取单条记录详情。 |
| `POST` | `/{module}/page` | 发送上面模型的 JSON 进行分页查询（支持复杂过滤 + 关键词）。联系人使用 `/account/contact/page`。 |
| `POST` | `/global/search/{module}` | 全局搜索，JSON body 结构同上，额外在多个字段里查关键词。池模块端点名：线索池 `/global/search/clue_pool`、公海 `/global/search/customer_pool`（`crm search pool/lead`、`pool/account` 已自动映射）。 |

> 全局搜索（`crm search`）覆盖 `lead`/`account`/`opportunity` 及线索池/公海；联系人由 CLI 特殊映射到 `/account/contact/page`，支持姓名和手机号关键词。签约后家族（`contract`/`invoice`/`order`/`contract/payment-record`/`contract/payment-plan`/`contract/business-title`/`opportunity/quotation`）无全局搜索，按父 id 走两个维度取数器：客户名下用 `crm acct-sub <子资源> <客户ID>`，合同名下用 `crm contract-sub payment-record|payment-plan|invoice-stat <合同ID>`（父 id 放对位置的坑藏在命令内部，不用手搓 body）；名称关键词用 `crm page {module} '{"keyword":"…"}'`。详见 §7、§10.2。
| `GET` | `/{module}/contact/list/{id}` | 获取某条记录的联系人列表（仅 `opportunity`、`account` 模块）。 |
| `GET` | `/pool/{module}/options` | 获取当前用户可见的线索池/公海列表（`module` 为 `lead`/`account`），返回各池的 `id`（即 poolId）与 `name`。 |
| `POST` | `/pool/{module}/page` | **单个**线索池/公海记录分页。body 同标准分页结构，`poolId` 必传，取自 `/pool/{module}/options`。跨池搜索用 `/global/search/clue_pool`、`/global/search/customer_pool`。 |

> `cordys raw {METHOD} {PATH} [JSON body]` 仅用于调用同一 `CORDYS_CRM_DOMAIN` 下的已知端点；认证 header 由脚本注入，调用方不得提供自定义 header 或任意 curl 参数。优先使用结构化 `crm ...` 命令。

---

## 跟进计划与记录 API
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/{module}/follow/plan/page` | 查询某条资源的跟进计划，必须带 `sourceId`，支持 `status`、`myPlan`、`keyword` 等字段。|
| `POST` | `/{module}/follow/record/page` | 查询某条资源的跟进记录，以 `sourceId` 为主，并可额外筛 `keyword`。|
| `POST` | `/{module}/follow/plan/add` | 新增跟进计划（后续要做的跟进）。走 `cordys_ext.sh follow-plan`。必填 `type`+`method`；字段见 `references/forms/follow-plan.md`。|
| `POST` | `/{module}/follow/record/add` | 新增跟进记录（已发生的跟进）。走 `cordys_ext.sh follow`。必填 `type`；字段见 `references/forms/follow.md`。|

> 跟进查询路径必须匹配 `/{module}/follow/{plan|record}/page`。路径结构不完整时可能仍返回 HTTP 200，但响应体为空，不能当作“没有跟进记录”的证据。
> 跟进查询必须区分父模块，`module` 同时决定 URL 前缀；payload 再通过 `sourceId`、`keyword`、`combineSearch` 等条件过滤。需要查计划时请填 `status`（推荐 `ALL` / `UNFINISHED` / `FINISHED`），`myPlan` 表示是否只看本人创建的计划；如果只传 `keyword` 而不带 `sourceId`，接口会返回空内容。
`module` 目前常用 `lead`、`account`、`opportunity`；CLI 会把它同时写入 URL。商机查询必须使用 `opportunity` 前缀，不能用其所属客户替代父模块。

`sourceId` 必须取当前查询模块的业务主键：查 `lead` 时取线索 `id`，查 `account` 时取客户 `id`/`customerId`，查 `opportunity` 时取商机 `id`。商机查询不要把 `customerId` 当作 `/opportunity/follow/...` 的 `sourceId`；如需客户维度跟进记录，应改查 `/account/follow/record/page` 并传客户 ID。

`page_payload` 只会补 `current` / `pageSize` / `sort` / `filters`，所以任何需要的 `sourceId` / `status` / `myPlan` 都必须在 JSON body 里显式提供。


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
cordys.sh crm follow record lead '{"sourceId":"927627065163785","current":1,"pageSize":10,"keyword":"回访"}'
cordys.sh crm follow plan account '{"sourceId":"1751888184018919","current":1,"pageSize":10,"status":"ALL","myPlan":false}'
```

跟进计划**新增**（走扩展 CLI，中文方式/时间自动转换）：
```bash
cordys_ext.sh follow-plan '{"module":"lead","clueId":"398984062159048704","content":"下周电话回访采购进度","跟进方式":"电话","计划时间":"2026-07-15 10:00"}'
```
> ⚠️ 新增走 `/{module}/follow/plan/add`（带 module 前缀），字段用**存储态名**（`type`/`clueId`/`estimatedTime`/`method`/`content`），**不是**表单 `/follow/plan/module/form` 暴露的 `planXxx` 键。必填 `type`+`method`。计划的方式选项 ID 与记录不同，详见 `references/forms/follow-plan.md`。
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
