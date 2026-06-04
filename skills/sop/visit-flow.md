# 拜访跟进流程

用户提到"拜访""跟进""记录"某公司时执行本流程。含"拜访"关键词→拜访打卡（走完整步骤1-4）；含"跟进""记录""聊了"但不含"拜访"→纯跟进（步骤1-3，写完即结束，不打卡）。"拜访"未说线上/线下时追问："请问是线上拜访还是线下拜访？"；纯跟进不问打卡类型。

---

## 步骤 1：提取信息

从用户输入提取以下字段：

| 字段 | 必填 | 说明 |
|------|------|------|
| customer_name | 是 | 用户消息中的公司/机构名。先排除类型词（"线索""商机""客户"），再识别公司名；不确定时追问 |
| checkin_type | 拜访场景必填 | 线上拜访 / 线下拜访。"线上""电话""远程""视频"→线上拜访；"线下""上门""面谈""去了""拜访"→线下拜访；纯跟进不需要 |
| crm_type_hint | 否 | 用户明确说了"线索""商机""客户""创建线索"时提取。未提类型则正常搜索三模块 |
| followMethod | 是 | 见 `references/mappings/follow-method.md` |
| extracted_fields | 否 | AI 语义识别：只提取语义明确的信息（联系人、产品等），不确定不填，不追问 |
| 用户业务描述 | 否 | 用户消息中除关键词外的内容（没说就不填，不追问） |

> `crm_type_hint` 为 `创建线索` 时，跳过步骤 2，直接走 `sop/write-flow.md` 创建线索 → 拿到 clueId → 继续步骤 3。

## 步骤 2：搜索 CRM 定位对象

如果 `crm_type_hint` 为 `创建线索`，跳过本步骤。

按 `crm_type_hint` 选择搜索模块：`线索`→lead，`商机`→opportunity，`客户`→account，空→并行三模块。

```bash
cordys.sh crm search lead '{"keyword":"<customer_name>","pageSize":10}'
cordys.sh crm search account '{"keyword":"<customer_name>","pageSize":10}'
cordys.sh crm search opportunity '{"keyword":"<customer_name>","pageSize":10}'
```

相关性过滤、结果分流、中断恢复详见 `references/mappings/visit-search.md`。核心分流逻辑：

- **1 条匹配** → 直接使用，进入步骤 3
- **多条匹配，同一实体** → 按优先级选取：商机 > 线索 > 客户，同一实体只保留最高优先级记录
- **多条匹配，不同实体** → 列出让用户选择（按商机→线索→客户排序），用户回复序号继续
- **0 条匹配** → 问用户是否创建新线索，确认→走 `sop/write-flow.md` 创建线索 → 拿到 clueId → 继续步骤 3；拒绝→结束

## 步骤 3：写跟进记录

```bash
cordys_ext.sh follow '<JSON>'
```

字段定义、必填清单详见 `references/forms/follow.md`。跟进方式映射详见 `references/mappings/follow-method.md`。

**type 与 ID 映射**：详见 `references/forms/follow.md`「type 与 ID 字段映射」。

**字段填充优先级**：详见 `references/forms/follow.md`「字段填充优先级」。核心：AI 语义识别 > 搜索结果原始记录 > 场景默认值。

> 搜索结果中的 `products` 是产品 ID 数组，需通过 `optionMap`（搜索结果同级返回）的 `products` 选项映射成产品名称，再填入 moduleFields。

**返回值**：详见 `references/forms/follow.md`「响应」。成功取 `data.id` 作为 `crmFollowUpId`；失败展示错误信息，提示用户稍后重试。

> follow 的必填字段全部由系统自动填充，不需要追问用户。

**示例**：用户"线下拜访了龙岩学院，聊了智慧校园产品"，搜索命中线索 `leadId=123`，`follower=userId456`，`products=[p1]`，`optionMap.products` 中 `p1=智慧校园`：

```json
{
  "module": "lead",
  "type": "CLUE",
  "clueId": "123",
  "content": "【AI打卡】线下拜访 | 2026-06-04 14:30\n聊了智慧校园产品",
  "followMethod": "VISIT",
  "followTime": 1749022200000,
  "owner": "userId456",
  "moduleFields": {"意向产品": "智慧校园"}
}
```

## 步骤 4：打卡卡片（仅拜访意图）

纯跟进在步骤 3 写完后即结束，不进入本步骤。

检查对话上下文中是否有企业微信 userid：有→调打卡 API 发卡片；无→提示"请在企业微信中发起打卡"，跟进记录已写入 CRM。

打卡 API 请求/响应格式、卡片 JSON 模板、时间段问候等详见 `references/checkin-api.md`。

- `success: true` → 用返回的 `link` 输出拜访打卡卡片
- `success: false` → 提示"跟进已写入 CRM，但打卡系统暂时不可用，请稍后再试"

> ⚠️ `crmFollowUpId` 是必填字段，不传打卡 API 会拒绝创建链接。值来自步骤 3 返回的 `data.id`。
