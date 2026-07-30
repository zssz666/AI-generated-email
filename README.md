# 📧 Hysun AI Email Agent v3.0

![Version](https://img.shields.io/badge/version-3.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.8%2B-green.svg)
![LLM](https://img.shields.io/badge/LLM-DeepSeek_Chat-blueviolet)

Hysun AI Email Agent 是一个专为国际贸易和集装箱销售业务打造的 **企业级 AI 自动化邮件中枢**。

本项目摒弃了传统的单体 Prompt 模式，采用了 **4-Stage Pipeline 架构** 与 **RAG 实时库存引擎**，结合了严苛的 **SOP 守卫机制 (Response Guard)**，彻底杜绝了大模型在商业谈判中可能产生的“幻觉”（如虚构价格、伪造集装箱号、越权承诺付款等），确保每一封对外发出的邮件 100% 严谨、合规。

---

## ✨ 核心亮点特性 (Core Features)

- 🧠 **Multi-Intent Router (多意图降维路由)**
  精准穿透复杂邮件中的多个业务诉求（例如：一封邮件同时包含“索要提箱号”与“确认最新发票”），并通过实体引擎精确提取箱型（包含特种箱后缀）、数量与目的地。拦截无效邮件及平台自动通知。
- 📊 **RAG Dynamic Pricing (实时库存与商业博弈心智)**
  AI 不仅仅是回复机器，更是王牌销售。系统实时调用后端 API 抓取底层库存数据，自动执行**“最具竞争力报价策略”（寻找最低底价）**及**“饥饿营销策略”（当库存少于客户需求时自动隐藏具体库存数量）**。
- 🛡️ **Response Guard v3.0 (AI 交叉审查守卫)**
  采用创新的双 AI 互搏机制。在草稿发出前，独立的 Reviewer 引擎将依据企业红线规则库，严格审核是否存在“付款承诺越权”、“未授权的放箱确认”等致命错误。验证失败则直接拦截重写。
- 🚨 **Bank Security Mode (零容忍银行风控)**
  内置高风险实体嗅探，一旦发现供应商尝试变更银行账户、修改受益人或发送紧急付款指令，立即阻断常规业务流，强制切入安全二次验证模式。
- 🔌 **Dynamic API & DeepSeek 驱动**
  基于 DeepSeek 模型（完美兼容 OpenAI SDK），提供高并发、高推理能力的极高性价比解决方案。

---

## 🏗️ 系统架构图 (Architecture Pipeline)

系统以 **4-Stage** 严密流水线处理海量邮件：

1. **Stage 1: Intent Router** - 解构邮件文本，输出 JSON 结构化数据（主意图、次要意图、风险等级、多维业务实体）。
2. **Stage 2: Skill Aggregator** - 基于路由结果，从 `skills/` 目录动态加载精准的业务 SOP（包含询价、议价、放箱、对账、投诉等 7 大核心模块）。
3. **Stage 3: Draft Generator** - 融合 RAG 检索的实时货柜库存、地理位置纠错库及业务规则，生成高度专业且带有谈判心智的商务草稿。
4. **Stage 4: Response Reviewer** - “质检员” AI 入场，依据 `response_guard.md` 进行无死角合规审查。审查 PASS 后，写入数据库等待自动化发送。

---

## 📂 核心知识库结构 (Skills Directory)

系统通过外置 Markdown 知识库实现逻辑与代码解耦，业务人员可随时维护 SOP：

```text
skills/
├── index.json                        # 路由网关、意图优先级及配置定义
├── global_rules.md                   # 全局 AI 基础规则 (红线控制、签名规范)
├── entity_rules.md                   # 业务实体抽取 (v6.0 特种箱强制对齐、标点豁免)
├── response_guard.md                 # 审查守卫红线 (v3.0 Reviewer 审核标准)
│
└── modules/                          # 垂直业务 SOP 模块
    ├── 01_sales_inquiry.md           # 售前询价、新造箱规则与报价跟进
    ├── 02_order_and_commission.md    # 订单确认、中介佣金保护与延期请求
    ├── 03_fulfillment_and_ops.md     # 放箱履约、提箱计划跟踪与单证流转
    ├── 04_complaint_and_aftersales.md# 坏箱投诉、订单取消与费用协商
    ├── 05_vendor_finance_soa.md      # 供应商对账、催款防守与状态同步
    ├── 06_vendor_procurement.md      # 采购发票审核、放箱安全与防诈骗模式
    └── 07_finance_payment.md         # 财务付款状态同步与打款凭证流转