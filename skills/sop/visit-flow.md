# 拜访跟进流程

用户提到"拜访""跟进""记录"某公司时执行本流程。涵盖拜访打卡和纯跟进两种场景。

---

## 意图识别

| 用户输入 | 场景 | 打卡卡片 |
|---------|------|---------|
| "线上拜访XX" / "线下拜访XX" / "拜访XX" | 拜访打卡 | 直接发 |
| "跟进XX" / "记录一下XX" / "XX聊了产品" | 纯跟进 | 不发，写完跟进即结束 |

> "拜访"未说线上/线下时，追问用户确认打卡类型。纯跟进场景不涉及打卡类型，也不问是否打卡。

---

## 步骤 1：提取信息

从用户输入提取以下字段：

| 字段 | 必填 | 来源 |
|------|------|------|
| customer_name | 是 | 用户消息中的公司/机构名 |
| checkin_type | 拜访场景必填 | 线上拜访 / 线下拜访（无法判断时追问用户） |
| crm_type_hint | 否 | 用户明确说了"线索""商机""客户""创建线索"时提取 |
| followMethod | 是 | 见 `references/mappings/follow-method.md` |
| extracted_fields | 否 | AI 语义识别的字段值（见下方规则） |
| 用户业务描述 | 否 | 用户消息中除关键词外的内容（没说就不填，不追问） |

### checkin_type 提取规则

| 用户表达 | checkin_type |
|---------|-------------|
| "线上""电话""远程""视频""打了个电话" | 线上拜访 |
| "线下""上门""面谈""当面""去了""去""拜访" | 线下拜访 |
| 纯跟进（"跟进""记录"等，不含"拜访"） | 不需要 |

> "拜访"就是线下拜访，不需要追问。只有用户明确说"线上"才是线上拜访。纯跟进场景不需要 checkin_type。

### crm_type_hint 提取规则

| 用户表达 | crm_type_hint | 效果 |
|---------|--------------|------|
| "跟进线索XX""线索打卡XX" | 线索 | 优先搜 lead 模块 |
| "跟进商机XX""商机打卡XX" | 商机 | 优先搜 opportunity 模块 |
| "跟进客户XX""客户打卡XX" | 客户 | 优先搜 account 模块 |
| "创建线索XX""新建线索XX" | 创建线索 | 跳过搜索，直接走创建 |
| 未提到具体类型 | 空 | 正常搜索三个模块 |

> 用户明确说了类型才提取，不推测。`创建线索`表示用户明确要新建，跳过搜索直接走 `sop/write-flow.md`。

### extracted_fields 提取规则（AI 语义识别）

AI 负责语义理解，识别用户明确表达的信息；不确定的字段不填。

| 语义 | 对应字段 | 识别示例 |
|------|---------|---------|
| 沟通方式 | 跟进方式 | "电话聊了"→电话，"微信上聊"→微信，"去见了"→拜访 |
| 人物 | 联系人 | "见了张经理"→张经理，"跟李总聊"→李总 |
| 业务/方案 | 产品/需求 | "聊了云平台"→云平台，"聊采购需求"→采购 |

**只提取语义明确的信息**：
- ✅ "见了张经理" → 联系人明确
- ✅ "电话聊了" → 跟进方式明确
- ❌ "聊了产品" → 产品不明确，不填
- ❌ "跟他们沟通" → 方式不明确，不填

### customer_name 提取规则

1. 先排除类型词（"线索""商机""客户""创建线索"），再识别公司名
2. "拜访""跟进""去了"后面紧跟的名词优先
3. 不确定时不填，追问用户

---

## 步骤 2：搜索 CRM 定位对象

如果 `crm_type_hint` 为 `创建线索`，跳过搜索，直接走 `sop/write-flow.md`。

否则，使用 `cordys.sh crm search` 搜索对应模块：

- `crm_type_hint` 为 `线索` → 只搜 lead
- `crm_type_hint` 为 `商机` → 只搜 opportunity
- `crm_type_hint` 为 `客户` → 只搜 account
- `crm_type_hint` 为空 → 并行搜索三个模块

```bash
cordys.sh crm search lead '{"keyword":"<customer_name>","pageSize":10}'
cordys.sh crm search account '{"keyword":"<customer_name>","pageSize":10}'
cordys.sh crm search opportunity '{"keyword":"<customer_name>","pageSize":10}'
```

### 搜索增强

原始搜索无结果时，AI 按以下顺序尝试增强搜索：

1. 去掉自然语言包裹（"的一家""这家""那个""某家""什么"等）
2. 去掉企业后缀（优先去长后缀：`有限责任公司`→`股份有限公司`→`有限公司`→`公司`→`企业`→`集团`等）
3. 拆分有意义片段（如"上海智能科技"→"上海"+"智能科技"）
4. 仅在仍无结果时，尝试双字到四字窗口

**约束**：
- 一旦某阶段得到结果，停止继续下钻
- 不单独搜索泛化词（"公司""有限""集团""银行""学院"等）
- 不搜索单字

### 相关性过滤

搜索结果需判断与 `customer_name` 的关系：

| 判断 | 标准 | 处理 |
|------|------|------|
| 同一实体 | 简称、全称、别名关系 | 保留 |
| 可能相关 | 母子公司、附属机构、同集团 | 保留 |
| 明显无关 | 只共享常见词 | 过滤 |

示例：搜"龙岩"命中"龙岩学院"→保留；命中"龙岩花园物业"→过滤。

### 结果分流

**1 条匹配** → 直接使用，进入步骤 3

**多条匹配，同一实体** → 按优先级选取：商机 > 线索 > 客户。同一实体只保留最高优先级的记录

**多条匹配，不同实体** → 列出让用户选择：

```
找到以下匹配记录：
1. 商机：XX项目（负责人：张三）
2. 线索：XX科技（负责人：李四）
请回复序号即可。
```

展示规则：
- 按优先级排序（商机在前，线索次之，客户最后）
- 客户和线索：显示 `类型 + 名称 + 负责人`
- 商机多条且客户名称相同：显示 `商机名称 + 意向产品`
- 商机多条且客户名称不同：显示 `客户名称 + 商机名称 + 负责人`
- 全部展示，不截断

**0 条匹配** → 问用户是否创建新线索：

```
CRM 中未找到"{customer_name}"相关记录，是否创建新线索？
```

- 用户确认 → 走 `sop/write-flow.md` 创建线索 → 拿到 clueId → 继续步骤 3
- 用户拒绝 → 结束

### 中断恢复

用户在多条匹配选择时：
- 回复序号 → 取对应记录继续
- 回复名称 → 匹配对应记录继续
- 说"都不是"或"不对" → 视为未命中，问是否创建线索
- 给出新的公司名 → 用新名称重新搜索

> 已提取的字段（contact、extracted_fields 等）继续沿用，不重新提取。

---

## 步骤 3：写跟进记录

```bash
cordys_ext.sh follow '<JSON>'
```

字段定义、type 映射、content 模板、moduleFields 等详见 `references/forms/follow.md`。

### content 模板

```
【AI打卡】{打卡类型} | {YYYY-MM-DD HH:mm}
{用户业务描述}
```

| 场景 | 打卡类型 | followMethod | 说明 |
|------|---------|-------------|------|
| 线下拜访 | 线下拜访 | 1（到访） | "拜访"默认线下 |
| 线上拜访 | 线上拜访 | 2（电话）或其他线上方式 | 用户明确说"线上" |
| 纯跟进 | 跟进 | 2（电话） | "跟进"不含"拜访"，默认电话跟进 |

> followMethod 和 content 的打卡类型必须一致：线下拜访→到访(1)，线上拜访→电话(2)或其他，纯跟进→电话(2)。纯跟进写完即结束，不打卡。

### JSON 参数构建

根据搜索结果的记录类型，构建不同参数。

**字段填充优先级**（从高到低）：

1. **AI 语义识别**（extracted_fields）：用户明确说了的信息优先
2. **搜索结果原始记录**：CRM 中已有的字段值直接复用
3. **场景默认值**：followMethod 等按场景取默认值

**搜索结果可复用字段**：

| 跟进字段 | 搜索结果字段 | 说明 |
|---------|------------|------|
| owner | `follower` 或 `owner` | 优先取 follower（当前跟进人），无则取 owner |
| contact | `contact` | CRM 中的联系人 |
| moduleFields | `products` | 产品 ID 需转为 moduleFields 格式：`[{"fieldId":"1127497634685009","fieldValue":["产品名"]}]` |

> 搜索结果中的 `products` 是产品 ID 数组，需要通过 `optionMap`（搜索结果同级返回）的 `products` 选项映射成产品名称，再填入 moduleFields。

根据搜索结果的记录类型，构建不同参数：

**线索**：
```json
{
  "module": "lead",
  "type": "CLUE",
  "clueId": "<线索ID>",
  "content": "【AI打卡】线下拜访 | 2026-06-03 10:30\n聊了产品需求",
  "followMethod": "1",
  "followTime": 1780453000000,
  "owner": "<userId>",
  "contact": "<联系人，有则传>",
  "moduleFields": []
}
```

**客户**：
```json
{
  "module": "account",
  "type": "CUSTOMER",
  "customerId": "<客户ID>",
  "content": "【AI打卡】线下拜访 | 2026-06-03 10:30\n聊了产品需求",
  "followMethod": "1",
  "followTime": 1780453000000,
  "owner": "<userId>",
  "contact": "<联系人，有则传>",
  "moduleFields": []
}
```

**商机**：
```json
{
  "module": "opportunity",
  "type": "CUSTOMER",
  "opportunityId": "<商机ID>",
  "customerId": "<商机所属客户ID>",
  "content": "【AI打卡】线下拜访 | 2026-06-03 10:30\n聊了产品需求",
  "followMethod": "1",
  "followTime": 1780453000000,
  "owner": "<userId>",
  "contact": "<联系人，有则传>",
  "moduleFields": []
}
```

### 返回值处理

- `code: 100200` → 写入成功，取 `data.id` 作为 `crmFollowUpId`
- 非 100200 → 展示错误信息，提示用户稍后重试

### 缺失字段处理

follow 的必填字段全部由系统自动填充，不需要追问用户：

| 字段 | 来源 |
|------|------|
| module | 搜索结果类型 |
| type | 搜索结果类型（CLUE/CUSTOMER） |
| clueId/customerId/opportunityId | 搜索结果 ID |
| content | 模板自动生成 |
| followMethod | 按场景默认值（见上方表格） |
| followTime | 当前时间戳 |
| owner | whoami 的 userId |

如果 follow 返回错误，展示错误信息让用户知道，不要追问字段。

---

## 步骤 4：打卡卡片（仅拜访意图）

纯跟进在步骤 3 写完后即结束，不进入本步骤。

### 场景判断

| 场景 | 处理 |
|------|------|
| 意图=拜访 | 直接进入打卡 |

### 企业微信判断

打卡节点检查对话上下文中是否有企业微信 userid：

- **有** → 调用打卡 API，发送卡片
- **无** → 提示"请在企业微信中发起打卡"，跟进记录已写入 CRM

### 调用打卡 API

打卡 API 请求/响应格式、卡片 JSON 模板、时间段问候等详见 `references/checkin-api.md`。

```bash
curl -s -X POST https://www.lobster-checkin.xyz/api/wechat/create-checkin \
  -H "Content-Type: application/json" \
  -d '{
    "userid": "<企业微信userid>",
    "填写人": "<User.md 中的姓名>",
    "所在部门": "<User.md 中的部门>",
    "打卡类型": "<线上拜访/线下拜访>",
    "用户类型": "企业微信用户",
    "crmFollowUpId": "<步骤3返回的data.id>",
    "拜访公司名称": "<customer_name>",
    "拜访公司类型": "<搜索结果的company_type>",
    "跟进类型": "<线索/客户/商机>",
    "跟进内容": "<content字段值>",
    "来源详情": "<联系人，有则传>",
    "交流产品类型": "<产品，有则传>",
    "是否首次拜访": "<用户说是首次→true，否则不传>",
    "webhookUrl": "<OPENCLAW_WEBHOOK_URL>"
  }'
```

> ⚠️ `crmFollowUpId` 是必填字段，不传打卡 API 会拒绝创建链接。值来自步骤 3 返回的 `data.id`。

### 响应处理

- `success: true` → 用返回的 `link` 输出拜访打卡卡片
- `success: false` → 提示"跟进已写入 CRM，但打卡系统暂时不可用，请稍后再试"

### 拜访打卡卡片

字段：`时间段问候`、`打卡类型`、`所在部门`、`拜访公司名称`、`跟进类型`、`link`

补充字段（有值时填入，无值时省略）：`contact`（联系人）、`followContent`（跟进内容摘要，取用户原始输入的业务描述部分，不超过20字）、`stageName`（商机阶段）、`products`（意向产品）

```text
{时间段问候}，已跟进到{跟进类型}「{拜访公司名称}」{如有contact：，联系人{contact}}{如有followContent：，{followContent}}。
{如有stageName或products：当前阶段：{stageName}，意向产品：{products}}
打卡卡片来了。
```

卡片 JSON 模板见 `references/checkin-api.md`。

---

## Webhook 回调

收到打卡系统的 webhook 通知时，原样发送给用户（纯文本，不用卡片/markdown），不暴露技术细节。详见 `references/checkin-api.md` 的 Webhook 回调章节。

失败通知：`打卡失败，请重新说"打卡"再试。`

---

## 错误处理

| 场景 | 处理 |
|------|------|
| CRM 搜索失败 | 提示"暂时无法查询 CRM，请稍后再试" |
| follow 返回非 100200 | 展示错误信息，提示稍后重试 |
| follow 返回缺少 followMethod | 检查是否传了 followMethod 字段 |
| 打卡 API 返回 success:false | "跟进已写入 CRM，但打卡系统暂时不可用" |
| 非企业微信环境 | "请在企业微信中发起打卡"，跟进已写入 |
| CRM 凭证失效（error_type=auth） | 提示检查 .env 中的 CORDYS_ACCESS_KEY / CORDYS_SECRET_KEY |
| CRM 未配置（error_type=config） | 提示配置 .env 中的 CRM 凭证 |
| 服务端错误（error_type=server/business/network） | 提示"暂时无法完成操作，请稍后再试" |
| customer_name 为空 | 追问"这次拜访的是哪家公司？" |
| customer_name 太模糊（如"那个""一家"等） | 追问"请提供具体的公司或机构名称。" |
