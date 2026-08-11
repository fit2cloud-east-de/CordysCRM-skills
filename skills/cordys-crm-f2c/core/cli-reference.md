# 📖 CLI 参考手册

> 本文件是 `cli-spec.md` 的补充参考，包含完整的字段类型映射表、操作符枚举和详细示例。
> **仅在构造复杂 conditions 且不确定字段类型或操作符时加载。** 日常查询优先使用 `cli-spec.md`。

---

## 0. page 统计索引

统计完整规则见 `core/funnel-engine.md`。所有统计只以各模块 `page` 为数据源；旧统计 API 和 `stat/stat-home/aggregate/dist` 方法均已弃用。

日常统计使用：

```bash
cordys.sh crm page lead '{"current":1,"pageSize":1,"viewId":"SELF","combineSearch":{"searchMode":"AND","conditions":[]}}'
cordys.sh crm page-summary opportunity '{"sum":["amount"],"groupBy":["stage"],"topN":20}' '{"viewId":"SELF","combineSearch":{"searchMode":"AND","conditions":[]}}'
```

---

## 1. 操作符总表

以下是所有可用操作符（enum 枚举值，**全大写**）：

| 操作符 | 含义 | 适用字段类型 |
|--------|------|-------------|
| `EQUALS` | 精确等于 | INPUT, TEXTAREA, PHONE, LINK, SERIAL_NUMBER, INPUT_NUMBER |
| `NOT_EQUALS` | 不等于 | 同上 |
| `CONTAINS` | 包含（模糊匹配） | INPUT, TEXTAREA, PHONE, LINK, SERIAL_NUMBER, ATTACHMENT, INPUT_MULTIPLE |
| `NOT_CONTAINS` | 不包含 | 同上 |
| `GT` | 大于 | INPUT_NUMBER, DATE_TIME |
| `LT` | 小于 | INPUT_NUMBER, DATE_TIME |
| `GE` | 大于等于 | INPUT_NUMBER |
| `LE` | 小于等于 | INPUT_NUMBER |
| `BETWEEN` | 在区间内 | DATE_TIME（时间戳数组 `[ts1, ts2]`） |
| `IN` | 在集合中（多选） | RADIO, SELECT, CHECKBOX, MEMBER, DEPARTMENT, DATA_SOURCE, SELECT_MULTIPLE, MEMBER_MULTIPLE, DEPARTMENT_MULTIPLE, DATA_SOURCE_MULTIPLE, LOCATION |
| `NOT_IN` | 不在集合中 | 同上 |
| `COUNT_GT` | 多值数量大于 | INPUT_MULTIPLE |
| `COUNT_LT` | 多值数量小于 | INPUT_MULTIPLE |
| `EMPTY` | 为空 | 除分割线/图片/公式/子表外的所有字段 |
| `NOT_EMPTY` | 不为空 | 同上 |
| `DYNAMICS` | 动态时间（需配合 `TIME_RANGE_PICKER` 类型） | DATE_TIME |

> `IN/NOT_IN` 要求 `value` 为数组，但 condition 的 `type` 仍取字段 schema 的真实类型。示例：`stage NOT_IN ["SUCCESS","FAIL"]` 必须写 `type:"SELECT"`，不能因为数组有两个值改写成 `SELECT_MULTIPLE`。

---

## 2. 字段类型 → 支持的操作符映射

> 本表是 Cordys CRM 后端的核心规则，**构造 conditions 时必须查询目标字段的实际类型，然后按此表选择合法操作符。**

| 字段类型 | 中文名 | 支持的操作符 |
|----------|--------|-------------|
| `INPUT` | 单行输入 | `EQUALS`, `NOT_EQUALS`, `CONTAINS`, `NOT_CONTAINS`, `EMPTY`, `NOT_EMPTY` |
| `TEXTAREA` | 多行输入 | `EQUALS`, `NOT_EQUALS`, `CONTAINS`, `NOT_CONTAINS`, `EMPTY`, `NOT_EMPTY` |
| `PHONE` | 电话 | `EQUALS`, `NOT_EQUALS`, `CONTAINS`, `NOT_CONTAINS`, `EMPTY`, `NOT_EMPTY` |
| `LINK` | 链接 | `EQUALS`, `NOT_EQUALS`, `CONTAINS`, `NOT_CONTAINS`, `EMPTY`, `NOT_EMPTY` |
| `SERIAL_NUMBER` | 流水号 | `EQUALS`, `NOT_EQUALS`, `CONTAINS`, `NOT_CONTAINS`, `EMPTY`, `NOT_EMPTY` |
| `INPUT_NUMBER` | 数字 | `EQUALS`, `NOT_EQUALS`, `GT`, `LT`, `GE`, `LE` |
| `ATTACHMENT` | 附件 | `CONTAINS`, `NOT_CONTAINS`, `EMPTY`, `NOT_EMPTY` |
| `DATE_TIME` | 日期时间 | `BETWEEN`, `GT`, `LT`, `EMPTY`, `NOT_EMPTY`，（另支持 `DYNAMICS` + `TIME_RANGE_PICKER`） |
| `INPUT_MULTIPLE` | 多值输入 | `COUNT_LT`, `COUNT_GT`, `CONTAINS`, `NOT_CONTAINS`, `EMPTY`, `NOT_EMPTY` |
| `RADIO` | 单选 | `IN`, `NOT_IN`, `EMPTY`, `NOT_EMPTY` |
| `SELECT` | 单选下拉 | `IN`, `NOT_IN`, `EMPTY`, `NOT_EMPTY` |
| `CHECKBOX` | 多选 | `IN`, `NOT_IN`, `EMPTY`, `NOT_EMPTY` |
| `MEMBER` | 成员（单选） | `IN`, `NOT_IN`, `EMPTY`, `NOT_EMPTY` |
| `DEPARTMENT` | 部门（单选） | `IN`, `NOT_IN`, `EMPTY`, `NOT_EMPTY` |
| `DATA_SOURCE` | 数据源（单选） | `IN`, `NOT_IN`, `EMPTY`, `NOT_EMPTY` |
| `SELECT_MULTIPLE` | 多选下拉 | `IN`, `NOT_IN`, `EMPTY`, `NOT_EMPTY` |
| `MEMBER_MULTIPLE` | 多选成员 | `IN`, `NOT_IN`, `EMPTY`, `NOT_EMPTY` |
| `DEPARTMENT_MULTIPLE` | 多选部门 | `IN`, `NOT_IN`, `EMPTY`, `NOT_EMPTY` |
| `DATA_SOURCE_MULTIPLE` | 多选数据源 | `IN`, `NOT_IN`, `EMPTY`, `NOT_EMPTY` |
| `LOCATION` | 地址 | `IN`, `NOT_IN`, `EMPTY`, `NOT_EMPTY` |
| `DIVIDER` | 分割线 | **无操作符**（纯展示字段，不可查询） |
| `PICTURE` | 图片 | **无操作符**（不可作为查询条件） |
| `INDUSTRY` | 行业 | **无操作符** |
| `FORMULA` | 公式 | **无操作符**（计算字段，不可查询） |
| `SUB_PRODUCT` | 子表-产品 | **无操作符**（子表结构，不可单独查询） |
| `SUB_PRICE` | 子表-价格 | **无操作符**（子表结构，不可单独查询） |

### 操作符归属速查

| 归属组 | 字段类型 | 可用操作符 |
|--------|----------|-----------|
| **文本类** | INPUT, TEXTAREA, PHONE, LINK, SERIAL_NUMBER | EQUALS, NOT_EQUALS, CONTAINS, NOT_CONTAINS, EMPTY, NOT_EMPTY |
| **数字类** | INPUT_NUMBER | EQUALS, NOT_EQUALS, GT, LT, GE, LE |
| **日期类** | DATE_TIME | BETWEEN, GT, LT, EMPTY, NOT_EMPTY, DYNAMICS |
| **附件类** | ATTACHMENT | CONTAINS, NOT_CONTAINS, EMPTY, NOT_EMPTY |
| **多值文本类** | INPUT_MULTIPLE | COUNT_LT, COUNT_GT, CONTAINS, NOT_CONTAINS, EMPTY, NOT_EMPTY |
| **单选/枚举类** | RADIO, SELECT, CHECKBOX, MEMBER, DEPARTMENT, DATA_SOURCE, SELECT_MULTIPLE, MEMBER_MULTIPLE, DEPARTMENT_MULTIPLE, DATA_SOURCE_MULTIPLE, LOCATION | IN, NOT_IN, EMPTY, NOT_EMPTY |
| **不可查询** | DIVIDER, PICTURE, INDUSTRY, FORMULA, SUB_PRODUCT, SUB_PRICE | （无） |

---

## 3. 各字段类型详细示例

### 文本类（INPUT / TEXTAREA / PHONE / LINK / SERIAL_NUMBER）

```json
// 精确匹配
{"value": "张三", "operator": "EQUALS", "name": "name", "type": "INPUT"}

// 模糊包含
{"value": "科技", "operator": "CONTAINS", "name": "company", "type": "INPUT"}

// 不包含
{"value": "测试", "operator": "NOT_CONTAINS", "name": "description", "type": "TEXTAREA"}

// 为空/不为空
{"value": "", "operator": "EMPTY", "name": "phone", "type": "PHONE"}
{"value": "", "operator": "NOT_EMPTY", "name": "website", "type": "LINK"}
```

### 数字类（INPUT_NUMBER）

```json
{"value": 100000, "operator": "EQUALS", "name": "amount", "type": "INPUT_NUMBER"}
{"value": 50000, "operator": "GT", "name": "amount", "type": "INPUT_NUMBER"}
{"value": 1000, "operator": "GE", "name": "quantity", "type": "INPUT_NUMBER"}
{"value": 10000, "operator": "LE", "name": "quantity", "type": "INPUT_NUMBER"}
```

### 日期类（DATE_TIME）

```json
// 时间戳区间（毫秒）
{"value": [1700000000000, 1700100000000], "operator": "BETWEEN", "name": "createTime", "type": "DATE_TIME"}

// 晚于某个时间
{"value": 1700000000000, "operator": "GT", "name": "createTime", "type": "DATE_TIME"}

// 动态时间
{"value": "MONTH", "operator": "DYNAMICS", "name": "createTime", "type": "TIME_RANGE_PICKER"}

// 为空/不为空
{"value": "", "operator": "EMPTY", "name": "followTime", "type": "DATE_TIME"}
```

> **时间格式**：`GT`/`LT`/`BETWEEN` 使用**毫秒级时间戳**；自然日按 `Asia/Shanghai`（固定 UTC+8）解释。禁止写 `CST` 或依赖宿主机本地时区，GNU `date` 会把 `CST` 解释成北美 UTC-6。
> **type 规则**：`DYNAMICS` 必须配 `type:"TIME_RANGE_PICKER"`；`BETWEEN` 必须配 `type:"DATE_TIME"`。
> **使用顺序**：本月、本年、近 30 天等相对时间用 `DYNAMICS`；上半年、下半年、自定义日期区间等明确自然日区间先运行 `cordys.sh crm date-range <开始日> <结束日>`，把返回的 `value` 原样放进 `BETWEEN`。

```bash
cordys.sh crm date-range 2026-07-01 2026-07-31
# {"timezone":"Asia/Shanghai",...,"value":[1782835200000,1785513599999]}
```

这里的 `1782835200000` 是上海时区 `2026-07-01 00:00`，对应 UTC `2026-06-30 16:00Z`；不是 UTC 午夜。

### 附件类 / 多值输入 / 枚举类

```json
// 附件
{"value": "合同", "operator": "CONTAINS", "name": "attachment", "type": "ATTACHMENT"}

// 多值输入
{"value": 2, "operator": "COUNT_GT", "name": "tags", "type": "INPUT_MULTIPLE"}
{"value": "VIP", "operator": "CONTAINS", "name": "tags", "type": "INPUT_MULTIPLE"}

// 枚举（单选/多选/成员/部门/数据源）
{"value": ["Qualification", "Negotiation"], "operator": "IN", "name": "stage", "multipleValue": false, "type": "SELECT"}
{"value": ["user123"], "operator": "IN", "name": "owner", "multipleValue": false, "type": "MEMBER"}
{"value": ["dept_a", "dept_b"], "operator": "IN", "name": "departmentId", "multipleValue": false, "type": "TREE_SELECT"}
```

### 动态时间常量表

| 常量 | 含义 | | 常量 | 含义 |
|------|------|-|------|------|
| `TODAY` | 今天 | | `YESTERDAY` | 昨天 |
| `WEEK` | 本周 | | `LAST_WEEK` | 上周 |
| `MONTH` | 本月 | | `LAST_MONTH` | 上个月 |
| `QUARTER` | 本季度 | | `LAST_QUARTER` | 上季度 |
| `YEAR` | 本年度 | | `LAST_YEAR` | 上年度 |
| `LAST_SEVEN` | 过去7天 | | `LAST_THIRTY` | 过去30天 |

自定义天数（如"早于90天/N天未更新"）：DYNAMICS **不支持**自定义天数（value 只收上表字符串常量，传数组会报 `ClassCastException`）。按当前时刻减 `N×86400×1000` 得到 `tsN`，`{"value":<tsN>,"operator":"LT","name":"<时间字段>","type":"DATE_TIME"}`（等价 `BETWEEN [0, tsN]`）。这是相对时长，不涉及自然日边界；"超过N天没跟进"还需另查 `EMPTY` 相加（LT/BETWEEN 不含 null）。详见 `cli-spec.md` §5.4。

---

## 4. 审批 API 完整参考

### 审批代办端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/approval-todo/pending/page` | POST | 待我审批分页 |
| `/approval-todo/processed/page` | POST | 我已处理的审批分页 |
| `/approval-todo/initiated/page` | POST | 我发起的审批分页 |
| `/approval-todo/cc/page` | POST | 抄送我的审批分页 |
| `/approval-todo/pending/count` | GET | 待审批统计 |

### 审批操作端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/approval-action/approve` | POST | 同意 |
| `/approval-action/reject` | POST | 驳回 |
| `/approval-action/back` | POST | 退回 |
| `/approval-action/sign` | POST | 加签 |
| `/approval-action/revoke` | POST | 撤回 |
| `/approval-action/batch-approve` | POST | 批量同意 |
| `/approval-action/batch-reject` | POST | 批量驳回 |

**请求体结构：**

```json
// 同意/驳回（单个）
{"resourceId":"审批资源ID", "remark":"审批意见"}

// 退回
{"resourceId":"审批资源ID", "backNodeId":"目标节点ID", "remark":"退回原因"}

// 加签
{"resourceId":"审批资源ID", "signUserIds":["user1","user2"], "remark":"加签说明"}

// 批量
{"resourceIds":["id1","id2"], "remark":"批量意见"}
```

### 审批资源端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/approval-resource/push` | POST | 提审 |
| `/approval-resource/revoke` | POST | 撤销 |
| `/approval-resource/simple-detail/{resourceId}` | GET | 列表详情 |
| `/approval-resource/detail/{resourceId}` | GET | 完整记录详情（含审批流进度） |

### 审批流端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/approval-flow/page` | POST | 审批流列表 |
| `/approval-flow/add` | POST | 新建审批流 |
| `/approval-flow/update` | POST | 更新审批流 |
| `/approval-flow/get/{id}` | GET | 审批流详情 |
| `/approval-flow/delete/{id}` | GET | 删除审批流 |
| `/approval-flow/enable/{id}` | GET | 启用/禁用 |
| `/approval-flow/get-by-form-type/{formType}` | GET | 按表单类型获取 |
| `/approval-flow/status-permission/setting/{formType}` | GET | 状态权限配置 |
| `/approval-flow/webhook/test` | POST | webhook 测试 |

### 审批代办响应字段

| 字段 | 说明 |
|------|------|
| `resourceId` | 审批资源ID |
| `resourceName` | 审批标题/名称 |
| `resourceType` | 资源类型（QUOTATION/CONTRACT/ORDER/INVOICE） |
| `status` | 审批状态 |
| `initiatorName` | 发起人 |
| `createTime` | 创建时间 |
| `currentApproverName` | 当前审批人 |

---

## 5. 写入 API 参考

> 完整写入流程和规范见 `core/write-engine.md`（创建/更新/批量/转化唯一入口）。本节仅列出端点速查。
> 下表「对应 CLI」列为命中该端点的命令，body 用 fieldId 双层结构（见 write-engine §0.4）；查重/省市/公海池用 `cordys_ext.sh check/loc/pool`。

### 5.1 表单获取端点

| 端点 | 方法 | 对应 CLI | 说明 |
|------|------|---------|------|
| `/lead/module/form` | GET | `crm form lead` | 线索表单定义 |
| `/account/module/form` | GET | `crm form account` | 客户表单定义 |
| `/opportunity/module/form` | GET | `crm form opportunity` | 商机表单定义 |
| `/account/contact/module/form` | GET | `crm form account/contact` | 联系人表单定义 |
| `/contract/module/form` | GET | `crm form contract` | 合同表单定义 |
| `/contract/payment-plan/module/form` | GET | `crm form contract/payment-plan` | 回款计划表单定义 |
| `/contract/payment-record/module/form` | GET | `crm form contract/payment-record` | 回款记录表单定义 |
| `/invoice/module/form` | GET | `crm form invoice` | 发票表单定义 |
| `/contract/business-title/module/form` | GET | `crm form contract/business-title` | 工商抬头表单定义 |
| `/opportunity/quotation/module/form` | GET | `crm form opportunity/quotation` | 报价单表单定义 |
| `/order/module/form` | GET | `crm form order` | 订单表单定义 |

### 5.2 创建端点

> `crm create <module> <JSON|->` 支持 `-`/`@-` 从 UTF-8 stdin 读取。同步后的 schema 含 `subFields` 时（当前为合同、发票、报价单、订单），CLI 自动读取当前 `/{module}/module/form` 并注入 `moduleFormConfigDTO`；下表只列调用方需要提供的业务字段。
> 创建订单先执行 `sop/order-create-flow.md`。调用方只传唯一 `contractId` 和可选的公共默认字段，不手传 `name`、owner、产品、收入类型、调整金额、订单子表或公式。CLI 读取合同全部有效子表行，按“具体产品/服务 ID + 收入类型中文标签”分组：同组合多行合并，不同组合顺序创建；每张名称仍为 `<合同编码>-<产品类型中文标签>-${订单编号}`，不追加收入类型。
> CLI 按同步后的合同/订单 forms 以“父表标签 + 子字段标签”映射每组源行全部有值的非 `FORMULA` 业务字段；SELECT/RADIO 以中文标签桥接两侧 option ID。PRICE 子行保留合同 `price_sub`、不复制合同子行 `id`；`*_ref_*` 投影只供校验/公式使用，POST 前剥离。每组独立计算全部子表/主表公式，合同调整金额按原始金额比例分摊、末组吸收尾差。任一组失败或状态不明即停止且禁止整批重跑；全部订单成功后才把合同“是否已拆订单”更新为“是”。

| 端点 | 方法 | 对应 CLI | 必填字段 |
|------|------|---------|---------|
| `/lead/add` | POST | `crm create lead` | `name`, `products` |
| `/account/add` | POST | `crm create account` | `name` |
| `/opportunity/add` | POST | `crm create opportunity` | `name`, `contactId`, `products`（owner 免传，后端设当前用户） |
| `/account/contact/add` | POST | `crm create account/contact` | `customerId`, `name` |
| `/contract/add` | POST | `crm create contract` | 同步后的本地 contract forms 必填字段 |
| `/contract/payment-plan/add` | POST | `crm create contract/payment-plan` | 同步后的本地 payment-plan forms 必填字段 |
| `/contract/payment-record/add` | POST | `crm create contract/payment-record` | 同步后的本地 payment-record forms 必填字段 |
| `/invoice/add` | POST | `crm create invoice` | 同步后的本地 invoice forms 必填字段 |
| `/contract/business-title/add` | POST | `crm create contract/business-title` | 同步后的本地 business-title forms 必填字段 |
| `/opportunity/quotation/add` | POST | `crm create opportunity/quotation` | `name`, `opportunityId`, `untilTime`, `products`, `moduleFields` |
| `/order/add` | POST | `crm create order` 批次编排内部调用 | 外层只需 `contractId`；CLI 为每组生成固定模板 `name`、合同 `owner/customerId/contractId`、合同编码、产品类型、顶层/子表收入类型、服务 ID、`price_sub`、分摊调整金额、完整业务字段和全部公式 |

### 5.3 更新端点

> **update 只传要改的字段即可**：`crm update` 内置读回合并（先 GET 现有记录再覆盖提交），其余字段自动保全，无需手动查回全部 moduleFields。详见 `core/write-engine.md §3`。
> 合同、发票、报价单、订单等子表模块的 update 同样自动附加当前 `moduleFormConfigDTO`，调用方不得手抄。

| 端点 | 方法 | 对应 CLI | 说明 |
|------|------|---------|------|
| `/lead/update` | POST | `crm update lead` | JSON 含 `id` + 要改的字段 |
| `/account/update` | POST | `crm update account` | JSON 含 `id` + 要改的字段 |
| `/opportunity/update` | POST | `crm update opportunity` | JSON 含 `id` + 要改的字段 |
| `/account/contact/update` | POST | `crm update account/contact` | JSON 含 `id` + 要改的字段 |
| `/contract/update` | POST | `crm update contract` | JSON 含 `id` + 要改的字段，脚本读回合并 |
| `/contract/payment-plan/update` | POST | `crm update contract/payment-plan` | 同上 |
| `/contract/payment-record/update` | POST | `crm update contract/payment-record` | 同上 |
| `/invoice/update` | POST | `crm update invoice` | 同上 |
| `/contract/business-title/update` | POST | `crm update contract/business-title` | 同上 |
| `/opportunity/quotation/update` | POST | `crm update opportunity/quotation` | API 要求完整对象；脚本读回并保留创建必填字段、`id`、`approvalStatus` |
| `/order/update` | POST | `crm update order` | JSON 含 `id` + 要改的字段，脚本读回合并 |
| `/lead/batch/update` | POST | `crm batch-update lead` | `ids[]` + `fieldId` + `fieldValue` |
| `/account/batch/update` | POST | `crm batch-update account` | 同上 |
| `/opportunity/batch/update` | POST | `crm batch-update opportunity` | 同上 |
| `/account/contact/batch/update` | POST | `crm batch-update account/contact` | 同上 |
| `/contract/batch/update` | POST | `crm batch-update contract` | 同上 |
| `/order/batch/update` | POST | `crm batch-update order` | 同上 |

> ⚠️ 所有写入操作使用 **POST** 方法，不存在 PUT 端点。不存在批量创建（batch-add）端点；批量编辑仅支持线索、客户、商机、联系人、合同和订单。
> 联系人的 `get/create/update/batch-update/form/view` 均可把 CLI 模块写成 `contact`；脚本会自动映射到真实的 `/account/contact/*` 路径。`account/contact` 显式写法继续兼容。

### 5.4 线索转化端点

| 端点 | 方法 | 对应 CLI | 必填字段 |
|------|------|---------|---------|
| `/lead/transition/account` | POST | 仅供转化封装内部使用，禁止 `raw` 直调 | `clueId`, `name` |
| `/lead/transform` | POST | 仅由 `cordys_ext.sh transform` 内部调用，禁止 `raw` 直调 | `clueId`（多步：转化+补联系人+补商机字段） |

**transition 请求体（ClueTransitionCustomerRequest）：**
```json
{
  "clueId": "线索ID",
  "name": "客户名称",
  "owner": "负责人（可选）",
  "moduleFields": [{"fieldId": "industry", "fieldValue": "科技"}]
}
```

**transform 请求体（ClueTransformRequest）：**
```json
{
  "clueId": "线索ID",
  "oppCreated": true,
  "oppName": "商机名称"
}
```

### 5.5 通用请求体结构

自定义字段通过 `moduleFields` 数组传递：
```json
{
  "name": "名称",
  "moduleFields": [
    {"fieldId": "自定义字段ID或key", "fieldValue": "值"}
  ]
}
```

## 6. 成员与组织范围参考

| 端点 | 方法 | 对应 CLI | 说明 |
|------|------|---------|------|
| `/department/tree` | GET | `crm org tree/ids/outline`；`crm members` 默认内部调用 | `ids` 用于 CRM 业务记录范围；`outline` 提供层级；members 用组织树递归父部门 |
| `/user/list` | POST | `crm members` | 顶层 `departmentIds` 只精确匹配，后端不会包含子部门；CLI 默认先展开全部子孙部门 |

成员范围必须使用顶层复数数组。下面一条命令即可取得三个部及其所有下级组/团队的在职名单，不要先用父部门精确查一次、发现人数少后再手工重跑：

```bash
cordys.sh crm members '{"departmentIds":["销售一部ID","销售二部ID","销售三部ID"]}' --active --compact
```

明确只看直属成员时才加 `--exact-departments`，它会跳过组织树读取并把所给 ID 原样交给 `/user/list`。顶层单数 `departmentId`、顶层 `enable` 或顶层 `status` 会被后端静默忽略，CLI 在联网前拒绝；在职过滤统一使用 `--active`。
