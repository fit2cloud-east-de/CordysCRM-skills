# 工商抬头字段参考

> 模块路径：`contract/business-title`。字段、选项和视图由 `sync` 从当前实例刷新。

<!-- AUTO-GENERATED-START -->
| # | 字段 | JSON 键名 | 格式 |
|---|------|----------|------|

选填：Name、Identification number、Opening bank、Bank account、Registration address、Phone number、Registered capital、Customer size、Registration number、Province、City、Scale、Industry、Remark、Company number


## 查询字段参考

> 用于 `combineSearch.conditions` 的 `name` 值。有 businessKey 的用 businessKey，否则用 fieldId。操作符规则见 `core/cli-reference.md`。

> “系统/API”字段可能不显示为自定义表单控件或“表单 SELECT 字段可选值”列表；只要列在本表中，即可作为 conditions 的字段依据。

| 字段 | name（条件用） | type | 来源 |
|------|--------------|------|------|
| createTime | createTime | DATE_TIME | 系统/API |
| updateTime | updateTime | DATE_TIME | 系统/API |
| departmentId | departmentId | DEPARTMENT | 系统/API |
| owner | owner | MEMBER | 系统/API |
| type | type | SELECT | 系统/API |
| approvalStatus | approvalStatus | SELECT | 系统/API |
| Name | name | INPUT | 表单 |
| Identification number | identificationNumber | INPUT | 表单 |
| Opening bank | openingBank | INPUT | 表单 |
| Bank account | bankAccount | INPUT | 表单 |
| Registration address | registrationAddress | INPUT | 表单 |
| Phone number | phoneNumber | INPUT | 表单 |
| Registered capital | registeredCapital | INPUT | 表单 |
| Customer size | companySize | INPUT | 表单 |
| Registration number | registrationNumber | INPUT | 表单 |
| Province | province | INPUT | 表单 |
| City | city | INPUT | 表单 |
| Scale | scale | INPUT | 表单 |
| Industry | industry | INPUT | 表单 |
| Remark | remark | INPUT | 表单 |
| Company number | companyNumber | INPUT | 表单 |

## 视图目录

> `viewId` 按模块选择。官方内置视图由 Cordys 前端定义；当前模块没有可用的 `/view/list`，不生成实例自定义视图。
> 自定义视图路由：用户明确引用视图，或去掉“看下/查看/查询/列出”等纯查询外壳后与唯一、已启用的视图名称完全一致时，直接使用该 `viewId`；精确命中后不从名称重复构造部门、时间条件。模糊相似仍按字段条件查询。视图不能扩大当前角色的数据范围。

### 官方内置视图

| 视图名称 | viewId |
|----------|--------|
| 所有工商抬头 | `ALL` |
| 我的工商抬头 | `SELF` |
| 部门工商抬头 | `DEPARTMENT` |

### 实例自定义视图（自动同步）

| 视图名称 | viewId | 启用 | 固定 |
|----------|--------|------|------|
| — | — | — | — |
<!-- AUTO-GENERATED-END -->
