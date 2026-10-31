# 🔍 全局模糊搜索（多模块并行）

用户明确说"搜索 / 搜一下 / 列出 XX"且**未指定模块**，或明确要求全局搜索时执行本流程。输出格式见 `core/output-engine.md` §7。

## 1. 先判定：查重、Customer 360 还是全局搜索

| 用户输入 | 走向 |
|---------|------|
| 直接给公司名 / 手机号 / 人名，或"查一下 / 有没有 / 查查 XX"，或"看看 XX 公司的 JS/MK"（带产品简称） | **查重**（所有角色默认）：`cordys_ext.sh check`，规则与模板见 `sop/duplicate-check.md` |
| "看看 XX 公司"且未带产品简称 | **Customer 360**：`core/linkage-engine.md` §3.2 |
| 含「线索/客户/商机/联系人/线索池/线索公海/客户公海」等模块词 | 只搜已消歧的指定模块（池术语按 `core/query-pools.md`） |
| 明确说"搜索 / 列出 …"且不指定模块，或明确要求全局搜索 | 本节全局模糊搜索 |

「的 + 产品简称」的消歧细则见 `sop/inference-rules.md`「产品简称转换」。

## 2. 并行搜索 6 个模块

| 中文名 | 模块名 | 优先级 |
|--------|--------|-------|
| 线索 | `lead` | 🔴 高 |
| 线索池 | `pool/lead` | 🔴 高 |
| 客户 | `account` | 🔴 高 |
| 商机 | `opportunity` | 🟡 中 |
| 客户公海 | `pool/account` | 🟡 中 |
| 联系人 | `contact`（CLI 自动走 `/account/contact/page`） | 🟢 低 |

每个模块使用统一模板、`pageSize: 10`、按 `core/role-engine.md` §2.4 带上范围条件；池模块用 `crm search pool/...` 且只传 `keyword`。用后台进程 `&` 并行发起，等待全部完成后合并输出。每个模块的 JSON 读完后立即提取命中总数和前几条核心字段，原始 JSON 不再保留（见 `core/output-engine.md` §4）。
