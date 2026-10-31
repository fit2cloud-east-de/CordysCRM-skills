# 拜访跟进流程

用户提到"拜访""跟进""记录""聊了""约了…拜访/回访"，或要求修改已有跟进记录/计划时执行本流程。先按下表判定走向：

| 用户说 | 走向 |
|--------|------|
| 公司名 + 已发生的拜访/跟进/记录/聊了 | 新增跟进记录 → 步骤 1–3 |
| 公司名 + 仅预约未来拜访/回访/建计划 | 新增跟进计划 → 步骤 1–2、3b |
| 公司名 + 已发生沟通 + 再约拜访/建计划 | 记录 + 计划 → 步骤 1–3、3b |
| “把跟进内容改成…” / “计划改到明天” / “修改跟进人” | 更新已有条目 → 「更新已有跟进记录/计划」U1–U3，必须展示变更并确认 |

> **写跟进/计划不要用 `check` 定位**（查重专用）；用下面最优 search 链路。

---

## 新增最优链路（强制，禁止串行试探）

```text
提取公司名（+ 联系人/产品/已发生内容/预约时间）
    │
    ├─① 并行（同一轮 3 条，keyword=公司名；先取用户明确范围，未指定时才用 profile 默认范围）
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
| `cordys_ext` 失败后用 `python -c` + 环境变量里写密钥 | **禁止**。只修/重跑 `scripts/cordys_ext.sh`；密钥不得出现在命令行 |
| 平台显示「运行成功」但无 JSON | 看 stderr / 输出里的 `error`；exit≠0 或有 `error` 即失败，勿当成功 |

---

## 步骤 1：提取 + 补全关键字段

从用户输入提取字段值，对照 `references/forms/follow.md` / `follow-plan.md` 补全。

**搜索前必须有**：
- `跟进客户名`（公司/机构）— 无则追问「跟进的是哪家公司？」

可选提取：联系人姓名、产品/JS·MK 等、已沟通内容、预约时间（「下周五」→ 按 `Asia/Shanghai` 解析；优先传日期时间字符串）、是否只要计划/只要记录/两者都要。

用户说「创建线索」：跳过步骤 2，走 `write-engine` 创建 → 拿 clueId → 步骤 3。  
用户明确只要某模块：仍可用单模块 search，**keyword 仍是公司名**。

## 步骤 2：搜索 CRM（定位，非查重）

默认 **并行三模块**（见上表①）。仅当用户明确「就这个线索/商机/客户」时缩成单模块。

**权限上限和本次范围必须在定位阶段同时生效**：范围判定按 `core/role-engine.md` §2.4（销售固定 SELF；经理说"我的"也用 SELF，说"团队/部门"或未指定范围才用部门及子部门）。下面示例同时适用于销售，以及明确查询本人的经理；禁止为命中结果而删除范围条件。

```bash
cordys.sh crm search lead '{"keyword":"<公司名>","pageSize":10,"viewId":"SELF"}'
cordys.sh crm search account '{"keyword":"<公司名>","pageSize":10,"viewId":"SELF"}'
cordys.sh crm search opportunity '{"keyword":"<公司名>","pageSize":10,"viewId":"SELF"}'
```

销售经理在用户明确查询团队/部门，或用户未指定范围而采用经理默认值时，使用下列完整模板；`value` 直接放 Cordys.md「部门范围」或 `crm org ids` 返回的完整数组（见 `core/query-members-org.md` §3.2），不要把条件键写成 `field`，也不要把 `TREE_SELECT` 猜成 `INPUT`。经理明确查询本人时不得使用本模板：

```bash
cordys.sh crm search lead '{"keyword":"<公司名>","pageSize":10,"combineSearch":{"searchMode":"AND","conditions":[{"value":["<部门ID>","<子部门ID>"],"operator":"IN","name":"departmentId","multipleValue":false,"type":"TREE_SELECT"}]}}'
cordys.sh crm search account '{"keyword":"<公司名>","pageSize":10,"combineSearch":{"searchMode":"AND","conditions":[{"value":["<部门ID>","<子部门ID>"],"operator":"IN","name":"departmentId","multipleValue":false,"type":"TREE_SELECT"}]}}'
cordys.sh crm search opportunity '{"keyword":"<公司名>","pageSize":10,"combineSearch":{"searchMode":"AND","conditions":[{"value":["<部门ID>","<子部门ID>"],"operator":"IN","name":"departmentId","multipleValue":false,"type":"TREE_SELECT"}]}}'
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

## 更新已有跟进记录 / 计划

更新不是新增重试，也不是普通业务模块的 `crm update`。必须先锁定**父模块 + 跟进条目 ID**，展示旧值与新值并确认，再走专用更新命令。

### U1：定位跟进条目

- 上下文已有跟进记录/计划返回的 `data.id`，且已知父模块时，直接执行 `follow-get` 读取当前详情。
- 只有公司/资源信息、没有跟进条目 ID 时，先按步骤 2 锁定 `lead/account/opportunity` 及资源 ID，再用 `crm follow record|plan` 查询该资源下的条目；0 条如实报告，多条列出时间、方式、内容、负责人让用户选择。
- 全局分页不使用顶层 `sourceId`。按资源定位时，线索/客户/商机分别在 `combineSearch.conditions` 中使用 `clueId` / `customerId` / `opportunityId`。更新 JSON 的 `id` 必须是列表返回的**跟进记录 ID 或跟进计划 ID**，两者不得混用。

```bash
cordys.sh crm follow record '{"current":1,"pageSize":10,"combineSearch":{"searchMode":"AND","conditions":[{"value":["<线索ID>"],"operator":"IN","name":"clueId","type":"DATA_SOURCE"}]}}'
cordys.sh crm follow plan '{"current":1,"pageSize":10,"status":"ALL","combineSearch":{"searchMode":"AND","conditions":[{"value":["<客户ID>"],"operator":"IN","name":"customerId","type":"DATA_SOURCE"}]}}'
cordys.sh crm follow-get record lead '<跟进记录ID>'
cordys.sh crm follow-get plan account '<跟进计划ID>'
```

### U2：展示变更并确认

以 `follow-get` 返回为当前值，至少展示：条目类型、条目 ID、所属线索/客户/商机、要改的字段、当前值、目标值。用户回复“确认”或“提交”后才能进入 U3；用户调整目标值后重新展示。**新增免确认例外不适用于更新。**

允许更新的业务字段：内容、时间、跟进方式、跟进人、联系人、意向产品。`type` 与 `clueId/customerId/opportunityId` 只能原值保留，禁止通过编辑改绑；计划的 `status`、`converted` 是状态字段，不属于本更新命令。

### U3：执行一次更新

```bash
cordys_ext.sh follow-update '{"module":"lead","id":"<跟进记录ID>","跟进内容":"【AI 跟进纪要】\n补充沟通结果","跟进方式":"微信"}'
cordys_ext.sh follow-plan-update '{"module":"account","id":"<跟进计划ID>","计划时间":"2026-08-10 10:00","跟进方式":"电话"}'
```

- JSON 只写用户确认要修改的字段，但 `module` 与跟进条目 `id` 必填。命令会再次读取 `/{module}/follow/{record|plan}/get/{id}`，保留所有未修改字段，再提交后端要求的完整请求体。
- 记录字段固定为 `followTime` / `followMethod`；计划字段固定为 `estimatedTime` / `method`。中文标签和业务时间由脚本按对应表单、UTC+8 转换，不得交叉复用选项 ID。
- 每个更新命令最多 POST 一次。返回 `code:100200` 为成功；`noOp:true` 表示目标值本来就一致且没有提交写请求；`verifiedAfterFailure:true` 表示更新响应异常但回读确认已生效，同样视为成功。
- 返回 `retryAllowed:false` 时表示写入状态未被回读确认，必须展示错误并停止；禁止自动重试，后续操作由用户决定。

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
| content / 跟进内容 | `【AI 跟进纪要】\n{用户业务描述}`，见下文「跟进内容」 |
| 跟进方式 / followMethod | 语义识别（电话/到访/…）或 ID |
| 跟进时间 / followTime | 默认当前毫秒戳；可传中文时间由脚本转 |

**示例（商机 + 电话记录，一次成功）**：

```bash
cordys_ext.sh follow '{"module":"opportunity","opportunityId":"<oppId>","customerId":"<accId>","contactId":"<可选>","跟进方式":"电话","跟进内容":"【AI 跟进纪要】\n电话联系了田先生，聊了 JumpServer"}'
```

## 步骤 3b：写跟进计划（预约/排期，可选）

用户说「约了下周五」「建个跟进计划」「下次拜访」等 → **另调** `follow-plan`（与记录字段名不同，勿混）。

```bash
cordys_ext.sh follow-plan '{"module":"opportunity","opportunityId":"<oppId>","customerId":"<accId>","contactId":"<可选>","跟进方式":"到访","计划时间":"2026-07-17 10:00","跟进内容":"现场拜访…","意向产品":"JumpServer 企业版"}'
```

- `module` 与资源 ID 规则同步骤 3（**同样必填 module**）  
- 计划时间：相对日（下周五）先按中国业务时区换算；优先传 `YYYY-MM-DD HH:MM`，脚本固定按 UTC+8 解析，也可传 JSON 整数毫秒戳 `1784253600000` 或纯数字字符串。禁止附加 `CST`；显式非法值会中止且不创建
- 记录 + 计划都要时：id 复用步骤 2，**不要**为计划再搜一遍  
- `follow-plan` 命令只负责新增。首次返回 `code:100200` 即已真实创建，必须保存 `data.id`，**禁止因时间或字段不符合预期再次调用新增命令**；纠错必须先查询并确认，再改用 `follow-plan-update`

---

**动态字段填充规则**：

1. 按 `references/forms/follow.md`（及同步后表单）判断必填、条件必填、SELECT 可选值、DATA_SOURCE 字段。
2. 字段值优先级：用户输入识别 > 搜索结果已有字段 > 场景默认值。
3. SELECT 传选项 ID 或 `references/mappings/` 中可识别的业务值，不编造枚举。
4. DATA_SOURCE 字段先解析成目标记录 ID 再写入。
5. 表单不存在的字段不强写；新增必填且无法推断时，一次性列出让用户补充。

**跟进内容**：content 必须保持 `【AI 跟进纪要】\n{用户业务描述}` 两行格式，按 `references/forms/follow.md`「跟进内容」填写；第一行不追加拜访或跟进类型。

**写库结果处理**：

- 返回 `code: 100200` 才视为 CRM 跟进记录写入成功，必须保存返回体中的 `data.id` 作为跟进记录 ID，供后续查询或更新使用。
- 跟进计划返回 `code: 100200` 后同样保存 `data.id`；成功响应后的异常字段不构成重试依据，禁止再次执行 `follow-plan`。
- `follow-plan` 返回非 `code: 100200` 时也不得直接重试：先按资源查询计划，确认未落库后再提示用户决定是否重试。
- 跟进记录返回非 `code: 100200` 时，展示错误并先按资源查询确认是否已落库；确认存在时禁止再次新增，确认未落库后再由用户决定是否重试。
- 跟进更新返回 `noOp:true` 或 `verifiedAfterFailure:true` 均按成功处理；返回 `retryAllowed:false` 时禁止自动重试。
- 用户请求的记录/计划写入完成后，汇报 CRM 写入结果并结束；分别保留记录与计划 ID，后续修改走对应更新命令。
