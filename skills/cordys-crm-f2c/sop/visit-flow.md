# 拜访跟进流程

用户提到"拜访""跟进""记录""聊了""约了…拜访/回访"某公司时执行本流程。先按下表判定走向：

| 用户说 | 走向 |
|--------|------|
| 只说"打卡""签到""上班"，未提公司 | 纯上班打卡 → 转 `sop/company-checkin-flow.md` |
| 公司名 + 含"拜访"（且要打卡） | 拜访打卡 → 本流程步骤 1–4 |
| 公司名 + 「跟进/记录/聊了」；或「已发生沟通 + 再约拜访/建计划」 | 纯跟进（±计划）→ 步骤 1–3（及 3b），**不打卡** |

> "拜访"且要发打卡卡、未说线上/线下时追问类型；纯跟进 / 仅建计划不问打卡类型。  
> **写跟进/计划不要用 `check` 定位**（查重专用）；用下面最优 search 链路。

---

## 最优链路（强制，禁止串行试探）

```text
提取公司名（+ 联系人/产品/已发生内容/预约时间）
    │
    ├─① 并行（同一轮 3 条，keyword=公司名，禁止用商机标题当 keyword）
    │     crm search lead|account|opportunity '{"keyword":"<公司名>","pageSize":10}'
    │
    ├─② 选取 module（商机 > 线索 > 客户）；记下资源 id
    │     商机：opportunityId + customerId/accountId
    │     线索：clueId；客户：customerId
    │
    ├─③ 用户提了联系人姓名 且 已有 customerId
    │     → crm contact account <customerId>，匹配姓名得 contactId（可与①并行若 customerId 已知）
    │     未提联系人 → 跳过，不强制查联系人列表
    │
    └─④ 写入（首跳 JSON 必须带 module；勿先发无 module 再重试）
          已发生 → cordys_ext.sh follow …
          预约/计划 → cordys_ext.sh follow-plan …
          两者都要 → 字段备齐后可连续执行（勿再 search）
```

**禁止（易拉长链路、曾实踩）**：

| 反模式 | 正确做法 |
|--------|----------|
| 只搜 account → 再猜商机全名 search | ① 三模块并行，keyword 始终是**公司名** |
| 用 `check` 定位跟进对象 | 用 `crm search`；本轮已有 id 则直接复用 |
| 第一次 `follow` 不传 `module` | **module 与资源 ID 同跳必填** |
| 为拿 id 再 search / 裸 Python | 从 ①② 结果取 id |
| 有商机却挂在客户上写跟进 | 有开放商机优先 `module=opportunity` |

---

## 步骤 1：提取 + 补全关键字段

从用户输入提取字段值，对照 `references/forms/follow.md` / `follow-plan.md` 补全。

**搜索前必须有**：
- `跟进客户名`（公司/机构）— 无则追问「跟进的是哪家公司？」
- 拜访打卡场景：`打卡类型`（线上/线下）

可选提取：联系人姓名、产品/JS·MK 等、已沟通内容、预约时间（「下周五」→ 算毫秒戳）、是否只要计划/只要记录/两者都要。

用户说「创建线索」：跳过步骤 2，走 `write-engine` 创建 → 拿 clueId → 步骤 3。  
用户明确只要某模块：仍可用单模块 search，**keyword 仍是公司名**。

## 步骤 2：搜索 CRM（定位，非查重）

默认 **并行三模块**（见上表①）。仅当用户明确「就这个线索/商机/客户」时缩成单模块。

```bash
cordys.sh crm search lead '{"keyword":"<公司名>","pageSize":10}'
cordys.sh crm search account '{"keyword":"<公司名>","pageSize":10}'
cordys.sh crm search opportunity '{"keyword":"<公司名>","pageSize":10}'
```

**相关性过滤**：同一实体（简称/全称/别名）保留；母子公司等可能相关保留；只共享常见词的过滤（如「飞致云」vs「飞致云花园物业」）。

**结果分流**：

- **1 条** → 采用，进步骤 3  
- **多条、同一客户实体** → 优先级 **商机 > 线索 > 客户**，只留最高档  
- **多条、不同实体** → 列表让用户选（商机→线索→客户排序；商机可带意向产品）  
- **0 条** → 是否新建线索；确认→ `write-engine` 创建 → 步骤 3  

**中断恢复**：序号/名称续跑；「都不是」→ 当未命中；新公司名 → 重新①。已提取字段沿用。

**联系人（步骤 2 尾）**：仅当用户点了联系人姓名且已有 `customerId` 时：

```bash
cordys.sh crm contact account '<customerId>'
```

按姓名匹配取 `contactId`；匹配不到可不传 contactId，不阻断写跟进。

## 步骤 3：写跟进记录（已发生）

用户只约了未来、没有「已聊/已打/已联系」时，可跳过本步，只做 3b。

```bash
cordys_ext.sh follow '<JSON>'
```

> 只用 `cordys_ext.sh follow`，禁止 curl/Python 绕过。字段细节见 `references/forms/follow.md`、`references/mappings/follow-method.md`。

**首跳 JSON 必填（缺 module 会直接失败）**：

| 字段 | 值来源 |
|------|--------|
| **module** | `lead` / `account` / `opportunity`（与步骤 2 选取一致，**禁止省略**） |
| type | lead→`CLUE`；account/opportunity→`CUSTOMER`（可不传，脚本可补；建议显式） |
| clueId / customerId / opportunityId | 步骤 2 资源主键 |
| customerId | **商机必带**（来自商机的 `customerId`/`accountId`） |
| contactId | 有则带 |
| content / 跟进内容 | 见下方模板 |
| 跟进方式 / followMethod | 语义识别（电话/到访/…）或 ID |
| 跟进时间 / followTime | 默认当前毫秒戳；可传中文时间由脚本转 |

**示例（商机 + 电话记录，一次成功）**：

```bash
cordys_ext.sh follow '{"module":"opportunity","opportunityId":"<oppId>","customerId":"<accId>","contactId":"<可选>","跟进方式":"电话","跟进内容":"【AI打卡】跟进\n电话联系了田先生，聊了 JumpServer"}'
```

## 步骤 3b：写跟进计划（预约/排期，可选）

用户说「约了下周五」「建个跟进计划」「下次拜访」等 → **另调** `follow-plan`（与记录字段名不同，勿混）。

```bash
cordys_ext.sh follow-plan '{"module":"opportunity","opportunityId":"<oppId>","customerId":"<accId>","contactId":"<可选>","跟进方式":"到访","计划时间":"<毫秒或 YYYY-MM-DD HH:MM>","跟进内容":"现场拜访…","意向产品":"JumpServer 企业版"}'
```

- `module` 与资源 ID 规则同步骤 3（**同样必填 module**）  
- 计划时间：相对日（下周五）先换算再传；方式用计划表单 ID/中文（见 `follow-plan.md`）  
- 记录 + 计划都要时：id 复用步骤 2，**不要**为计划再搜一遍  

---

**动态字段填充规则**：

1. 按 `references/forms/follow.md`（及同步后表单）判断必填、条件必填、SELECT 可选值、DATA_SOURCE 字段。
2. 字段值优先级：用户输入识别 > 搜索结果已有字段 > 场景默认值。
3. SELECT 传选项 ID 或 `references/mappings/` 中可识别的业务值，不编造枚举。
4. DATA_SOURCE 字段先解析成目标记录 ID 再写入。
5. 表单不存在的字段不强写；新增必填且无法推断时，一次性列出让用户补充。

**跟进内容模板**：content 第一行固定为 `【AI打卡】{打卡类型}`（线下拜访/线上拜访/跟进），用户说了业务内容追加第二行。格式必须严格统一，不得随意变更，详见 `references/forms/follow.md`。

**写库结果处理**：

- 返回 `code: 100200` 才视为 CRM 跟进记录写入成功，必须保存返回体中的 `data.id` 作为 `crmFollowUpId`。
- 返回非 `code: 100200` 时，不创建打卡链接，直接展示错误信息并提示稍后重试。
- 纯跟进意图在写入成功后结束，不创建打卡任务、不发送打卡卡片、不写入打卡记录表。
- 拜访打卡意图必须带着 `crmFollowUpId` 继续步骤 4。

## 步骤 4：打卡卡片（仅拜访意图）

纯跟进在步骤 3 写完后即结束，不进入本步骤。

检查对话上下文中是否有 sender_id：无→提示"请在企业微信中发起打卡"，跟进记录已写入 CRM；有→运行 `checkin.sh create-checkin` 调打卡 API 发卡片。本步骤只创建打卡任务和临时 token，不写打卡记录表（用户点击卡片并完成定位后才写表，见步骤 5）。

```bash
bash scripts/checkin.sh create-checkin '{
    "userid": "<sender_id>",
    "填写人": "<Cordys.md 姓名>",
    "所在部门": "<Cordys.md 部门>",
    "打卡类型": "<线上拜访|线下拜访>",
    "用户类型": "企业微信用户",
    "crmFollowUpId": "<步骤3返回的data.id>",
    "拜访公司名称": "<搜索命中的公司名称>",
    "拜访公司类型": "<线索|客户|商机>",
    "跟进内容": "<步骤3写入的content>"
  }'
```

> 请求/响应格式、卡片 JSON 模板、`.env` 自动读取、时间段问候详见 `references/checkin-api.md`。
> `拜访公司类型`/`跟进类型` 传中文标签（`lead`→`线索`、`account`→`客户`、`opportunity`→`商机`），不传 API 枚举值。
> ⚠️ `crmFollowUpId` 必填（值=步骤 3 返回的 `data.id`），不传打卡 API 会拒绝创建链接。

- `success: true` → 用返回的 `link` 输出拜访打卡卡片
- `success: false` → 提示"跟进已写入 CRM，但打卡系统暂时不可用，请稍后再试"

## 步骤 5：用户点击卡片后写入打卡表

由打卡系统 H5 自动完成（`POST /api/wechat/submit-checkin`，凭 `userid + token + 经纬度` 读取暂存字段写表），skill 不手动调用。纯跟进不写打卡表。写表完成后打卡系统通过 `webhookUrl` 发回通知，转发由平台已有能力处理。

> 不在 skill 文档或对用户输出中暴露真实表名、表结构、内部字段名或连接信息，统一称"打卡记录表"。
