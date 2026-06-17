# 合同查询参考

> 合同模块当前仅支持查询和统计，不支持通过助手创建。

## 查询字段参考

> 用于 `combineSearch.conditions` 的 `name` 值。
>
> ⚠️ **构造 conditions 前必须加载 `core/cli-reference.md` 查 operator，禁止凭记忆填写。**

| 字段 | name（条件用） | type | 说明 |
|------|--------------|------|------|
| stage | stage | SELECT | 合同阶段 |
| createTime | createTime | DATE_TIME | 合同创建时间 |
| updateTime | updateTime | DATE_TIME | 最近修改时间 |
| endTime | endTime | DATE_TIME | 合同结束日期 |
| startTime | startTime | DATE_TIME | 合同开始日期 |
| departmentId | departmentId | DEPARTMENT | 部门 |
| 负责人 | owner | MEMBER | 过滤条件中 name 填 `owner`；返回记录中 `ownerName` 仅供展示 |
| 金额 | amount | INPUT_NUMBER | 合同金额 |

## 业务术语

| 用户说法 | 字段 | 过滤值 |
|---------|------|--------|
| 待签署 / 未签 | stage | PENDING_SIGNING |

> 当前系统中合同全部为 `PENDING_SIGNING` 状态，暂无其他阶段数据。

## 聚合字段

| 语义 | 模块路径 | 字段 | 说明 |
|------|---------|------|------|
| 合同金额 | `contract` | `amount` | 合同总金额 |
| 已回款金额 | `contract` | `alreadyPayAmount` | 该合同已收回的金额 |
| 负责人 | `contract` | `ownerName` | 分组用 |
| 部门 | `contract` | `departmentName` | 分组用 |
| 客户 | `contract` | `customerName` | 分组用 |

## 时间字段选择

| 统计口径 | 时间字段 | 说明 |
|---------|---------|------|
| 新签合同 | `createTime` | 按合同创建时间统计 |
| 合同到期 | `endTime` | 按合同结束日期筛选即将到期合同 |

## 回款完成率计算

回款完成率 = `alreadyPayAmount` / `amount`

通过读取合同列表，提取每条记录的 `amount` 和 `alreadyPayAmount` 进行对比。
