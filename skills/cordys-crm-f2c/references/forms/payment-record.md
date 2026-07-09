# 回款记录查询参考

> 模块路径：`contract/payment-record`。仅支持查询和统计，不支持通过助手创建。

> 查询字段的取值/用法补充（人工维护，位于自动生成区块外，`sync` 不会覆盖）。
>
> ⚠️ **构造 conditions 前必须加载 `core/cli-reference.md` 查 operator，禁止凭记忆填写。**
> - `负责人`：过滤条件中 name 填 `owner`（值=userId）；返回记录中 `ownerName` 仅供展示。
> - 回款统计主时间字段是 `recordEndTime`（实际回款日期）。

<!-- AUTO-GENERATED-START -->


## SELECT 字段可选值

> **创建和查询都传 ID**：标注「传 ID」的字段，中文与 ID 不一致，必须填 `=` 右侧的 ID（填中文会静默失败——创建写空、查询返回空）；未标注的字段中文即 ID，直接传中文即可。
> 创建时 SELECT 字段放 `moduleFields` 的 `fieldValue`、产品放 `products`；查询时放 `combineSearch.conditions` 的 `value`。

- **收款银行**（传 ID）：中国银行=1, 中国农业银行=2, 中国工商银行=3, 中国建设银行=4
- **收款银行账号**（传 ID）：银行账号1=1, 银行账号2=2, 银行账号3=3
- **产品类型（可多选）**（传 ID）：JumpServer 企业版=1751888184000091, MaxKB 专业版=1751888184000102, MaxKB 企业版=8327632349528064, MaxKB 一体机=373302305212559360, DataEase 企业版=1751888184000101, DataEase 专业版=1751888184000092, DataEase 嵌入式版=1751888184000097, Cordys CRM 企业版=10034933389336576, SQLBot 专业版=8366853990875136, MeterSphere 企业版=1751888184000098, CloudExplorer 云管平台=1751888184000093, 1Panel AI 助理一体机=329298398169903104, 1Panel AI 编程一体机=369329829830946816, 1Panel 专业版=1751888184000088, 1Panel 企业版=369330027399442432, Zabbix=391660490084315136, 第三方产品（Gitea）=1751888184000099, 第三方产品（TAPD）=1751888184000094, 第三方产品（公有云服务）=1751888184000090, 第三方产品（USBKey）=2579076322140160, 第三方产品（国密SSL证书）=2580141474029568, 第三方产品（PCIE密码卡）=2580433531805696, 第三方产品（缓存服务器）=2580931748012032, 第三方产品（Web服务器）=389209953543909376, 第三方产品（数据库）=388735960953122825, 第三方产品（其他）=1751888184000095, 培训服务=5139031449427968, 高校合作计划=1751888184000100, Halo 企业版=312882406099316736, Halo 专业版=312881942242848768, KubeOperator 容器平台=1751888184000089


## 查询字段参考

> 用于 `combineSearch.conditions` 的 `name` 值。有 businessKey 的用 businessKey，否则用 fieldId。操作符规则见 `core/cli-reference.md`。

| 字段 | name（条件用） | type |
|------|--------------|------|
| createTime | createTime | DATE_TIME |
| updateTime | updateTime | DATE_TIME |
| departmentId | departmentId | DEPARTMENT |
| 回款记录名 | name | INPUT |
| 合同名 | contractId | DATA_SOURCE |
| 合同编码 | 758216347107333_ref_176968185541500000 | INPUT |
| 产品类型 | 758216347107333_ref_177027611329500000 | DATA_SOURCE_MULTIPLE |
| 回款计划 | paymentPlanId | DATA_SOURCE |
| 回款时间 | recordEndTime | DATE_TIME |
| 回款金额 | recordAmount | INPUT_NUMBER |
| 收款银行 | 758216347107339 | SELECT |
| 收款银行账号 | 758216347107340 | SELECT |
<!-- AUTO-GENERATED-END -->

## 聚合字段

| 语义 | 字段 | 说明 |
|------|------|------|
| 回款金额 | `recordAmount` | 单笔回款金额，聚合用 |
| 负责人 | `ownerName` | 分组用 |
| 部门 | `departmentName` | 分组用 |
| 关联合同 | `contractName` | 分组用 |

## 时间字段选择

| 统计口径 | 时间字段 | 说明 |
|---------|---------|------|
| 回款（默认） | `recordEndTime` | 实际回款发生日期 |
| 记录创建 | `createTime` | 回款记录录入时间 |

## 常用聚合示例

```bash
# 本月回款总额
cordys.sh crm aggregate contract/payment-record recordAmount sum '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"DYNAMICS","name":"recordEndTime","value":"MONTH","type":"TIME_RANGE_PICKER"}]}}'

# 本季度回款总额
cordys.sh crm aggregate contract/payment-record recordAmount sum '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"DYNAMICS","name":"recordEndTime","value":"QUARTER","type":"TIME_RANGE_PICKER"}]}}'
```
