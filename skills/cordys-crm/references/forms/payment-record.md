# 回款记录查询参考

> 模块路径：`contract/payment-record`。仅支持查询和统计，不支持通过助手创建。

> 查询字段的取值/用法补充（人工维护，位于自动生成区块外，`sync` 不会覆盖）。
>
> ⚠️ **构造 conditions 前必须加载 `core/cli-reference.md` 查 operator，禁止凭记忆填写。**
> - `负责人`：过滤条件中 name 填 `owner`（值=userId）；返回记录中 `ownerName` 仅供展示。
> - 回款统计主时间字段是 `recordEndTime`（实际回款日期）。

<!-- AUTO-GENERATED-START -->


## SELECT 字段可选值

> **创建时传中文标签**（支持简称，CLI 自动前缀匹配）。
> **查询时（`combineSearch.conditions` 的 `value`）传选项 ID**：标注「查询用 ID」的字段，中文与 ID 不一致，查询必须填 `=` 右侧的 ID（填中文会静默返回空）；未标注的字段中文即 ID，查询直接传中文即可。

- **收款银行**（查询用 ID）：中国银行=1, 中国农业银行=2, 中国工商银行=3, 中国建设银行=4
- **收款银行账号**（查询用 ID）：银行账号1=1, 银行账号2=2, 银行账号3=3
- **产品类型（可多选）**：JumpServer 企业版, MaxKB 专业版, MaxKB 企业版, MaxKB 一体机, DataEase 企业版, DataEase 专业版, DataEase 嵌入式版, Cordys CRM 企业版, SQLBot 专业版, MeterSphere 企业版, CloudExplorer 云管平台, 1Panel AI 助理一体机, 1Panel AI 编程一体机, 1Panel 专业版, 1Panel 企业版, Zabbix, 第三方产品（Gitea）, 第三方产品（TAPD）, 第三方产品（公有云服务）, 第三方产品（USBKey）, 第三方产品（国密SSL证书）, 第三方产品（PCIE密码卡）, 第三方产品（缓存服务器）, 第三方产品（Web服务器）, 第三方产品（数据库）, 第三方产品（其他）, 培训服务, 高校合作计划, Halo 企业版, Halo 专业版, KubeOperator 容器平台


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
