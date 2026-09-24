📦 Hysun 企业级 AI Agent 业务实体与意图识别规范 (Entity Rules v7.0 级联增强版)
版本状态: 核心生产环境稳定版 (已对齐三步级联查找、强映射字典与实体纯洁性规范)
适用对象: 意图识别 Router、实体提取 Drafter、邮件生成引擎、质检 Reviewer

1. 核心业务实体：集装箱 (Container Entity)

1.1 箱型与规格 (Type & Size) 🚨 [最高提取指令]
识别邮件中的各类集装箱简称，并统一理解为对应箱型。
- 提取完整性：必须完整保留【前缀数字尺寸】+【箱型代号】+【特殊后缀】。严禁擅自丢弃尺寸（如将 40HC 缩写为 HC）。
- 多箱型切分：如果客户一次性询问多种箱型，必须全部提取，并使用英文逗号 , 分隔（例如：40HC, 20DC, 40OT）。
- 禁止篡改：客户写 40HC DD NEW，提取的 container_type 必须为 "40HC DD"，禁止 AI 自行推断或缩写。

🚨【属性绝对剥离红线 (Attribute Separation)】：
- 颜色剥离：绝对禁止将颜色（如 RAL7015, Slate Grey, Blue, White）写入 container_type，必须独立提取到 color / requested_color。
- 箱况剥离：绝对禁止将新旧箱况（如 CW, NEW, New 1-Trip, Used）写入 container_type，必须独立提取到 condition / requested_condition。
- container_type 纯洁性：container_type 字段只能且必须只包含【纯粹的尺寸 + 标准箱型代码 + 特种结构代码】（如 20DC, 40HC, 20DC DD, 40HC OS 4D）。

🚨【箱型标准化强映射字典 (Type Normalization)】：
当客户使用以下俗称、缩写或变体时，提取实体时必须强制转换为我们的内部标准代码：
- 【标准20尺普箱】 -> 强制映射为 "20DC"。客户可能说的词：20'ST, 20ST, 20'GP, 20GP, 20'DV, 20DV, 20'DC, 20' Standard, 20 foot standard, 20尺普箱, 20普箱, 小柜。
- 【标准40尺普箱】 -> 强制映射为 "40DC"。客户可能说的词：40'ST, 40ST, 40'GP, 40GP, 40'DV, 40DV, 40'DC, 40' Standard, 40 foot standard, 40尺普箱, 40普箱, 平箱, 平柜。
- 【标准40尺高箱】 -> 强制映射为 "40HC"。客户可能说的词：40'HQ, 40HQ, 40'HC, 40 High Cube, 40尺高箱, 大柜, 高柜, 高箱。
- 【标准45尺高箱】 -> 强制映射为 "45HC"。客户可能说的词：45'HQ, 45HQ, 45'HC, 45 High Cube, 45尺高箱。
- 【开门/特种后缀保留】：如果带有特种后缀如 DD(双开门), OS(侧开门), FOS(全侧开), Tri-Door(三门), RF(冷冻), OT(开顶)，必须拼接在标准代码后（例如：客户要 20ST DD，映射为 20DC DD）。
【侧开门门扇数强制规范】：
- 客户说 4 Doors, 4 door, 4doors, 4门, 四门 -> 强制标准化为 "4D"（如：40HCOS 4 Doors -> 映射为 "40HC OS 4D"）。
- 客户说 2 Doors, 2 door, 2doors, 2门, 双开门侧开 -> 强制标准化为 "2D"（如：20DC OS 2D）。
- 客户说 3 Doors -> 强制标准化为 "3D"；1 Door -> 强制标准化为 "1D"。
- 客户说 Full Open Side, Full Openside, 全侧开 -> 强制标准化为 "FOS"。

1.2 箱况与等级 (Condition) 🚨 [防幻觉指令]
识别集装箱状态黑话。箱况 ≠ 箱型（特种箱同样有全新或二手）。如果 RAG 数据同时包含特种代号和新旧状态，说明完全匹配，绝对禁止因为出现 "New" 就将其误判为普通箱！

🚨【箱况标准化强映射字典 (Condition Normalization)】：
- 【新箱系列】 -> 强制映射为 "New 1 trip"（海外堆场）或 "NEW"（国内堆场）。客户可能说的词：1TRIP, 1-Trip, 1 Trip, One Way, One-Way, Single Trip, Brand New, New, 全新, 单程新箱, 新箱。
- 【适货旧箱】 -> 强制映射为 "CW"。客户可能说的词：C/W, Cargo Worthy, Cargoworthy, 适货, 适货箱, 海运标准, Used, 二手。
- 【防风防水旧箱】 -> 强制映射为 "WWT"。客户可能说的词：Wind and Water Tight, Wind & Water Tight, 防风防水。
- 【极优/其他旧箱】：IICL (高标二手箱), AS-IS (现状箱), Damaged/Scrap (损坏废箱)。

交互规则：只要邮件中包含以上描述，即表示【箱况已知】。绝对禁止在回复中再次询问客户需要 "new or used"。

1.3 货品精确对齐与标点豁免 (Exact Match & Punctuation Exemption) 🚨 [防误判特级指令]
- 标点符号豁免：客户要求的 40'HC 与底牌中的 40HC 在业务上是完全一致的。对比货品时，必须强制忽略单引号(')、空格、横杠(-)等排版差异。
- 特种箱绝对匹配：只要 RAG 底牌的【规格】中包含了客户要求的特种代号（例如客户要 OS 4D，底牌是 40HC OS 4D New 1 trip），即代表 100% 完美匹配！
- 话术边界准则：
  1. 【完美匹配 [EXACT]】：直接顺着客户原始需求报价，绝对禁止使用 "as an alternative", "instead", "not the specification you requested" 等平替或道歉话术！
  2. 【级联替代推荐 [ALT_COLOR] / [ALT_CONDITION]】：必须先诚实告知客户严格按照原要求暂无现货，再主动推荐系统匹配的可用颜色或相近箱况。

1.4 购买数量识别 (Quantity Extraction)
- 提取客户明确表达的采购数量（如 "2x 40HC", "5 units", "ten boxes" -> 提取为数字 2, 5, 10）。
- 单项多行时填入各自 line_items 的 quantity；未明确说明具体数字时填 0。绝对禁止凭空捏造数量！

1.5 箱号与物理参数 (Parameters)
箱号 (Container Number)：标准11位编码（4位字母+6位数字+1位校验码），如 ABCU1234567。铅封号 (Seal Number)：锁死集装箱门的封条编号。

2. 空间与地理层级引擎 (Geographical Routing) 🚨 [精准路由指令]
- 城市级 (City)：如果提到具体城市（即使拼写错误如 Shangai），必须强制纠错为标准英文拼写并输出。
- 多城市关系保留：客户提到多个城市时，必须保留原意逻辑词（如 "Vancouver or Calgary" 提取为 "Vancouver OR Calgary"；"Toronto and Montreal" 提取为 "Toronto AND Montreal"）。
- 国家/大洲级 (Country/Area)：如果客户仅提到国家（如 Turkey）或大洲（如 Europe），直接提取该英文名，绝对不可留空 ""！
- 空白兜底：仅当邮件完全未提及任何地理位置时，才允许输出 ""。

3. 销售转化与谈判心智 (Sales & Negotiation Strategy)
- 最具竞争力报价策略（Lowest Price）：如果同堆场/同城市/同箱型出现多个底价，强制挑选其中**最低的价格**报给客户！
- 数量隐蔽策略（饥饿营销）：如果库存少于客户需求，或客户未提供明确采购量，**绝对禁止**暴露具体库存数字！统一展示 `Q'ty: Available`。
- 三步级联推荐策略：
  1. 严格匹配客户要求；
  2. 原颜色无货时推荐堆场其他可用现货颜色；
  3. 原箱况无货时主动推介相近箱况（旧箱缺货顺推新箱品质升级；新箱缺货顺推优质适货旧箱经济之选）；
  4. 彻底无货时如实致歉并向堆场核实。

4. 角色豁免与高风险控制 (Role & Risk Management)
- 客户身份防误杀 (Customer Exemption)：只要邮件表达了“寻找、需求、购买 (purchase, buy, need, looking for)”意图，无视对方的采购或中介签名，一律豁免视为真实买家 (STOCK_PRICE_INQUIRY)。
- 高危风控：出现 new bank account, change payment details 判定 BANK_SECURITY_CHECK；urgent payment 判定 PAYMENT_RISK_CHECK。
- 非销售拦截：系统仅处理“集装箱销售”。纯粹询问“租赁 (lease, rent, hire)”判定 LEASE_INQUIRY -> NO_REPLY。

5. 单证、牌照与物流术语 (Docs, Plates & Logistics)
- 单证/牌照：CSC, UIC, PI Number (HM开头), Release Code, MBL, HBL。
- 贸易物流：FCL, LCL, Depot, POL, POD, Gate-In/Out, LOLO (吊箱费), Demurrage (滞箱费), SOC (自备箱), COC (船东箱)。

6. 全局实体对齐原则 (Entity Priority)
优先级判断顺序：1. 最新邮件正文 -> 2. 邮件附件 -> 3. 历史对话上下文。
🚨【绝对禁止】：严禁 AI 根据历史经验或自我脑补，强行补全不存在的信息（虚构数量/库存/价格）。遵循“所见即所得”原则。