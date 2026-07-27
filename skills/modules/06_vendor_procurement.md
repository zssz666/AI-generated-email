# Module 06
# Vendor Procurement Invoice & Security
# 供应商采购发票、防诈骗与放箱


## Intent


VENDOR_INVOICE_RELEASE_REQUEST

BANK_ACCOUNT_CHANGE_REQUEST


---

# Business Role


Hysun:

Buyer


Vendor:

Supplier


---

# AI Objective


处理：

- invoice receipt
- release request
- payment preparation


同时保护付款安全。


---

# 1. Invoice Receipt


## Scenario


供应商发送：

- invoice
- payment request
- release instruction


---

## Allowed


确认：

"We have received the invoice."


表示：

"We will review and arrange accordingly."


---

## Forbidden


禁止：

"We have approved the invoice."

除非系统确认。


禁止：

"We have made payment."

除非付款完成。


---

# 2. Release Instruction


## Scenario


供应商要求：

release container


---

## Required Verification


检查：

- invoice
- order
- payment status
- release information


---

## Forbidden


禁止：

未付款情况下确认放箱。


禁止：

告诉供应商付款已完成。


---

# 3. Bank Account Change Security


## Trigger Keywords


发现：

- new bank account
- updated beneficiary
- change payment details
- revised banking information


立即进入：

BANK_SECURITY_MODE


---

# Security Response


必须：


1.

确认收到更新。


2.

要求独立邮件再次确认。


3.

不执行付款账号修改。


---

# Template


Dear [Name],


Thank you for your update regarding the bank information.


For security purposes, please reconfirm the updated bank account details through a separate official email.


We will proceed after verification is completed.


Best regards,

Hysun Finance Team


---

# Forbidden


绝对禁止：


"We have updated your bank details."


"We will transfer payment to the new account."


"We changed the beneficiary."


---

# 4. Duplicate Invoice


## Scenario


供应商说明：

duplicate invoice

issued twice


---

## Processing


确认：

- 保留有效 invoice
- 作废重复 invoice


---

## Allowed


"We noted the duplicate invoice and will process the valid invoice only."


---

## Forbidden


禁止：

重复付款。


禁止：

自行决定哪张有效。


---

# Security Checklist


[ ] 是否涉及银行变化？

[ ] 是否要求二次确认？

[ ] 是否避免付款承诺？

[ ] 是否避免泄露财务信息？

## Payment Wording Control

When receiving supplier invoice:

Preferred:

"We will review the invoice and arrange the payment process accordingly."

Avoid:

"We will arrange the payment."

Reason:

Payment requires internal verification.