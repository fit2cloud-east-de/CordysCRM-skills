# 跟进记录字段参考

## 写入端点

```
POST /{module}/follow/record/add
```

module 取值：`lead`（线索）、`account`（客户）、`opportunity`（商机）

> 跟进表单全局接口：`GET /follow/record/module/form`

## 必填字段清单

| # | 字段 | JSON 键名 | 格式 | 填充来源 |
|---|------|----------|------|---------|
| 1 | module | module | 文本：`lead` / `account` / `opportunity` | 搜索结果类型 |
| 2 | 跟进类型 | type | SELECT：`CLUE` 或 `CUSTOMER` | 搜索结果类型 |
| 3 | 记录 ID | clueId / customerId / opportunityId | 文本 | 搜索结果 ID |
| 4 | 跟进内容 | content | 文本（建议带 `【AI打卡】` 前缀） | 模板自动生成 |
| 5 | 跟进方式 | followMethod | SELECT ID（见 `mappings/follow-method.md`） | AI 识别 > 场景默认值 |
| 6 | 跟进时间 | followTime | 毫秒时间戳 | 当前时间 |
| 7 | 跟进人 | owner | userId（不是姓名） | 搜索结果的 follower > owner > whoami |

## 字段填充优先级

所有字段按以下优先级填充（从高到低）：

1. **AI 语义识别**（extracted_fields）：用户明确说了的信息
2. **搜索结果原始记录**：CRM 中已有的字段值直接复用
3. **场景默认值**：followMethod 等按场景取默认值

### 搜索结果可复用字段

| 跟进字段 | 搜索结果字段 | 说明 |
|---------|------------|------|
| owner | `follower` 或 `owner` | 优先取 follower（当前跟进人），无则取 owner |
| contact | `contact` | CRM 中的联系人，AI 识别的联系人优先 |
| moduleFields（意向产品） | `products` | 产品 ID 需通过 optionMap 映射成名称，再填入 moduleFields |

## type 与 ID 字段映射

| module | type | ID 字段 | 说明 |
|--------|------|---------|------|
| lead | CLUE | clueId | 线索跟进 |
| account | CUSTOMER | customerId | 客户跟进 |
| opportunity | CUSTOMER | opportunityId + customerId | 商机跟进（需同时传 customerId，从搜索结果的 `accountId` 字段获取） |

> ⚠️ 商机的 type 是 `CUSTOMER`（不是 OPPORTUNITY），这是 CRM API 的要求。商机写入时需同时传 `opportunityId` 和 `customerId`。

## 选填字段

<!-- AUTO-GENERATED-START -->

| 字段 | JSON 键名 | 格式 | 说明 |
|------|----------|------|------|
| 意向产品 | 意向产品 | ⚠️ 实体 ID（可多选） | |

## 跟进方式可选值（自动同步）

- `1` = 到访
- `2` = 电话
- `176776376843300000` = 微信
- `176092552150400000` = 邮件
- `175375487193300000` = 线上会议
<!-- AUTO-GENERATED-END -->

## 跟进内容模板

```
【AI打卡】{打卡类型} | {YYYY-MM-DD HH:mm}
{用户业务描述}
```

- 第一行必带，标识 AI 打卡产生的跟进
- 打卡类型取值：线下拜访 → `线下拜访`，线上拜访 → `线上拜访`，纯跟进 → `跟进`
- 用户说了业务内容 → 追加在第二行
- 用户没说业务内容 → 只有第一行

## 跟进方式

见 `mappings/follow-method.md`。

## 响应

成功：`{"code": 100200, "data": {"id": "跟进记录ID", ...}}`

失败：`{"code": 非100200, "message": "错误描述"}`

> `data.id` 是打卡 API 必需的 `crmFollowUpId`，写入成功后必须保存此值。
