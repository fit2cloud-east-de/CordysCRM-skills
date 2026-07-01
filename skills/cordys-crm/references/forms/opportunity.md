# 商机创建参考

## 必填字段清单

<!-- AUTO-GENERATED-START -->

| # | 字段 | JSON 键名 | 格式 | 条件必填 |
|---|------|----------|------|---------|
| 1 | 商机名 | 商机名 | 文本 | — |
| 2 | 区域 | 区域 | SELECT | — |
| 3 | 产品类型(可多选) | 产品类型(可多选) | ⚠️ 实体 ID（可多选） | — |
| 4 | 客户名 | 客户名 | ⚠️ 实体 ID | — |
| 5 | 行业 | 行业 | SELECT | — |
| 6 | 来源 | 来源 | SELECT | — |
| 7 | 线上来源详情 | 线上来源详情 | SELECT | — |
| 8 | 关键决策人（KP） | 关键决策人（KP） | ⚠️ 实体 ID | — |
| 9 | 结束日期 | 结束日期 | YYYY-MM-DD | — |
| 10 | 金额 | 金额 | 数字 | — |
| 11 | 有效合同额 | 有效合同额 | 数字 | — |
| 12 | 签约类型 | 签约类型 | SELECT | 区域=东区 |
| 13 | 报备号/代签方名称 | 报备号/代签方名称 | 文本 | 签约类型=盟军报备签 / 非盟军报备签 / 商务平台代签 / 盟军代签 |
| 14 | 省市 | 省市 | LOCATION | 区域=凌霞软件 |

选填：最终用户工商全称、最终用户简称、纸质合同编码、可能性、国家


> 「条件必填」列非「—」的字段，仅当满足条件时才必填；不满足时可留空。


## SELECT 字段可选值

> **创建和查询都传 ID**：标注「传 ID」的字段，中文与 ID 不一致，必须填 `=` 右侧的 ID（填中文会静默失败——创建写空、查询返回空）；未标注的字段中文即 ID，直接传中文即可。
> 创建时 SELECT 字段放 `moduleFields` 的 `fieldValue`、产品放 `products`；查询时放 `combineSearch.conditions` 的 `value`。

- **区域**（传 ID）：东区=东区, 北区=北区, 南区=南区, KA=KA, 凌霞软件=175464963179500000, 培训认证中心=176878872228000000, 总部框架=177460307956800000
- **行业**（传 ID）：银行=银行, 非银金融（证券、基金、保险、期货‌、信托、资管、租赁等）=非银金融（证券、基金、保险等）, 制造=制造, 交通和物流=交通和物流, 零售和服务（酒店、连锁、餐饮、快销等）=零售和服务（酒店、连锁、餐饮、快销等）, 高科技和互联网=高科技和互联网, 媒体（报业、广电等）=媒体（报业、广电等）, 通信（运营商）=通信（运营商）, 建筑和房地产=建筑和房地产, 能源和电力=能源和电力, 政府和军工=政府和军工, 教育=教育, 医疗（医药、医院、医学检测等）=医疗（医药、医院、医学检测等）, 公共事业（燃气、水务等）=公共事业（燃气、水务等）
- **来源**（传 ID）：线上=Advertisement, 多期续费、维保、扩容、增购=二期及续费, 交叉销售=增购和交叉销售, 线下-员工发掘（新客户）=Employee Referral, 线下-合作伙伴=Partner, 线下-客户推荐=Customer Referral, 线下-赞助会议=Sponsored Meeting, 线下-自办会议=Self-hosted Meeting
- **线上来源详情**（传 ID）：线下不涉及=线下不涉及, 400电话=400电话, 企业版试用=企业版试用, 技术咨询=技术咨询, 安装包下载=安装包下载, 网页购买咨询=网页购买咨询, 预约演示=预约演示, 社区交流群=社区交流群, 解决方案咨询=解决方案咨询, 招标信息=175565602110800000, 邮件=邮件, 培训=培训, 网络空间测绘=网络空间测绘, 阿里云市场=阿里云市场, AWS 云市场=175456040136700000, 凌霞开票用户=175324083631400000, Cloud来源=Cloud来源
- **签约类型**（传 ID）：飞致云直签=176847297349200001, 商务平台代签=176847297349200002, 盟军代签=176975823877700000, 联合培养销售签=176881828167100000, 盟军报备签=176847297349300000, 非盟军报备签=177010696382400000
- **产品类型（可多选）**（传 ID）：JumpServer 企业版=1751888184000091, MaxKB 专业版=1751888184000102, MaxKB 企业版=8327632349528064, MaxKB 一体机=373302305212559360, DataEase 企业版=1751888184000101, DataEase 专业版=1751888184000092, DataEase 嵌入式版=1751888184000097, Cordys CRM 企业版=10034933389336576, SQLBot 专业版=8366853990875136, MeterSphere 企业版=1751888184000098, CloudExplorer 云管平台=1751888184000093, 1Panel AI 助理一体机=329298398169903104, 1Panel AI 编程一体机=369329829830946816, 1Panel 专业版=1751888184000088, 1Panel 企业版=369330027399442432, Zabbix=391660490084315136, 第三方产品（Gitea）=1751888184000099, 第三方产品（TAPD）=1751888184000094, 第三方产品（公有云服务）=1751888184000090, 第三方产品（USBKey）=2579076322140160, 第三方产品（国密SSL证书）=2580141474029568, 第三方产品（PCIE密码卡）=2580433531805696, 第三方产品（缓存服务器）=2580931748012032, 第三方产品（Web服务器）=389209953543909376, 第三方产品（数据库）=388735960953122825, 第三方产品（其他）=1751888184000095, 培训服务=5139031449427968, 高校合作计划=1751888184000100, Halo 企业版=312882406099316736, Halo 专业版=312881942242848768, KubeOperator 容器平台=1751888184000089


## 查询字段参考

> 用于 `combineSearch.conditions` 的 `name` 值。有 businessKey 的用 businessKey，否则用 fieldId。操作符规则见 `core/cli-reference.md`。

| 字段 | name（条件用） | type |
|------|--------------|------|
| lastStage | lastStage | INPUT |
| stage | stage | SELECT |
| createTime | createTime | DATE_TIME |
| updateTime | updateTime | DATE_TIME |
| reservedDays | reservedDays | INPUT_NUMBER |
| follower | follower | MEMBER |
| followTime | followTime | DATE_TIME |
| departmentId | departmentId | DEPARTMENT |
| actualEndTime | actualEndTime | DATE_TIME |
| 商机名 | name | INPUT |
| 区域 | 1751888184000030 | SELECT |
| 产品类型(可多选) | products | DATA_SOURCE_MULTIPLE |
| 客户名 | customerId | DATA_SOURCE |
| 行业 | 1751888184000037_ref_1751888184000005 | SELECT |
| 来源 | 1751888184000034 | SELECT |
| 最终用户工商全称 | 1751888184000039 | INPUT |
| 线上来源详情 | 1751888184000036 | SELECT |
| 最终用户简称 | 1751888184000042 | INPUT |
| 关键决策人（KP） | contactId | DATA_SOURCE |
| 结束日期 | expectedEndTime | DATE_TIME |
| 金额 | amount | INPUT_NUMBER |
| 有效合同额 | 1751888184000041 | INPUT_NUMBER |
| 纸质合同编码 | 1751888184000045 | INPUT |
| 签约类型 | 176847297349200000 | SELECT |
| 可能性 | possible | INPUT_NUMBER |
| 报备号/代签方名称 | 176490831663000000 | INPUT |
| 国家 | 1751888184000037_ref_177684248426900000 | LOCATION |
| 省市 | 1751888184000037_ref_1751888184000011 | LOCATION |
<!-- AUTO-GENERATED-END -->

> `owner`：创建免传（系统自动设为当前用户）；查询填 userId 过滤指定人，但查他人受角色权限约束（见 `profiles/*.md`）。

## 查重规则

统一走 SKILL.md 查重流程：用客户名搜索线索+开放商机，判断客户名+产品是否重复。

## 默认值

- 有效合同额：未单独指定时等于金额
- 线上来源详情：来源为"线下"开头时填 `线下不涉及`

> 条件必填字段（如报备号/代签方名称、签约类型、省市）见上方必填清单的「条件必填」列，满足条件时才需填写。

## 业务术语

stage 字段只接受英文枚举值作为过滤条件，中文标签（如"成功""失败"）会静默返回空结果。

| 用户说法 | 字段 | 过滤值 |
|---------|------|--------|
| 赢单 / 赢了 / 签单 / 已下单 / 成交 / 拿下了 | stage | SUCCESS |
| 输单 / 丢单 / 输了 / 没拿下 | stage | FAIL |
| 新建 / 新商机 | stage | CREATE |
| 开放商机 / 进行中 / 在跟的 | stage | NOT_IN [SUCCESS, FAIL] |

### 时间维度筛选规则

| 结果口径 | 时间字段 | 说明 |
|---------|---------|------|
| 赢单 / 输单 / 成交 / 开放 / 结束 | expectedEndTime | 商机的**唯一**结束时间口径，所有涉及"结束时间/成交/赢单/输单"的筛选统计都用它 |
| 新建商机 | createTime | 商机创建时间 |

> **时间字段选择**：商机的结束时间**一律用 `expectedEndTime`**（赢单/输单/成交/开放/结束都用它），新建用 `createTime`。**`actualEndTime` 在实际业务上不具备统计意义，不要用于任何筛选或统计。**

> **统计字段选择**：API 返回的记录包含语义化顶层字段（如 `amount`、`ownerName`、`departmentName`、`stageName`），统计时优先用这些字段做分组和聚合。注意：`ownerName`/`stageName`/`departmentName`/`customerName` 是返回展示字段，过滤条件中使用对应的 ID 字段（`owner`/`stage`/`departmentId`/`customerId`）。

### 聚合字段

| 用户说法 | aggregate 字段参数 | 说明 |
|---------|-------------------|------|
| 金额 / 总金额 | `amount` | 顶层字段，直接用 |
| 有效合同额 | `1751888184000041` | moduleFields 字段，用 fieldId |
| 负责人分组 | — | 读列表后按 `ownerName` 本地分组 |
| 部门分组 | — | 读列表后按 `departmentName` 本地分组 |

> "有效合同额"是 **opportunity 模块**的字段（不在 contract 模块），统计时走 `crm aggregate opportunity 1751888184000041 sum`。

> **阶段更新时间口径**：`stageUpdateTime` 用于展示商机阶段最近变更时间；筛选赢单/输单/成交时间时统一使用 `expectedEndTime`（不用 `actualEndTime`）。

## DATA_SOURCE 字段

⚠️ 商机有 2 个 DATA_SOURCE 字段需要解析 ID：

1. **客户名** → 用 `cordys.sh crm search account` 解析客户 ID
2. **关键决策人（KP）** → 用 `cordys.sh crm search contact` 解析联系人 ID

## 创建命令

命令：`cordys.sh crm create opportunity '<JSON>'`（body 双层结构，见 `core/write-engine.md` §0.4）

**顶层系统字段**：商机名→`name`、客户名→`customerId`（传客户ID）、KP→`contactId`（传联系人ID）、产品→`products`（传产品ID数组）、金额→`amount`、结束日期→`expectedEndTime`。
**moduleFields**（fieldId 见上方「查询字段参考」表，注意商机多为 `..._ref_..` 复合ID；选项 value 见「SELECT 字段可选值」表）：区域、行业、来源、线上来源详情、有效合同额、最终用户全称、签约类型、省市等。不传 owner。

```bash
cordys.sh crm create opportunity '{"name":"千里眼-MS-2026-订阅新购","customerId":"370020872889004032","contactId":"370024944518000640","products":["<MS产品ID>"],"amount":500000,"moduleFields":[{"fieldId":"1751888184000030","fieldValue":"东区"},{"fieldId":"1751888184000037_ref_1751888184000005","fieldValue":"<行业选项ID>"},{"fieldId":"1751888184000034","fieldValue":"<来源选项ID>"},{"fieldId":"176847297349200000","fieldValue":"<签约类型选项ID>"}]}'
```

## 完整示例

**用户**："帮我创建一个商机，千里眼科技要买 MS 企业版，50 万，预计年底成交，KP 是张三，飞致云直签"

**步骤 1** — 提取 + 推断：
- 客户名=千里眼科技，产品=MeterSphere 企业版，金额=500000
- 结束日期=2024-12-31，KP=张三，签约类型=飞致云直签
- 有效合同额=500000（默认等于金额）
- 报备号=空（直签）
- 缺失：商机名、区域、行业、来源、线上来源详情、最终用户全称、省市

**步骤 2** — 查重（按 `sop/duplicate-check.md` 执行）：规则 1~4 未触发 → 继续

**步骤 3** — 解析 ID：

解析客户 ID：
```bash
cordys.sh crm search account '{"keyword":"千里眼科技","current":1,"pageSize":5}'
```
→ 客户 ID = `370020872889004032`

解析联系人 ID：
```bash
cordys.sh crm search contact '{"keyword":"张三","current":1,"pageSize":5}'
```
→ 联系人 ID = `370024944518000640`

**步骤 4** — 校验：缺失字段，问用户补充

**用户补充后步骤 5** — 创建（不传 owner；系统字段顶层、其余进 moduleFields，fieldId/选项value 见上方字段表）：
```bash
cordys.sh crm create opportunity '{"name":"千里眼-MS-2026-订阅新购","customerId":"370020872889004032","contactId":"370024944518000640","products":["<MS产品ID>"],"amount":500000,"expectedEndTime":"2026-12-31","moduleFields":[{"fieldId":"1751888184000030","fieldValue":"东区"},{"fieldId":"1751888184000037_ref_1751888184000005","fieldValue":"<行业选项ID>"},{"fieldId":"1751888184000034","fieldValue":"<来源选项ID>"},{"fieldId":"1751888184000041","fieldValue":"500000"},{"fieldId":"1751888184000039","fieldValue":"杭州千里眼科技有限公司"},{"fieldId":"176847297349200000","fieldValue":"<签约类型选项ID>"}]}'
```
返回：`{"code":100200,"data":{"id":"370025374014730240","amount":500000}}`

**回复**："商机创建成功！商机名：千里眼-MS-2026-订阅新购，ID：370025374014730240，金额：50万元"
