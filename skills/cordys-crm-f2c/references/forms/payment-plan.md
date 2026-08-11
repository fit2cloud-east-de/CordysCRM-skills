# 回款计划字段参考

> 模块路径：`contract/payment-plan`。字段、选项和视图由 `sync` 从当前实例刷新。

<!-- AUTO-GENERATED-START -->
| # | 字段 | JSON 键名 | 格式 |
|---|------|----------|------|
| 1 | 回款计划名 | 回款计划名 | 文本 |
| 2 | 合同名 | 合同名 | ⚠️ 实体 ID |
| 3 | 合同编码 | 合同编码 | 文本 |
| 4 | 预计回款金额 | 预计回款金额 | 数字 |
| 5 | 预计回款时间 | 预计回款时间 | YYYY-MM-DD |

选填：最终客户名、回款记录、发票记录


## 查询字段参考

> 用于 `combineSearch.conditions` 的 `name` 值。有 businessKey 的用 businessKey，否则用 fieldId。操作符规则见 `core/cli-reference.md`。

> “系统/API”字段可能不显示为自定义表单控件或“表单 SELECT 字段可选值”列表；只要列在本表中，即可作为 conditions 的字段依据。

| 字段 | name（条件用） | type | 来源 |
|------|--------------|------|------|
| createTime | createTime | DATE_TIME | 系统/API |
| updateTime | updateTime | DATE_TIME | 系统/API |
| departmentId | departmentId | DEPARTMENT | 系统/API |
| owner | owner | MEMBER | 系统/API |
| planStatus | planStatus | SELECT | 系统/API |
| planEndTime | planEndTime | DATE_TIME | 系统/API |
| planAmount | planAmount | INPUT_NUMBER | 系统/API |
| 回款计划名 | name | INPUT | 表单 |
| 最终客户名 | 1081644564316174_ref_177227450327600000 | DATA_SOURCE_MULTIPLE | 表单 |
| 合同编码 | 1081644564316174_ref_176968185541500000 | INPUT | 表单 |
| 回款记录 | 178244148010200000 | DATA_SOURCE_MULTIPLE | 表单 |
| 发票记录 | 178332219391200000 | DATA_SOURCE | 表单 |

## 视图目录

> `viewId` 按模块选择。官方内置视图由 Cordys 前端定义；实例自定义视图由 `sync` 从对应 `/view/list` 自动刷新。
> 自定义视图路由：用户明确引用视图，或去掉“看下/查看/查询/列出”等纯查询外壳后与唯一、已启用的视图名称完全一致时，直接使用该 `viewId`；精确命中后不从名称重复构造部门、时间条件。模糊相似仍按字段条件查询。视图不能扩大当前角色的数据范围。

### 官方内置视图

| 视图名称 | viewId |
|----------|--------|
| 所有计划 | `ALL` |
| 我的计划 | `SELF` |
| 部门计划 | `DEPARTMENT` |

### 实例自定义视图（自动同步）

| 视图名称 | viewId | 启用 | 固定 |
|----------|--------|------|------|
| — | — | — | — |
<!-- AUTO-GENERATED-END -->
