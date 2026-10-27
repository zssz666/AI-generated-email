📦 Hysun 企业级 AI Agent 业务实体与意图识别规范 (Entity Rules v7.2 九级箱况逐级推荐版)
版本状态: 九级箱况品质映射版 (保留动态箱型清单、提箱地安全解析、预算增报与原有风控)
适用对象: 意图识别 Router、实体提取 Drafter、邮件生成引擎、质检 Reviewer
1. 核心业务实体：集装箱 (Container Entity)
1.1 箱型与规格 (Type & Size) 🚨 [最高提取指令]
🚨 箱型标准化权威来源：
系统内部已有权威箱型清单（编号 | 缩写 | 英文全称 | 中文全称），
该清单由系统在 Router 调用时动态注入（见 00_router_engine.md 第 5 节）。
所有箱型提取必须与系统清单严格对齐，禁止依赖任何硬编码字典。
- 提取完整性：必须完整保留【尺寸】+【箱型缩写】+【特殊结构后缀】。严禁擅自丢弃尺寸。
- 多箱型切分：多个箱型用英文逗号 , 分隔。
- 禁止篡改：客户写 40HC DD，提取必须是 "40HC DD"，禁止 AI 自行推断或缩写。
- 同箱型去重：同一封邮件中重复出现的相同箱型只保留一条 line_items，不同数量分别累加；若客户分行列出相同箱型但颜色/箱况/地点不同，必须拆成独立 line_items。
- 中英混写归一：客户中英混写（如"40尺高箱"、"大柜"、"冻柜"、"20尺普箱"）必须先语义归一为系统清单缩写，再提取。
  - 40尺高箱 / 大柜 / 高柜 → 40HC
  - 20尺普箱 / 平箱 / 平柜 / 小柜 → 20DC
  - 冻柜 / 冷柜 / 冷藏箱 → RF
🚨【属性绝对剥离红线 (Attribute Separation)】：
- 颜色剥离：绝对禁止将颜色（如 RAL7015, Slate Grey, Blue）写入 container_type，必须独立提取到 requested_color。
- 箱况剥离：绝对禁止将新旧箱况（如 CW, NEW, New 1-Trip, Used）写入 container_type，必须独立提取到 requested_condition。
- 数量剥离：绝对禁止将数量（如 2x, 5 units）写入 container_type。
- container_type 纯洁性：只允许包含【尺寸 + 箱型缩写 + 特种结构后缀】。
🚨【Reefer 冷藏箱专用规则】：
- 所有冷藏箱统一映射为 RF。
- Convertible Reefer / Reefer Convertible 中的 Convertible 是可转换属性，不是独立箱型，提取时必须剥离。
  例如："40FT CONVERTIBLE REEFER CONTAINER" → "40RF"。
🚨【侧开门门扇数强制规范】：
- 4 Doors / 4 door / 四门 → "4D"
- 2 Doors / 双开门侧开 → "2D"
- 3 Doors / 三门 → "3D"
- 1 Door → "1D"
- Full Open Side / 全侧开 → "FOS"
1.2 箱况与等级 (Condition) 🚨 [品质顺序与对外显示双重约束]
箱况 ≠ 箱型。特种箱和普通箱均可有不同箱况。Router 只提取客户原始箱况含义；是否默认新箱、是否逐级替代由 Python 库存引擎决定，Router 禁止自行升级/降级。
🚨【ERP 唯一权威编码与品质顺序：从好到差，严禁按编号大小排序】
品质排名	ERP 编码	内部标准箱况	对外展示箱况
1	1	NEW	NEW（国内）
2	2	New 1 trip	New 1-Trip
3	3	New-IICL	New-IICL
4	4	IICL	IICL
5	9	CW+	CW
6	5	CW	CW
7	6	CW-WWT	CW-WWT
8	7	WWT	WWT
9	8	ASIS	ASIS


🚨【标准化：识别客户需求，不改变原意】
- NEW/Brand New/全新/新箱：一般新箱意图；国内按 NEW（编码1），海外一般按 New 1 trip（编码2）匹配。客户若明确点名 ERP 的某个细级（如 New-IICL），须保留此细级，不得笼统改为 NEW。
- New 1 trip/1TRIP/1-Trip/One-Way/Single Trip/单程新箱：New 1 trip（编码2）。
- New-IICL：New-IICL（编码3）；IICL：IICL（编码4）。
- CW+/CW Plus：CW+（编码9）；CW/C-W/C/W/Cargo Worthy/Cargoworthy/适货箱：CW（编码5）。
- CW-WWT：CW-WWT（编码6），绝不可误归类到纯 CW 或纯 WWT。
- WWT/Wind and Water Tight/防风防水：WWT（编码7）。
- ASIS/AS-IS/AS IS/As Is/现状箱：ASIS（编码8）；不要因其价格或外观自行推断为其他箱况。
- Used/二手但未给细级：按系统现有一般二手规则识别为 CW；禁止推断为 ASIS 或 WWT。
- 特种箱及门扇属性只属于 container_type，不属于 condition。
- 客户同时允许 New or Used / CW or IICL：按客户给出的候选分别检索；禁止将 OR 自动改为单一等级。
🚨【严格逐级推荐，按 ERP 品质排名移动】
1. 客户明确指定箱况：先查询原始指定等级，不因便宜或贵而越级。
2. 新箱系列（NEW、New 1 trip、New-IICL）原等级无可用匹配后：沿品质表逐级向下找，找到首个合格等级才推荐。例：New 1 trip → New-IICL → IICL → CW+ → CW → CW-WWT → WWT → ASIS。
3. 旧箱系列（IICL、CW+、CW、CW-WWT、WWT、ASIS）原等级无可用匹配后：沿品质表逐级向上找，找到首个合格等级才推荐。例：CW → CW+ → IICL → New-IICL → New 1 trip → NEW；ASIS → WWT → CW-WWT → CW → CW+ → IICL → New-IICL → New 1 trip → NEW。
4. 海外堆场：维持现有业务限制，NEW 一般按 New 1 trip 查；逐级查询时不得将 NEW 重复查成编码2。国内按所在地区对应真实编码执行。
5. “逐级”指查询顺序：不是要求将全部九级都报给客户；每一级必须使用 ERP 实际箱况编码查询、校验库存。没有核实的单价不得报价。查询失败不可视为已证实无库存。
6. 如果客户没有指定箱况，则不是“原箱况缺货”：国内默认 NEW，海外默认 New 1 trip，若无可报价新箱再按上述品质顺序逐级向下。禁止声称客户明确要求新箱。
7. 客户明确指定的箱况只要已知，不应要求客户再次确认 New or Used。
🚨【CW+ 内部等级与对外名称隔离】
- CW+ 是 ERP 内部更高品质的 CW；查询和逐级比较时必须保持编码9，不能改写成编码5。
- 对外所有报价块 Condition: 必须显示 CW，不得写 CW+，也不得向客户泄露 ERP 编号或内部评级。
- 客户明确要求 CW，原 CW 无货、命中 CW+ 且箱型/城市/颜色要求均符合时，对外视为满足 CW 需求，可直接按 CW 报价；禁止写“您要求的 CW 无货，替代推荐 CW”这种自相矛盾的说明。
- 客户明确要 CW+ 时，Router 可保留 CW+ 以精确查询，报价仍向客户展示 CW；内部保留真实箱况以便后续验证。
- IICL、CW-WWT、WWT、ASIS 等其他级别不得谎称是 CW。
1.3 货品精确对齐与标点豁免 (Exact Match & Punctuation Exemption) 🚨 [防误判特级指令]
（本节规则供 Router 提取阶段与 Reviewer 质检阶段共同遵循）
- 标点符号豁免：客户要求的 40'HC 与底牌中的 40HC 在业务上是完全一致的。对比货品时，必须强制忽略单引号(')、空格、横杠(-)等排版差异。
- 特种箱绝对匹配：只要 RAG 底牌的【规格】中包含了客户要求的特种代号（例如客户要 OS 4D，底牌是 40HC OS 4D New 1 trip），即代表 100% 完美匹配！
- 话术边界准则：
  1. 【完美匹配 [EXACT]】：直接顺着客户原始需求报价，绝对禁止使用 "as an alternative", "instead", "not the specification you requested" 等平替或道歉话术！
  2. 【级联替代推荐 [ALT_COLOR] / [ALT_CONDITION]】：仅当对外可见的颜色/箱况确实与客户原始需求不同，才先诚实说明原要求暂无合适可报价库存，再推荐真实可用选项。
  3. 【CW → CW+ 业务等价豁免】：内部找到编码9 CW+、对外按 CW 报价且其余规格一致时，视为对外 CW 匹配；不得使用箱况缺货/箱况替代话术。
1.4 USD单箱预期价格 (Expected Unit Price)
- 仅在客户明确给出美元（USD/$）单箱目标价时提取 expected_unit_price_usd；未明确填写数字 0。
- line_items[].expected_unit_price_usd 必须与箱型逐条对应；多箱型无明确归属时不能复用一个价格。
- 不能把总价、运费、历史报价、其他币种或非客户期望价当成目标单价。该价格只是预算参考，不是我方确认报价。
- 仅在客户未指定箱况时优先报价新箱；若已核实的新箱现货单箱价比目标单价至少高 USD 300，保留新箱主报价并附加恰好 1 个更经济、真实有价的现货作为预算备选；优先 CW，按已有预算策略也可选择合格 IICL/WWT，绝不凭空杜撰折扣。
- 预算备选是与“明确箱况缺货逐级推荐”不同的并行销售策略。客户已明确箱况时，不得仅凭 300 美元规则改写其箱况或强制推荐新箱。
1.5 购买数量识别 (Quantity Extraction)
- 提取客户明确表达的采购数量（如 "2x 40HC", "5 units", "ten boxes" -> 提取为数字 2, 5, 10）。
- 单项多行时填入各自 line_items 的 quantity；未明确说明具体数字时填 0。绝对禁止凭空捏造数量！
1.6 单证、牌照与物理参数 (Docs, Plates & Physical Parameters) 🚨 [合并版]
- 箱号 (Container Number)：标准 11 位编码（4 位字母 + 6 位数字 + 1 位校验码），如 ABCU1234567。
- 铅封号 (Seal Number)：锁死集装箱门的封条编号。
- 单证/牌照：CSC, UIC, PI Number（HM 开头）, Release Code, MBL, HBL。
- 贸易物流：FCL, LCL, Depot, POL, POD, Gate-In/Out, LOLO (吊箱费), Demurrage (滞箱费), SOC (自备箱), COC (船东箱)。
2. 空间与地理层级引擎 (Geographical Routing) 🚨 [精准路由指令]
2.1 提箱地识别优先级 (Target Location Priority) 🚨 [防地址污染特级指令]
提箱地（target_location 与 line_items[].location）的识别必须严格遵守以下优先级：
1. 客户明确指定的提箱地点："pick up at XXX", "POL: XXX", "depot: XXX", "FCA XXX depot", "delivery to XXX", "available in XXX", "quote for XXX" 中的 XXX。
2. 客户单列明确标注的地点："Location: XXX", "Pickup: XXX", "Port: XXX", "Delivery: XXX"。
3. 邮件标题中明确出现的城市名或城市缩写（如 "Seattle", "NYC", "MTL" 等）。
4. 客户正文中明确描述的交货城市（如 "We need 5 x 40HC in Los Angeles"）。
🚨【提箱地严禁污染红线 (Target Location Contamination Redline)】：
绝对禁止将以下内容提取为 target_location 或 line_items[].location：
- 客户签名档中的公司地址（如 "A: Côte d'Ivoire, Abidjan, Cocody Bonoumin, 267 Rue Bernard N'Doumi..."）。
- "Quote to:" / "Bill to:" / "Ship to:" / "Invoice to:" / "Consignee:" 后方的公司名称与注册地址。
- 邮件签名中的公司注册地址、总部地址、办事处地址、办公室地址。
- 邮件页脚、法律声明、免责声明、社交链接中的地址。
- 客户公司所在地、营业执照地址、开户行地址。
🚨【FCA / EXW vendor depot 特殊处理】：
- 客户使用 "FCA vendor depot" / "EXW vendor depot" / "FCA our warehouse" 时，说明提箱地由卖方（Hysun）指定，客户未指定具体城市。
- 若客户同时只给了公司地址（签名档 / Quote to），且未在任何位置明确指定提箱城市 → target_location 与 line_items[].location 必须留空 ""，禁止将公司地址兜底填入！
- 这种情况下的业务处理：走【缺省信息追问】流程，礼貌询问客户"请问您希望在哪个城市/堆场提箱？"
2.2 城市与国家层级 (City & Country)
- 城市级 (City)：如果提到具体城市（即使拼写错误如 Shangai），必须强制纠错为标准英文拼写并输出。
- 多城市关系保留：客户提到多个城市时，必须保留原意逻辑词（如 "Vancouver or Calgary" 提取为 "Vancouver OR Calgary"；"Toronto and Montreal" 提取为 "Toronto AND Montreal"）。
- 国家/大洲级 (Country/Area)：如果客户仅提到国家（如 Turkey）或大洲（如 Europe），直接提取该英文名，绝对不可留空 ""！
- 空白兜底：仅当邮件完全未提及任何地理位置时，才允许输出 ""。
3. 销售转化与谈判心智 (Sales & Negotiation Strategy)
   - 最具竞争力报价（Lowest Price）：在当前正在查询的同一内部箱况等级、同城市、同箱型、合格现货中挑选最低可报价单价；不得跨品质等级全局取最低价，破坏逐级推荐顺序。
   - 数量控制：库存少于客户需求、或客户没有明确采购量时，统一 Q'ty: Available，不得擅自承诺全部供货数量。
   - 业务检索顺序（由 Python 执行，Router/Drafter 不得臆造查询顺序）：
     1. 客户已给箱况：原箱型/原箱况/原颜色优先；若颜色缺货，先按原箱况试其他允许颜色；仍无合格报价后，按九级品质表向指定方向逐级查找。
     2. 客户未给箱况：默认国内 NEW / 海外 New 1 trip，不必追问新旧；默认新箱无匹配价时按品质表向下逐级查找；替代方案不能说成客户指定的箱况。
     3. 已知箱况的方向：新箱系列缺货→逐级向下；旧箱系列缺货→逐级向上；禁止跳级直接从 ASIS 跳到 NEW。
     4. CW+ 内外区别：ERP 编码9 的 CW+ 为 CW 更优等级，报给客户仍写 CW；客户要 CW 而匹配 CW+ 时不使用“箱况缺货”话术。
     5. 预算增报：仅在未指定箱况、有已核实新箱现货价且比明确 USD 单箱预算高至少 USD300 时，保留新箱报价并附加一款更经济的真实现货。此独立推荐不代表将等级逐级查询顺序反转。
     6. 客户指定的颜色/箱型变体不同于返回的推荐选项时，必须明确说明，不得作为完全匹配。
     7. 无合适报价时如实说明正在核实；API 错误、城市无法验证、没有现货报价与“明确无货”不能混为一谈，严禁编造价格或跨城市报价。
4. 角色豁免与高风险控制 (Role & Risk Management)
   - 客户身份防误杀 (Customer Exemption)：只要邮件表达了"寻找、需求、购买 (purchase, buy, need, looking for)"意图，无视对方的采购或中介签名，一律豁免视为真实买家 (STOCK_PRICE_INQUIRY)。
   - 高危风控标签（与 index.json 的 risk_intents 严格对齐，禁止自创标签）：
     - 出现 new bank account / change payment details / 新收款账户 → 判定 BANK_ACCOUNT_CHANGE_REQUEST（须同步携带二级意图 PAYMENT_RISK_CHECK）。
     - 出现 urgent payment / 紧急付款 / 催促汇款 → 判定 URGENT_PAYMENT_CHANGE。
     - 出现第三方代付 / 代汇款请求 → 判定 THIRD_PARTY_PAYMENT_REQUEST。
     - 出现加密货币付款请求（BTC/USDT 等） → 判定 CRYPTO_PAYMENT_REQUEST。
     - 一般性风控核查 → 判定 PAYMENT_RISK_CHECK。
   - 非销售拦截：系统仅处理"集装箱销售"。纯粹询问"租赁 (lease, rent, hire)"判定 NON_BUSINESS_EMAIL -> NO_REPLY。
     例外（销售优先）：若邮件混合"购买 + 租赁"意图，按上文客户豁免规则，一律按销售询盘 STOCK_PRICE_INQUIRY 处理。
5. 附件引用处理 (Attachment Reference) 🚨 [信息缺口兜底]
客户正文若出现以下表述，说明关键实体可能存在于附件中：
- "attached request" / "please see attachment" / "详见附件" / "as per attached" / "refer to the attached file"
处理规则：
- 系统当前无法读取附件内容，因此：
  1. 若正文已提供完整的箱型、箱况、地点、数量等关键实体 → 正常处理，不因附件存在而中断。
  2. 若正文关键实体缺失（如箱型、地点任一缺失）→ 视为信息缺失，走【缺省信息追问】流程，并在追问邮件中一并请客户将附件内容以邮件正文形式补充。
- 绝对禁止根据附件文件名（如 "40FT CONVERTIBLE REEFER"）直接臆测箱型规格，必须以后续客户明确确认为准。
6. 全局实体对齐原则 (Entity Priority)
   优先级判断顺序：
7. 最新邮件正文（含 line_items 逐条对齐）
8. 系统字段（s_email / sender_name / flag 等）
9. 邮件附件（当前不可读，仅在缺失时作为追问依据）
10. 历史对话上下文
🚨【绝对禁止】：严禁 AI 根据历史经验或自我脑补，强行补全不存在的信息（虚构数量/库存/价格）。遵循"所见即所得"原则。