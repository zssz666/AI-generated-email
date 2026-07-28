# Entity Rules v4.0
# 企业业务实体与行业术语识别规范 (包含全集装箱品类与货代术语)

# 1. Container Entity (集装箱实体)

## 1.1 Container Type & Size (箱型与规格)
识别邮件中的各类集装箱简称，并统一理解为对应箱型。

标准干货柜 (Dry Container / DC):
- 20GP / 20DV / 20 Dry / 小柜: 20尺普箱 (约 28CBM)
- 40GP / 40DV / 40 Dry / 大柜: 40尺普箱 (约 58CBM)
- 40HC / 40HQ / 大柜: 40尺高箱 (约 68CBM)
- 45HC / 45HQ: 45尺高箱 (约 75CBM)
- 40HCDD / 20HCDD: 双开门高箱 (Double Door)
- TEU / FEU: 量级计量单位 (TEU=20尺标准箱，FEU=40尺标准箱)
- 双背: 两个20尺小柜

特种集装箱 (Special Container):
- 20RF / 40RF / 40RH / Reefer: 冷冻集装箱 
- 20OT / 40OT / Open Top: 开顶集装箱 (用于吊装重货、玻璃、钢材)
- 20FR / 40FR / Flat Rack: 框架集装箱 (无顶无侧壁，用于超宽超高货)
- 20TK / 40TK / Tank: 罐式集装箱 (用于液体、化工、食品)
- Pen Container: 牲畜集装箱
- Platform Container: 平台集装箱
- Ventilated Container: 通风集装箱
- Bulk Container: 散装货集装箱

禁止：自行修改客户描述。客户写 40HCDD NEW，回复必须是 40HCDD NEW。

---

## 1.2 Container Condition (集装箱状态与等级)
识别集装箱状态黑话。只要邮件中包含以下描述，即表示【箱况 (Condition) 已知】，绝对禁止在回复中再次询问客户需要 "new or used"。

新箱系列：
- NEW / Brand New / Factory New (全新箱)
- Single Trip / One-Way / 1-Trip (单程新箱)

二手箱系列 (从高到低)：
- IICL (国际集装箱出租人协会标准 - 高标二手箱)
- CW / Cargo Worthy (适货箱 - 达到海运标准)
- WWT / Wind and Water Tight (防风防水箱)
- AS-IS / As Is Where Is (现状箱 - 买家自担风险)
- Damaged / Scrap (损坏箱 / 废箱)

操作状态术语：
- 空箱 / 吉箱 (Empty Container): 未装货的箱子
- 重箱 (Laden Container): 已经装载货物的箱子

---

## 1.3 Container Number & Parameters (箱号与物理参数)
- 箱号 (Container Number): 标准11位编码。格式为 4个英文字母(前三位箱主+U) + 6位数字 + 1位校验码。例如：ABCU1234567。
- 铅封号 (Seal Number): 锁死集装箱门的封条编号。
- MAX GROSS WEIGHT (总重): 皮重 + 净重之和。
- TARE WEIGHT (皮重): 空箱自重 (20GP约1.7吨，40GP约3.4吨)。
- PAYLOAD / NET WEIGHT (净重): 集装箱可负荷的最大货重。
- CUBIC CAPACITY: 立方容积。

---

# 2. Certifications & Plates (行业认证与牌照实体)
识别客户对特定铭牌和认证的要求：
- CSC (安全合格牌照): 集装箱海运通行证 (International Convention for Safe Container)。
- UIC (国际铁路联盟标记): 欧洲铁路运输通行标志。
- TCT (木材防疫处理牌照): 针对带有裸露木件的集装箱，大洋洲(澳新)地区清关必备。
- CCC (通关合格牌照): 国际集装箱关务公约认证标志。

---

# 3. Document & Order Entity (单证与订单实体)
- Vendor Invoice Number: 供应商发票号 (例如 LC123456)。
- PI Number (Proforma Invoice): Hysun内部发票号，HM开头 (例如 HM20260725001)。
- Release Code: 放箱代码 (例如 USCM, 896-HYGUZ)。
- MBL (Master Bill of Lading): 船东提单。
- HBL (House Bill of Lading): 货代提单。

---

# 4. Logistics & Operation Terms (物流与履约黑话)
- FCL (Full Container Load): 整箱操作。
- LCL (Less than Container Load): 拼箱操作。
- Depot / CY (Container Yard): 堆场。
- POL / POD: 装港 (Port of Loading) / 卸货港 (Port of Discharge)。
- Gate-In / Ingate: 进场 / 还箱进场。
- Gate-Out / Outgate: 提箱出场 / 离场。
- Gate Out Report: 出场报告。
- Lift-on / Lift-off (LOLO): 吊上吊下费 / 堆场装卸费。
- Demurrage / Detention: 滞港费 / 滞箱费。
- 倒箱: 堆场内挪动上面箱子以提取底部箱子的操作。
- SOC (Shipper Owned Container): 货主自备箱 (买方买箱运输)。
- COC (Carrier Owned Container): 船东箱。

---

# 5. Payment Entity
识别：payment, wire transfer, bank slip, wire proof, remittance
统一：payment_status
状态：pending, processing, completed, unknown
禁止：AI 自己推断付款状态。

---

# 6. Company Role Recognition
根据邮件判断角色。
- Customer (客户): 关键词 buy, purchase, quotation, offer, price
- Vendor (供应商): 关键词 invoice, statement, payment reminder, bank account
- Intermediary (中介): 关键词 commission, broker, agent, customer contact

---

# 7. Risk Entity (高风险)
- Bank Change: 关键词 new bank account, updated beneficiary, change payment details。进入 BANK_SECURITY_CHECK。
- Urgent Payment: 关键词 urgent payment, pay immediately, today only。进入 PAYMENT_RISK_CHECK。

---

# 8. Inquiry Completeness Logic (询价完整性逻辑)
处理客户询价 (STOCK_PRICE_INQUIRY) 时，必须检查以下 3 个核心要素：
1. 箱型与规格 (Type/Size)
2. 数量 (Quantity)
3. 位置 (Location/Depot)

缺失信息处理规则：
- 仅追问缺失的要素。
- 如果客户未提及 Condition (见 Section 1.2)，在追问数量或位置时，可顺带询问（"preferred condition"）。
- 如果 Condition 已知，严禁再问。

---

# 9. Entity Priority
如果实体冲突，优先级：
1. 最新邮件内容
2. 明确附件
3. 历史邮件
4. 模型推测
禁止：根据经验补全不存在的信息。