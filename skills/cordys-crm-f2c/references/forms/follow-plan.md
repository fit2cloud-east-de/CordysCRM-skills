# 跟进计划字段参考

> 跟进**计划** = 后续要做的跟进（预约/排期）；跟进**记录** = 已发生的跟进。写入契约不同，见 `follow.md`。

## 写入端点

```
POST /{module}/follow/plan/add
```

module 取值：`lead`（线索）、`account`（客户）、`opportunity`（商机）

> 跟进计划表单全局接口：`GET /follow/plan/module/form`
> 查询跟进计划的 `sourceId` 映射见 `references/crm-api.md`，不要和本文件的写入字段混用。

## 必填字段清单

> 由 `sync` 从 `/follow/plan/module/form` 自动拉取，反映跟进计划表单的字段结构。CRM 新增/改名/改必填/改选项会自动反映到这里。
> ⚠️ 表单 rules 把字段都标"否"，但**写入 API 实际强制必填 `type` + `method`**（后端 @NotBlank，表单给不出）——真必填以下方「写入补充」为准。
> 字段怎么填、格式约定、跨接口映射等**写入语义**见文末「写入补充」。

<!-- AUTO-GENERATED-START -->
| 字段 | businessKey | 类型 | 必填 |
|------|------------|------|------|
| 跟进类型 | type | SELECT | 是 |
| 客户名称 | customerId | DATA_SOURCE | 是 |
| 公司名称 | clueId | DATA_SOURCE | 是 |
| 商机 | opportunityId | DATA_SOURCE | 否 |
| 联系人 | contactId | DATA_SOURCE | 是 |
| 预计开始时间 | estimatedTime | DATE_TIME | 是 |
| 跟进方式 | method | SELECT | 是 |
| 跟进人 | owner | MEMBER | 是 |
| 意向产品 | — | DATA_SOURCE_MULTIPLE | 是 |
| 预计沟通内容 | content | TEXTAREA | 是 |

## 选填自定义字段

| 字段 | JSON 键名 | 格式 | 说明 |
|------|----------|------|------|
| 意向产品 | 意向产品 | ⚠️ 实体 ID（可多选） | |

## 跟进方式可选值

- `1` = 到访
- `2` = 电话
- `176776378282600000` = 微信
- `176092554492700000` = 邮件
- `175375488829300000` = 线上会议


## 查询字段参考

> 用于 `combineSearch.conditions` 的 `name` 值。有 businessKey 的用 businessKey，否则用 fieldId。操作符规则见 `core/cli-reference.md`。

> “系统/API”字段可能不显示为自定义表单控件或“表单 SELECT 字段可选值”列表；只要列在本表中，即可作为 conditions 的字段依据。

| 字段 | name（条件用） | type | 来源 |
|------|--------------|------|------|
| 跟进类型 | type | SELECT | 表单 |
| 客户名称 | customerId | DATA_SOURCE | 表单 |
| 公司名称 | clueId | DATA_SOURCE | 表单 |
| 商机 | opportunityId | DATA_SOURCE | 表单 |
| 联系人 | contactId | DATA_SOURCE | 表单 |
| 预计开始时间 | estimatedTime | DATE_TIME | 表单 |
| 跟进方式 | method | SELECT | 表单 |
| 跟进人 | owner | MEMBER | 表单 |
| 意向产品 | 1127497634685019 | DATA_SOURCE_MULTIPLE | 表单 |
| 预计沟通内容 | content | TEXTAREA | 表单 |

## 视图目录

> `viewId` 按模块选择。官方内置视图由 Cordys 前端定义；实例自定义视图由 `sync` 从对应 `/view/list` 自动刷新。
> 自定义视图只在用户明确引用视图时使用；未明确引用时按角色基础范围查询。视图不能扩大当前角色的数据范围。

### 官方内置视图

| 视图名称 | viewId |
|----------|--------|
| 所有计划 | `ALL` |
| 我的计划 | `SELF` |
| 部门计划 | `DEPARTMENT` |

### 实例自定义视图（自动同步）

| 视图名称 | viewId | 启用 | 固定 |
|----------|--------|------|------|
| — | — | — | — |
<!-- AUTO-GENERATED-END -->

## 写入补充

> 表单接口给不出的**写入语义**：API 级参数、格式约定、填充来源、跨接口映射（人工维护，位于自动生成区块外，`sync` 不会覆盖）。

### 写入参数与格式约定

| 参数 | 格式 / 约定 | 填充来源 | 说明 |
|------|------------|---------|------|
| module | `lead` / `account` / `opportunity` | 搜索结果类型 | 写入端点 URL 路径参数，非表单字段 |
| type | `CLUE` 或 `CUSTOMER`，**必填** | 搜索结果类型 | 取值与 module 绑定，见下方映射 |
| 记录 ID | clueId / customerId / opportunityId 三选一 | 搜索结果 ID | 按 module 取对应字段 |
| content | 文本（预计沟通内容） | AI 识别用户描述 | 计划内容 |
| method | SELECT ID，**必填** | AI 识别 > 场景默认值（电话 `2`） | 传 ID 不传中文；⚠️ 选项 ID 见本文件 AUTO 区块，与跟进记录表单**不同**，不可复用 follow.md 的 ID |
| estimatedTime | 毫秒时间戳（计划时间） | 用户指定的计划日期，缺省取当前时间 | 接受 `YYYY-MM-DD HH:MM`（固定按 UTC+8 解析）、JSON 整数毫秒戳或纯数字字符串毫秒戳；禁止 `CST` 等时区缩写。显式非法值直接报错且不创建。字段名是 `estimatedTime`，不是记录的 `followTime` |
| owner | userId（不是姓名） | 搜索结果的 follower > owner > whoami | |
| status | 缺省不传 | 后端默认置 `PREPARED` | |

### type 与 ID 字段映射

| module | type | ID 字段 | 说明 |
|--------|------|---------|------|
| lead | CLUE | clueId | 线索跟进计划 |
| account | CUSTOMER | customerId | 客户跟进计划 |
| opportunity | CUSTOMER | opportunityId + customerId | 商机跟进计划（需同时传 customerId，从搜索结果的 `accountId` 字段获取） |

> ⚠️ 商机的 type 是 `CUSTOMER`（不是 OPPORTUNITY），这是 CRM API 的要求。商机写入时需同时传 `opportunityId` 和 `customerId`。

### 与跟进记录（follow.md）的字段差异

| | 跟进计划（本文件） | 跟进记录（follow.md） |
|---|---|---|
| 端点 | `/{module}/follow/plan/add` | `/{module}/follow/record/add` |
| 必填 | `type` + `method` | `type` |
| 时间字段 | `estimatedTime` | `followTime` |
| 方式字段 | `method` | `followMethod` |
| 方式选项 ID | 计划表单专属（见 AUTO 区块） | 记录表单专属 |

### 字段填充优先级

所有字段按以下优先级填充（从高到低）：

1. **AI 语义识别**（extracted_fields）：用户明确说了的信息（计划时间、跟进方式、计划内容）
2. **搜索结果原始记录**：CRM 中已有的字段值直接复用（owner、contact、products）
3. **场景默认值**：method 缺省取「电话」（`2`）

## 响应

成功：`{"code": 100200, "data": {"id": "跟进计划ID", "status": "PREPARED", ...}}`

失败：`{"code": 非100200, "message": "错误描述"}`

> `/{module}/follow/plan/add` 只有新增语义。成功返回后即使发现时间或字段不符合预期，也不得再次调用 `follow-plan`；先按返回 ID 查询核验，再向用户说明并确认纠错/清理方案。
