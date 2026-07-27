# Entity Rules v2.0
# 企业业务实体识别规范


## 1. Container Entity


## Container Type


标准格式：


20GP

40GP

40HQ

40HCDD

45HC


禁止：

自行修改客户描述。


例如：

客户：

40HCDD NEW


回复：

40HCDD NEW


不要改：

40HC DD New Container


---

## Container Number


格式：

4个英文字母 + 7个数字


例如：

ABCU1234567


识别为：

container_number


---

# 2. Invoice Entity


## Vendor Invoice Number


供应商发票号：

例如：

LC123456

INV20260001

EWSCUSHEC001


字段：

vendor_invoice_number


---

## PI Number


Hysun PI:

HM 开头


例如：

HM20260725001


字段：

pi_number


---

# 3. Release Code


放箱代码：

可能格式：

USCM

HYBOS

HOU

T

HCA

896-HYGUZ


字段：

release_code


---

# 4. Payment Entity


识别：


payment

wire transfer

bank slip

wire proof

remittance


统一：

payment_status


状态：


pending

processing

completed

unknown


禁止 AI 自己推断状态。


---

# 5. Company Role Recognition


根据邮件判断角色。


## Customer


关键词：

buy

purchase

quotation

offer

price


角色：

customer


---

## Vendor / Supplier


关键词：

invoice

statement

payment reminder

bank account


角色：

vendor


---

## Intermediary


关键词：

commission

broker

agent

customer contact


角色：

intermediary


---

# 6. Attachment Recognition


关键词：

attached

attachment

invoice attached

please find


识别：

has_attachment=true


回复：

确认收到即可。


---

# 7. Date Entity


识别：

payment date

pickup date

delivery date


但是：

日期只能来自邮件。


禁止：

AI生成日期。


---

# 8. Money Entity


识别：

USD

$

EUR

RMB


金额：

必须保持原币种。


禁止：

自动转换。


---

# 9. Risk Entity


高风险：

## Bank Change


关键词：

new bank account

updated beneficiary

change payment details


进入：

BANK_SECURITY_CHECK


---

## Urgent Payment


关键词：

urgent payment

pay immediately

today only


进入：

PAYMENT_RISK_CHECK


---

# 10. Entity Priority


如果实体冲突：

优先级：


1. 最新邮件内容

2. 明确附件

3. 历史邮件

4. 模型推测


禁止：

根据经验补全。

