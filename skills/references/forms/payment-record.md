# 回款记录查询参考

> 模块路径：`contract/payment-record`

## 查询字段参考

> 用于 `combineSearch.conditions` 的 `name` 值。

| 字段 | name（条件用） | type | 说明 |
|------|--------------|------|------|
| recordEndTime | recordEndTime | DATE_TIME | 回款日期（统计主时间字段） |
| createTime | createTime | DATE_TIME | 记录创建时间 |
| departmentId | departmentId | DEPARTMENT | 部门 |
| 负责人 | owner | MEMBER | 过滤条件中 name 填 `owner`；返回记录中 `ownerName` 仅供展示 |

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
