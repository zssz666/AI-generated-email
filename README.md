readme_content = """# Hysun AI Email Agent v2.0

![Version](https://img.shields.io/badge/version-2.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![DeepSeek API](https://img.shields.io/badge/LLM-DeepSeek-brightgreen)

Hysun AI Email Agent is an enterprise-grade, multi-stage AI email processing system. It is designed to automatically analyze incoming business emails, classify intents, extract key entities, apply specific business Standard Operating Procedures (SOPs), and generate safe, professional, and context-aware replies.

## 🌟 Core Features

- **Multi-Intent Routing:** Accurately parses complex emails into primary and secondary business intents (e.g., handling an invoice receipt, a wire proof request, and a pickup schedule request all in one email).
- **Dynamic SOP Aggregation:** Modular design that dynamically injects only the necessary business rules based on the identified intents.
- **Strict Response Guard (Reviewer):** A secondary AI review mechanism to absolutely prevent AI hallucinations, unauthorized commitments (like faking a payment or pickup date), or compliance violations.
- **Role-Based Identity:** Automatically detects if the sender is a Customer, Vendor, or Intermediary, adjusting the tone and signature accordingly (e.g., `Hysun Purchasing Team` vs. `Hysun Sales Team`).
- **High-Risk Security Mode:** Automatically flags and isolates high-risk requests, such as bank account changes or urgent payment modifications, requiring secondary human validation.

## 🏗 System Architecture

The system operates on a robust 4-Stage Pipeline:

1. **Stage 1: Intent Router (`predict_intent`)**
   - Analyzes the email subject and body.
   - Extracts `primary_intent`, `secondary_intents`, `entities` (Container specs, Invoices, Release codes), and evaluates `risk_level`.
2. **Stage 2: Skill Aggregator (`build_skill_context`)**
   - Maps the identified intents to specific Markdown-based business modules (e.g., `01_sales_inquiry.md`, `06_vendor_procurement.md`).
3. **Stage 3: Draft Generator (`generate_draft_reply`)**
   - Compiles the Global Rules, Entity Rules, Response Guard rules, and Business Modules into a master prompt to generate the draft reply.
4. **Stage 4: Response Reviewer (`review_ai_reply`)**
   - Evaluates the draft against strict criteria (no fabricated data, no unauthorized approvals). Returns `PASS` or `FAIL`.

## 📂 Project Structure

```text
├── main.py                     # Main application entry point and pipeline logic
├── .env                        # Environment variables (DB config, API Keys)
└── skills/                     # AI Prompt and Rule Directory
    ├── index.json              # Router configuration and intent mapping
    ├── global_rules.md         # Global identity, output, and commitment rules
    ├── entity_rules.md         # Rules for extracting containers, invoices, etc.
    ├── response_guard.md       # Anti-hallucination and security checkpoint rules
    └── modules/                # Business SOP Modules
        ├── 01_sales_inquiry.md
        ├── 02_order_and_commission.md
        ├── 03_fulfillment_and_ops.md
        ├── 04_complaint_and_aftersales.md
        ├── 05_vendor_finance_soa.md
        ├── 06_vendor_procurement.md
        └── 07_finance_payment.md
