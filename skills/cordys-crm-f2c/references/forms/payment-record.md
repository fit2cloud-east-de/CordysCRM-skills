# 回款记录查询参考

> 模块路径：`contract/payment-record`。仅支持查询和统计，不支持通过助手创建。

> 查询字段的取值/用法补充（人工维护，位于自动生成区块外，`sync` 不会覆盖）。
>
> ⚠️ **构造 conditions 前必须加载 `core/cli-reference.md` 查 operator，禁止凭记忆填写。**
> - `负责人`：过滤条件中 name 填 `owner`（值=userId）；返回记录中 `ownerName` 仅供展示。
> - 回款统计主时间字段是 `recordEndTime`（实际回款日期）。统计请求出现 `createTime`/`updateTime` 会直接拒绝。
> - `createTime` 只表示“这条回款记录何时录入 CRM”。只有用户明确询问“本月录入了哪些回款记录”时，才可在 `crm page contract/payment-record` 明细查询中使用；不得把它当实际回款业绩。

<!-- AUTO-GENERATED-START -->
## 表单 SELECT 字段可选值

> **创建和查询都传 ID**：标注「传 ID」的字段，中文与 ID 不一致，必须填 `=` 右侧的 ID（填中文会静默失败——创建写空、查询返回空）；未标注的字段中文即 ID，直接传中文即可。
> 创建时 SELECT 字段放 `moduleFields` 的 `fieldValue`、产品放 `products`；查询时放 `combineSearch.conditions` 的 `value`。

> 本节只列自定义表单字段；系统/API 的 SELECT 字段以“查询字段参考”为准。

- **收款银行**（传 ID）：中国银行=1, 中国农业银行=2, 中国工商银行=3, 中国建设银行=4
- **收款银行账号**（传 ID）：银行账号1=1, 银行账号2=2, 银行账号3=3
- **产品类型（可多选）**（传 ID）：JumpServer 企业版=1751888184000091, MaxKB 专业版=1751888184000102, MaxKB 企业版=8327632349528064, MaxKB 一体机=373302305212559360, DataEase 企业版=1751888184000101, DataEase 专业版=1751888184000092, DataEase 嵌入式版=1751888184000097, Cordys CRM 企业版=10034933389336576, SQLBot 专业版=8366853990875136, MeterSphere 企业版=1751888184000098, CloudExplorer 云管平台=1751888184000093, 1Panel AI 助理一体机=329298398169903104, 1Panel AI 编程一体机=369329829830946816, 1Panel 专业版=1751888184000088, 1Panel 企业版=369330027399442432, Zabbix=391660490084315136, 第三方产品（Gitea）=1751888184000099, 第三方产品（TAPD）=1751888184000094, 第三方产品（公有云服务）=1751888184000090, 第三方产品（USBKey）=2579076322140160, 第三方产品（国密SSL证书）=2580141474029568, 第三方产品（PCIE密码卡）=2580433531805696, 第三方产品（缓存服务器）=2580931748012032, 第三方产品（Web服务器）=389209953543909376, 第三方产品（数据库）=388735960953122825, 第三方产品（其他）=1751888184000095, 培训服务=5139031449427968, 高校合作计划=1751888184000100, Halo 企业版=312882406099316736, Halo 专业版=312881942242848768, KubeOperator 容器平台=1751888184000089


## 查询字段参考

> 用于 `combineSearch.conditions` 的 `name` 值。有 businessKey 的用 businessKey，否则用 fieldId。操作符规则见 `core/cli-reference.md`。

> “系统/API”字段可能不显示为自定义表单控件或“表单 SELECT 字段可选值”列表；只要列在本表中，即可作为 conditions 的字段依据。

| 字段 | name（条件用） | type | 来源 |
|------|--------------|------|------|
| createTime | createTime | DATE_TIME | 系统/API |
| updateTime | updateTime | DATE_TIME | 系统/API |
| departmentId | departmentId | DEPARTMENT | 系统/API |
| owner | owner | MEMBER | 系统/API |
| recordEndTime | recordEndTime | DATE_TIME | 系统/API |
| recordAmount | recordAmount | INPUT_NUMBER | 系统/API |
| 回款记录名 | name | INPUT | 表单 |
| 合同名 | contractId | DATA_SOURCE | 表单 |
| 合同编码 | 758216347107333_ref_176968185541500000 | INPUT | 表单 |
| 产品类型 | 758216347107333_ref_177027611329500000 | DATA_SOURCE_MULTIPLE | 表单 |
| 回款计划 | paymentPlanId | DATA_SOURCE | 表单 |
| 收款银行 | 758216347107339 | SELECT | 表单 |
| 收款银行账号 | 758216347107340 | SELECT | 表单 |

## 视图目录

> `viewId` 按模块选择。官方内置视图由 Cordys 前端定义；实例自定义视图由 `sync` 从对应 `/view/list` 自动刷新。
> 自定义视图只在用户明确引用视图时使用；未明确引用时按角色基础范围查询。视图不能扩大当前角色的数据范围。

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

## 统计字段

| 语义 | 字段 | 说明 |
|------|------|------|
| 回款金额 | `recordAmount` | 单笔回款金额，本地汇总用 |
| 负责人 | `ownerName` | 分组用 |
| 部门 | `departmentName` | 分组用 |
| 关联合同 | `contractName` | 分组用 |

## 时间字段选择

| 统计口径 | 时间字段 | 说明       |
|---------|---------|----------|
| 回款（默认） | `recordEndTime` | 回款日期     |
| 记录创建（仅明细查询） | `createTime` | 回款记录录入时间；禁止用于回款统计 |

## 常用统计示例

```bash
# 本月回款总额（基于 page 全量分页，本地流式求和）
cordys.sh crm page-summary contract/payment-record '{"sum":["recordAmount"]}' '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"DYNAMICS","name":"recordEndTime","value":"MONTH","type":"TIME_RANGE_PICKER"}]}}'

# 本季度回款总额（基于 page 全量分页，本地流式求和）
cordys.sh crm page-summary contract/payment-record '{"sum":["recordAmount"]}' '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"DYNAMICS","name":"recordEndTime","value":"QUARTER","type":"TIME_RANGE_PICKER"}]}}'
```
