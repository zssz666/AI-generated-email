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
    """加载 skills/index.json"""
    path = os.path.join(SKILLS_DIR, "index.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("[index.json加载失败]", e)
        return {}

def load_skill_file(filename):
    """通用md读取"""
    path = os.path.join(SKILLS_DIR, filename)
    if not os.path.exists(path):
        print("[Skill不存在]", path)
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
    """加载业务SOP模块"""
    return load_skill_file(module_path)

# ==========================================================
# 4. Stage 1: Multi Intent Router
# ==========================================================
def predict_intent(e_title, e_content):
    cfg = get_index_config()
    valid_intents = list(cfg.get("intent_to_module", {}).keys())

    router_prompt = f"""你是Hysun企业邮件意图识别引擎。

你的任务：
分析邮件标题和正文。
识别：
1. primary_intent
主要业务类型
2. secondary_intents
邮件中的额外动作
3. entities
提取业务实体
4. risk_level
判断风险

合法意图列表：{json.dumps(valid_intents, ensure_ascii=False, indent=2)}

必须严格输出JSON：
{{
 "primary_intent":"",
 "secondary_intents":[],
 "risk_level":"",
 "entities":{{}}
}}

规则：
- 如果邮件包含多个请求，不允许只返回一个意图。
- 不要解释。
- 不要输出Markdown。
- 不要猜测不存在的信息。
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
            "risk_level": "LOW",
            "entities": {}
        }

# ==========================================================
# 5. Stage 2: Skill Aggregator (多意图加载业务SOP)
# ==========================================================
def build_skill_context(router_result):
    """根据Router结果加载多个业务模块"""
    cfg = get_index_config()
    intent_map = cfg.get("intent_to_module", {})
    modules = []
    used_modules = set()
    intents = []

    primary = router_result.get("primary_intent")
    if primary:
        intents.append(primary)

    secondary = router_result.get("secondary_intents", [])
    intents.extend(secondary)

    for intent in intents:
        module_path = intent_map.get(intent)
        if module_path and module_path not in used_modules:
            module_content = load_module(module_path)
            if module_content:
                modules.append(f"\n==============================\n业务模块:{intent}\n文件:{module_path}\n==============================\n{module_content}\n")
                used_modules.add(module_path)

    return "\n".join(modules)

# ==========================================================
# 6. Stage 3: AI邮件生成
# ==========================================================
def generate_draft_reply(e_title, e_content, router_result):
    global_rules = load_global_rules()
    response_guard = load_response_guard()
    entity_rules = load_entity_rules()
    module_context = build_skill_context(router_result)

    system_prompt = f"""你是Hysun企业邮件助手。

你的任务：
根据客户/供应商邮件，生成可以直接发送的商务回复。

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
1. 只输出邮件正文。
禁止：
- 解释
- Markdown
- 分析过程
2. 必须回复邮件中的所有请求。
3. 不得添加原邮件没有的信息。
4. 不得承诺：
- 已付款
- 已放箱
- 已确认提货
- 已批准费用
除非邮件明确提供。
5. 签名必须符合业务角色。
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
def review_ai_reply(original_title, original_content, draft_reply):
    review_prompt = """
    你是企业邮件质量审核系统。
    你的任务：
    判断下面AI生成邮件是否可以发送。
    只允许两个输出：
    PASS
    或者
    FAIL
    禁止解释。
    审核标准：
    FAIL条件：
    1. 回复没有回答原邮件主要请求
    2. 虚构付款完成
    3. 承诺付款日期
    4. 承诺放箱完成
    5. 修改银行信息
    6. 给出不存在的信息
    7. 严重遗漏客户问题
    如果没有以上问题：
    输出 PASS
    """

    try:
        response = ai_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": review_prompt},
                {"role": "user", "content": f"原邮件：{original_title}\n{original_content}\n\nAI回复：{draft_reply}"}
            ],
            temperature=0,
            max_tokens=20
        )
        result = response.choices[0].message.content.strip().upper()
        return "PASS" in result
    except Exception as e:
        print("[审核失败]", e)
        return True  # 审核失败时不阻塞邮件

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
    print(
        "\n====== AI Draft ======"
    )

    print(
        draft
    )

    print(
        "======================"
    )
    passed = review_ai_reply(e_title, e_content, draft)
    if passed:
        return draft
    else:
        print("[Reviewer拒绝该回复]")
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
            WHERE ai_status = 0 AND flag = 0
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
                    print("\n【AI回复预览】\n", reply)
                else:
                    print("AI生成失败")
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
                f"UPDATE {TABLE_NAME} SET ai_status = 1 WHERE e_id=%s",
                (e_id,)
            )
            conn.commit()

            reply = generate_ai_reply(title, content)

            if reply:
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
                print(f"[失败] {e_id}")

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
# 11. 程序入口
# ==========================================================
if __name__ == "__main__":
    print("================================")
    print(" Hysun AI Email Agent v2.0 ")
    print("================================")
    test_preview_emails()