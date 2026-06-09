# 销售经理角色配置

> 匹配规则见 core/role-engine.md

## 意图路由

> 写操作（查重/创建/转换/跟进/打卡）规则与销售角色一致；查询类意图按本角色「默认查询偏好」走团队视角。

| 用户意图 | 动作 | 参考文档 |
|---------|------|---------|
| "查一下 xxx" / "查重 xxx" / "有没有 xxx" | `cordys_ext.sh check '{"客户名":"xxx","产品":[...]}'` | `sop/duplicate-check.md` |
| "创建线索/客户/商机/联系人" | 执行创建 5 步流程 | `sop/write-flow.md` + `references/forms/{module}.md` |
| "转客户" / "转换线索" | `cordys_ext.sh transform '<JSON>'` | `sop/transform.md` |
| "拜访xx" / "跟进xx" / "记录一下xx" / "xx聊了产品" | 搜索 CRM → 写跟进 → 拜访打卡 | `sop/visit-flow.md` |
| "打卡" / "签到" / "上班" / "到公司" | 创建打卡链接 | `sop/company-checkin-flow.md` |

> **拜访/跟进意图细分**：含"拜访"→拜访打卡（走完整流程）；含"跟进""记录""聊了"但不含"拜访"→纯跟进（写完即结束）。详见 `sop/visit-flow.md` 开头。

> **查重参数构建**：用户输入中如果包含产品名或产品简称（JS/JMS=JumpServer、MK=MaxKB、MS=MeterSphere、DE=DataEase 等，完整映射见 `sop/inference-rules.md`），必须识别出来放入 `产品` 字段，不要当作客户名。示例："查一下赛摩智能和 JS" → `{"客户名":"赛摩智能","产品":["JumpServer 企业版"]}`
>
> **参数校验**：查重必须有明确的客户名或手机号。如果用户提供的信息中没有公司名称也没有手机号（如"未告知公司名称"），不得用城市名、产品名或其他信息替代，应直接告知用户"信息不足，无法查重，请补充公司名或联系电话"。

> **意图区分**：用户说"查一下 xxx"默认走查重（cordys_ext.sh check），而非 cli-spec.md §12 的全局模糊搜索。只有明确说"搜索 xxx 的线索/客户/商机"或"看团队/部门 xxx"等指定查询时，才走 cordys.sh crm search/page（团队场景套用下方「默认查询偏好」）。

## 核心关注
- **团队看板**：部门线索总量、商机漏斗、签约进度
- **成员执行力**：跟进覆盖率、转化率、排名
- **目标达成**：团队目标进度、个人排名对比
- **风险巡检**：长期未跟进客户、商机卡点、团队短板
- **数据下钻**：从团队概览 → 个人详情 → 具体记录
- **审批管理**：团队成员的待审批、审批效率、驳回情况

## 默认查询偏好
| 场景 | 推荐命令 |
|------|---------|
| 团队线索总览 | `crm page lead '{"combineSearch":{"searchMode":"AND","conditions":[{"value":"{departmentId}","operator":"IN","name":"departmentId","multipleValue":false,"type":"TREE_SELECT"}]}}'` |
| 团队商机漏斗 | `crm page opportunity '{"combineSearch":{"searchMode":"AND","conditions":[{"value":"{departmentId}","operator":"IN","name":"departmentId","multipleValue":false,"type":"TREE_SELECT"}]}}'` |
| 部门组织架构 | `crm org` |
| 部门成员列表 | `crm members '{"departmentId":"{departmentId}"}'` |
| 团队成员跟进情况 | `crm follow plan lead '{"status":"ALL","myPlan":false}'` + 遍历成员 |
| 本月签约合同 | `crm search contract '{"combineSearch":{"conditions":[{"operator":"DYNAMICS","name":"signTime","value":"MONTH","type":"TIME_RANGE_PICKER"}]}}'` |
| 本月开放商机（结束日期在本月，未赢单未输单） | `crm page opportunity '{"viewId":"ALL","combineSearch":{"searchMode":"AND","conditions":[{"operator":"DYNAMICS","name":"expectedEndTime","value":"MONTH","type":"TIME_RANGE_PICKER"},{"operator":"NOT_EQUALS","name":"stage","value":"SUCCESS"},{"operator":"NOT_EQUALS","name":"stage","value":"FAIL"}]}}'` |
| 本月赢单商机（实际成交时间在本月） | `crm page opportunity '{"viewId":"ALL","combineSearch":{"searchMode":"AND","conditions":[{"operator":"DYNAMICS","name":"actualEndTime","value":"MONTH","type":"TIME_RANGE_PICKER"},{"operator":"EQUALS","name":"stage","value":"SUCCESS"}]}}'` |
| 某成员今年赢单（替换 ownerId） | `crm page opportunity '{"viewId":"ALL","combineSearch":{"searchMode":"AND","conditions":[{"operator":"DYNAMICS","name":"actualEndTime","value":"YEAR","type":"TIME_RANGE_PICKER"},{"operator":"EQUALS","name":"stage","value":"SUCCESS"},{"operator":"EQUALS","name":"ownerId","value":"{userId}"}]}}'` |

> **注意**：`{departmentId}` 是占位符，实际运行时 AI 会调用 `crm org` 获取组织架构树，递归展开所有子部门，替换为部门ID数组，详见 cli-spec.md 第10节「部门组织架构展开」。
>
> `{userId}` 是成员的用户 ID。获取方式：先调 `crm org` 定位该成员所在部门，再调 `crm members '{"departmentIds":["{departmentId}"]}'` 从返回列表中匹配姓名取 `id` 字段值。

## 交互模式
- **默认输出**：团队层面统计优先，附个人排名，允许下钻到个人
- **数据深度**：团队全貌 → 个人详情，提供多层下钻路径
- **提醒风格**：关注结构性问题和团队整体风险
- **行动建议**：定位到具体成员和具体问题，给出管理决策建议

## 异常预警
详见核心引擎 [risk-engine.md §3 经理预警](../core/risk-engine.md)、[risk-engine.md §5 审批预警](../core/risk-engine.md#5-审批相关预警)
