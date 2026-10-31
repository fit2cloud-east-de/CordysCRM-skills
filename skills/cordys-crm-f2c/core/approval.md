# ✅ 审批操作

用户提到待审批、批一下、驳回、提审、审批进度时读本文件。端点、请求体和响应字段的完整参考见 `core/cli-reference.md` §4。

## 1. 意图 → 命令

| 用户说 | 映射命令 | 副作用 |
|--------|---------|--------|
| 我的待审批、看看谁需要我批 | `approval todo pending` | 只读 |
| 我处理过的审批 | `approval todo processed` | 只读 |
| 我发起的 | `approval todo initiated` | 只读 |
| 抄送我的 | `approval todo cc` | 只读 |
| 有多少待审批 | `approval todo count` | 只读 |
| 审批进度 | `approval resource detail <resourceId>` | 只读 |
| 审批流设置 | `approval flow list` | 只读 |
| 同意/通过这个审批 | `approval action approve` + `resourceId` | **写，需确认** |
| 驳回/拒绝 | `approval action reject` + `resourceId` + `remark` | **写，需确认** |
| 退回/打回 | `approval action back` + `resourceId` + `backNodeId` | **写，需确认** |
| 加签 | `approval action sign` + `resourceId` + `signUserIds` | **写，需确认** |
| 撤回申请 | `approval action revoke` + `resourceId` | **写，需确认** |
| 批量同意 / 批量驳回 | `approval action batch-approve` / `batch-reject` + `resourceIds` | **写，需确认** |
| 提交审批/提审 | `approval resource push` + `resourceId` | **写，需确认** |
| 撤销审批 | `approval resource revoke` + `resourceId` | **写，需确认** |

## 2. 二次确认（强制）

审批动作不可逆，与创建/修改同等对待：执行任何 `approval action *`、`approval resource push/revoke` 前，必须展示 **审批对象（名称、类型、发起人、当前节点）+ 将执行的动作 + 意见/备注**，用户回复「确认」或「提交」后才调用。批量操作必须逐条列出 `resourceIds` 对应的记录。`approval flow add/update/enable/disable` 修改审批流配置，同样需确认。高管角色只读，不执行审批写操作。

## 3. 代办 JSON 结构

和 CRM page 参数结构一致，额外多一个可选字段 `resourceType`：`ALL` / `QUOTATION` / `CONTRACT` / `ORDER` / `INVOICE`。

```bash
cordys.sh crm approval todo pending '{"current":1,"pageSize":30,"resourceType":"CONTRACT"}'
cordys.sh crm approval todo count
cordys.sh crm approval action approve '{"resourceId":"xxx","remark":"同意"}'
cordys.sh crm approval resource detail RESOURCE_ID
```

## 4. 预警触发

审批相关预警规则见 `core/risk-engine.md` §5：在用户查看审批列表、审批详情，或经理/财务首次询问团队/财务概览时扫描；不在每次对话开始时自动调用 `approval todo count`。
