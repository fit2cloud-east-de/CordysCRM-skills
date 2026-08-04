# 跟进记录字段参考

## 新增与更新端点

```
POST /{module}/follow/record/add
GET  /{module}/follow/record/get/{id}
POST /{module}/follow/record/update
```

module 取值：`lead`（线索）、`account`（客户）、`opportunity`（商机）

> 跟进表单全局接口：`GET /follow/record/module/form`
> 查询跟进计划/记录的 `sourceId` 映射见 `references/crm-api.md`，不要和本文件的写入字段混用。
> 结构化命令：新增用 `cordys_ext.sh follow`；更新前详情用 `cordys.sh crm follow-get record`；确认后更新用 `cordys_ext.sh follow-update`。

## 必填字段清单

> 由 `sync` 从 `/follow/record/module/form` 自动拉取，反映跟进表单的字段结构。CRM 新增/改名/改必填/改选项会自动反映到这里。
> 字段怎么填、格式约定、跨接口映射等**写入语义**见文末「写入补充」。

<!-- AUTO-GENERATED-START -->
| 字段 | businessKey | 类型 | 必填 |
|------|------------|------|------|
| 跟进类型 | type | SELECT | 是 |
| 客户名称 | customerId | DATA_SOURCE | 是 |
| 公司名称 | clueId | DATA_SOURCE | 是 |
| 商机 | opportunityId | DATA_SOURCE | 否 |
| 跟进内容 | content | TEXTAREA | 是 |
| 联系人 | contactId | DATA_SOURCE | 是 |
| 跟进方式 | followMethod | SELECT | 是 |
| 跟进时间 | followTime | DATE_TIME | 是 |
| 跟进人 | owner | MEMBER | 是 |
| 意向产品 | — | DATA_SOURCE_MULTIPLE | 否 |

## 选填自定义字段

| 字段 | JSON 键名 | 格式 | 说明 |
|------|----------|------|------|
| 意向产品 | 意向产品 | ⚠️ 实体 ID（可多选） | |

## 跟进方式可选值

- `1` = 到访
- `2` = 电话
- `176776376843300000` = 微信
- `176092552150400000` = 邮件
- `175375487193300000` = 线上会议


## 查询字段参考

> 用于 `combineSearch.conditions` 的 `name` 值。有 businessKey 的用 businessKey，否则用 fieldId。操作符规则见 `core/cli-reference.md`。

> “系统/API”字段可能不显示为自定义表单控件或“表单 SELECT 字段可选值”列表；只要列在本表中，即可作为 conditions 的字段依据。

| 字段 | name（条件用） | type | 来源 |
|------|--------------|------|------|
| 跟进类型 | type | SELECT | 表单 |
| 客户名称 | customerId | DATA_SOURCE | 表单 |
| 公司名称 | clueId | DATA_SOURCE | 表单 |
| 商机 | opportunityId | DATA_SOURCE | 表单 |
| 跟进内容 | content | TEXTAREA | 表单 |
| 联系人 | contactId | DATA_SOURCE | 表单 |
| 跟进方式 | followMethod | SELECT | 表单 |
| 跟进时间 | followTime | DATE_TIME | 表单 |
| 跟进人 | owner | MEMBER | 表单 |
| 意向产品 | 1127497634685009 | DATA_SOURCE_MULTIPLE | 表单 |

## 视图目录

> `viewId` 按模块选择。官方内置视图由 Cordys 前端定义；实例自定义视图由 `sync` 从对应 `/view/list` 自动刷新。
> 自定义视图路由：用户明确引用视图，或去掉“看下/查看/查询/列出”等纯查询外壳后与唯一、已启用的视图名称完全一致时，直接使用该 `viewId`；精确命中后不从名称重复构造部门、时间条件。模糊相似仍按字段条件查询。视图不能扩大当前角色的数据范围。

### 官方内置视图

| 视图名称 | viewId |
|----------|--------|
| 所有记录 | `ALL` |
| 我的记录 | `SELF` |
| 部门记录 | `DEPARTMENT` |

### 实例自定义视图（自动同步）

| 视图名称 | viewId | 启用 | 固定 |
|----------|--------|------|------|
| — | — | — | — |
<!-- AUTO-GENERATED-END -->

## 跟进内容模板

content 必须严格按以下格式，不得随意变更：

**拜访打卡**：`【AI打卡】{打卡类型}\n{用户业务描述}`
- 线下拜访 → `【AI打卡】线下拜访\n{用户业务描述}`
- 线上拜访 → `【AI打卡】线上拜访\n{用户业务描述}`

**纯跟进**：`【AI打卡】跟进\n{用户业务描述}`

示例：
- 用户说"线下拜访飞致云聊了产品" → content = `【AI打卡】线下拜访\n在飞致云聊了产品`
- 用户说"线上拜访千里眼科技" → content = `【AI打卡】线上拜访\n拜访千里眼科技`
- 用户说"跟进一下飞致云，聊了需求" → content = `【AI打卡】跟进\n跟进飞致云，聊了需求`
- 用户说"记录一下千里眼科技" → content = `【AI打卡】跟进\n记录千里眼科技`

> ⚠️ 第一行格式固定为 `【AI打卡】{打卡类型}`，不要写成其他格式（如"线下拜访了XX公司""拜访打卡"等）。第二行保留用户的完整业务描述，不要缩减内容。

## 跟进方式

见 `references/mappings/follow-method.md`。

## 响应

成功：`{"code": 100200, "data": {"id": "跟进记录ID", ...}}`

失败：`{"code": 非100200, "message": "错误描述"}`

> `data.id` 是打卡 API 必需的 `crmFollowUpId`，写入成功后必须保存此值。

更新目标值与当前值相同时返回 `noOp:true`，不会发送 POST。更新响应异常但回读确认生效时返回 `verifiedAfterFailure:true`；无法回读确认时返回 `retryAllowed:false`，调用方必须停止，禁止自动重试。

## 写入补充

> 表单接口给不出的**写入语义**：API 级参数、格式约定、填充来源、跨接口映射（人工维护，位于自动生成区块外，`sync` 不会覆盖）。

### 写入参数与格式约定

| 参数 | 格式 / 约定 | 填充来源 | 说明 |
|------|------------|---------|------|
| module | `lead` / `account` / `opportunity` | 搜索结果类型 | 写入端点 URL 路径参数，非表单字段 |
| type | `CLUE` 或 `CUSTOMER` | 搜索结果类型 | 取值与 module 绑定，见下方映射 |
| 记录 ID | clueId / customerId / opportunityId 三选一 | 搜索结果 ID | 按 module 取对应字段 |
| content | 文本，建议带 `【AI打卡】` 前缀 | 模板自动生成 | 格式见「跟进内容模板」 |
| followMethod | SELECT ID（见 `references/mappings/follow-method.md`） | AI 识别 > 场景默认值 | 传 ID 不传中文 |
| followTime | 毫秒时间戳 | 当前时间 | 字符串日期按 UTC+8（Asia/Shanghai）解析；禁止 `CST` 等歧义时区缩写 |
| owner | userId（不是姓名） | 搜索结果的 follower > owner > whoami | |

### 更新参数与安全约定

更新接口不是 PATCH，OpenAPI 实际要求完整携带 `id`、`content`、`followMethod`、`owner`、`type`。禁止根据用户只说的一个字段手工拼裸请求；`follow-update` 会先 GET 详情，保留资源归属、负责人、自定义字段等旧值，再覆盖用户明确修改的字段并只 POST 一次。

| 参数 | 更新约定 |
|------|---------|
| module | 必填，取该跟进记录真实父模块 `lead/account/opportunity` |
| id / recordId / followRecordId | 必填，必须是**跟进记录 ID**，不是线索/客户/商机 `sourceId` |
| content / 跟进内容 | 可改，必须是非空文本；AI 打卡记录继续保持本文内容模板 |
| followTime / 跟进时间 | 可改，传 UTC+8 业务日期字符串或毫秒时间戳 |
| followMethod / 跟进方式 | 可改，读取跟进记录表单的专属选项，不能使用计划方式 ID |
| owner / 跟进人 | 可改，最终必须唯一解析为 userId |
| contactId / 联系人ID | 可改；传空值表示清空联系人 |
| products / 意向产品 | 可改；名称或 ID 数组，脚本保留其他 moduleFields |
| moduleFields | 高级完整数组写法；与“意向产品”不能同时传，按完整自定义字段集合处理 |

执行更新前必须用 `crm follow-get record <module> <id>` 展示当前值与目标值并取得用户确认。`type` 与资源 ID 只能保留原值，禁止通过编辑改绑。`noOp:true` 表示未提交写请求；`verifiedAfterFailure:true` 表示异常响应后回读确认成功；`retryAllowed:false` 时禁止自动重试。

### type 与 ID 字段映射

| module | type | ID 字段 | 说明 |
|--------|------|---------|------|
| lead | CLUE | clueId | 线索跟进 |
| account | CUSTOMER | customerId | 客户跟进 |
| opportunity | CUSTOMER | opportunityId + customerId | 商机跟进（需同时传 customerId，从搜索结果的 `accountId` 字段获取） |

> ⚠️ 商机的 type 是 `CUSTOMER`（不是 OPPORTUNITY），这是 CRM API 的要求。商机写入时需同时传 `opportunityId` 和 `customerId`。

### 字段填充优先级

所有字段按以下优先级填充（从高到低）：

1. **AI 语义识别**（extracted_fields）：用户明确说了的信息
2. **搜索结果原始记录**：CRM 中已有的字段值直接复用
3. **场景默认值**：followMethod 等按场景取默认值

#### 搜索结果可复用字段

| 跟进字段 | 搜索结果字段 | 说明 |
|---------|------------|------|
| owner | `follower` 或 `owner` | 优先取 follower（当前跟进人），无则取 owner |
| contact | `contact` | CRM 中的联系人，AI 识别的联系人优先 |
| moduleFields（意向产品） | `products` | 产品 ID 需通过 optionMap 映射成名称，再填入 moduleFields |
