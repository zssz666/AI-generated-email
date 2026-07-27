# 📧 Hysun AI Email Agent v2.0

![Version](https://img.shields.io/badge/version-2.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.8%2B-green.svg)
![LLM](https://img.shields.io/badge/LLM-DeepSeek_Chat-blueviolet)

Hysun AI Email Agent 是一个专为国际贸易和集装箱租赁/销售业务设计的**企业级 AI 邮件自动化处理系统**。

与普通的 AI 对话机器人不同，本项目采用了严格的 **SOP（标准作业程序）驱动** 和 **Response Guard（响应守卫）审核机制**，彻底杜绝 AI 在商务沟通中可能产生的“幻觉”（如虚构价格、伪造集装箱号、越权承诺付款等），确保每一封发出的邮件都 100% 符合企业合规要求。

---

## ✨ 核心特性 (Core Features)

- 🧠 **Multi-Intent Router (多意图路由):** 能够精准识别一封邮件中的多个业务诉求（如：同时包含“确认付款”与“索要提箱号”），并拦截无效的非业务邮件（如系统通知、营销广告）。
- 📚 **Skill Aggregator (SOP 聚合器):** 根据识别出的意图，动态组合加载对应的业务处理规则（Modules 01-07），AI 仅在当前业务上下文内生成回复。
- 🛡️ **Response Guard (响应守卫):** 独创的 AI 二次审查机制（Reviewer）。在邮件发出前，Reviewer 会根据致命错误清单（如虚假承诺、越权决策、忽视核心诉求）进行拦截，验证失败则拒绝发送。
- 🚨 **Bank Security Mode (银行安全模式):** 内置敏感信息嗅探，一旦发现供应商尝试变更银行账户或收款人，立即阻断常规流程，触发安全二次验证。
- 🔌 **DeepSeek API 驱动:** 基于 DeepSeek 模型（兼容 OpenAI SDK），提供极高的性价比与逻辑推理能力。

---

## 🏗️ 系统架构 (Architecture)

系统采用 **4-Stage Pipeline** 架构处理每一封邮件：

1. **Stage 1: Intent Router** - 分析邮件标题和正文，输出 JSON 格式的主要意图、次要意图、提取实体以及风险等级。
2. **Stage 2: Skill Aggregator** - 解析 `skills/index.json`，根据意图映射表动态拼接全局规则、实体规范、防越权守卫以及具体业务 SOP。
3. **Stage 3: Draft Generator** - 结合上下文环境与原邮件，严格按照要求生成符合语境、专业且安全的邮件草稿。
4. **Stage 4: Response Reviewer** - 另一个独立的 AI 视角对草稿进行“挑刺”，若发现违反 SOP（如捏造日期、过度承诺），则直接拦截（返回 FAIL）。只有 PASS 的邮件才会入库等待发送。

---

## 📂 目录结构 (Directory Structure)

```text
hysun-ai-email-agent/
│
├── main.py                  # 核心主程序 (Pipeline 调度与 DB 交互)
├── .env                     # 环境变量配置文件 (API Keys & DB)
│
└── skills/                  # AI 技能与规则知识库
    ├── index.json           # 全局路由、意图映射与 schema 配置
    ├── global_rules.md      # 全局 AI 基础规则 (禁止项、签名规范)
    ├── entity_rules.md      # 业务实体识别规则 (箱号、发票、金额)
    ├── response_guard.md    # 回复审查红线 (Reviewer 审核标准)
    │
    └── modules/             # 垂直业务 SOP 模块
        ├── 01_sales_inquiry.md         # 售前询价与报价跟进
        ├── 02_order_and_commission.md  # 订单确认、发票与佣金
        ├── 03_fulfillment_and_ops.md   # 放箱履约与过户
        ├── 04_complaint_and_aftersales.md # 投诉与费用协商
        ├── 05_vendor_finance_soa.md    # 供应商对账与催款
        ├── 06_vendor_procurement.md    # 采购发票与放箱安全
        └── 07_finance_payment.md       # 付款咨询与状态