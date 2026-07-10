# 联系人创建参考

## 必填字段清单

<!-- AUTO-GENERATED-START -->

| # | 字段 | JSON 键名 | 格式 |
|---|------|----------|------|
| 1 | 姓名 | 姓名 | 文本 |
| 2 | 客户名 | 客户名 | ⚠️ 实体 ID |
| 3 | 手机 | 手机 | 手机/电话 |

选填：职务、联系人部门、电子邮件、电话


## 查询字段参考

> 用于 `combineSearch.conditions` 的 `name` 值。有 businessKey 的用 businessKey，否则用 fieldId。操作符规则见 `core/cli-reference.md`。

| 字段 | name（条件用） | type |
|------|--------------|------|
| createTime | createTime | DATE_TIME |
| updateTime | updateTime | DATE_TIME |
| departmentId | departmentId | DEPARTMENT |
| owner | owner | MEMBER |
| 姓名 | name | INPUT |
| 客户名 | customerId | DATA_SOURCE |
| 职务 | 1751888184000051 | INPUT |
| 联系人部门 | 1751888184000052 | INPUT |
| 电子邮件 | 1751888184000053 | INPUT |
| 手机 | phone | PHONE |
| 电话 | 1751888184000055 | PHONE |
<!-- AUTO-GENERATED-END -->

## 字段业务术语

> 查询字段的取值/用法补充（人工维护，位于自动生成区块外，`sync` 不会覆盖）。

| 字段 | 业务术语 / 用法 |
|------|----------------|
| 负责人（owner） | 值填 userId |


> `owner`：创建免传（系统自动设为当前用户）；查询填 userId 过滤指定人，但查他人受角色权限约束（见 `profiles/*.md`）。

## 查重规则

统一走 SKILL.md 查重流程：用联系人手机号搜索线索+开放商机，判断客户名+产品是否重复。

## 默认值

无特殊默认值。

## DATA_SOURCE 字段

⚠️ 联系人有 1 个 DATA_SOURCE 字段需要解析 ID：

1. **客户名** → 用 `cordys.sh crm search account` 解析客户 ID

## 创建命令

命令：`cordys.sh crm create account/contact '<JSON>'`（body 双层结构，见 `core/write-engine.md` §0.4）

**要填的字段（中文示意）**：姓名、客户名（传客户ID）、手机（均为顶层系统字段）；职务、电子邮件为自定义字段放 moduleFields。

```bash
cordys.sh crm create account/contact '{"name":"韩梅梅","customerId":"370020872889004032","phone":"13900139000"}'
```

带选填字段（职务/电子邮件放 moduleFields，fieldId 见上方「查询字段参考」表）：
```bash
cordys.sh crm create account/contact '{"name":"韩梅梅","customerId":"370020872889004032","phone":"13900139000","moduleFields":[{"fieldId":"1751888184000051","fieldValue":"CTO"},{"fieldId":"1751888184000053","fieldValue":"han@example.com"}]}'
```

## 完整示例

**用户**："帮我给千里眼科技添加一个联系人，韩梅梅，手机 13900139000"

**步骤 1** — 提取：姓名=韩梅梅，客户名=千里眼科技，手机=13900139000

**步骤 2** — 查重（按 `sop/duplicate-check.md` 执行）：规则 1~4 未触发 → 继续

**步骤 3** — 解析客户 ID：
```bash
cordys.sh crm search account '{"keyword":"千里眼科技","current":1,"pageSize":5}'
```
返回：`{"code":100200,"data":{"list":[{"id":"370020872889004032","name":"千里眼科技"}],"total":1}}`
→ 客户 ID = `370020872889004032`

**步骤 4** — 校验：姓名 ✓ 客户ID ✓ 手机 ✓ → 全部齐全

**步骤 5** — 创建：
```bash
cordys.sh crm create account/contact '{"name":"韩梅梅","customerId":"370020872889004032","phone":"13900139000"}'
```
返回：`{"code":100200,"data":{"id":"370024257323233280","name":"韩梅梅"}}`

**回复**："联系人创建成功！姓名：韩梅梅，所属客户：千里眼科技，ID：370024257323233280"
