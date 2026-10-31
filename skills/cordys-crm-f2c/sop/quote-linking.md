# 报价单：报价上下文、创建报价单、为报价新建商机

把已有报价（Word 文件和报价行）写成 Cordys 报价单时使用。本文件是以下三件事的唯一权威：

1. `crm quote-context`：创建报价单前需要的只读上下文及其输出格式；
2. 创建报价单时一并新建关联记录（`to_resolve`，格式见 `references/forms/quotation.md`「一并新建关联记录」）：需要新建的联系人、工商抬头和报价单放进**同一张确认表**；
3. 为报价新建商机（含新建客户、线索转化）。新建商机与创建报价单是两次独立的写入，各自确认。

body 结构、附件、报价单名称公式、写入错误处理沿用 `core/write-engine.md`（§0.4、§2.4、§2.5、§8）；数据范围规则沿用 `core/role-engine.md` §2.4。

---

## 1. 报价上下文（只读）

```bash
cordys.sh crm quote-context '{"customer":"<客户名>","contact":"<联系人姓名，可选>","phone":"<联系人手机，可选>"}'
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `customer` | 是 | 用户报价时给的客户名称，按关键词匹配 |
| `contact` | 否 | 联系人姓名；给了就按姓名查联系人 |
| `phone` | 否 | 联系人手机；只给手机时按手机查联系人 |
| `viewId` | 否 | 用户明确指定范围时传 `SELF` / `ALL` / `DEPARTMENT`；省略时按角色默认 |

取报价上下文只执行这一条命令，不再分别调用 `search account/opportunity/lead/contact`、`acct-sub opportunity`、`contact account`、`page contract/business-title`。输出已经合并、去重、归一化，直接读取，不要二次合并。

### 1.1 命令内部做什么

1. 并行按 `customer` 搜索客户、商机和线索；传了 `contact` 或 `phone` 时同时搜索联系人。
2. 候选客户 = 客户搜索结果 + 商机结果中出现、但不在客户结果中的客户。
3. 候选客户不超过 5 个时，对每个客户并行取名下商机、客户联系人和同名工商抬头。商机与搜索结果按 ID 合并；金额优先取客户名下商机接口；产品 ID 转成名称（先用响应的 optionMap，不够再查产品数据源）。
4. 候选客户超过 5 个时只返回客户列表（`truncated: true`），不展开商机、联系人和工商抬头。
5. 联系人、线索只保留公司名与 `customer` 相同或互相包含的记录。

### 1.2 数据范围

| 查询 | 范围 |
|---|---|
| 客户、商机、线索、联系人搜索，客户名下商机 | 按 role-engine §2.4：销售 `SELF`；经理默认本部门及子部门（`viewId:ALL` + `departmentId IN`）；高管、财务、商务 `ALL` |
| 已锁定客户的联系人列表 | `/account/contact/list/{客户ID}`，与 write-engine 步骤 3「已知客户 ID」一致 |
| 工商抬头 | 全公司（`viewId:ALL`）：工商抬头是开票主数据，不属于销售受限模块；后端权限照常生效，无权限时进 `errors` |

- `viewId` 只能在授权内调整：经理和其他角色可传 `SELF`、`ALL`、`DEPARTMENT`；销售传任何非 `SELF` 值都仍按 `SELF` 查询，并在 `scope.note` 说明。
- 身份：`Cordys.md` 有效（7 天内、角色 ID 合法）时直接使用；缺失、过期或损坏时，命令内部调用 `whoami` 并按 role-engine §2 判定角色（不改写 `Cordys.md`），`scope.source` 标明 `cache` 或 `whoami`。经理的部门范围取缓存「部门范围」，缺失时展开部门树；账号没有所属部门（如内置 admin，其名下记录的 `departmentId` 也为空）时不加部门条件，按全部可见数据查询并在 `scope.note` 说明。
- 本地兜底：`SELF` 时丢弃负责人不是本人的记录；部门范围时丢弃 `departmentId` 不在范围内的记录。

### 1.3 输出契约

```json
{
  "code": 100200,
  "data": {
    "query": {"customer": "测试客户一号科技有限公司", "contact": "", "phone": ""},
    "scope": {"role": "sales", "viewId": "SELF", "source": "cache"},
    "truncated": false,
    "customers": [
      {
        "id": "483703889800654848",
        "name": "测试客户一号科技有限公司",
        "owner_name": "张三",
        "name_match": "exact",
        "opportunities": [
          {
            "id": "483704293527580672", "name": "测试客户一号-MK-2026-订阅新购",
            "stage": "CREATE", "stage_name": "新建", "closed": false, "amount": 100000,
            "owner_name": "张三", "products": ["MaxKB 企业版"],
            "contact_id": "483703949930196992", "contact_name": "王测试"
          }
        ],
        "contacts": [{"id": "483703949930196992", "name": "王测试", "phone": "13800000003"}],
        "business_titles": [
          {"id": "483716405335355392", "name": "测试客户一号科技有限公司", "approval_status": "APPROVED", "name_match": "exact"}
        ]
      }
    ],
    "leads": [{"id": "483703821081178112", "name": "测试客户一号科技有限公司", "contact": "", "phone": "13800000001"}],
    "errors": [],
    "queried_at": "2026-10-15T09:00:00+08:00"
  }
}
```

| 字段 | 说明 |
|---|---|
| `scope` | `role`、`viewId`、`source`；使用部门范围时有 `department_count`（部门及子部门个数）；销售范围被收窄、或账号没有所属部门而未加部门条件时有 `note` |
| `truncated` | 候选客户超过 5 个时为 `true`，此时 `customers[]` 只有 `id`、`name`、`owner_name`、`name_match` |
| `customers[].name_match` | `exact` 名称完全一致；`contains` 互相包含（如分公司）；`none` 名称不相关，只因商机名称命中而列入（常见于集成商名下的商机） |
| `customers[].owner_name` | 只从商机结果补入的客户为空字符串 |
| `opportunities[]` | 未关闭的在前。`closed` 在阶段为 `SUCCESS`/`FAIL` 时为 `true`，是否过滤由使用方决定；`amount` 取客户名下商机接口，为空时用搜索结果，都没有时为 `null`；`products` 是产品名称数组，没填产品时为 `[]` |
| `contacts[]` | 该客户的全部联系人 |
| `business_titles[]` | 名称与客户名相同或互相包含的工商抬头，`exact` 在前；`approval_status` 原样返回 |
| `contact_matches[]` | 只在传了 `contact` 或 `phone` 时出现；字段 `id`、`name`、`phone`、`customer_id`、`customer_name` |
| `leads[].contact` | 线索有联系人姓名时返回，没有时为空字符串 |
| `queried_at` | 北京时间 ISO 8601 |

输出不含 `optionMap`、`moduleFields` 等原始结构和凭据。字段名是公开格式：可以新增字段；改名或删除属于不兼容变更，须升版本并写进变更记录。

### 1.4 失败

- **部分失败**：某项查询失败时其他结果照常返回，失败项写进 `errors`，命令仍以 `code: 100200`、退出码 0 结束。`part` 取值：`opportunities`、`contacts`、`business_titles`（带 `customer_id`），`contact_matches`、`leads`、`products`。
- **整体失败**：参数错误、凭证或域名错误、身份获取失败、客户或商机搜索本身失败时，stdout 输出 `{"code":0,"errorCategory":"invalid_request|auth_failed|identity_failed|search_failed","message":"…"}`，退出码 1。命令只读，排除原因后可重跑一次；不得改用分散的 search/page 命令拼凑结果。

---

## 2. 创建报价单：同一张确认表

### 2.1 输入

- 完整的 `opportunity/quotation` 创建请求体文件：已存在的客户联系人、工商抬头已以 ID 写入 `moduleFields`；`attachments` 中是要写入“报价文件”的 Word。
- `to_resolve`（可选）：需要随报价单一并新建或补全的关联记录，格式和 `action` 取值见 `references/forms/quotation.md`「一并新建关联记录」。
- `warnings`（可选）：需要在确认表中提醒的事项，例如“商机产品与报价产品不一致，用户已确认继续”，或待补的必填字段。

请求体中已经写入的商机、联系人、工商抬头视为用户已选定，**不再让用户重选**；`warnings` 中已注明用户确认过的提醒，只写进确认表，不单独再确认。

### 2.2 预检（只读，不发写请求）

1. `cordys_ext.sh sync-if-needed`，读 `references/forms/quotation.md`、`contact.md`、`business-title.md`。高管角色只读：直接说明不能写入，停止。
2. 按 forms 校验请求体：`opportunityId`、`untilTime`、子表行、`moduleFields`；不传 `name`（write-engine §2.5）。
3. 报价文件：`cordys.sh crm upload --check "<Word 路径>"`，取文件名和大小。
4. 联系人 `resolve`：先 `cordys.sh crm contact account <客户ID>` 按姓名或手机匹配，唯一命中直接使用并在确认表写明“已存在，直接使用”，否则按 `create` 处理。联系人 `create`：执行 `cordys_ext.sh check '{"客户名":"<客户名>","手机":"<手机>"}'`（write-engine 步骤 2 的强制查重）。命中结果不另起一轮提问，作为“查重提醒”写进确认表。
5. 工商抬头 `create` / `resolve`：执行 `cordys.sh crm page contract/business-title '{"keyword":"<名称>","viewId":"ALL"}'`。已有名称完全一致的记录时改用该记录、不新建，在确认表写明“已存在，直接使用”及其 ID、审批状态。
6. 只在有缺项时**合并成一条消息**一次性补问，不逐项追问：
   - `collect` 的工商抬头字段：名称默认客户名称，其余全部选填、可跳过（税号、开户行、银行账号、注册地址、电话等，字段以 `forms/business-title.md` 为准）；
   - `warnings` 中的必填缺项（如销售手机）；
   - 工商抬头 `resolve` 查到多条同名记录时的选择（唯一时直接使用）。

### 2.3 确认表（一次确认）

```
请确认以下内容，回复“确认”后依次创建：联系人 → 工商抬头 → 报价单（并上传 Word）。

**新建客户联系人**
| 字段 | 值 |
|---|---|
| 客户 | 测试客户一号科技有限公司（483703889800654848） |
| 姓名 | 王测试 |
| 手机 | 13800000003 |

**新建工商抬头**
| 字段 | 值 |
|---|---|
| 名称 | 测试客户一号科技有限公司 |
| 其他字段 | 留空，以后可在 Cordys 补充 |

**报价单**
| 字段 | 值 |
|---|---|
| 名称 | 测试客户一号科技有限公司-${报价编号}（编号由系统生成） |
| 商机 | 测试客户一号-MK-2026-订阅新购（483704293527580672） |
| 客户联系人 | 王测试（本次新建） |
| 客户工商抬头 | 测试客户一号科技有限公司（本次新建） |
| 报价日期 / 有效期至 | 2026-10-15 / 2026-11-14 |
| 金额 | 100,000.00 |
| 报价文件 | quote-测试客户一号.docx（35.2 KB） |
| ⚠ 提醒 | 商机产品与报价产品不一致，用户已确认继续 |

**报价行**
| 子表 | SKU | 数量 | 年限 | 折后金额（含税） |
|---|---|---|---|---|
| 订阅产品 | MK-EE-SUB | 1 | 1 | 100,000.00 |
```

- 没有需要新建的记录时省略对应分组；查重提醒、“已存在，直接使用”写在对应分组下。
- 用户改了任何值，更新后再展示一次；用户放弃则不上传文件、不创建任何记录。

### 2.4 执行顺序（用户回复“确认”后）

每步只发一次写请求，读回 ID 后才进入下一步；任一步失败或结果未知立即停止，后续步骤一律不执行。

1. 联系人：`cordys.sh crm create contact '{"customerId":"<客户ID>","name":"<姓名>","phone":"<手机>"}'`，取 `data.id`。
2. 工商抬头：`cordys.sh crm create contract/business-title '{"name":"<名称>"}'`（`collect` 时加上收集到的字段），取 `data.id`；再 `cordys.sh crm get contract/business-title <ID>` 读回 `approvalStatus`。工商抬头只填名称即可创建。
3. 报价单：请求体文件经 stdin 送入，新 ID 通过覆盖 JSON 按 fieldId 写入，不手工改写请求体（fieldId 取 `forms/quotation.md` 的「客户联系人」「客户工商抬头」）：

   ```bash
   cordys.sh crm create opportunity/quotation @- '{"moduleFields":[{"fieldId":"<客户联系人 fieldId>","fieldValue":"<联系人ID>"},{"fieldId":"<客户工商抬头 fieldId>","fieldValue":"<工商抬头ID>"}]}' < "<请求体文件>"
   ```

   §2.2 补问得到的必填值（如销售手机）也放进同一个覆盖 JSON。CLI 按表单公式生成名称、上传 Word、只发一次 create，再读回 `attachmentState`（write-engine §2.4、§2.5）。

### 2.5 结果与失败

| 情况 | 处理 |
|---|---|
| 全部成功 | 给出报价单名称、ID 和 `attachmentState`；新建的联系人给名称和 ID，工商抬头给名称、ID 和审批状态 |
| 联系人或工商抬头创建失败、无权限或结果未知 | 不创建报价单；说明哪一步、什么原因，以及已创建的记录（名称、ID）。结果未知时只做只读核验，不重发 |
| 当前角色无权创建工商抬头 | 如实说明，建议请合同管理员创建后再同步；不改用 raw、其他模块或他人身份 |
| 报价单创建失败或结果未知 | 说明已创建的联系人、工商抬头（再次同步时直接按 ID 使用，不重复新建）；结果未知时按 write-engine §8.1 禁止自动重试 |
| 报价文件 | 按 `attachmentState` 汇报，规则保持 write-engine §2.4；只有 `confirmed` 才说 Word 已上传 |

---

## 3. 为报价新建商机

用户在关联时选择“在某客户下新建商机”或“新建客户和商机”时使用。

### 3.1 输入

客户（名称；已有时附 ID）、客户联系人（姓名、手机，作为关键决策人 KP 的候选；已有时附 ID）、报价产品名称（及价格行 `product_id`）、报价总额，以及（如有）线索 ID。

### 3.2 路径判定

| 输入 | 路径 |
|---|---|
| 有客户 ID | 在该客户下新建商机；不转化线索，有线索 ID 时在确认表提示线索保持不变 |
| 无客户 ID、有线索 ID | 线索转化：`cordys_ext.sh transform`，转为客户 + 联系人 + 商机（write-engine §5）。线索不可见、已转化或不允许转化时改为新建客户，并在确认表写明原因 |
| 无客户 ID、无线索 ID | 新建客户 → 联系人 → 商机 |

财务、商务角色不能新建商机，高管只读：说明原因，不执行。

### 3.3 字段取值（先用默认，再一次性询问）

商机、客户、联系人的每个必填项按以下顺序取值，取到即停：

1. 输入和用户原话已给的值；
2. **该客户已有商机**（仅在已有客户下新建时）：取 `quote-context` 返回的该客户第一条商机（未关闭的在前），`cordys.sh crm get opportunity <ID>` 读一次详情，沿用其区域、行业、来源、线上来源详情、签约类型、报备号/代签方名称、省市、最终用户工商全称；结束日期、金额、产品类型、KP 不沿用；
3. `references/forms/{module}.md` 必填清单的「表单默认值」列；
4. `sop/inference-rules.md` 的推断：区域（按部门）、行业（按公司名）、来源联动、商机名、签约类型、有效合同额 = 金额、最终用户工商全称；
5. 报价信息：金额取报价总额；产品类型按报价产品名称从 forms「产品类型（可多选）」取 ID；KP 用输入的联系人，没有 ID 时先用 `cordys.sh crm contact account <客户ID>` 按姓名或手机匹配，匹配不到就在同一张确认表中新建；
6. 仍缺的必填项（典型如结束日期）按 write-engine 步骤 4 的模板**一次性**询问，不逐项追问。

查重（write-engine 步骤 2）照常执行，命中结果写进确认表，不另起一轮。

### 3.4 确认表与执行

- 客户（新建或已有）、联系人（新建或已有，作为 KP）、商机的全部字段放进同一张确认表；沿用已有商机、取自表单默认值或推断的值分别标注“（沿用 <商机名>，可改）”“（表单默认，可改）”“（推断，可改）”。线索转化时列出转化方式和将生成的客户、联系人、商机。
- 用户确认后按“客户 → 联系人 → 商机”顺序执行（线索转化是一次 transform），每步读回 ID；任一步失败或结果未知立即停止，说明已创建的记录，不重发。
- 商机创建成功后执行 `cordys.sh crm get opportunity <ID>` 读回，输出商机名称、`id`、`customerId`，以及使用或新建的联系人名称和 ID。报价单不在这一步创建：有了商机 ID 后，按 §2 另行确认并创建。
