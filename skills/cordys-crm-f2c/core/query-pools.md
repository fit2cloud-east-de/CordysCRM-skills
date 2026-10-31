# 🌊 私海 / 线索池 / 线索公海 / 客户公海

用户话里出现"私海""公海""线索池"时读本文件。这是全技能关于池术语消歧与池查询的**唯一权威**；其他文档只引用，不另行改写。池的写操作（领取/分配/退回）见 `core/write-engine.md` §6。

## 1. 先按业务对象消歧，再谈池名

| 用户明确名词 | 记录类型 | 查询模块 | 说明 |
|------------|---------|---------|------|
| 线索私海；线索上下文中的"私海" | 线索 | 普通 `lead` | **不是池模块**：不取 options、不传 `poolId` |
| 客户私海；客户上下文中的"私海" | 客户 | 普通 `account` | 同上 |
| 线索池、线索公海、线索（含公海）、线索(含公海)、线索里的公海 | 线索 | `pool/lead` | options `/pool/lead/options`；跨池搜索 `/global/search/clue_pool` |
| 客户公海、客户池 | 客户 | `pool/account` | options `/pool/account/options`；跨池搜索 `/global/search/customer_pool` |
| 裸"公海"，无业务对象上下文 | 客户 | `pool/account` | 同一句或当前上下文已明确在谈线索时按 `pool/lead` |
| 裸"私海"，上下文无法判断线索/客户 | — | 先询问 | 不得默认到 `lead`、`account` 或任何 `pool/*` |

- 私海只完成业务对象路由，不覆盖查询范围：范围按 `core/role-engine.md` §2.4 从原话解析（"我的/我名下的私海" → `viewId:SELF`；"张三的私海" → `owner=张三的 userId`；团队/部门 → 组织范围；未指定 → 角色默认值）。例如"看看我的线索私海" = `crm page lead` + `viewId:SELF`。
- 不同模块可以有同名池（线索公海和客户公海都可能叫"东区"）。池名只在**已锁定模块**的 options 内匹配；目标模块匹配不到或池为空时，列出该模块候选或如实报告空结果，**禁止改查另一模块兜底**，也不得两个模块都试。
- "东区客户公海 / 东区线索公海"中的"东区"直接修饰池，默认是池名；"公海里区域是东区"才把"东区"作为记录字段条件。

## 2. 两条查询路径，poolId 要求不同

| 目的 | 命令 | 命中端点 | poolId |
|------|------|---------|--------|
| 看**某个具体池**的记录 | `crm page pool/lead` 或 `crm page pool/account` | `/pool/{module}/page` | **必传**：payload 顶层非空字符串，值来自已锁定模块 options 的目标池 id |
| **跨池按关键词搜** | `crm search pool/lead` 或 `crm search pool/account` | `/global/search/clue_pool` 或 `/global/search/customer_pool` | **不得传**，但必须传非空字符串 `keyword` |

`poolId` 缺失、为空、传成 JSON 数字、写成 `poolid`、放进 `combineSearch`/conditions，CLI 都会在 sync/联网前拒绝并给出 options 命令和正确模板。不得绕过为 raw `/pool/{module}/page`。

## 3. 典型场景

| 用户说 | 做法 |
|------|------|
| "东区线索池" / "东区线索公海" | `raw GET /pool/lead/options` → 只在线索池 options 中按 name 匹配"东区" → `crm page pool/lead`，顶层 `poolId` |
| "东区客户公海" | `raw GET /pool/account/options` → 只在客户公海 options 中匹配 → `crm page pool/account`，顶层 `poolId` |
| "东区公海" | 无线索上下文按客户公海；上下文明确为线索时按线索公海。锁定后只查对应 options |
| "看看线索（含公海）" | 只用 `pool/lead`；先列 options，再按每个目标 poolId 分别 page |
| "公海有哪些" | 无上下文时只用 `pool/account`；先列 options，再按每个 poolId 分别 page |
| "看看我的线索私海" | `crm page lead` + `viewId:SELF`，不是 pool 查询 |

```bash
cordys.sh raw GET /pool/lead/options
cordys.sh crm page pool/lead '{"poolId":"<线索池ID>","current":1,"pageSize":30,"sort":{"createTime":"desc"}}'
cordys.sh crm search pool/account '{"keyword":"华星","current":1,"pageSize":10}'
```

## 4. 输出标签

- `pool/lead` 的结果写"线索池"或"线索公海"，不能只写容易误解的裸"公海"。
- `pool/account` 的结果写"客户公海"，上下文明确时可简称"公海"。
- 私海触发的普通 `lead` 查询写"线索私海（线索模块）"，普通 `account` 查询写"客户私海（客户模块）"；不得把 `pool/*` 标成私海，也不得暗示存在独立的私海池或 `poolId`。
- 两个模块的结果不得混为一类。

## 5. 工具区分

查询用 `crm page` / `crm search pool/...`；`cordys_ext.sh pool` 只做 pick / assign / to-pool 等**写**操作（流程与确认见 `core/write-engine.md` §6），不用于查询。
