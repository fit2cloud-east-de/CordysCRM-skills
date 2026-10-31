# 💲 价格目录查询（PRICE 数据源）

用户询问产品价格、SKU、购买方式、收入类型、价格表时读本文件。价格目录是独立的只读数据源，不属于 `crm page` 的业务模块列表。原始端点与响应结构见 `references/crm-api.md`「字段数据源：订单服务与价格目录」。

## 1. 命令

```text
cordys.sh crm price-form
cordys.sh crm price
cordys.sh crm price --sku 2026v1-JS-STD-SW
cordys.sh crm price --product JumpServer --purchase-mode 软件授权 --income-type 软件授权
cordys.sh crm price-sku 2026v1-JS-STD-SW
cordys.sh crm price-detail <价格表ID或价格行ID>
```

| 命令 | 作用 |
|------|------|
| `price-form` | 每次读取 `GET /price/module/form`，从 `businessKey=products` 的 `SUB_PRODUCT.subFields` 动态建立价格子字段映射；返回主表字段、products 子表字段（`fieldId/name/type/businessKey/required`）、SELECT/RADIO 的 `value/label`，以及产品、价格、税率、购买方式、收入类型、服务等级、开票项目、重要说明等语义映射 |
| `price` / `price-sku` | 先读价格表单，再 POST `/field/source/price`，按 `data.total` 连续分页到完整价格主表，逐条展开 `products[]` 子行；SKU/产品/购买方式/收入类型在 CLI 读取完整子行后**本地筛选**，不依赖后端 keyword |
| `price-detail` | 按价格表 ID 或价格行 ID 定向核验 |

## 2. 规则

- 默认只保留价格主表 `status=1`；需要禁用目录时加 `--include-disabled`。
- 不得在模型或脚本中写死 fieldId、SKU 字段名或选项值；选项值按价格表单自身 options 翻译为中文 label。
- 含税成交指导价的语义映射必须兼容当前表单的 `businessKey=amount` 与字段名「成交指导价（含税）」，不能只匹配 `price`、`standardPrice` 等英文或历史别名。
- 价格行统一返回：`catalog_id`、`catalog_name`、`catalog_status`、`price_row_id`、`product_id`、`product_name`、`sku`、`description`、`product_version`、`purchase_mode`、`income_type`、`unit`、`service_tier`、`currency`、`standard_price_tax_included`、`tax_rate_percent`、`invoice_item`、`important_notes`、`queried_at`。税率用百分数语义（如 `13`），价格保持数字类型，缺失字段为 `null`。重要说明原样保留，不能把按授权金额计算的百分比规则改写成固定单价。
- 新建合同等单据的子表行时：「产品/服务」传 `catalog_id`，同一行加 `price_sub` = `price_row_id`；产品类型、SKU、描述、购买方式、收入类型、成交指导价等带出列由 `crm create` 按价格行自动带出，不用把这些值抄进行里。写法见对应 forms「新建一行怎么写」。
- 多个价格表命中同一 SKU 时保留全部价格行。
- 只允许 GET/POST 读取接口。表单读取失败、价格目录读取失败、分页未完成、认证失败、SKU 未命中、字段类型无法解析必须返回非零错误及诊断类别，**不能把失败伪装成空数组**。
