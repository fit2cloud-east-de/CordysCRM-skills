# 创建流程（5 步）

所有模块（线索/客户/商机/联系人）遵循相同流程。

---

## 步骤 1：提取 + 推断

从用户输入提取字段值，应用 `core/inference-rules.md` 自动补充。

## 步骤 2：查重

```bash
cordys_ext.sh check '{"客户名":"<名称>","手机":"<手机号>","产品":["<产品名>"],"场景":"创建"}'
```

- `pass: true` → 继续
- `pass: false` → 展示 blocks 问用户是否继续
- `warnings` → 告知用户但不阻断

创建场景必须传 `"场景":"创建"` 和产品参数。详见 `core/duplicate-check.md`。

## 步骤 3：解析 DATA_SOURCE 字段 ID

仅商机和联系人需要（参见各 references 中标记 ⚠️ 实体 ID 的字段）。

```bash
cordys.sh crm search account '{"keyword":"<客户名>","current":1,"pageSize":5}'
cordys.sh crm search contact '{"keyword":"<联系人名>","current":1,"pageSize":5}'
```

- 1 条 → 取 `id`
- 多条 → 列出候选，问用户
- 0 条 → 提示未找到，停止

## 步骤 4：校验必填字段

对照 `references/{module}.md` 中的必填清单逐项检查：
- 齐全 → 步骤 5
- 缺失 → 列出缺失字段和可选值，问用户补充

## 步骤 5：创建

```bash
cordys_ext.sh create <module> '<JSON>'
```

module：`lead` / `account` / `opportunity` / `contact`

返回 `code: 100200` 为成功，取 `data.id`。

> SELECT 字段传中文值，支持简称前缀匹配，CLI 自动转换。
