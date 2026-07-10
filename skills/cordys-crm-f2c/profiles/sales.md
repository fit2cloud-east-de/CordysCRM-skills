# 销售角色配置

> 匹配规则见 core/role-engine.md

## 目录

- [意图路由](#意图路由)
- [流程概要](#流程概要)
- [核心关注](#核心关注)
- [默认查询偏好](#默认查询偏好)
- [L2C 典型工作流](#l2c-典型工作流)
- [交互模式](#交互模式)
- [异常预警](#异常预警)

## 意图路由

| 用户意图 | 动作 | 参考文档 |
|---------|------|---------|
| "查一下 xxx" / "查重 xxx" / "有没有 xxx" | `cordys_ext.sh check '{"客户名":"xxx","产品":[...]}'` | `sop/duplicate-check.md`（**展示必须按该文档模板：6 分类表格+判断结果，禁止替换成摘要或自定义表格，禁止追加总结/评价段落**） |
| "看看 xxx 公司" / "看看 xxx"（上下文明确是公司，且未带产品简称） | 执行 Customer 360，不走查重 | `core/linkage-engine.md` §3.2 + 本文 日常 §客户深耕 |
| "创建线索/客户/商机/联系人" | 执行创建 5 步流程 | `core/write-engine.md` + `references/forms/{module}.md` |
| "更新/修改/改一下 xxx" / "把 xxx 改成 yyy" | 定位记录 → 展示原值→新值对比 → 确认后 `cordys.sh crm update <module> '<JSON>'`（JSON 含 id + 只需要改的字段，脚本自动读回合并保全其余） | `core/write-engine.md` §更新 |
| "批量修改/把这几条都改成 xxx" | 圈定记录 → 确认范围+字段 → `cordys.sh crm batch-update` 或循环 `update` | `core/write-engine.md` §批量更新 |
| "领取线索/客户" / "从公海/线索池捞 xxx" | `crm page pool/lead` 定位 → `raw GET /pool/lead/options` 拿 poolId → 确认 → `cordys_ext.sh pool pick` | `core/write-engine.md` §公海/线索池操作 |
| "把 xxx 退回公海/线索池" | 定位记录 → 确认 → `cordys_ext.sh pool to-pool` | `core/write-engine.md` §公海/线索池操作 |
| "转客户" / "转换线索" / "转商机" / "转客户并建商机" | `cordys_ext.sh transform '<JSON>'`（传中文字段，多步自动补全；"转商机/并建商机"=同时建商机，"只转客户"=仅转客户，未提则问一次） | `core/write-engine.md` §线索转化 |
| "拜访xx" / "跟进xx" / "记录一下xx" / "xx聊了产品" | 搜索 CRM → 写跟进 → 拜访打卡 | `sop/visit-flow.md` |
| "下次/下周跟进xx" / "给xx排个跟进计划" / "预约回访xx" / "计划x号联系xx" | `crm search` 带 `viewId:SELF` 定位本人记录取 id → 写跟进计划 `cordys_ext.sh follow-plan` | `references/forms/follow-plan.md` |
| "打卡" / "签到" / "上班" / "到公司" | 创建打卡链接 | `sop/company-checkin-flow.md` |

> **拜访/跟进意图细分**：含"拜访"→拜访打卡（走完整流程）；含"跟进""记录""聊了"但不含"拜访"→纯跟进（写完即结束）。详见 `sop/visit-flow.md` 开头。

> **查重参数构建**：识别输入中的产品名/简称（JS/JMS=JumpServer、MK=MaxKB、MS=MeterSphere、DE=DataEase 等，完整映射见 `sop/inference-rules.md`），放入 `产品` 字段而非客户名。例："查一下赛摩智能和 JS" → `{"客户名":"赛摩智能","产品":["JumpServer 企业版"]}`。
>
> **「的」消歧**：「X 的 JS」「X 的 MK 情况」与「X 和 JS」**等价，都走查重**，简称进 `产品` 字段，不要因"的"误判为下钻。仅当「的」后接**业务对象模块词**（商机/合同/订单/联系人/回款/开票）才走 Customer-360 下钻（定位 account → `cordys.sh crm acct-sub`，见 `core/linkage-engine.md`）。
>
> **参数校验**：查重必须有客户名或手机号。二者皆无时（如"未告知公司名称"）不得用城市名/产品名替代，直接告知"信息不足，无法查重，请补充公司名或联系电话"。

> **意图区分**：用户说"看看 xxx 公司"或上下文明确公司对象的"看看 xxx"，且**未带产品简称**时，唯一走 Customer 360；用户说"查一下 xxx"、"看看 xxx 公司的 JS/MK"，或**直接甩一个手机号/公司名/人名**，默认走查重（`cordys_ext.sh check`，手机号进 `手机`），而非 cli-spec §12 全局模糊搜索。只有明确说"搜索 xxx 的线索/客户/商机"等指定模块查询时，才走 `cordys.sh crm search/page`。此规则所有角色通用，见 `SKILL.md`「Customer 360 vs 查重 vs 搜索」。
>
> **查重不是范围授权**：`check` 只按 `sop/duplicate-check.md` 输出创建前的冲突判断，不得借“全部/所有人/全公司”把它改造成他人明细、团队列表或全量导出。

## 流程概要

### 创建流程

创建线索/客户/商机/联系人统一遵循 5 步流程（详见 `core/write-engine.md`）：

1. **提取 + 推断** — 从用户输入提取字段，应用 `sop/inference-rules.md` 自动补充
2. **查重** — 调用 `cordys_ext.sh check`，根据结果决定是否继续
3. **解析关联 ID** — 商机/联系人需解析所属客户/联系人 ID
4. **校验必填** — 对照 `references/forms/{module}.md` 检查必填字段
5. **创建** — 调用 `cordys.sh crm create <module> '<JSON>'`（body 双层结构、不传 owner、SELECT 传选项ID，见 `core/write-engine.md` §0.4）

### 拜访跟进

用户提到"拜访""跟进"某公司时，执行拜访跟进流程（详见 `sop/visit-flow.md`）：

1. **提取信息** — 从用户输入提取 customer_name、checkin_type、followMethod、crm_type_hint、extracted_fields（AI 语义识别的联系人/产品等）、用户业务描述
2. **搜索定位** — `cordys.sh crm search` 带 `viewId:SELF` 并行搜 lead/account/opportunity，按商机>线索>客户优先级选取
3. **写跟进** — `cordys_ext.sh follow '<JSON>'`，字段定义见 `references/forms/follow.md`，跟进方式映射见 `references/mappings/follow-method.md`
4. **打卡卡片**（仅拜访意图）— 调打卡 API 发卡片，API 详情见 `references/checkin-api.md`；纯跟进意图写完即结束，不打卡

> **路径区分**：拜访意图走完整步骤1-4；纯跟进意图只走步骤1-3，写完跟进即结束。
>
> **企业微信限制**：打卡卡片仅在企业微信环境下发送（上下文有企业微信 userid 时）。非企业微信环境只写跟进，提示"请在企业微信中发起打卡"。

### 跟进计划录入

用户表达"后续/下次要做的跟进"（如"下周电话回访 xx""给 xx 排个跟进计划""预约 x 号拜访 xx"）时，录入跟进计划（区别于上面记录**已发生**的跟进）：

1. **提取信息** — customer_name、计划时间（→ estimatedTime）、跟进方式、计划内容
2. **搜索定位** — `cordys.sh crm search account/lead/opportunity` 均带 `viewId:SELF` 取本人记录 id（按商机>线索>客户选取）。**用 search 不用 check**：定位已知对象一次调用即拿 id，check 是查重专用、又慢又文不对题（若本轮前面刚 check 过且结果含本人目标 id，直接复用免再查）
3. **写计划** — `cordys_ext.sh follow-plan '<JSON>'`，字段定义见 `references/forms/follow-plan.md`，跟进方式映射见 `references/mappings/follow-method.md`

> ⚠️ 跟进**计划**用 `follow-plan`（字段 `estimatedTime`/`method`），跟进**记录**用 `follow`（字段 `followTime`/`followMethod`），两者字段名和跟进方式选项 ID 都不同，勿混用。计划无需打卡。

### 公司打卡

用户说"打卡""签到"时，执行公司打卡流程（详见 `sop/company-checkin-flow.md`）：直接调打卡 API 创建链接，不涉及 CRM。

## 核心关注
- **我的线索**：待跟进、今日新增、即将超时
- **我的商机**：推进中、即将赢单、卡住需要推动
- **我的客户**：近期活跃、需要回访、跟进记录
- **今日计划**：今日跟进计划提醒
- **我的业绩**：合同签约、目标进度

## 默认查询偏好
| 场景 | 推荐命令 |
|------|---------|
| 查看今天的跟进计划 | `crm follow plan lead '{"myPlan":true,"status":"UNFINISHED","sourceId":"..."}'` |
| 查看我的线索列表 | `crm page lead '{"viewId":"SELF"}'` |
| 查看我的待办商机 | `crm page opportunity '{"viewId":"SELF","combineSearch":{"searchMode":"AND","conditions":[{"operator":"NOT_IN","name":"stage","value":["SUCCESS","FAIL"],"type":"SELECT"}]}}'`（待办=未赢未输的开放商机） |
| 查看我的客户 | `crm page account '{"viewId":"SELF"}'`（按负责人 `owner` 判定归属，勿用 `follower`；owner/follower 区分见 `core/cli-spec.md` §2.4） |
| 查看今日新增线索 | `crm search lead '{"viewId":"SELF","combineSearch":{"conditions":[{"operator":"DYNAMICS","name":"createTime","value":"TODAY","type":"TIME_RANGE_PICKER"}]}}'` |
| 查看我的签约 | `crm page contract '{"viewId":"SELF","combineSearch":{"conditions":[{"operator":"DYNAMICS","name":"signTime","value":"MONTH","type":"TIME_RANGE_PICKER"}]}}'` |

## L2C 典型工作流

### 日常

#### 晨会速览（"看看今天"）
```
执行流程：
  1. cordys.sh crm follow plan lead '{"myPlan":true,"status":"UNFINISHED"}'
     → 今日跟进计划
  2. cordys.sh crm search lead '{"viewId":"SELF","combineSearch":{"conditions":[
       {"value":"TODAY","operator":"DYNAMICS","name":"createTime","type":"TIME_RANGE_PICKER"}
     ]}}'
     → 今日新增线索
  3. cordys.sh crm page lead '{"viewId":"SELF"}'
     → 我的线索列表（提取总数、检查风险）
输出：今日计划 + 最新线索 + 风险提醒
```

#### 跟进优先级排序（"哪些要先跟"）
```
排序规则（按紧急度降序）：
  1. 🚨 超过 7 天未跟进的线索/商机
  2. ⚠️  商机在某个阶段停留超过 7 天
  3. 📋 今日跟进计划中的待办
  4. 🟢 近 3 天新创建的线索

执行：
  1. cordys.sh crm page lead '{"viewId":"SELF","sort":{"followTime":"asc"}}'
     → 按跟进时间升序，最久未跟的排前面
  2. cordys.sh crm page opportunity '{"viewId":"SELF","sort":{"followTime":"asc"}}'
```

#### 客户深耕（"看看XX公司"）

> **唯一触发路由**："看看 XX 公司"或上下文明确公司对象的"看看 XX"，只要未带产品简称，就直接执行本节 Customer 360，不得改走 `check` 查重。

```
执行：
  1. 带 `viewId:SELF` 搜索本人客户并取得 account ID；未命中即停止，不扩大到 ALL
  2. 客户360：名下商机、合同、回款、联系人
  3. 跟进历史：最近 5 条跟进记录
  4. 关联线索（如果有）
输出：公司全景视图
```

### 周常

#### 周回顾（"这周怎么样"）
```
执行流程：
  1. 本周新增线索数（DYNAMICS WEEK）
  2. 本周新增商机数 + 金额汇总
  3. 本周签约合同数 + 金额汇总
  4. 超期未跟进线索（followTime < 3天前）
输出：漏斗快照 + 跟进行为 + 签约成果
```

#### 管线检查（"我的商机怎么样"）
```
执行：
  1. cordys.sh crm page opportunity '{"viewId":"SELF"}'
     → 按阶段分组统计
  2. 识别卡点商机（在阶段停留 > 7 天）
  3. 汇总各阶段金额
输出：阶段分布 + 卡点商机 + 金额预测
```

### 月常

#### 月度总结（"本月做了多少"）
```
执行流程：
  1. 本月新增线索/商机数 + 环比
  2. 本月签约合同数 + 金额
  3. 本月回款金额
  4. 下月预测（当前进行中商机金额 × 赢单率）
输出：月度漏斗 + 签约成果 + 下月预测
```

#### 链路回查（"查查这笔单子"）
> 完整流程见 `core/linkage-engine.md` §3.3 合同全线追踪

> **查询范围边界（不可覆盖）**：销售角色只能查本人名下的线索、客户、商机和联系人。lead/account/opportunity 优先用 `viewId:SELF`（或 `owner=当前用户 userId`）；contact 必须用 `owner=当前用户 userId`。**不得使用 `viewId:ALL`、`searchType:ALL`、他人 userId 或无 owner 的全量查询，也不得去 `crm members` 查别人。**
>
> 用户说“全部”“所有人”“全公司”“全部门”或指定同事，**不能覆盖上述范围**，也不能删除 SELF/owner 条件。当用户要求查别人或团队数据时，不构造查询，直接回复：「我这边只能查询你本人名下的数据。查看团队或其他成员的数据需要销售经理权限，可以让对应的经理来查，或联系管理员调整权限。」

> `{userId}` 取自 Cordys.md 中的用户 ID（whoami 返回的 `data.userId`）。

| 场景 | 推荐命令 |
|------|---------|
| 我的赢单/输单商机 | `crm page opportunity '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"<时间操作符>","name":"expectedEndTime","value":"<时间值>","type":"<时间类型>"},{"operator":"IN","name":"stage","value":["<SUCCESS 或 FAIL>"],"type":"SELECT"},{"operator":"IN","name":"owner","value":["{userId}"],"type":"MEMBER"}]}}'` |
| 我的开放商机 | `crm page opportunity '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"<时间操作符>","name":"expectedEndTime","value":"<时间值>","type":"<时间类型>"},{"operator":"NOT_IN","name":"stage","value":["SUCCESS","FAIL"],"type":"SELECT"},{"operator":"IN","name":"owner","value":["{userId}"],"type":"MEMBER"}]}}'` |
| 我的线索 | `crm page lead '{"combineSearch":{"searchMode":"AND","conditions":[{"operator":"<时间操作符>","name":"createTime","value":"<时间值>","type":"<时间类型>"},{"operator":"IN","name":"owner","value":["{userId}"],"type":"MEMBER"}]}}'` |

> 组合规则：结果口径（赢单=SUCCESS 等）与时间字段见 `references/forms/{module}.md`，时间过滤写法见 `core/cli-spec.md §5.4`，聚合做法见 `core/cli-spec.md §10`。销售角色的 SELF/当前 owner 是最高优先级强制条件，任何用户措辞都不得删除或改为 ALL。

## 交互模式
- **默认输出**：列表优先，摘要展示，辅以关键状态 emoji
- **数据深度**：仅查看本人范围；团队或他人数据必须切换为具备权限的经理角色处理
- **提醒风格**：主动提醒跟进超时、线索积压、商机停滞
- **行动建议**：具体到"联系谁、做什么、优先级"

## 异常预警
详见核心引擎 [risk-engine.md §2 销售预警](../core/risk-engine.md)
