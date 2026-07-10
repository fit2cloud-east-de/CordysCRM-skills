# ✏️ 写入操作引擎

Cordys CRM 写入操作的**唯一权威文档**：创建、查重、更新、批量更新、线索转化、公海/线索池操作。
支持模块：`lead`（线索）、`account`（客户）、`opportunity`（商机）、`contact`（联系人）。

> **创建/更新/批量入口为 `cordys.sh crm create/update/batch-update`**（body 用 fieldId 双层结构，见 §0.4）。
> **线索转化唯一入口为 `cordys_ext.sh transform`**；查重、省市代码、公海/线索池用 `cordys_ext.sh check/loc/pool`。
> `cordys.sh` 的写入命令已内置：中文 UTF-8 处理、owner 默认剥离交后端兜底、HTTP 500 假失败检测。

---

## 0. 核心设计原则

### 0.1 高度抽象，统一流程

所有模块的写入遵循**完全相同的流程**，不按模块重复实现：

```
用户意图 → 识别模块/操作 → 读表单定义(forms)+读推断规则(inference-rules) → 校验+推断 → 查重 → 展示确认 → 执行写入 → 验证结果 → 输出
```

### 0.2 两阶段写入：先懂表单 + 推断规则，再写入

创建/更新前**必须先读这两份文档**，缺一不可：

1. **`references/forms/{module}.md`** —— 了解字段、类型、必填项、SELECT 合法值、以及构建 body 所需的 **fieldId** 和 **选项 value/ID**。
2. **`sop/inference-rules.md`** —— 字段推断/补全规则(区域、行业、**省市代码格式**、来源联动、商机名生成、默认值等)。**这不是可选参考,而是执行"校验+推断"步骤前的强制前置**：省市直辖市规则、区域推断等只在此文档定义,不读就会凭常识乱猜(典型：直辖市省市代码,见该文档 §省市格式)。

> 构建 body 所需信息（字段、fieldId、选项 value）全部从 `references/forms/{module}.md` 取，**不要调 `cordys.sh crm form`**（除非 forms 文档明显过期需实时核对）。
> 字段值的推断/默认/格式换算（含省市代码怎么查）一律以 `sop/inference-rules.md` 为准，不要自行发挥。

### 0.3 owner 与假失败（cordys.sh 已内置处理）

- **owner（负责人）**：
  - **创建**默认剥离 owner，后端自动设为当前用户。要归到他人名下：先创建（归自己）再 `crm update` 改 `owner`=**userId**，或用 `pool assign`。
  - **更新**自动保留 owner（`crm update` 内置读回合并）：不改负责人就不传，改负责人直接传 `owner`=userId。**不会因不传而清空 owner**。
- **假失败**：HTTP 500/超时时 `cordys.sh` 会读响应体判 `code=100200`，按返回的 `code` 判成败即可。

### 0.4 body 构建规则

`cordys.sh crm create/update` 的 body 是**双层结构**：

```json
{
  "name": "...",              // 系统字段用 businessKey（见 forms 查询字段参考表 name 列）
  "phone": "...",
  "contact": "...",
  "products": ["产品ID"],      // 产品传 ID，从 forms「产品类型（可多选）」可选值表直接取（见下方 products 说明）
  "moduleFields": [           // 自定义字段：{fieldId, fieldValue} 数组
    {"fieldId": "1751888184000015", "fieldValue": "东区"},
    {"fieldId": "175188949491200000", "fieldValue": "175188976309600000"}  // SELECT 传选项 ID
  ]
}
```

规则：
- **系统字段**（name/phone/contact/customerId/contactId/amount/products 等，见 forms 查询字段参考表里 name 列是英文 businessKey 的）→ 放 body 顶层。
- **自定义字段**（fieldId 是数字/复合 ID 的）→ 放 `moduleFields`，格式 `{"fieldId":..., "fieldValue":...}`。
- **SELECT 字段的 fieldValue**：传该选项的 value/ID（从 forms「SELECT 字段可选值」表取，如 行业「高科技和互联网」→ `175188976309600000`；部分选项 value 与中文一致，如 区域「东区」→ `东区`）。
- **fieldId 来源**：forms「查询字段参考」表的 name 列。
  - 商机 opportunity 的 fieldId 多为复合形式（如 行业 `1751888184000037_ref_1751888184000005`）——已实测：简单数字 fieldId（lead）和复合 fieldId（opportunity）在 create 中均可正常落库。
- **products**：传产品 ID 数组，**直接从 `references/forms/{module}.md`（lead/opportunity）「SELECT 字段可选值」里的「产品类型（可多选）」表读 ID**（该表已含全部产品的中文→ID 映射，先经 `sop/inference-rules.md` 把简称归一成产品全名再查表）。仅当该表里查不到（如新上架产品）才 fallback `cordys.sh crm product '{"keyword":"名称"}'` 查 id。

---

## 1. 数据校验与推断

### 1.1 内置校验（基于 forms/{module}.md）

| 规则 | 来源 | 处理 |
|------|------|------|
| 必填字段为空 | `references/forms/{module}.md` 必填清单 | 阻止提交，向用户索取 |
| 条件必填触发 | 必填清单的「条件必填」列 | 当前取值满足条件时按必填处理（如签约类型=代签 → 报备号必填） |
| 枚举值不合法 | forms 的 SELECT 可选值 | 提示并列出合法选项 |

### 1.2 智能推断（先推断，再问用户）

对缺失字段，先用 `sop/inference-rules.md` 自动填充，只有推断不了的才问用户：区域（按部门）、行业（按公司名）、来源联动、省市代码（`cordys_ext.sh loc`）、商机名生成、最终用户全称、各类默认值。

### 1.3 自定义规则（运行时加载边界）

| 路径 | 运行时 | 动作 |
|------|--------|------|
| `rules/field-mapping/lead-to-*.md` | **启用** | 转化时**必须读**（§5 权威源） |
| `rules/form-rules/*` | **未启用** | 内容为「技术站位，不加载」或等价占位 → **不要读、不要当校验规则** |
| `rules/business-rules/*` | **未启用** | 同上，**跳过** |
| `rules/README.md` | 开发说明 | **运行时不要加载**；格式与扩展约定给人看，不参与执行 |

以后若 form/business 落地：文件须含可执行规则正文（非站位句），再在创建/更新校验步骤显式加载。未落地前只用 `references/forms/` + 本节推断与内置规则。

---

## 2. 创建操作

### 2.1 创建流程（5 步）

```
1. 提取 + 补全关键字段（应用 inference-rules）
2. 查重（强制步骤）
3. 解析实体 ID（商机/联系人需要）
4. 校验其余必填字段（对照 forms/{module}.md，含条件必填）
5. 展示完整表单 → 用户确认 → 执行 create
```

### 步骤 1：提取 + 补全关键字段

从用户输入提取字段值，应用 `sop/inference-rules.md` 自动推断补充。

**关键字段必须在查重前收集完整**：
- `客户名`（公司名称）— 必须有
- `手机` — 必须有（查重依赖手机号检测重复）
- `产品` — 尽量有（精确判断产品冲突）

如果用户未提供客户名或手机号，**一次性列出所有缺失的关键字段问用户补充，再进入步骤 2**。不要带着缺失的关键字段去查重，也不要分多轮逐个询问。

> ⚠️ 查重是创建流程的**强制步骤**，关键字段齐全后直接执行，不要询问用户"是否需要查重"。

### 步骤 2：查重

```bash
cordys_ext.sh check '{"客户名":"<名称>","手机":"<手机号>","产品":["<产品名>"]}'
```

- `conflicts` 为空 → 继续
- `conflicts` 不为空 → 展示冲突，问用户是否继续
- `warnings` → 告知用户但不阻断

创建前必须传产品参数以精确判断。**查重结果解读、展示模板、规则说明见 `sop/duplicate-check.md`**（该文件是查重的权威规范）。

### 步骤 3：解析 DATA_SOURCE 字段 ID

仅商机和联系人需要（参见各 references 中标记 ⚠️ 实体 ID 的字段）。

**解析客户 ID**：
```bash
cordys.sh crm page account '{"keyword":"<客户名>","current":1,"pageSize":5,"viewId":"ALL"}'
```

**解析联系人 ID（KP）**：通过客户 ID 获取其下联系人列表，再按姓名匹配：
```bash
cordys.sh crm contact account <客户ID>
```

- 1 条 → 取 `id`
- 多条 → 列出候选，问用户
- 0 条 → 提示未找到，停止

> **每个 ID 只调一次命令，不要用其他命令重复查。联系人不支持全局 keyword 搜索，必须通过客户 ID 获取。**

### 步骤 4：校验其余必填字段

对照 `references/forms/{module}.md` 中的必填清单逐项检查。**若清单含「条件必填」列**，按当前字段取值判断这些字段是否触发必填（如签约类型选了代签 → 报备号/代签方名称变必填），触发了就当作必填项处理。

**先推断，再问用户**：对每个缺失字段，先尝试用 `sop/inference-rules.md` 的规则自动填充（区域、行业、来源联动、省市代码、商机名、最终用户全称等）。只有推断不了的才问用户。

**商机特别注意**：
- 商机名自动生成后，**必须展示给用户确认**（放在询问模板开头）
- 产品类型（可多选）是必填字段，从用户输入中提取后**必须传入创建 JSON**
- 关键决策人（KP）是必填字段，需解析联系人 ID

- 齐全 → 步骤 5
- 仍有缺失 → 一次性列出**无法推断的**缺失字段，附可选值，问用户补充

**询问格式（固定模板）**：

```
请补充以下必填信息：

1. {字段名}：{可选值1} / {可选值2} / ...
2. {字段名}：（说明）
3. ...
```

示例（创建线索缺少来源和区域）：

```
请补充以下必填信息：

1. 线索来源：线上 / 线下活动 / 线下-员工发掘 / 线下-合作伙伴 / 线下-客户推荐
2. 线上来源详情：400电话 / 企业版试用 / 解决方案咨询 / 预约演示 / ...
3. 区域：东区 / 北区 / 南区
```

> 一次性列出所有缺失项，不要分多轮逐个询问。用户回复后直接进入步骤 5。

### 步骤 5：创建

> **步骤 4 与步骤 5 是两个不同环节**：步骤 4 是"补全缺失字段"（只问推断不出来的），步骤 5 是"展示全部字段做最终确认"。即使步骤 4 没有任何缺失字段，步骤 5 的确认也必须执行，不可跳过；但不要把两步合并成两轮重复询问。

**提交前必须先展示完整表单给用户确认**。用以下格式列出所有字段：

```
请确认以下信息，确认无误后回复"确认"或"提交"，需要修改请直接说明：

| 字段 | 值 |
|------|-----|
| 客户名 | xxx |
| 手机 | xxx |
| 产品 | xxx |
| 区域 | xxx |
| 行业 | xxx |
| 来源 | xxx |
| 省市 | xxx (110108-) |
| ... | ... |
```

> 用户确认后才执行创建命令。如果用户要求修改某些字段，更新后再次展示确认，不要直接提交。

```bash
cordys.sh crm create <module> '<JSON>'
```

module：`lead` / `account` / `opportunity` / `contact`（联系人用 `account/contact`）

body 按 §0.4 双层结构构建。示例（创建线索，已实测通过）：

```bash
cordys.sh crm create lead '{"name":"华星科技","contact":"王总","phone":"13812345678","products":["8327632349528064"],"moduleFields":[{"fieldId":"1751888184000015","fieldValue":"东区"},{"fieldId":"175188949491200000","fieldValue":"175188976309600000"},{"fieldId":"1751888184000018","fieldValue":"Advertisement"}]}'
```

返回 `code: 100200` 为成功，取 `data.id`。

> **不要传 owner**，cordys.sh 自动交后端设为当前用户（见 §0.3）。
> SELECT 字段的 fieldValue 传选项 value/ID、产品传 ID（见 §0.4），均从 `references/forms/{module}.md` 取。

### 2.2 各模块必填字段（速查，以 forms/{module}.md 为准）

| 模块 | 必填字段 |
|------|---------|
| 线索 | 公司、产品类型（可多选）（+ 区域/手机等条件必填见 forms） |
| 客户 | 客户名（+ 区域/行业/来源/类型/省市见 forms） |
| 商机 | 商机名、客户名、关键决策人（KP）、产品类型（可多选） |
| 联系人 | 客户名、姓名、手机 |

### 2.3 批量创建

> ⚠️ Cordys CRM **不提供批量创建端点**，逐条调用 `cordys.sh crm create`。

创建前 AI 应：展示全部待创建记录的预览表格 → 标注问题字段 → 用户确认后逐条执行。

---

## 3. 更新操作

用户说"修改/更新/改一下"时触发。不需要查重、推断、校验必填。

> **只传要改的字段即可**：`cordys.sh crm update` 内置**读回合并**——先 GET 现有记录，把你传的字段覆盖上去再整体提交，其余 moduleFields、结束日期、owner 等**自动保全**。`/{module}/update` 端点本身是全量覆盖，但脚本已替你处理，不用手动查回全部字段。

### 3.1 流程

1. **定位记录** — 用户提供了 ID 直接用；没提供则搜索定位（`cordys.sh crm search`），多条让用户选
2. **确认（二次确认原则）** — 展示 **原值 → 新值** 对比表，仅列出有变化的字段：

```
即将更新 [模块] 记录「名称」，请确认：

| 字段 | 原值 | 新值 |
|------|------|------|
| 行业 | 高科技和互联网 | 制造 |

确认无误请回复"确认"。
```

3. **执行** — `cordys.sh crm update <module> '<JSON>'`，JSON 含 `id` + **只需要改的字段**：

```bash
# ✅ 只传要改的字段：把行业改成制造，其余字段（区域/来源/类型/省市/结束日期/owner…）脚本自动保留
cordys.sh crm update account '{"id":"405703444004376576","moduleFields":[{"fieldId":"1751888184000005","fieldValue":"制造"}]}'

# ✅ 改顶层字段同理：只传 amount，结束日期/客户/KP/产品/moduleFields 全保留
cordys.sh crm update opportunity '{"id":"405712557924978697","amount":300000}'
```

返回 `code: 100200` 为成功。

> ⚠️ id 放在 **JSON body 里**（cordys.sh 端点 `/{module}/update` 要求 body 含 id）。
> **与创建确认的区别**：创建展示全量字段表，更新只展示变更字段的 diff。
> **负责人变更**：改负责人直接在 JSON 里传 `owner`（值为 **userId**，不是 id），先用 `crm members` 搜索确认 userId。不改 owner 时不传即可（脚本自动保留现有 owner）。
> **显式置空**：要把某字段清空，在 JSON 里把该字段传 `null`/`""`（读回合并会用你的值覆盖，含空值）。
> **只读字段**：`stage`/`stageName`/`createTime`/各 `*Name` 等展示/派生字段脚本不回发也不会被清空，无需关心。

---

## 4. 批量更新

用户说"把这几条/这批 xxx 都改成 yyy"、"批量修改"时触发。

### 4.1 适用场景

- 多条记录改**同一个字段**为**同一个值**（如：统一改负责人、统一改阶段、统一标记已拜访）
- 如果每条改不同值或改多个字段 → 循环调单条 `update`

### 4.2 流程

1. **圈定记录** — 用户提供 ID 列表，或通过查询条件筛选出目标记录（`cordys.sh crm page/search`），多条时列出让用户确认范围
2. **确定字段** — 确认要改的字段名和目标值；从 `references/forms/{module}.md` 查询字段参考表取 fieldId
3. **确认（二次确认原则）** — 展示影响范围：

```
即将批量更新 [模块] 共 N 条记录：

| 字段 | 新值 |
|------|------|
| 是否已拜访 | 是 |

影响记录：
1. 「浪潮集团广西分公司」(394648017795821568)
2. 「中科软科技」(394648017795821569)
3. ...

确认无误请回复"确认"。
```

4. **执行** —
   - 同字段同值：`cordys.sh crm batch-update <module> '{"ids":["id1","id2"],"fieldId":"<字段ID>","fieldValue":"<选项value/ID>"}'`
   - 不同值/多字段：逐条 `cordys.sh crm update <module> '<JSON>'`（JSON 含 id），串行执行

```bash
# 同字段同值（一次 API）—— fieldId 是数字字段 ID，不是中文字段名！
# 例：把两条线索的「分级」统一改为「一般客户」(选项 value=175307914302000003)
cordys.sh crm batch-update lead '{"ids":["id1","id2"],"fieldId":"175307914302000000","fieldValue":"175307914302000003"}'

# 不同值（循环，JSON 含 id）
cordys.sh crm update lead '{"id":"id1","phone":"13900001111"}'
cordys.sh crm update lead '{"id":"id2","phone":"13900002222"}'
```

5. **汇报结果** — 成功 N 条 / 失败 M 条，失败的列出具体错误

> **fieldId 来源**：从 `references/forms/{module}.md` 的「查询字段参考」表取字段的数字/复合 ID（如 `分级` → `175307914302000000`），**不能传中文字段名**。
> **fieldValue 取选项 value/ID**：SELECT 字段传选项 value（多数与中文一致，如「一般客户」→ `175307914302000003`；见 forms「SELECT 字段可选值」表）。
> **数量上限**：单次 batch-update 建议不超过 100 条 ID。超过时分批执行，每批 ≤100。

---

## 5. 线索转化

线索转客户（可同时创建商机）。转换后自动补全联系人的电话和邮件。

### 5.1 步骤 1：确认转换方式

用 `page lead` 一次性定位线索并获取完整字段（姓名、手机、产品、区域等），**避免遗漏已有信息反复询问用户**。

```bash
cordys.sh crm page lead '{"keyword":"<线索关键词>","current":1,"pageSize":5,"viewId":"ALL"}'
```

- 找到 → 从返回的 moduleFields 中提取已有字段
- 未找到 → 告知用户，停止
- 多条 → 列出候选，问用户确认哪条

> **只调一次 `page`，不要再用 `search`、`get` 等命令重复查。**

**确定转换方式（优先按用户说法判断，不要明知故问）：**

| 用户说法 | 转换方式 | 动作 |
|---------|---------|------|
| "转商机" / "转客户并建商机" / "转客户加商机" / "转成商机" | 同时创建商机 | 直接按"同时创建商机"走，**不要再问** |
| "只转客户" / "仅转客户" / "转客户不建商机" | 只转客户 | 直接按"只转客户"走，**不要再问** |
| "转客户" / "转换" / "转一下"（未提商机） | 意图不明 | 此时才问一句："只转客户，还是同时创建商机？" |

> 用户说法已经表明意图时（尤其"转**商机**"明确要建商机），跳过此问，直接进入步骤 2。

### 5.2 步骤 2：补全目标模块必填字段

转换 API 不校验目标模块必填字段，缺的会留空。**必须在转换前收集齐全，不得跳过。**

**字段映射与默认值以 `rules/field-mapping/` 为准（唯一权威源，务必先读）：**
- 只转客户 → 读 `rules/field-mapping/lead-to-account.md`
- 同时创建商机 → 读 `rules/field-mapping/lead-to-account.md` + `rules/field-mapping/lead-to-opportunity.md`

这两个文件规定了：哪些字段**自动继承线索的值**（客户名/区域/行业/来源/线上来源详情/省市/产品）、哪些字段**有默认值**（客户类型=最终客户、签约类型=飞致云直签、有效合同额=金额、最终用户全称=客户名）、以及**真正需要向用户补充**的字段。

> ⚠️ **铁律（曾被漏执行）**：
> - **自动继承的字段**（尤其**省市**，线索有代码就原样继承）**绝不当缺失项问用户**。
> - **有默认值的字段**（尤其**签约类型=飞致云直签**）自动填充，只在最终确认表里展示"（默认，可改）"，**绝不当缺失项问用户**。
> - 只有 field-mapping 里列为"需向用户补充"的字段（商机的金额/结束日期/服务类型/业务机会类型），才向用户索取。

必填清单本身对照 `references/forms/{account,opportunity}.md` 的必填字段列。

**商机名称**：按 `sop/inference-rules.md` "商机名自动生成"规则生成，在收集缺失字段时一并展示确认，不单独当缺失项问。

> 例外：**关键决策人（KP）** 可在转换后补充，因为联系人是转换时才创建的。

**询问格式（固定模板）** —— 注意"补充项"只问 4 个，默认值字段只展示不问：

```
请补充以下信息：

1. 金额：（预计合同金额）
2. 结束日期：（预计签约日期，如 2026-12-31）
3. 服务类型：订阅 / 授权 / 服务 / 维保 / 一体机
4. 业务机会类型：新购 / 续费 / 维保 / 扩容

以下字段已设默认值，如需修改请说明：
- 客户类型：最终客户（默认）
- 签约类型：飞致云直签（默认）
- 最终用户全称：同线索公司名（默认）

商机名称将自动生成为：{简称}-{产品}-{年份}-{服务类型}{业务机会类型}
示例：东方测试-JS-2026-订阅新购
```

> 一次性列出所有待补充项，不要分多轮逐个询问。用户回复后即可执行。
>
> **条件必填**：按 `references/forms/opportunity.md` 的「条件必填」列判断。如签约类型选了代签类，「报备号/代签方名称」变必填，须追加索取后才能提交。

### 5.3 步骤 3：执行转换

**提交前必须先展示完整表单给用户确认**。用以下格式列出所有字段：

```
请确认以下信息，确认无误后回复"确认"或"提交"，需要修改请直接说明：

【转换内容】只转客户 / 同时创建商机

【客户】
| 字段 | 值 |
|------|-----|
| 客户名 | xxx |
| 类型 | 最终客户 |
| ... | ... |

【商机】（如同时创建）
| 字段 | 值 |
|------|-----|
| 商机名 | xxx |
| 金额 | xxx |
| ... | ... |

【联系人补全】
| 字段 | 值 |
|------|-----|
| 电话 | xxx |
| 电子邮件 | xxx |
```

> 用户确认后才执行转换命令。如果用户要求修改某些字段，更新后再次展示确认，不要直接提交。

将所有收集到的字段一次性传给转换命令，`cordys_ext.sh transform` 内部完成多步事务：转换建壳 → 补全联系人（电话/邮件）→ 补全客户类型 → 搜出新商机并补全商机字段（金额/结束日期/签约类型/moduleFields）。

> ⚠️ **转化必须走 `cordys_ext.sh transform`**。旧 `cordys.sh crm transform/transition` 已禁用，因为裸端点只建客户、联系人和空壳商机，会静默丢弃金额、结束日期及 moduleFields；多步封装会在转化后更新新商机并补齐这些字段。

```bash
cordys_ext.sh transform '{"clueId":"<线索ID>","oppName":"<商机名>","contactName":"<联系人姓名>","phone":"<手机>","电话":"<座机>","电子邮件":"<邮箱>","类型":"最终客户","金额":500000,"有效合同额":500000,"结束日期":"2026-09-30","签约类型":"飞致云直签","最终用户全称（工商可查）":"xxx公司"}'
```

参数说明（**传中文字段名/中文值，`cordys_ext.sh transform` 内部自动转 ID**，不用 fieldId 双层结构）：
- `clueId`（必填）：线索 ID
- `oppName`：商机名称，传了就同时创建商机（内部自动设 `oppCreated`），不传则只转客户+联系人
- `contactName` + `phone`：用于转换后定位联系人补全字段
- `电话`、`电子邮件`：补充到联系人
- `类型`：客户类型（最终客户/代理商），默认最终客户
- 商机字段（`金额`、`有效合同额`、`结束日期`、`签约类型`、`最终用户全称（工商可查）`、`报备号/代签方名称` 等）：转化后自动补全到新商机，SELECT 传中文、金额传数字、日期传 `YYYY-MM-DD`

> 转换成功后无需再搜索客户/商机/联系人来验证，`code: 100200` 即为全部完成。直接告知用户结果。
> 若返回 `partialSuccess:true` / `transformCompleted:true` / `retryTransform:false`，表示基础转化已完成但商机字段未全部补齐。**禁止再次执行 transform**；应按错误中的商机名查询新商机，再用 `cordys.sh crm update opportunity` 补字段。

---

## 6. 公海 / 线索池操作

线索有**线索池**、客户有**公海**，是未分配/已退回记录的归属容器。三类操作：

| 操作 | 含义 | 命令 |
|------|------|------|
| **领取 pick** | 把池子里的记录领到**自己**名下 | `pool pick <lead\|account> <id> <poolId>` |
| **分配 assign** | 把池子里的记录指派给**指定成员**（经理场景） | `pool assign <lead\|account> <id> <用户ID>` |
| **移入池 to-pool** | 把自己的记录**退回**线索池/公海 | `pool to-pool <lead\|account> <id> [原因ID]` |

批量版本：`batch-pick` / `batch-assign` / `batch-to-pool`，ID 用逗号分隔。

> **用户说"私海""我的池子""操作私海"时**：私海指"记录归属到个人名下"的状态。识别用户真实意图，对应到下面四类直接执行：
>
> | 用户意图 | 对应能力 |
> |---------|---------|
> | **看**私海里有什么（"我名下的客户/线索""我的私海"） | 查本人数据：`cordys.sh crm page <account\|lead> '{"viewId":"SELF"}'`（非池操作，无需确认） |
> | 往私海**捞**（"领一条进来"） | 领取 `pool pick` |
> | 把私海里的**退**出去（"这条我跟不动了，退回去"） | 退回 `pool to-pool` |
> | 把我名下的**转**给别人（"派给张三"） | 分配 `pool assign` |
>
> 即"进私海"=`pick`、"出私海"=`to-pool`、"转他人私海"=`assign`、"看私海"=`viewId:SELF` 查询。

### 6.1 流程

1. **定位记录** — 池子记录用 `cordys.sh crm page pool/<lead|account>` 查；自己名下记录退回时用 `cordys.sh crm search`
2. **补齐参数**：
   - 领取需 `poolId` → `cordys.sh raw GET /pool/<lead|account>/options` 获取当前用户可领取的池子
   - 分配需 `assignUserId` → `cordys.sh crm members` 按姓名查用户 ID
   - 退回的 `原因ID` 选填，多数场景可省略
3. **确认（二次确认原则）** — 展示操作类型、影响记录、目标归属：

```
即将【领取】2 条线索到你名下：

1. 「明基电通科技」(395179812056477696)
2. 「中冶华天工程」(395174262958731264)

确认无误请回复"确认"。
```

4. **执行** — 调对应 `pool` 命令，返回 `code: 100200` 为成功
5. **汇报结果** — 成功/失败条数

```bash
# 领取单条（先查池子拿 poolId）
cordys.sh raw GET /pool/lead/options
cordys_ext.sh pool pick lead 395179812056477696 <poolId>

# 分配给成员（先 crm members 查用户ID）
cordys_ext.sh pool assign account 395178712544849920 1131998760411284

# 批量退回线索池
cordys_ext.sh pool batch-to-pool lead "id1,id2,id3"
```

> **领取 vs 分配**：`pick` 领到当前操作人名下（销售自己捞）；`assign` 指派给别人（经理派活）。两者用的接口不同，别混。
>
> **归属变更属于敏感操作**，执行前必须二次确认，展示清楚"哪些记录、归给谁"。
>
> **池子操作不可随意测试**：线索池/公海里都是真实记录，pick/assign/to-pool 会真实改变归属，没有"原值写回"的无副作用测法。

---

## 6.5 跟进记录 / 跟进计划写入

给已存在的线索/客户/商机写跟进。两者平行但**是两套**：跟进**记录**=已发生；跟进**计划**=后续预约/排期。均走 `cordys_ext.sh`，脚本自动完成方式 label→ID、姓名→userId、时间→毫秒戳、产品名→ID，**无需二次确认**。拜访/「聊了+约访」完整话术优先走 **`sop/visit-flow.md`（最优链路）**。

```bash
cordys_ext.sh follow      '<JSON>'   # 记录 → POST /{module}/follow/record/add
cordys_ext.sh follow-plan '<JSON>'   # 计划 → POST /{module}/follow/plan/add
```

### 最优调用链（强制）

```text
并行 search lead+account+opportunity（keyword=公司名，禁止商机标题当 keyword）
  → 选取 商机>线索>客户，记下 module + 资源 id（商机必带 customerId）
  → 提了联系人且有 customerId：crm contact account <id> 匹配姓名
  → follow / follow-plan（首跳 JSON 必须含 module + 资源 id；两者都要则复用 id，勿再搜）
```

| 规则 | 说明 |
|------|------|
| 定位 | **只用** `crm search`，**不用** `check`（查重专用）。本轮 check 已带 id 可复用 |
| keyword | **公司名**；禁止先只搜客户再猜商机全名串行试探 |
| **module** | JSON **必填** `lead`/`account`/`opportunity`；脚本**不会**从 type/opportunityId 推断，缺则直接报错 |
| 双写 | 记录+计划各调一次；id 同源，字段名勿混（见下表） |
| 失败处理 | 只重跑 `cordys_ext.sh`；**禁止** `python -c` 塞密钥。无 JSON/`error` 字段=失败，勿当成功 |

```bash
# 记录（商机，一次成功）
cordys_ext.sh follow '{"module":"opportunity","opportunityId":"<id>","customerId":"<id>","跟进方式":"电话","跟进内容":"……"}'
# 计划
cordys_ext.sh follow-plan '{"module":"opportunity","opportunityId":"<id>","customerId":"<id>","跟进方式":"到访","计划时间":"2026-07-17 09:00","跟进内容":"……","意向产品":"JumpServer 企业版"}'
```

⚠️ **记录与计划字段名不同，勿混用**：

| | 跟进记录 `follow` | 跟进计划 `follow-plan` |
|---|---|---|
| 端点 | `/{module}/follow/record/add` | `/{module}/follow/plan/add` |
| 脚本必填 | **module** + 资源 id + content | **module** + 资源 id + content + 方式 |
| 时间字段 | `followTime` / 跟进时间 | `estimatedTime` / 计划时间 |
| 方式字段 | `followMethod` / 跟进方式 | `method` / 跟进方式 |
| 方式选项 ID | 记录表单专属 | 计划表单专属（与记录不同） |
| type/ID 映射 | lead→CLUE/clueId；account→CUSTOMER/customerId；opportunity→CUSTOMER/opportunityId(+customerId) | 同左 |

> 中文键可用；计划时间可传毫秒戳。字段权威：`references/forms/follow.md`、`follow-plan.md`。

---

## 7. 写入安全约束

### 7.1 必须做的事

| 约束 | 说明 |
|------|------|
| **先懂表单** | 创建/更新前必须读 `references/forms/{module}.md` 拿字段定义、fieldId、选项 value，不得盲写 |
| **创建必查重** | 创建前必须执行 `cordys_ext.sh check`，不得跳过 |
| **展示确认** | 单条展示全量字段表、更新展示 diff、批量展示影响范围，确认后执行 |
| **验证结果** | 以 `code: 100200` 为成功判据 |

### 7.2 绝对不能做的事

| 禁止 | 说明 |
|------|------|
| ❌ **乱传 owner** | 创建不传 owner（交后端兜底）；要归他人先创建再 `crm update` 改 `owner`=**userId**（不是 id），否则记录静默归错人 |
| ❌ **SELECT 传中文进 moduleFields** | moduleFields 的 fieldValue 要传选项 value/ID（见 §0.4），传中文可能静默写空 |
| ❌ **跳过查重/校验** | 创建不得跳过 `cordys_ext.sh check`，写入不得绕过必填校验 |
| ❌ **删除操作** | 不提供、不执行任何删除 API |
| ❌ **批量不预览** | 批量操作必须预览确认 |
| ❌ **修改系统字段** | 不修改 `id`、`createTime`、`createUser` 等 |

---

## 8. 错误处理

所有写入命令返回 JSON，`code: 100200` 为成功。非成功时按下表处理：

| 响应 | 处理 |
|------|------|
| `code ≠ 100200` | 读取 `message`，格式化后告知用户，不要原样抛 JSON |
| 必填字段缺失 | 列出缺失字段（含条件必填触发项），引导用户一次性补充 |
| 字段值不合法 | 说明原因 + 列出合法选项（取自 `references/forms/{module}.md` 的 SELECT 可选值） |
| 重复数据（查重命中） | 展示冲突记录，询问用户是否仍要创建，不要自动跳过 |
| 权限不足 | 提示用户联系管理员，不要重试 |

### 8.1 ⚠️ HTTP 500 / 超时：先查证，再重试（防"假失败真成功"）

create/update 及 `cordys_ext.sh transform` 调用 Cordys API 时，遇 **HTTP 500 或超时**，**后端可能已经写入成功**——这是已知行为，曾因盲目重试建出重复数据。

- `cordys.sh crm create/update/batch-update` 与 `cordys_ext.sh transform` 的底层脚本会读取 HTTP 500 响应体；若 body 里 `code=100200` 则按成功处理，body 为空（真网络中断）才返回 `code:0` 错误。
- 若最终仍报失败/超时，**重试前必须先用 `cordys.sh crm page <模块> '{"keyword":"<刚写的名称>"}'` 查证**该记录是否已存在；已存在则不要重复创建，直接取已有记录。
- 这条对**创建**尤其关键（更新/批量是幂等的，重复执行无害）。
