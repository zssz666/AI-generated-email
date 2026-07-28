import json
import os
import pymysql
from dotenv import load_dotenv
from openai import OpenAI

# ==========================================================
# 1. 环境配置
# ==========================================================
load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

ai_client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL
)

# ==========================================================
# 2. 数据库配置
# ==========================================================
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASS"),
    "database": os.getenv("DB_NAME"),
    "charset": "utf8mb4",
    "autocommit": False
}

TABLE_NAME = "e_track"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.join(BASE_DIR, "skills")


# ==========================================================
# 3. Skill系统加载
# ==========================================================
def get_index_config():
    path = os.path.join(SKILLS_DIR, "index.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("[index.json加载失败]", e)
        return {}


def load_skill_file(filename):
    path = os.path.join(SKILLS_DIR, filename)
    if not os.path.exists(path):
        print(f"[Skill不存在] {path}")
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_global_rules():
    cfg = get_index_config()
    return load_skill_file(cfg.get("global_rules_file", "global_rules.md"))


def load_response_guard():
    cfg = get_index_config()
    return load_skill_file(cfg.get("response_guard_file", "response_guard.md"))


def load_entity_rules():
    cfg = get_index_config()
    return load_skill_file(cfg.get("entity_rules_file", "entity_rules.md"))


def load_module(module_path):
    return load_skill_file(module_path)


# ==========================================================
# 4. Stage 1: Multi Intent Router
# ==========================================================
def predict_intent(e_title, e_content):
    cfg = get_index_config()
    valid_intents = list(cfg.get("intent_to_module", {}).keys())

    router_schema = cfg.get("router_output_schema", {})
    non_business_cfg = cfg.get("non_business_config", {})
    router_config = cfg.get("router_config", {})

    router_prompt = f"""你是Hysun企业邮件意图识别引擎。

你的任务：
分析邮件标题和正文，识别主要意图、次要意图、实体信息以及动作指令。

合法意图列表：
{json.dumps(valid_intents, ensure_ascii=False, indent=2)}

非业务邮件规则：
{json.dumps(non_business_cfg, ensure_ascii=False, indent=2)}

路由配置 (优先级与多意图限制)：
{json.dumps(router_config, ensure_ascii=False, indent=2)}

必须严格输出 JSON 格式，结构如下：
{json.dumps(router_schema, ensure_ascii=False, indent=2)}

规则：
1. 【最高指令 - 身份拦截】：系统当前仅服务于客户(Customer)。如果邮件来自供应商(Vendor)或中介(Intermediary)，或者涉及催款、发票对账，primary_intent 必须是 NON_CUSTOMER_EMAIL，action 必须强制输出 NO_REPLY！
2. 【最高指令 - 业务拦截】：系统仅处理“销售(Sale)”业务，不处理“租赁(Lease/Rent)”业务。如果客户询问租赁集装箱(如提及 lease, rent)，primary_intent 必须是 LEASE_INQUIRY，action 必须强制输出 NO_REPLY！
3. 如果匹配到非业务邮件(如营销、平台通知)，primary_intent 必须是 NON_BUSINESS_EMAIL，action 必须是 NO_REPLY。
4. 只有当确定对方是 Customer 且询问买卖业务时，action 才允许是 REPLY。
5. 如果邮件包含多个请求，请在 secondary_intents 中列出。不要解释。不要输出 Markdown。禁止猜测不存在的实体信息。
"""

    try:
        response = ai_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": router_prompt},
                {"role": "user", "content": f"邮件标题：{e_title}\n\n邮件正文：{e_content}"}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        data = json.loads(content)
        return data
    except Exception as e:
        print("[Router异常]", e)
        return {
            "primary_intent": "STOCK_PRICE_INQUIRY",
            "secondary_intents": [],
            "action": "REPLY",
            "risk_level": "LOW",
            "entities": {}
        }


# ==========================================================
# 5. Stage 2: Skill Aggregator (多意图加载业务SOP)
# ==========================================================
def build_skill_context(router_result):
    cfg = get_index_config()
    intent_map = cfg.get("intent_to_module", {})
    modules = []
    used_modules = set()
    intents = []

    primary = router_result.get("primary_intent")
    if primary:
        intents.append(primary)

    secondary = router_result.get("secondary_intents", [])
    if isinstance(secondary, list):
        intents.extend(secondary)

    for intent in intents:
        module_path = intent_map.get(intent)
        if module_path and module_path not in used_modules:
            module_content = load_module(module_path)
            if module_content:
                modules.append(
                    f"\n==============================\n业务模块:{intent}\n文件:{module_path}\n==============================\n{module_content}\n")
                used_modules.add(module_path)

    return "\n".join(modules)


# ==========================================================
# 6. Stage 3: AI邮件生成
# ==========================================================
def generate_draft_reply(e_title, e_content, router_result):
    # 如果意图识别为无需回复，则直接短路处理，节省 Token
    if router_result.get("action") == "NO_REPLY" or router_result.get("primary_intent") in ["NON_BUSINESS_EMAIL",
                                                                                            "NON_CUSTOMER_EMAIL",
                                                                                            "LEASE_INQUIRY"]:
        return "NO_REPLY"

    global_rules = load_global_rules()
    response_guard = load_response_guard()
    entity_rules = load_entity_rules()
    module_context = build_skill_context(router_result)

    system_prompt = f"""你是Hysun企业邮件助手。

你的任务：
根据客户邮件，生成可以直接发送的商务回复。

========================
【全局规则】
{global_rules}

========================
【实体识别规则】
{entity_rules}

========================
【回复安全控制】
{response_guard}

========================
【业务SOP】
{module_context}

========================

当前邮件分析结果：
{json.dumps(router_result, ensure_ascii=False, indent=2)}

生成要求：
1. 只输出邮件正文。禁止解释、Markdown 及分析过程。
2. 必须回复邮件中的所有请求。不得添加原邮件没有的信息。
3. 不得承诺：已付款、已放箱、已确认提货、已批准费用，除非邮件中明确提供了证据。
4. 签名必须符合业务角色(Hysun Sales/Operations/Support Team)。
"""

    try:
        response = ai_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"邮件标题:{e_title}\n\n邮件正文:{e_content}\n\n请生成回复。"}
            ],
            temperature=0.2,
            max_tokens=800
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("[邮件生成失败]", e)
        return None


# ==========================================================
# 7. Stage 4: Response Reviewer (AI二次审查)
# ==========================================================
def review_ai_reply(original_title, original_content, draft_reply, router_result):
    if draft_reply == "NO_REPLY":
        if router_result.get("action") == "NO_REPLY":
            return True, "Correctly identified as NO_REPLY"
        else:
            return False, "Generated NO_REPLY but Router indicated REPLY"

    review_prompt = """你是 Hysun 企业的邮件质量审核专家 (Response Guard)。
    你的任务是严格审查 AI 生成的邮件草稿是否符合企业合规要求，并决定是否可以直接发送给客户。

    审核标准 (致命错误)：
    1. 错误处理非客户邮件：当前系统仅限回复客户(Customer)。
       -> 【身份界定】：向我们询价、寻找箱子 (looking for containers)、要求我们提供报价 (send us your price/offer) 的都是【客户】，属于合法业务！只有当发件人是向我们索要欠款、发送发票(invoice)的供应商，或是要佣金的中介时，才必须 FAIL！
    2. 错误处理无需回复：如果是自动通知/营销邮件，AI没有输出 NO_REPLY。
    3. 遗漏核心问题：草稿完全没有提及原邮件中的主要请求。
       -> 【重要例外声明】：如果草稿中说明了“正在与内部团队确认 (checking with our team)”、“内部审核中 (reviewing internally)”，或者“追问了缺失信息（如确认数量）”，这属于完全合规的业务防守，绝对不属于遗漏请求！
    4. 虚假承诺：承诺了原邮件中不存在的付款完成、放箱完成或具体日期。
    5. 高危操作：未经授权确认了银行信息更改。
    6. 捏造数据：捏造了不存在的价格、金额、提单号或集装箱号。
    7. 越权决策：擅自同意退款、打折或承担额外费用。

    必须严格输出 JSON 格式：
    {
      "status": "PASS", // 或者 "FAIL"
      "feedback": "如果 FAIL，请用一句话指出具体违反了哪条标准，并给出修改建议。如果 PASS，则输出空字符串。"
    }
    """

    try:
        response = ai_client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": review_prompt},
                {"role": "user",
                 "content": f"原邮件标题：{original_title}\n原邮件正文：{original_content}\n\nAI生成草稿：\n{draft_reply}"}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )

        result_content = response.choices[0].message.content
        data = json.loads(result_content)
        status = data.get("status", "FAIL").upper()
        return status == "PASS", data.get("feedback", "")
    except Exception as e:
        print("[审核系统异常]", e)
        return True, "Review system failed, allowing pass"


# ==========================================================
# 8. 最终生成入口
# ==========================================================
def generate_ai_reply(e_title, e_content):
    print("Stage 1: Intent Router...")
    router_result = predict_intent(e_title, e_content)
    print("Router Result:")
    print(json.dumps(router_result, ensure_ascii=False, indent=2))

    print("Stage 2/3: Generate Draft...")
    draft = generate_draft_reply(e_title, e_content, router_result)
    if not draft:
        return None

    print("Stage 4: Reviewing...")
    print("\n====== AI Draft ======\n" + draft + "\n======================\n")

    passed, feedback = review_ai_reply(e_title, e_content, draft, router_result)

    if passed:
        return draft
    else:
        print(f"[Reviewer 拒绝该回复] 原因: {feedback}")
        return None


# ==========================================================
# 9. 测试预览模式
# ==========================================================
def test_preview_emails():
    conn = None
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            sql = f"""
            SELECT e_id, e_title, e_content
            FROM {TABLE_NAME}
            WHERE ai_status = 0 AND flag = 0 and e_id = 647
            ORDER BY uptime DESC, e_id ASC
            LIMIT 1;
            """
            cursor.execute(sql)
            emails = cursor.fetchall()

            if not emails:
                print("暂无待处理邮件")
                return

            for email in emails:
                e_id = email["e_id"]
                title = email.get("e_title", "")
                content = email.get("e_content", "")

                print("\n" + "=" * 80)
                print(f"正在测试邮件ID:{e_id}")
                print("=" * 80)
                print("\n【标题】\n", title)
                print("\n【正文】\n", content)
                print("\n" + "-" * 80)
                print("AI处理中...")

                reply = generate_ai_reply(title, content)
                if reply:
                    print("\n【最终确认回复 (PASS)】\n", reply)
                else:
                    print("\n【AI生成中断或被Reviewer拦截】")
                print("=" * 80)
    except Exception as e:
        print("[Preview数据库错误]", e)
    finally:
        if conn:
            conn.close()


# ==========================================================
# 10. 正式生产处理模式
# ==========================================================
def process_pending_emails():
    conn = None
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            sql = f"""
            SELECT e_id, e_title, e_content
            FROM {TABLE_NAME}
            WHERE ai_status = 0 AND flag = 0
            ORDER BY uptime DESC
            LIMIT 1
            FOR UPDATE;
            """
            cursor.execute(sql)
            email = cursor.fetchone()

            if not email:
                return False

            e_id = email["e_id"]
            title = email.get("e_title", "")
            content = email.get("e_content", "")

            print(f"开始处理邮件:{e_id}")

            cursor.execute(
                f"UPDATE {TABLE_NAME} SET flag = 2,ai_status = 1 WHERE e_id=%s",
                (e_id,)
            )
            conn.commit()

            reply = generate_ai_reply(title, content)

            if reply:
                if reply == "NO_REPLY":
                    cursor.execute(
                        f"UPDATE {TABLE_NAME} SET ai_reply=%s, ai_status=4, uptime=NOW() WHERE e_id=%s",
                        (reply, e_id)
                    )
                    print(f"[跳过回复] {e_id} 识别为 NON_BUSINESS_EMAIL 或 NON_CUSTOMER_EMAIL")
                else:
                    cursor.execute(
                        f"UPDATE {TABLE_NAME} SET ai_reply=%s, ai_status=2, uptime=NOW() WHERE e_id=%s",
                        (reply, e_id)
                    )
                    print(f"[成功] {e_id}")
            else:
                cursor.execute(
                    f"UPDATE {TABLE_NAME} SET ai_status=3, uptime=NOW() WHERE e_id=%s",
                    (e_id,)
                )
                print(f"[失败/被拦截] {e_id}")

            conn.commit()
            return True
    except Exception as e:
        print("[生产处理错误]", e)
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()


# ==========================================================
# 10. 粘贴测试模式
# ==========================================================
def test_static_email():
    print("\n" + "=" * 80)
    print(" 📧 本地测试模式")
    print("=" * 80)

    # --------------------------------------------------
    # ↓↓↓ 请在此处直接粘贴您的测试邮件标题和正文 ↓↓↓
    # --------------------------------------------------
    title = "Looking 40'HC CW and young IICL in Shangai"

    content = """
Good afternoon

 

Hope this email finds you well and safe.

 

We are looking 40'HC CW and young IICL in Shangai form the below depots:

 

Depot Name

Depot Address

Brilliant No.6  depot

No. 2100 Hua Dong road, PuDong, Shanghai, China

Lichang  No. 3 depot

No.711,Dong Tang  Road,Shanghai,China 200137

ZIDONG

Yangshan depot          NO 2761 Wusi Road

ZIDONG

Luchaogang Jiangshan depot NO 678 Yuyu Road

 

If you have something to offer us, please send us your offer with prices.    

           

Many thanks in advance ☺

 

 

Best Regards,

Nathaly Alfonso
    """
    # --------------------------------------------------

    print("\n【标题】\n", title)
    print("\n【正文】\n", content)
    print("\n" + "-" * 80)
    print("AI处理中...")

    reply = generate_ai_reply(title, content)

    if reply:
        print("\n【最终确认回复 (PASS)】\n", reply)
    else:
        print("\n【AI生成中断或被Reviewer拦截】")
    print("=" * 80)


# ==========================================================
# 11. 程序入口
# ==========================================================
if __name__ == "__main__":
    print("================================")
    print(" Hysun AI Email Agent")
    print("================================")

    # 您可以在这里自由切换想要运行的方法：
    test_static_email()  # <- 临时测试某封特定邮件
    # test_preview_emails()   # <- 从数据库拉取未处理邮件进行预览
    # process_pending_emails() # <- 生产环境处理入库
