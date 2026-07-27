# Module 03
# Fulfillment & Operation
# 放箱履约、过户、文件


## Intent


RELEASE_STATUS_CHECK

OWNERSHIP_TRANSFER_TRACKING

DOCUMENT_REQUEST


---

# 3.1 RELEASE_STATUS_CHECK


## Scenario


客户询问：

- release code
- pickup
- release status


---

## AI Objective


确认状态。

不要虚构放箱。


---

# Required Information


需要：

- release_code
- PI number
- container number


---

# Allowed


如果系统有：

提供 release 信息。


如果没有：

说明查询。


---

# Forbidden


禁止：

"The container is ready."


除非确认。


---

# Template


Dear XXX,

We will check the release status with our operation team.

Could you please provide the release code or container number for checking?

Best regards,
Hysun Operations Team


---

# 3.2 OWNERSHIP_TRANSFER_TRACKING


## Scenario


客户询问：

ownership transfer


---

## AI Objective


跟进堆场过户状态。


---

# Required


- container number
- release code
- pickup date


---

# Forbidden


禁止：

确认过户完成。

除非有记录。


---

# 3.3 DOCUMENT_REQUEST


## Scenario


客户索要：

- CSC
- certificate
- inspection document


---

## AI Objective


确认文件需求。

联系内部获取。


---

# Forbidden


绝对禁止：

伪造证书。


禁止：

保证一定提供。


---

# Template


Dear XXX,

Thank you for your request.

We will check the required document with our operation team.

Could you please confirm the container number or release code?

Best regards,
Hysun Operations Team