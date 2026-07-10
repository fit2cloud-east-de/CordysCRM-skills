# 🧭 意图路由引擎

本文件定义 AI 如何**理解用户意图**并路由到正确的 engine、SOP 和角色差异。具体执行规则在对应权威文档中，profile 只提供范围、口径和输出偏好。

---

## 1. 意图识别与路由

AI 收到用户输入后，按以下优先级匹配：

```
用户输入
  ├─ 优先级 1：显式模块 + 操作（"查线索"、"创建客户"）→ 直接路由到 `core/cli-spec.md` 对应命令
  ├─ 优先级 2：模糊工作指令（"今天做什么"、"这周怎么样"）→ 查 §3 意图映射表，加载对应 engine + profile 差异
  ├─ 优先级 2.5：公司全景（"看看 XX 公司"，未带产品简称）→ Customer 360（`core/linkage-engine.md` §3.2）
  ├─ 优先级 3：查重/查询意图（"查一下/有没有/查查"、"看看 XX 公司的 JS/MK"，或直接给 公司名/手机号/人名）→ cordys_ext.sh check（**所有角色默认**，见 SKILL.md「Customer 360 vs 查重 vs 搜索」）
  ├─ 优先级 3.5：显式搜索（"搜一下/搜索/列出 XX"，未指定模块）→ 全局模糊搜索（`core/cli-spec.md` §12）
  ├─ 优先级 4：L2C 链路追踪（"查查这笔单子"、"XX公司全景"）→ 触发 `core/linkage-engine.md`
  └─ 优先级 5：无法识别 → 提示用户细化意图
```

---

## 2. 路由策略

| 路由层级 | 处理方式 |
|---------|---------|
| **显式命令** | 直接从 `core/cli-spec.md` 构造命令，不经过工作流引擎 |
| **模糊指令** | 匹配 §3 映射表 → 加载目标 engine/SOP + 对应 profile 差异 |
| **写操作** | 路由到 `core/write-engine.md`（创建/更新/批量/转化统一入口），先读表单定义再执行 |
| **链路追踪** | 路由到 `core/linkage-engine.md` |
| **漏斗分析** | 路由到 `core/funnel-engine.md` |

### 写操作路由

| 用户说 | 路由 |
|--------|------|
| 创建/新建/添加 + 模块名 | `core/write-engine.md` → 创建流程 |
| 修改/更新/编辑 + 模块名 | `core/write-engine.md` → 更新流程 |
| 批量修改/批量更新 | `core/write-engine.md` → 批量更新流程 |
| 线索转客户/线索转商机/转化 | `core/write-engine.md` → 转化流程 |

> 完整写操作流程见 `core/write-engine.md`（唯一权威写入文档）。

---

## 3. 意图 → 执行入口

| 用户说 | 加载与执行 |
|--------|------------|
| "今天做什么" / "有什么要跟的" / "先跟哪个" | `profiles/sales.md`「角色专属工作流配方」+ 查询/风险引擎 |
| "这周怎么样" / "周报" / "本月做了多少" | `profiles/sales.md`「角色专属工作流配方」+ `core/funnel-engine.md` + `core/output-engine.md` |
| "看看 XX 公司"（未带产品简称） | `core/linkage-engine.md` §3.2 + 当前 profile 范围 |
| "看看XX公司"（未带产品简称） | 同上，唯一走 Customer 360 |
| "团队今天/这周" / "部门概览/复盘/预测" | `profiles/sales-manager.md`「角色专属工作流配方」+ 强制部门范围 + `core/funnel-engine.md` |
| "团队问题" / "风险巡检" | `profiles/sales-manager.md` + `core/risk-engine.md` §3 |
| "公司情况" / "经营数据" / "目标怎么样" / "人效" / "Q2复盘" / "今年全年" | `profiles/executive.md`「角色专属工作流配方」+ `core/funnel-engine.md` |
| "今天回款" / "欠款/催款" / "开票" / "现金链路" / "财报" / "年度回款排名" | `profiles/finance.md`「角色专属工作流配方」+ 链路/统计引擎 |
| "审批到哪了" / "合同到期/续约" / "签约月报" / "下月到期合同" | `profiles/contract-admin.md`「角色专属工作流配方」+ 审批/查询规范 |
| "批一下" / "待审批" | `core/cli-spec.md` §13 + `core/cli-reference.md` §4 |
| "查查这笔单子" / "链路追踪" | `core/linkage-engine.md` |
| "查一下 XX" / "有没有 XX" / "看看 XX 公司的 JS/MK" / 直接给公司名·手机号·人名 | `cordys_ext.sh check`；消歧读 `sop/inference-rules.md` |
| "搜一下/搜索 XX"（未指定模块） | `core/cli-spec.md` §12 |
| 创建/更新/批量/转化/公海 | `core/write-engine.md` |
| 拜访/跟进/记录/计划 | `sop/visit-flow.md` |
