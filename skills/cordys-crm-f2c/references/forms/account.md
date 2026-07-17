# 客户创建参考

## 必填字段清单

<!-- AUTO-GENERATED-START -->
| # | 字段 | JSON 键名 | 格式 |
|---|------|----------|------|
| 1 | 客户名 | 客户名 | 文本 |
| 2 | 区域 | 区域 | SELECT |
| 3 | 行业 | 行业 | SELECT |
| 4 | 客户来源 | 客户来源 | SELECT |
| 5 | 类型 | 类型 | SELECT |
| 6 | 线上来源详情 | 线上来源详情 | SELECT |
| 7 | 省市 | 省市 | LOCATION |

选填：客户标签、分级、国家


## 表单 SELECT 字段可选值

> **创建和查询都传 ID**：标注「传 ID」的字段，中文与 ID 不一致，必须填 `=` 右侧的 ID（填中文会静默失败——创建写空、查询返回空）；未标注的字段中文即 ID，直接传中文即可。
> 创建时 SELECT 字段放 `moduleFields` 的 `fieldValue`、产品放 `products`；查询时放 `combineSearch.conditions` 的 `value`。

> 本节只列自定义表单字段；系统/API 的 SELECT 字段以“查询字段参考”为准。

- **区域**（传 ID）：东区=东区, 北区=北区, 南区=南区, KA=KA, 凌霞软件=175464961933400000, 培训认证中心=176878871530500000
- **行业**（传 ID）：银行=银行, 非银金融（证券、基金、保险、期货‌、信托、资管、租赁等）=非银金融（证券、基金、保险等）, 制造=制造, 交通和物流=交通和物流, 零售和服务（酒店、连锁、餐饮、快销等）=零售和服务（酒店、连锁、餐饮、快销等）, 高科技和互联网=高科技和互联网, 媒体（报业、广电等）=媒体（报业、广电等）, 通信（运营商）=通信（运营商）, 建筑和房地产=建筑和房地产, 能源和电力=能源和电力, 政府和军工=政府和军工, 教育=教育, 医疗（医药、医院、医学检测等）=医疗（医药、医院、医学检测等）, 公共事业（燃气、水务等）=公共事业（燃气、水务等）
- **客户来源**（传 ID）：线上=Advertisement, 多期续费、维保、扩容、增购=二期及续费, 交叉销售=增购和交叉销售, 线下-员工发掘（新客户）=Employee Referral, 线下-合作伙伴=Partner, 线下-客户推荐=Customer Referral, 线下-赞助会议=Sponsored Meeting, 线下-自办会议=Self-hosted Meeting
- **类型**（传 ID）：最终客户=Customer, 代理商=Partner
- **线上来源详情**（传 ID）：线下不涉及=线下不涉及, 400电话=400电话, 企业版试用=企业版试用, 技术咨询=技术咨询, 安装包下载=安装包下载, 网页购买咨询=网页购买咨询, 预约演示=预约演示, 社区交流群=社区交流群, 解决方案咨询=解决方案咨询, 招标信息=175565598367100000, 邮件=邮件, 培训=培训, 网络空间测绘=网络空间测绘, 阿里云市场=阿里云市场, AWS 云市场=175464200938400000, 凌霞开票用户=175464202341700000, Cloud来源=Cloud来源
- **分级**（传 ID）：战略客户=Hot, 重要客户=Warm, 一般客户=Cold


## 查询字段参考

> 用于 `combineSearch.conditions` 的 `name` 值。有 businessKey 的用 businessKey，否则用 fieldId。操作符规则见 `core/cli-reference.md`。

> “系统/API”字段可能不显示为自定义表单控件或“表单 SELECT 字段可选值”列表；只要列在本表中，即可作为 conditions 的字段依据。

| 字段 | name（条件用） | type | 来源 |
|------|--------------|------|------|
| createTime | createTime | DATE_TIME | 系统/API |
| updateTime | updateTime | DATE_TIME | 系统/API |
| departmentId | departmentId | DEPARTMENT | 系统/API |
| owner | owner | MEMBER | 系统/API |
| follower | follower | MEMBER | 系统/API |
| followTime | followTime | DATE_TIME | 系统/API |
| latestFollowUpTime | latestFollowUpTime | DATE_TIME | 系统/API |
| reasonId | reasonId | MEMBER | 系统/API |
| 客户名 | name | INPUT | 表单 |
| 区域 | 1751888184000009 | SELECT | 表单 |
| 行业 | 1751888184000005 | SELECT | 表单 |
| 客户来源 | 1751888184000006 | SELECT | 表单 |
| 类型 | 1751888184000007 | SELECT | 表单 |
| 线上来源详情 | 1751888184000008 | SELECT | 表单 |
| 客户标签 | 176335018842400000 | INPUT_MULTIPLE | 表单 |
| 分级 | 1751888184000004 | SELECT | 表单 |
| 省市 | 1751888184000011 | LOCATION | 表单 |
| 国家 | 177684248426900000 | LOCATION | 表单 |

## 视图目录

> `viewId` 按模块选择。官方内置视图由 Cordys 前端定义；实例自定义视图由 `sync` 从对应 `/view/list` 自动刷新。
> 自定义视图只在用户明确引用视图时使用；未明确引用时按角色基础范围查询。视图不能扩大当前角色的数据范围。

### 官方内置视图

| 视图名称 | viewId |
|----------|--------|
| 所有客户 | `ALL` |
| 我的客户 | `SELF` |
| 部门客户 | `DEPARTMENT` |
| 协作客户 | `CUSTOMER_COLLABORATION` |

### 实例自定义视图（自动同步）

| 视图名称 | viewId | 启用 | 固定 |
|----------|--------|------|------|
| — | — | — | — |
<!-- AUTO-GENERATED-END -->

## 字段业务术语

> 查询字段的取值/用法补充（人工维护，位于自动生成区块外，`sync` 不会覆盖）。

| 字段 | 业务术语 / 用法 |
|------|----------------|
| 负责人（owner） | 我的/某人的客户，值填 userId |
| reasonId | 放入公海原因操作人（系统字段，一般不用于查询） |


> `owner`：创建免传（系统自动设为当前用户）；查询填 userId 过滤指定人，但查他人受角色权限约束（见 `profiles/*.md`）。

## 查重规则

统一执行 `cordys_ext.sh check`（流程见 `SKILL.md` 和 `sop/duplicate-check.md`）：用客户名和手机号并行搜索线索、线索池、客户、公海、商机、联系人 6 个分类；任一分类查到记录就提示可能存在冲突，不按产品细分。不得自行拆成 6 条查询命令。

## 默认值

- 类型：默认"最终客户"（可选值：最终客户 / 代理商），用户未指定用默认，展示确认时可改
- 线上来源详情：客户来源为"线下"开头时填 `线下不涉及`

## DATA_SOURCE 字段

无（客户不需要解析 ID）

## 创建命令

命令：`cordys.sh crm create account '<JSON>'`（body 双层结构，见 `core/write-engine.md` §0.4）

**要填的字段（中文示意）**：客户名、客户来源=线上、线上来源详情=400电话、区域=东区、行业=高科技和互联网、类型=最终客户、省市=3301-

构建 body 时：客户名→`name` 放顶层；其余（区域/行业/客户来源/线上来源详情/类型/省市）放 `moduleFields`，fieldId 见上方「查询字段参考」表、选项 value 见「SELECT 字段可选值」表。不传 owner。

```bash
cordys.sh crm create account '{"name":"千里眼科技","moduleFields":[{"fieldId":"1751888184000009","fieldValue":"东区"},{"fieldId":"1751888184000005","fieldValue":"<行业选项ID>"},{"fieldId":"1751888184000006","fieldValue":"<客户来源选项ID>"},{"fieldId":"1751888184000007","fieldValue":"最终客户"},{"fieldId":"1751888184000008","fieldValue":"400电话"},{"fieldId":"1751888184000011","fieldValue":"3301-"}]}'
```

## 完整示例

**用户**："帮我创建一个客户，千里眼科技，杭州的，来源是线上 400 电话"

**步骤 1** — 提取 + 推断：
- 客户名=千里眼科技，来源=线上，详情=400电话
- 省市=3301-（杭州，`cordys_ext.sh loc 杭州` 得到）
- 区域：浙江 → 东区（推断）
- 行业：含"科技" → 高科技和互联网（推断）
- 类型：最终客户（默认，确认时可改）
- 缺失：无

**步骤 2** — 查重（按 `sop/duplicate-check.md` 执行）：6 个分类均无记录 → 未查到相关记录，继续

**步骤 3** — 无 DATA_SOURCE 字段，跳过

**步骤 4** — 校验：全部齐全 ✓

**步骤 5** — 创建（不传 owner；客户名顶层、其余进 moduleFields，fieldId/选项value 见上方字段表）：
```bash
cordys.sh crm create account '{"name":"千里眼科技","moduleFields":[{"fieldId":"1751888184000009","fieldValue":"东区"},{"fieldId":"1751888184000005","fieldValue":"<行业选项ID>"},{"fieldId":"1751888184000006","fieldValue":"<客户来源选项ID>"},{"fieldId":"1751888184000007","fieldValue":"最终客户"},{"fieldId":"1751888184000008","fieldValue":"400电话"},{"fieldId":"1751888184000011","fieldValue":"3301-"}]}'
```
返回：`{"code":100200,"data":{"id":"370020872889004032","name":"千里眼科技"}}`

**回复**："客户创建成功！客户名：千里眼科技，ID：370020872889004032"
