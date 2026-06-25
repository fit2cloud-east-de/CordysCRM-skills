# 合同查询参考

> 合同模块当前仅支持查询和统计，不支持通过助手创建。

> 查询字段的取值/用法补充（人工维护，位于自动生成区块外，`sync` 不会覆盖）。
>
> ⚠️ **构造 conditions 前必须加载 `core/cli-reference.md` 查 operator，禁止凭记忆填写。**
> - `负责人`：过滤条件中 name 填 `owner`（值=userId）；返回记录中 `ownerName` 仅供展示。
> - 金额聚合优先用顶层 `amount`（合同金额）、`alreadyPayAmount`（已回款金额）。

<!-- AUTO-GENERATED-START -->


## SELECT 字段可选值

> **创建时传中文标签**（支持简称，CLI 自动前缀匹配）。
> **查询时（`combineSearch.conditions` 的 `value`）传选项 ID**：标注「查询用 ID」的字段，中文与 ID 不一致，查询必须填 `=` 右侧的 ID（填中文会静默返回空）；未标注的字段中文即 ID，查询直接传中文即可。

- **法人实体**（查询用 ID）：杭州飞致云信息科技有限公司=177002244338500000, 凌霞（香港）软件有限公司=177002244338500001
- **区域**（查询用 ID）：东区=东区, 北区=北区, 南区=南区, KA=KA, 凌霞软件=175464963179500000, 培训认证中心=176878872228000000, 总部框架=177460307956800000
- **签约类型**（查询用 ID）：直销签约客户=176967729298500001, 认证合作伙伴=176967729298500002, 预充值合作伙伴=176967732863200000, 指定合作伙伴=176967729298500003, 未认证合作伙伴=176967733670400000
- **签约方式**（查询用 ID）：我方发起-电子签签约=178039002227900001, 对方发起-电子签签约=178039002227900002, 我方先打印-纸质签约盖章邮寄=178039002227900003, 对方先打印-纸质签约盖章邮寄=178039015782100000
- **合同等级**（查询用 ID）：A类合同=178039067183600001, B类合同=178039067183600002, C类合同=178039067183600003
- **是否需要验收**（查询用 ID）：是=178039073502400001, 否=178039073502400002
- **调整金额原因**（查询用 ID）：无调整=178039062388600000, 汇率差=177250708116700001, 平台服务费=177250708116700002, 合同让利=177250708116700003, 承兑汇票贴现手续费=177250710373100000, 坏账=177391193779600000
- **存档状态**（查询用 ID）：未存档=177320941614700001, 变更待存档=177849169119600000, 已存档=177320941614700002
- **产品类型（可多选）**：JumpServer 企业版, MaxKB 专业版, MaxKB 企业版, MaxKB 一体机, DataEase 企业版, DataEase 专业版, DataEase 嵌入式版, Cordys CRM 企业版, SQLBot 专业版, MeterSphere 企业版, CloudExplorer 云管平台, 1Panel AI 助理一体机, 1Panel AI 编程一体机, 1Panel 专业版, 1Panel 企业版, Zabbix, 第三方产品（Gitea）, 第三方产品（TAPD）, 第三方产品（公有云服务）, 第三方产品（USBKey）, 第三方产品（国密SSL证书）, 第三方产品（PCIE密码卡）, 第三方产品（缓存服务器）, 第三方产品（Web服务器）, 第三方产品（数据库）, 第三方产品（其他）, 培训服务, 高校合作计划, Halo 企业版, Halo 专业版, KubeOperator 容器平台


## 查询字段参考

> 用于 `combineSearch.conditions` 的 `name` 值。有 businessKey 的用 businessKey，否则用 fieldId。操作符规则见 `core/cli-reference.md`。

| 字段 | name（条件用） | type |
|------|--------------|------|
| createTime | createTime | DATE_TIME |
| updateTime | updateTime | DATE_TIME |
| approvalStatus | approvalStatus | SELECT |
| stage | stage | SELECT |
| departmentId | departmentId | DEPARTMENT |
| alreadyPayAmount | alreadyPayAmount | INPUT_NUMBER |
| 合同名 | name | INPUT |
| 合同编码 | 176968185541500000 | INPUT |
| 合同开始时间 | startTime | DATE_TIME |
| 合同结束时间 | endTime | DATE_TIME |
| 法人实体 | 177002244338400000 | SELECT |
| 客户名 | customerId | DATA_SOURCE |
| 商机名 | 177227151390900000 | DATA_SOURCE |
| 区域 | 177227151390900000_ref_1751888184000030 | SELECT |
| 商机金额 | amount | INPUT_NUMBER |
| 结束日期 | expectedEndTime | DATE_TIME |
| 最终客户名 | 177227450327600000 | DATA_SOURCE_MULTIPLE |
| 签约客户名 | 176968277393700000 | DATA_SOURCE |
| 签约类型 | 176967729298500000 | SELECT |
| 合作伙伴名称 | 178159459136900000 | DATA_SOURCE |
| 产品类型 | 177027611329500000 | DATA_SOURCE_MULTIPLE |
| 收入类型 | 177018624588200000 | SELECT_MULTIPLE |
| 申请日期 | 178038973211200000 | DATE_TIME |
| 有效服务期（月） | 176967383723200000 | INPUT |
| 关联报价 | 176605494863600000 | DATA_SOURCE |
| 订阅产品 | 177010505928900000 | SUB_PRODUCT |
| 授权及一体机 | 1081644564316182 | SUB_PRODUCT |
| 维保 | 177010538760000000 | SUB_PRODUCT |
| 专业服务 | 177010507957200000 | SUB_PRODUCT |
| 培训服务 | 177017254683600000 | SUB_PRODUCT |
| 其他产品 | 177017257291800000 | SUB_PRODUCT |
| 累计金额（原始合同金额） | amount | FORMULA |
| 有效应收金额 | 177320936295500000 | FORMULA |
| 产品表格 | 178039111935400000 | SUB_PRODUCT |
| 签约方式 | 178039002227900000 | SELECT |
| 收件人/电子签接收人信息 | 178039020892600000 | INPUT |
| 合同审核附件 | 177996316359300000 | ATTACHMENT |
| 备注 | 177096671614300000 | TEXTAREA |
| 合同等级 | 178039067183600000 | SELECT |
| 是否需要验收 | 178039073502400000 | SELECT |
| 调整金额原因 | 177250708116700000 | SELECT |
| 调整金额 | 177459163595400000 | INPUT_NUMBER |
| 存档状态 | 177320941614700000 | SELECT |
| 存档编码 | 177027697150400000 | INPUT |
| 合同归档附件 | 177002283223000000 | ATTACHMENT |
<!-- AUTO-GENERATED-END -->

## 业务术语

| 用户说法 | 字段 | 过滤值 |
|---------|------|--------|
| 待签署 / 未签 | stage | PENDING_SIGNING |

> 当前系统中合同全部为 `PENDING_SIGNING` 状态，暂无其他阶段数据。

## 聚合字段

| 语义 | 模块路径 | 字段 | 说明 |
|------|---------|------|------|
| 合同金额 | `contract` | `amount` | 合同总金额 |
| 已回款金额 | `contract` | `alreadyPayAmount` | 该合同已收回的金额 |
| 负责人 | `contract` | `ownerName` | 分组用 |
| 部门 | `contract` | `departmentName` | 分组用 |
| 客户 | `contract` | `customerName` | 分组用 |

## 时间字段选择

| 统计口径 | 时间字段 | 说明 |
|---------|---------|------|
| 新签合同 | `createTime` | 按合同创建时间统计 |
| 合同到期 | `endTime` | 按合同结束日期筛选即将到期合同 |

## 回款完成率计算

回款完成率 = `alreadyPayAmount` / `amount`

通过读取合同列表，提取每条记录的 `amount` 和 `alreadyPayAmount` 进行对比。
