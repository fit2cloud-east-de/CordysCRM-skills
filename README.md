# Cordys CRM Skill

<p align="center">
  <br/>
  <em><strong>你的专属 AI 助手，告别在传统页面上点来点去</strong></em>
  <br/>
  <em>角色感知 &nbsp;·&nbsp; 管道原生 &nbsp;·&nbsp; 默认零信任</em>
  <br/><br/>
</p>

---

## 同一个 CRM，不同的人看到不同的世界

同一个系统。同一份数据。同一个问题：*"看看线索"*

销售听到的是**待办优先级**。经理看到的是**团队健康仪表盘**。财务得到的是**资金回笼全景**。

Cordys CRM Skill 不是给 CRM 加一层界面，而是加一层**智能**——它理解*谁*在问、*卡在* L2C 链路的哪个环节。它说人话，跨模块推理，在你开口问之前就告诉你哪里不对劲。

> **一行配置。** 填好 API 密钥，系统自动识别你的身份、匹配角色、激活对应的认知视角。不用搭仪表盘，不用存筛选器。

---

## 五个角色，五种视角

不是偏好设置。是系统在"展示什么、先展示什么、以什么紧迫度展示"这三个维度上的本质切换。

<table>
<tr>
<td width="20%" valign="top">

### 销售
```
关注： 我接下来该做什么？
范围： 我的客户/线索/商机
预警： 超期未跟、商机卡顿
输出： 优先级行动清单
```
</td>
<td width="20%" valign="top">

### 经理
```
关注： 谁需要我关注？
范围： 全部门 + 子团队
预警： 跟进率低、转化骤降
输出： 团队看板 → 下钻到人
```
</td>
<td width="20%" valign="top">

### 高管
```
关注： 公司能交多少？
范围： 全公司
预警： 目标缺口、部门偏离
输出： 趋势 → 对比 → 预测
```
</td>
<td width="20%" valign="top">

### 商务
```
关注： 合同签对了没有？
范围： 合同 + 审批流
预警： 到期未续、审批卡顿
输出： 合同状态 + 到期预警
```
</td>
<td width="20%" valign="top">

### 财务
```
关注： 钱在哪？
范围： 合同 → 回款 → 发票
预警： 逾期、未开票、链断裂
输出： 应收全景 → 催收排序
```
</td>
</tr>
</table>

---

## 架构

不是一个巨型提示词。是七个目标明确的**引擎晶格**，按需加载，通过共享上下文总线协同工作。

```mermaid
flowchart LR
    U(["💬 输入"]) --> GATE{"意图路由"}

    GATE -->|"查询"| QUERY["🔍 查询引擎"]
    GATE -->|"追踪"| LINK["🔗 链路引擎"]
    GATE -->|"漏斗"| FUNNEL["📊 漏斗引擎"]
    GATE -->|"意图"| FLOW["🗺️ 工作流引擎"]
    GATE -->|"审批"| APPR["✅ 审批管道"]

    QUERY --> ROLE{"🧠 角色透镜"}
    LINK --- ROLE
    FUNNEL --- ROLE
    FLOW --- ROLE
    APPR --- ROLE

    ROLE --> SL["👤 销售"]
    ROLE --> SM["👥 经理"]
    ROLE --> EX["🏢 高管"]
    ROLE --> CA["📋 商务"]
    ROLE --> FN["💰 财务"]

    SL --- RISK["⚠️ 风险引擎"]
    SM --- RISK
    EX --- RISK
    CA --- RISK
    FN --- RISK

    RISK --> FMT["🧾 输出引擎"]
    FMT --> OUT(["✨ 响应"])
```

**核心原则**：`role-engine.md` 是唯一启动必加载的引擎。其余全部按意图懒加载——保持上下文窗口精瘦。

---

## 七引擎晶格

| 引擎 | 激活信号 | 职责 |
|------|---------|------|
| **角色** | 会话启动 | 身份识别、角色匹配、人格绑定 |
| **CLI 规范** | 任何查询 | 自然语言 → `cordys.sh crm` 语义翻译 |
| **CLI 参考** | 复杂筛选条件 | 字段类型 → 操作符速查表 |
| **输出** | 每次响应 | JSON → 人类可读、角色自适应格式化 |
| **风险** | 数据展示后 | 单模块异常 + 跨模块链断裂检测 |
| **链路** | "查这笔单子" / "360视图" | L2C 正向追溯 / 反向溯源 |
| **漏斗** | "管道怎么样" / "转化率" | 多模块聚合、快照与趋势 |
| **工作流** | "今天做什么" | 模糊意图 → 结构化工作流 |

---

## L2C 管道 —— 从线索到现金，一气贯通

线索 → 客户 → 商机 → 报价 → 合同 → 订单 → 回款计划 → 回款记录 → 发票

```mermaid
flowchart LR
    L["🔹 线索"] -->|"转化"| A["🔹 客户"]
    A --> O["🔹 商机"]
    O --> Q["📄 报价"]
    O --> C["🔹 合同"]
    C --> OD["📦 订单"]
    C --> PP["💰 回款计划"]
    PP --> PR["💰 回款记录"]
    OD --> I["🧾 发票"]

    L -.- AL1["🟡 超30天"]
    O -.- AL2["🔴 无合同"]
    C -.- AL3["🔴 无计划"]
    I -.- AL4["🟡 未回款"]

    style AL1 fill:#fbbf24,stroke:none
    style AL2 fill:#ef4444,stroke:none
    style AL3 fill:#ef4444,stroke:none
    style AL4 fill:#fbbf24,stroke:none
```

每一个环节转换都是**可能的断裂点**。系统监控整条链路，在问题变成事故之前主动暴露——不只是单模块内，而是跨 L2C 全局。

### 链断裂检测示例

| 断裂场景 | 检测方式 | 严重度 |
|---------|---------|--------|
| 线索创建 > 30 天未转化 | 查线索无关联客户 | 🟡 警告 |
| 商机赢单 > 15 天无合同 | 赢单商机 vs 合同模块交叉比对 | 🔴 严重 |
| 合同签约无回款计划 | 合同 vs 回款计划交叉比对 | 🔴 严重 |
| 已开发票 > 90 天未回款 | 发票 vs 回款记录交叉比对 | 🔴 严重 |
| 客户 > 180 天无跟进 | 客户跟进记录时间交叉检查 | 🟡 警告 |

---

## 业务操作能力

除了查询和统计，技能还覆盖常见 CRM 写入、数据准备和打卡流程：

| 能力 | 入口 | 说明 |
|------|------|------|
| 查重 | `scripts/cordys_ext.sh check` | 创建前主动查重，避免重复线索/客户 |
| 创建 | `scripts/cordys_ext.sh create` | 支持线索、客户、商机、联系人创建 |
| 跟进 | `scripts/cordys_ext.sh follow` | 写入跟进记录，拜访打卡链路会复用返回 ID |
| 线索转客户 | `scripts/cordys_ext.sh transform` | 按 SOP 补字段并转换 |
| 省市转换 | `scripts/cordys_ext.sh loc` | 本地查询行政代码，避免全文读取 JSON |
| 部门展开 | `scripts/cordys_ext.sh dept-children` | 获取部门及所有子部门 ID |
| 字段同步 | `scripts/cordys_ext.sh sync` | 同步表单字段到 `references/forms/` |
| 打卡 | `scripts/checkin.sh` | 公司打卡、拜访打卡、webhook 回调 |

写入类动作遵循 `sop/write-flow.md`：除跟进记录外，创建、修改、删除前必须先展示字段并等待用户确认。

---

## 实际体验

### 销售 —— 晨会速览

```
> 今天有什么要跟的？

📋 今日跟进计划（3 项）
| 客户 | 内容 | 优先级 |
| YYY集团 | 确认需求 | 🚨 超期5天 |
| 华星科技 | 发送报价 | ⚠️ 今日到期 |
| ABC技术 | 初次联系 | 🟢 新线索 |

📊 我的管线：线索12 / 商机4（¥52万） / 签约1（¥12万）
💡 商机"XX项目"在需求确认阶段停留10天，建议推进
```

### 经理 —— 周会看板

```
> 团队这周怎么样？

📊 团队 L2C 漏斗（本周）
| 成员 | 新增线索 | 新增商机 | 签约 | 签约额 |
| 张三 | 8 | 2 | 1 | ¥12万 |
| 李四 | 5 | 1 | 0 ⚠️ | ¥0 |
| 王五 | 12 | 4 | 2 | ¥35万 🏆 |

🚨 李四本周签约为零，跟进率 40% < 团队均值 68%
📋 2 条待审批超过 3 天未处理
💡 建议 1v1 了解李四管线卡点
```

### 财务 —— 应收全景

```
> 欠款情况

💰 应收账款全景
汇总：总应收 ¥285万 | 已逾期 ¥45万 🚨 | 7天内到期 ¥62万 ⚠️

🚨 逾期回款（3 笔）
| 合同 | 客户 | 逾期 | 金额 |
| CRM-001 | 华星 | 15天 | ¥15万 |
| CRM-008 | 远航 | 32天 | ¥20万 |
| CRM-012 | 星辰 | 8天 | ¥10万 |

⚠️ 链断裂：2份签约合同未创建回款计划（¥55万）
```

### 创建线索 —— 写入流程

```
> 帮我创建一条线索，千里眼科技，李老师，13777788888，对 MeterSphere 企业版感兴趣

执行流程：
1. `scripts/cordys_ext.sh check` 查重
2. 读取 `references/forms/lead.md` 补齐必填字段
3. 表格展示待创建字段，等待用户确认
4. 用户确认后 `scripts/cordys_ext.sh create lead '<JSON>'`
```

---

## 安全姿态

| 原则 | 实现 |
|------|------|
| **默认零信任** | API 请求仅发往已配置的 `CORDYS_CRM_DOMAIN` |
| **凭证隔离** | 密钥存 `.env`，永不进版本控制，永不出现于输出 |
| **非信任域拦截** | 跨域请求默认拒绝，除非显式设 `CORDYS_ALLOW_UNTRUSTED=1` |
| **输出脱敏** | Access Key / Secret Key 在所有可见输出中自动剥离 |
| **最小权限兜底** | 角色匹配失败时降级为 `sales`（最受限视角） |
| **写入确认** | 创建、修改、删除前必须先展示字段并等待确认 |

---

## 快速开始

```bash
# Clawdhub 安装（推荐）
clawdhub install cordys-crm

# 手动安装
git clone --branch main https://github.com/1Panel-dev/CordysCRM-skills \
  ~/.openclaw/workspace/skills/CordysCRM-skills
mv ~/.openclaw/workspace/skills/CordysCRM-skills/skills \
  ~/.openclaw/workspace/skills/cordys-crm
rm -rf ~/.openclaw/workspace/skills/CordysCRM-skills
```

```bash
# 配置
vi ~/.openclaw/workspace/skills/cordys-crm/.env

# 必填
CORDYS_ACCESS_KEY=***
CORDYS_SECRET_KEY=***
CORDYS_CRM_DOMAIN=https://你的域名

# 业务操作与打卡使用
MAXKB_DOMAIN=http://你的业务服务地址
MAXKB_API_KEY=***
CHECKIN_API_URL=https://你的打卡服务地址
OPENCLAW_WEBHOOK_URL=http://你的打卡回调地址

# 可选：自定义角色映射
ROLE_MAP=总经理|副总裁|VP=executive,总监|经理=sales-manager,商务|合同管理=contract-admin,销售|顾问=sales,财务|会计|出纳=finance
```

---

## CLI 速查

```bash
# 主 CLI
scripts/cordys.sh crm whoami
scripts/cordys.sh crm verify
scripts/cordys.sh crm page lead '{"viewId":"SELF"}'
scripts/cordys.sh crm search account '{"keyword":"华星科技"}'
scripts/cordys.sh crm aggregate contract amount sum '{"combineSearch":{"conditions":[]}}'
scripts/cordys.sh crm stat contract '{"viewId":"ALL","combineSearch":{"conditions":[]}}'
scripts/cordys.sh crm stat-home lead '{"searchType":"SELF","timeField":"CREATE_TIME","userField":"OWNER","priorPeriodEnable":true}'
scripts/cordys.sh crm glocount 华星科技
scripts/cordys.sh crm acct-sub payment-record-stat ACCOUNT_ID
scripts/cordys.sh crm contract-sub invoice-stat CONTRACT_ID

# 扩展 CLI
scripts/cordys_ext.sh check '<JSON>'
scripts/cordys_ext.sh create lead '<JSON>'
scripts/cordys_ext.sh follow '<JSON>'
scripts/cordys_ext.sh transform '<JSON>'
scripts/cordys_ext.sh loc 杭州
scripts/cordys_ext.sh dept-children 苏皖线下团队

# 打卡 CLI
scripts/checkin.sh create-checkin '<JSON>'
scripts/checkin.sh submit-checkin '<JSON>'
```

---

## 仓库结构

```
CordysCRM-skills/
├── README.md
├── install.sh
├── tools/
│   ├── check_duplicate.py
│   ├── create_entity.py
│   ├── add_follow_record.py
│   ├── transform_lead.py
│   └── sync_forms.py
└── skills/
    ├── SKILL.md
    ├── registry.json
    ├── .env.example
    ├── Cordys.md                 # 运行时身份缓存（不提交）
    ├── core/
    │   ├── role-engine.md
    │   ├── cli-spec.md
    │   ├── cli-reference.md
    │   ├── output-engine.md
    │   ├── risk-engine.md
    │   ├── search-engine.md
    │   ├── stats-engine.md
    │   ├── linkage-engine.md
    │   ├── funnel-engine.md
    │   └── workflow-engine.md
    ├── profiles/
    │   ├── sales.md
    │   ├── sales-manager.md
    │   ├── executive.md
    │   ├── contract-admin.md
    │   └── finance.md
    ├── scripts/
    │   ├── cordys.sh             # Shell CLI（主路径）
    │   ├── cordys.py             # Python CLI（备用）
    │   ├── cordys_ext.sh         # 业务操作 CLI
    │   └── checkin.sh            # 打卡 CLI
    ├── sop/
    │   ├── write-flow.md
    │   ├── duplicate-check.md
    │   ├── transform.md
    │   ├── visit-flow.md
    │   ├── company-checkin-flow.md
    │   └── inference-rules.md
    └── references/
        ├── crm-api.md
        ├── checkin-api.md
        ├── forms/
        │   ├── lead.md
        │   ├── account.md
        │   ├── opportunity.md
        │   ├── contact.md
        │   ├── follow.md
        │   ├── contract.md
        │   └── payment-record.md
        └── mappings/
            ├── follow-method.md
            ├── industry-mapping.md
            ├── product-alias.md
            └── location_codes.json
```

---

## 设计思路

> **不是数据浏览器，是智能层。**

- **角色变形**：不问你是谁，自己判断。在说出第一个字之前，输出已经适配了你的角色。
- **管道原生**：L2C 不是"功能模块"，是系统的脊柱。每一次查询、每一次预警、每一条工作流，都锚定在这条链上。
- **引擎晶格**：多个精小引擎，各司其职。用到才加载，用不到不浪费注意力。
- **先于提问的预警**：风险检测是主动的。系统主动告诉你你没注意到的，而不是等你来问。
- **业务闭环**：覆盖查重、创建、转换、跟进、打卡、字段同步和本地映射能力。
- **无头设计**：轻量 CLI 调用 REST API。无 UI 依赖，可嵌入任何环境。
