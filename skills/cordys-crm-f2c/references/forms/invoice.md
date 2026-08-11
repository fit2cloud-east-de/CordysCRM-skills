# 发票字段参考

> 模块路径：`invoice`。字段、选项和视图由 `sync` 从当前实例刷新。

<!-- AUTO-GENERATED-START -->
| # | 字段 | JSON 键名 | 格式 |
|---|------|----------|------|
| 1 | 发票名 | 发票名 | 文本 |
| 2 | 合同名 | 合同名 | ⚠️ 实体 ID |
| 3 | 签约客户名 | 签约客户名 | ⚠️ 实体 ID |
| 4 | 开票类型 | 开票类型 | SELECT |
| 5 | 开票项目 | 开票项目 | 文本 |
| 6 | 开户名称 | 开户名称 | ⚠️ 实体 ID |
| 7 | 开票日期 | 开票日期 | YYYY-MM-DD |
| 8 | 正数发票/负数发票 | 正数发票/负数发票 | SELECT |
| 9 | 税率 | 税率 | 数字 |
| 10 | 发票金额 | 发票金额 | 数字 |

选填：数电发票号码、订单列表、公司名称、纳税人识别号、开户银行、银行账户、规格型号、单位、数量、单价、税额、发票金额（自动计算）、接收人邮箱、备注、附件、财务合同编号、财务往来单位编码、财务结算编码、财务收入编码


## 表单 SELECT 字段可选值

> **创建和查询都传 ID**：标注「传 ID」的字段，中文与 ID 不一致，必须填 `=` 右侧的 ID（填中文会静默失败——创建写空、查询返回空）；未标注的字段中文即 ID，直接传中文即可。
> 创建时 SELECT 字段放 `moduleFields` 的 `fieldValue`、产品放 `products`；查询时放 `combineSearch.conditions` 的 `value`。

> 本节只列自定义表单字段；系统/API 的 SELECT 字段以“查询字段参考”为准。

- **开票类型**（传 ID）：数电普通发票(CODE2)=1, 形式发票(CODE3)=2, 数电专用发票(CODE4)=177305331700300000
- **正数发票/负数发票**（传 ID）：正数发票=178418788414100001, 负数发票=178418788414100002
- **单位**（传 ID）：年=3, 套=2, 人天=177305354317700000, 个=1, 人月=177305354754000000, 项=177305355075500000


## 子表字段参考

> 子表按父 fieldId 保留层级；不同父子表中的同名字段不是同一个字段，禁止只按名称猜 fieldId。
> 子表字段不能直接放入 `combineSearch.conditions`。更新时外层 `moduleFields.fieldId` 使用父 fieldId，`fieldValue` 传完整行数组；行内保留 `id` 和未修改字段，目标子字段使用下表 fieldId，SELECT/RADIO 使用选项 value。

### 订单列表（父 fieldId：`178609094278200000`）

| 子字段 | fieldId | businessKey | type | 必填 |
|--------|---------|-------------|------|------|
| 订单名 | `178609099957500000` | — | DATA_SOURCE | 否 |
| 订单编号 | `178609099957500000_ref_318677768680583170` | number | SERIAL_NUMBER | 否 |
| 订单金额 | `178609099957500000_ref_178158161446300000` | — | FORMULA | 是 |
| 开票金额 | `178635587225900000` | — | INPUT_NUMBER | 是 |
| 订单状态 | `178609099957500000_ref_stage` | — | SELECT | 否 |
| 审批状态 | `178609099957500000_ref_approvalStatus` | — | SELECT | 否 |

SELECT/RADIO 可选值：
- **订单状态** (`178609099957500000_ref_stage`)：新建=`CREATE`, 待交付=`PENDING_SHIPMENT`, 交付中=`PARTIALLY_SHIPPED`, 验收中=`PENDING_ACCEPTANCE`, 履约中=`SHIPPED`, 履约完毕=`COMPLETED`, 已作废=`VOIDED`
- **审批状态** (`178609099957500000_ref_approvalStatus`)：已通过=`APPROVED`, 审批中=`APPROVING`, 已驳回=`UNAPPROVED`, 已撤销=`REVOKED`, 待提审=`PENDING`, -=`NONE`


## 查询字段参考

> 用于 `combineSearch.conditions` 的 `name` 值。有 businessKey 的用 businessKey，否则用 fieldId。操作符规则见 `core/cli-reference.md`。

> “系统/API”字段可能不显示为自定义表单控件或“表单 SELECT 字段可选值”列表；只要列在本表中，即可作为 conditions 的字段依据。

| 字段 | name（条件用） | type | 来源 |
|------|--------------|------|------|
| createTime | createTime | DATE_TIME | 系统/API |
| updateTime | updateTime | DATE_TIME | 系统/API |
| departmentId | departmentId | DEPARTMENT | 系统/API |
| owner | owner | MEMBER | 系统/API |
| approvalStatus | approvalStatus | SELECT | 系统/API |
| contractAmount | contractAmount | INPUT_NUMBER | 系统/API |
| 数电发票号码 | 177305438251500000 | INPUT | 表单 |
| 发票名 | name | INPUT | 表单 |
| 订单列表 | 178609094278200000 | SUB_PRODUCT | 表单 |
| 签约客户名 | 178332334748500000 | DATA_SOURCE | 表单 |
| 公司名称 | name | INPUT | 表单 |
| 纳税人识别号 | identificationNumber | INPUT | 表单 |
| 开户银行 | openingBank | INPUT | 表单 |
| 银行账户 | bankAccount | INPUT | 表单 |
| 开票类型 | invoiceType | SELECT | 表单 |
| 开票项目 | 177305498168100000 | INPUT | 表单 |
| 开户名称 | businessTitleId | DATA_SOURCE | 表单 |
| 规格型号 | 177305430193500000 | INPUT | 表单 |
| 开票日期 | 177305528717300000 | DATE_TIME | 表单 |
| 正数发票/负数发票 | 178418788414100000 | SELECT | 表单 |
| 单位 | 758216347107349 | SELECT | 表单 |
| 数量 | 758216347107350 | INPUT_NUMBER | 表单 |
| 单价 | 177305384950900000 | FORMULA | 表单 |
| 税率 | taxRate | INPUT_NUMBER | 表单 |
| 税额 | 177305381738100000 | FORMULA | 表单 |
| 发票金额 | amount | INPUT_NUMBER | 表单 |
| 发票金额（自动计算） | 178635591509800000 | FORMULA | 表单 |
| 接收人邮箱 | 177321354734800000 | INPUT | 表单 |
| 备注 | 177311499811000000 | INPUT | 表单 |
| 附件 | 177305535013800000 | ATTACHMENT | 表单 |
| 财务合同编号 | 177321357174200000 | INPUT | 表单 |
| 财务往来单位编码 | 177321359112100000 | INPUT | 表单 |
| 财务结算编码 | 177321360016900000 | INPUT | 表单 |
| 财务收入编码 | 177321360774800000 | INPUT | 表单 |

## 视图目录

> `viewId` 按模块选择。官方内置视图由 Cordys 前端定义；实例自定义视图由 `sync` 从对应 `/view/list` 自动刷新。
> 自定义视图路由：用户明确引用视图，或去掉“看下/查看/查询/列出”等纯查询外壳后与唯一、已启用的视图名称完全一致时，直接使用该 `viewId`；精确命中后不从名称重复构造部门、时间条件。模糊相似仍按字段条件查询。视图不能扩大当前角色的数据范围。

### 官方内置视图

| 视图名称 | viewId |
|----------|--------|
| 所有发票 | `ALL` |
| 我的发票 | `SELF` |
| 部门发票 | `DEPARTMENT` |

### 实例自定义视图（自动同步）

| 视图名称 | viewId | 启用 | 固定 |
|----------|--------|------|------|
| — | — | — | — |
<!-- AUTO-GENERATED-END -->
