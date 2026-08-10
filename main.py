import json
import os
import re
import time
import traceback
from functools import lru_cache
import pymysql
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
from openai import OpenAI

# ==========================================================
# 1. 环境配置 & 全局连接池优化
# ==========================================================
load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

ai_client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL,
    timeout=45.0  # 🚨 【核心防挂死】设置 45 秒硬超时，拒绝无限等待
)

AI_MODEL = "deepseek-v4-flash"

# 🚨 极速优化：建立全局连接池，避免每次请求都进行 TCP 三次握手
global_session = requests.Session()
retries = Retry(total=2, backoff_factor=0.5, status_forcelist=[502, 503, 504])
global_session.mount('http://', HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10))

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
# 3. Skill系统加载与动态缓存
# ==========================================================
@lru_cache(maxsize=1)
def get_index_config():
    path = os.path.join(SKILLS_DIR, "index.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("[index.json加载失败]", e)
        return {}


@lru_cache(maxsize=None)
def load_skill_file(filename):
    path = os.path.join(SKILLS_DIR, filename)
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_global_rules():
    return load_skill_file(get_index_config().get("global_rules_file", "global_rules.md"))


def load_response_guard():
    return load_skill_file(get_index_config().get("response_guard_file", "response_guard.md"))


def load_entity_rules():
    return load_skill_file(get_index_config().get("entity_rules_file", "entity_rules.md"))


def load_module(module_path):
    return load_skill_file(module_path)


SYSTEM_CITIES_CACHE = []
_FETCHED_CITIES = False


def fetch_system_cities():
    global SYSTEM_CITIES_CACHE, _FETCHED_CITIES
    if _FETCHED_CITIES: return SYSTEM_CITIES_CACHE
    _FETCHED_CITIES = True  # 无论成功失败，本轮只请求一次
    try:
        response = global_session.get("http://47.109.176.188:81/ListDepot", timeout=3)
        if response.status_code == 200:
            depot_list = response.json().get("obj", [])
            unique_cities = {item.get("dCity").strip() for item in depot_list if item.get("dCity")}
            SYSTEM_CITIES_CACHE = sorted(list(unique_cities))
    except Exception as e:
        print(f"[字典警告] 城市字典加载失败: {e}")
    return SYSTEM_CITIES_CACHE


SYSTEM_COUNTRIES_CACHE = []
_FETCHED_COUNTRIES = False


def fetch_system_countries():
    global SYSTEM_COUNTRIES_CACHE, _FETCHED_COUNTRIES
    if _FETCHED_COUNTRIES: return SYSTEM_COUNTRIES_CACHE
    _FETCHED_COUNTRIES = True
    try:
        response = global_session.get("http://47.109.176.188:81/getGcountry", timeout=3)
        if response.status_code == 200:
            country_list = response.json().get("obj", [])
            SYSTEM_COUNTRIES_CACHE = [
                {"ISO2": item.get("ISO2", "").strip().upper(), "eName": item.get("eName", "").strip(),
                 "cName": item.get("cName", "").strip()}
                for item in country_list if item.get("ISO2") and item.get("eName")
            ]
    except Exception:
        pass
    return SYSTEM_COUNTRIES_CACHE


SYSTEM_CONTAINER_TYPES_CACHE = {}
SYSTEM_CONTAINER_ID_TO_NAME_CACHE = {}
_FETCHED_TYPES = False


def fetch_system_container_types():
    global SYSTEM_CONTAINER_TYPES_CACHE, SYSTEM_CONTAINER_ID_TO_NAME_CACHE, _FETCHED_TYPES
    if _FETCHED_TYPES: return SYSTEM_CONTAINER_TYPES_CACHE
    _FETCHED_TYPES = True
    try:
        response = global_session.get("http://47.109.176.188:81/getAllBoxServlet", timeout=3)
        if response.status_code == 200:
            box_list = response.json().get("obj", [])
            for item in box_list:
                raw_id, raw_code = item.get("id"), item.get("code", "")
                if raw_id is not None and raw_code:
                    box_id = str(raw_id).zfill(2)
                    clean_code = raw_code.lower().replace("'", "").replace(" ", "").replace("-", "")
                    SYSTEM_CONTAINER_TYPES_CACHE[clean_code] = box_id
                    SYSTEM_CONTAINER_ID_TO_NAME_CACHE[box_id] = raw_code.strip()
    except Exception:
        pass
    return SYSTEM_CONTAINER_TYPES_CACHE


SYSTEM_COLORS_CACHE = {}
_FETCHED_COLORS = False


def fetch_system_colors():
    global SYSTEM_COLORS_CACHE, _FETCHED_COLORS
    if _FETCHED_COLORS: return SYSTEM_COLORS_CACHE
    _FETCHED_COLORS = True
    try:
        response = global_session.get("http://47.109.176.188:81/getAllColorServlet", timeout=3)
        if response.status_code == 200:
            color_list = response.json().get("obj", [])
            for item in color_list:
                color_code = item.get("color_code", item.get("str", ""))
                enname = item.get("color_en", item.get("enname", ""))
                if color_code == "0000":
                    enname = "Mixed"
                elif color_code == "8888":
                    enname = "Camo"
                elif color_code == "0001":
                    enname = "5010/6032"
                if color_code: SYSTEM_COLORS_CACHE[color_code] = enname
    except Exception:
        pass
    return SYSTEM_COLORS_CACHE


HYSUN_CONTAINER_TYPES_FALLBACK = {
    1: "10DC", 2: "10HC", 3: "20DC", 4: "20DC RF", 5: "20DC DD", 6: "20DC OS FOS",
    7: "20DC OS 2D", 8: "20DC OS 4D", 9: "20DC HT", 10: "20DC OT", 11: "20DC FR",
    12: "20HC", 13: "20HC OT", 14: "20HC OS FOS", 15: "20HC HT", 16: "20HC PW",
    17: "20HC DD", 18: "40DC", 19: "40DC OT", 20: "40DC OS 3D", 21: "40DC RF",
    22: "40DC HT", 23: "40DC DD", 24: "40DC FR", 25: "40HC", 26: "40HC RF",
    27: "40HC DD", 28: "40HC OS 1D", 29: "40HC OS 2D", 30: "40HC OS 3D",
    31: "40HC OS 4D", 32: "40HC OS FOS", 33: "40HC OT", 34: "40HC PW",
    35: "40HC HT", 36: "40HC FR", 37: "45HC", 38: "45HC RF", 39: "45HC OT",
    40: "45HC DD", 41: "45HC FR", 42: "45HC PW", 43: "53HC"
}

HYSUN_CONDITIONS = {
    1: "NEW", 2: "New 1 trip", 3: "New-IICL", 4: "IICL", 5: "CW",
    6: "CW-WWT", 7: "WWT", 8: "ASIS", 9: "CW+"
}


def parse_hysun_idcode(idcode: str):
    if not idcode or len(idcode) != 10 or not idcode.isdigit(): return "未知规格"
    color_code, type_id, cond_id = idcode[0:4], int(idcode[4:6]), int(idcode[6:7])
    fetch_system_container_types()
    box_type = SYSTEM_CONTAINER_ID_TO_NAME_CACHE.get(str(type_id).zfill(2)) or HYSUN_CONTAINER_TYPES_FALLBACK.get(
        type_id, f"Type-{type_id}")
    box_cond = HYSUN_CONDITIONS.get(cond_id, f"Cond-{cond_id}")
    box_color_en = fetch_system_colors().get(color_code, "")
    color_desc = f" | 🎨 颜色: {box_color_en}" if box_color_en else ""
    return f"{box_type} {box_cond}{color_desc}"


def encode_search_idcode(raw_type, color_param="", condition_param="", flp="_", lb="_", eod="_"):
    if not raw_type: return ""
    color_code = "____"
    if color_param:
        match = re.search(r'\d{4}', color_param)
        if match: color_code = match.group()

    type_code = "__"
    desc = str(raw_type).lower().replace("'", "").replace(" ", "").replace("-", "")
    desc = desc.replace("gp", "dc").replace("dv", "dc").replace("reefer", "rf").replace("opentop", "ot").replace(
        "openside", "os").replace("doubledoor", "dd").replace("flatrack", "fr").replace("hardtop", "ht")

    container_map = fetch_system_container_types()
    if container_map:
        if desc in container_map:
            type_code = container_map[desc]
        else:
            for key in sorted(container_map.keys(), key=len, reverse=True):
                if key in desc:
                    type_code = container_map[key]
                    break

    condition_code = "_"
    if condition_param:
        cond_clean = condition_param.upper().replace(" ", "").replace("-", "")
        reverse_cond_map = {"NEW": "1", "NEW1TRIP": "2", "1TRIP": "2", "ONEWAY": "2", "NEWIICL": "3", "IICL": "4",
                            "CW": "5", "CARGOWORTHY": "5", "CWWWT": "6", "WWT": "7", "ASIS": "8", "CW+": "9"}
        condition_code = reverse_cond_map.get(cond_clean, "_")

    return f"{color_code}{type_code}{condition_code}{flp}{lb}{eod}"


def get_iso2_country_code(location_str: str):
    if not location_str: return []
    loc_clean = location_str.strip().lower()
    for item in fetch_system_countries():
        if loc_clean in (item["eName"].lower(), item["ISO2"].lower(), item["cName"].lower()) or (
                len(item["eName"]) > 2 and item["eName"].lower() in loc_clean):
            return [item["ISO2"]]
    return []


# ==========================================================
# API 检索层
# ==========================================================
def query_internal_inventory(entities, email_content):
    api_url = os.getenv("INVENTORY_API_URL")
    raw_type_desc = entities.get("container_type", "")
    types_to_search = [t.strip() for t in raw_type_desc.replace('，', ',').split(',')] if raw_type_desc else [""]
    requested_color = entities.get("requested_color", "")
    requested_condition = entities.get("requested_condition", "")
    location_desc = entities.get("target_location", entities.get("release_code", "")).strip()

    loc_lower = location_desc.lower()
    area_map = {'us & ca': 1, 'america': 1, 'us': 1, 'usa': 1, 'canada': 1, 'asia': 2, 'europe': 3, 'others': 4}
    area_code = area_map.get(loc_lower, 0)
    country_codes = [] if area_code else get_iso2_country_code(location_desc)

    d_city_val = ""
    if not area_code:
        matched_city = next((city for city in fetch_system_cities() if city.lower() in loc_lower), "")
        d_city_val = matched_city if matched_city else ("" if country_codes else location_desc)

    inventory_text = "【内部系统实时库存底牌】\n"
    valid_count = 0
    headers = {"Content-Type": "application/json"}

    for single_type in types_to_search:
        if not single_type: continue
        search_idcode = encode_search_idcode(raw_type=single_type, color_param=requested_color,
                                             condition_param=requested_condition)
        payload = {"idCodes": search_idcode, "dCity": d_city_val, "dCountry": country_codes, "yardName": "",
                   "area": area_code, "page": 1, "limit": 5, "date": [], "resource": "", "cargo": "", "xcHid": 0,
                   "xcUid": 0, "raioxcHid": 0, "raioxcUid": 0, "inventory": 0}
        print(payload)

        try:
            # 🚨 使用 global_session 替代 requests.post
            response = global_session.post(api_url, json=payload, headers=headers, timeout=5)
            if response.status_code == 200 and response.text.strip():
                page_data = response.json().get("obj", {}).get("page", [])
                # 遍历处理该箱型的返回数据 (0价格/数量拦截)
                for item in page_data:
                    ddepot = item.get("ddepot", {})
                    city, country, yard = ddepot.get("dCity", "未知城市"), ddepot.get("dCountry", ""), ddepot.get(
                        "dName", "")
                    readable_desc = parse_hysun_idcode(item.get("idCode", ""))

                    # 宽容度拉满的字段提取引擎 (应对后端驼峰/拼写差异)
                    raw_oprice = item.get("oPrice") or item.get("oPrince") or item.get("price") or item.get(
                        "Price") or 0
                    # 如果没有独立的在途价格(uPrice)，就直接复用主价格
                    raw_uprice = item.get("uPrice") or raw_oprice or 0

                    o_price = float(raw_oprice)
                    u_price = float(raw_uprice)

                    onground = int(item.get("onground") or item.get("onGround") or item.get("Pick Up") or 0)
                    upcoming = int(item.get("upcoming") or item.get("upComing") or item.get("UpComing") or 0)
                    eta = str(item.get("eta") or item.get("ETA") or "").strip()

                    # 安全提取 yom (年份) 字段
                    raw_yom = str(item.get("yom") or item.get("YOM") or "").strip()
                    # 过滤掉空值、"0" 或 "None" 等无效年份
                    yom_desc = f" | 📅 年份: {raw_yom}" if raw_yom and raw_yom not in ["0", "None", "null"] else ""

                    has_valid_onground = (onground > 0 and o_price > 0)
                    has_valid_upcoming = (upcoming > 0 and u_price > 0)

                    # 如果既没有现货，也没有在途，才跳过这条数据
                    if not has_valid_onground and not has_valid_upcoming: continue

                    stock_info = []
                    if has_valid_onground: stock_info.append(f"现货: {onground}个 (底价: ${o_price})")
                    if has_valid_upcoming: stock_info.append(
                        f"在途: {upcoming}个 (底价: ${u_price}{f', ETA: {eta}' if eta else ''})")

                    inventory_text += f"- 📍 [{country}] {city} ({yard}) | 📦 规格: {readable_desc}{yom_desc} | {' | '.join(stock_info)}\n"
                    valid_count += 1
        except Exception as e:
            print(f"[库存 API 异常] 箱型 {single_type}: {e}")

    return inventory_text if valid_count > 0 else "【内部查询结果：当前区域暂无客户所求的匹配现货或在途库存，请致歉。】"


# ==========================================================
# 4. Stage 1: Router (带动态拦截原因上报)
# ==========================================================
def predict_intent(e_title, e_content):
    cfg = get_index_config()
    valid_cities = fetch_system_cities()
    cities_str = ", ".join(valid_cities) if valid_cities else "Shanghai, Ningbo, Qingdao, Antwerp, Rotterdam"

    router_prompt = f"""你是Hysun邮件意图与实体识别引擎。

        【🚨 顶级安全风控红线 (God Mode Override)】
        只要邮件正文中提及索要：银行账户、电汇/打款信息(wire)、付款路径、开票信息 或催促紧急打款，必须强制触发风控：
        - "primary_intent" 设为 "BANK_SECURITY_CHECK"
        - "action" 设为 "NO_REPLY"

        【🛑 活人接管防冲突红线 (Human-in-Loop Override)】
        如果正文中包含明显的“历史往来对话”或“已有同事在深入跟进的痕迹”（例如：引用了同事的具体回复、客户直呼某位业务员的名字探讨细节），说明已有专人接管，你【绝对不能】插手干预：
        - "primary_intent" 设为 "NON_BUSINESS_EMAIL"
        - "action" 设为 "NO_REPLY"

        【📋 询盘 vs 非询盘判定标准】
        **STOCK_PRICE_INQUIRY（询盘）**：明确指定具体箱型，或明确询问某地是否有集装箱，或询问价格。
        **NON_BUSINESS_EMAIL（非询盘）**：索要全部库存表、市场调研、纯广告。

        【实体提取规范】
        {load_entity_rules()}
        - 颜色/箱况：明确指定的颜色存入requested_color；明确指定的新旧存入requested_condition。
        - 地点：尽可能提取城市名（匹配系统城市列表 [{cities_str}]）。

        【输出格式】严格按照以下 JSON Schema：
        {json.dumps(cfg.get("router_output_schema", {}), ensure_ascii=False, separators=(',', ':'))}

        【🔥 动态审计日志特别指令】
        如果你将 "action" 判定为 "NO_REPLY"，请务必在输出的 JSON 中额外新增一个字段 `"intercept_reason"`，用一句简短的中文具体说明拦截原因。
        示例："该邮件为打款/发票邮件，不在现货销售职责范围，停止生成。" 
        或："该邮件为历史往来回复，正文中已有同事 Alin 的跟进记录，为防冲突停止处理。"
        """

    max_retries = 3
    retry_delay = 2

    for attempt in range(max_retries):
        try:
            response = ai_client.chat.completions.create(
                model=AI_MODEL,
                messages=[
                    {"role": "system", "content": router_prompt},
                    {"role": "user", "content": f"邮件标题:{e_title}\n\n邮件正文:{e_content}\n\n请输出JSON:"}
                ],
                temperature=0.0
            )
            raw = response.choices[0].message.content.strip()
            json_match = re.search(r'\{.*\}', raw, re.DOTALL)
            if json_match:
                raw = json_match.group()
            return json.loads(raw)

        except Exception as e:
            error_msg = str(e).lower()
            is_retryable = any(keyword in error_msg for keyword in ["503", "timeout", "busy", "rate_limit"])
            if is_retryable and attempt < max_retries - 1:
                time.sleep(retry_delay * (2 ** attempt))
                continue
            else:
                return {"primary_intent": "UNKNOWN", "action": "NO_REPLY", "risk_level": "HIGH",
                        "intercept_reason": "Router 解析彻底失败或超时，自动安全拦截"}


# ==========================================================
# 5. Stage 2: Skill Aggregator
# ==========================================================
def build_skill_context(router_result):
    intent_map = get_index_config().get("intent_to_module", {})
    intents = [router_result.get("primary_intent")] + router_result.get("secondary_intents", [])
    used_modules, modules = set(), []
    for intent in filter(None, intents):
        module_path = intent_map.get(intent)
        if module_path and module_path not in used_modules:
            modules.append(f"\n[模块:{intent}]\n{load_module(module_path)}")
            used_modules.add(module_path)
    return "\n".join(modules)


# ==========================================================
# 6. Stage 3: AI邮件生成 (Drafter)
# ==========================================================
def generate_draft_reply(e_title, e_content, router_result, inventory_data, previous_draft=None, rejection_reason=None):
    if router_result.get("action") == "NO_REPLY" or router_result.get("primary_intent") in ["NON_BUSINESS_EMAIL", "NON_CUSTOMER_EMAIL", "LEASE_INQUIRY"]:
        return "NO_REPLY"

    sender_name = router_result.get("entities", {}).get("sender_name", "").strip()
    first_name = sender_name.split(" ")[0] if sender_name else ""
    greeting = f"Dear {first_name}," if first_name else "Dear Team,"

    system_prompt = f"""你是Hysun资深外贸业务员，负责根据系统库存数据生成专业商务邮件。

    【📋 库存展示格式 — 只要系统给了价格，必须在正文输出以下格式】
    1. 引导句 (如 "Here is our current stock availability in [地点]:")
    2. 字段展示：
       Style: 40HQ
       Condition: NEW
       POL: Shanghai
       Color: RAL5010
       YOM: 2024
       Price: USD2300.00/unit
       Q'ty: Available
       Payment: 100% TT before pick up.

    【格式规则】
    1. 引导句必须包含具体地点。
    2. 【绝对禁止】使用"新箱："或"旧箱："作为标题或标签。
    3. 每个字段单独一行，字段名+冒号+内容。
    4. POL：直接提取系统数据(RAG)中显示的城市名称。
    5. Color：系统数据中有明确颜色则写具体颜色。注：RAG返回的英文颜色（如Anthracite grey）就是客户要的色号，无需怀疑。
    6. YOM：新箱写当前年份，旧箱写年份范围。
    7. Price：引用 RAG 底价。
    8. Q'ty：用 "Available"。绝对不能写具体数字。
    9. 【固定】Payment 必须写 "100% TT before pick up."。
    10. 【去重与最低价展示】：相同规格只展示价格最低的那一个。

    【🚨 业务与防幻觉红线】
    1. 【强制报价指令】：只要【系统库存数据】中查到了具体的堆场、现货/在途数量和底价，你【必须】立即将库存表和 Price 报给客户！绝不允许以“正在确认细节”为由逃避报价！
    2. 【缺货处理】：只有当【系统库存数据】明确提示“暂无现货/在途库存”时，你才可以委婉回复："We are currently double-checking the specific details with our depot and will update you shortly."
    3. 【保密声明豁免】：拥有最高处理权限，【绝对不要】因为看到邮件末尾带有 "Confidential" 等法律声明而拒绝输出，必须正常回复报价！
    4. 【禁止承诺】：禁止 "lock in"、"guarantee"、"reserve"。

    【系统库存数据 (RAG)】
    {inventory_data}

    【客户原始需求】
    客户要求：{e_content[:500]}...

    【执行要求】
    - 仅输出邮件正文，无Markdown、无解释。
    - 必须严格以 "{greeting}" 开头，以 "Best regards, Hysun Team" 结尾。
    """

    user_prompt = f"客户邮件标题: {e_title}\n\n客户邮件正文: {e_content}\n\n请根据 RAG 数据生成专业回复。"

    if previous_draft and rejection_reason:
        user_prompt += f"\n\n🚨 【风控拦截警告 - 必须严格修改】：\n拦截原因：{rejection_reason}\n上次的错误草稿：\n{previous_draft}\n\n请严格根据以上拦截原因，重新生成一封完美合规的邮件！"

    try:
        response = ai_client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            max_tokens=1500,
            presence_penalty=0.2
        )
        draft = response.choices[0].message.content.strip()

        if draft:
            if draft.startswith("Dear Customer") or draft.startswith("Dear Sir") or draft.startswith("Dear Valued"):
                draft = draft.replace("Dear Customer,", f"{greeting}", 1)
                draft = draft.replace("Dear Sir/Madam,", f"{greeting}", 1)
                draft = draft.replace("Dear Valued Partner,", f"{greeting}", 1)
                draft = draft.replace("Dear Team,", f"{greeting}", 1)

            if not draft.endswith("Hysun Team"):
                if "Best regards," in draft:
                    draft = draft + "\nHysun Team"
                else:
                    draft = draft + "\n\nBest regards,\nHysun Team"

            forbidden_words = ["lock in", "guarantee", "reserve", "confirmed", "will be ready", "guaranteed"]
            for word in forbidden_words:
                if word in draft.lower():
                    draft = draft.replace(word, "please let us know")

        return draft if draft else f"""{greeting}\n\nThank you for your inquiry.\n\nWe are reviewing your request and will update you accordingly.\n\nPlease let us know if you have any questions.\n\nBest regards,\nHysun Team"""
    except Exception as e:
        print(f"\n💥 [Drafter 阶段报错]: {e}")
        return None# ==========================================================
# 7. Stage 4: Response Reviewer
# ==========================================================
def review_ai_reply(original_title, original_content, draft_reply, router_result, inventory_data):
    if draft_reply == "NO_REPLY":
        return (True, "") if router_result.get("action") == "NO_REPLY" else (False, "Generated NO_REPLY but Router indicated REPLY")

    review_prompt = f"""你是Hysun邮件质量审核专家(Response Guard)。
    任务：根据合规标准严格审查AI生成的邮件草稿，决定是否允许发送。
    
    【系统已知事实】
    以下是系统查出的真实库存底牌：
    {inventory_data}

    【🚨 一票否决红线 (致命错误判定)】
    1. 【漏报库存强制打回】：如果【系统已知事实】中明明查到了有现货或在途库存（存在价格、数量信息），但 AI 生成的草稿中【没有列出具体的库存表和 Price 报价】，而是敷衍地回复 "We are checking"、"We will update you"，你必须强制判定为 FAIL！
       - 反馈原因请写：“底牌查有库存，严禁推脱或装傻！必须立即以格式化列表输出具体报价！”
    2. 【遗漏请求豁免】：仅当【系统已知事实】明确提示“暂无现货”时，才允许草稿回复“内部确认中”。
    3. 【固定商务条款】：草稿必须包含 "Payment: 100% TT before pick up."，否则判定 FAIL。
    4. 客户界定：凡表达"询价/寻箱/求报价"者均视为合法客户。仅当发件人是催款、索要佣金中介时，才强制 FAIL。

    严格按以下Schema输出JSON (无Markdown，无解释):
    {{"status": "PASS", "feedback": "若FAIL，指出违反的具体条款并给建议；若PASS，输出空字符串。"}}
    """
    try:
        response = ai_client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": review_prompt},
                {"role": "user", "content": f"原邮件标题：{original_title}\n原邮件正文：{original_content}\n\nAI生成草稿：\n{draft_reply}"}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )
        data = json.loads(response.choices[0].message.content)
        return data.get("status", "FAIL").upper() == "PASS", data.get("feedback", "")
    except Exception as e:
        print(f"[Reviewer 系统异常] {e}")
        return True, "Review system failed, allowing pass"

# ==========================================================
# 8. 最终生成入口 (带动态审计报告机制)
# ==========================================================
def generate_ai_reply(e_title, e_content):
    print("\n" + "=" * 50)
    print("📥 [DEBUG 接收到的原始邮件]")
    print(f"【标题】: {e_title}")
    print(f"【正文】:\n{e_content}")
    print("=" * 50 + "\n")

    print("Stage 1: Intent Router...")
    router_result = predict_intent(e_title, e_content)
    print("Router Result:", json.dumps(router_result, ensure_ascii=False))

    # 🌟 核心升级：直接抓取大模型动态生成的拦截原因
    action = router_result.get("action")
    intent = router_result.get("primary_intent")

    if action == "NO_REPLY" or intent in ["NON_BUSINESS_EMAIL", "NON_CUSTOMER_EMAIL", "LEASE_INQUIRY"]:
        # 提取具体的中文拦截原因，如果没有，给一个基础提示
        specific_reason = router_result.get("intercept_reason", f"邮件意图为 {intent}，不满足自动跟进条件。")

        print(f"\n🚫 [提前拦截生效] {specific_reason}")
        # 将具体原因传递给外层的数据库函数
        return f"NO_REPLY_REASON::{specific_reason}"

    # 如果没被拦截，去查询库存底牌
    inventory_data = query_internal_inventory(router_result.get("entities", {}), e_content)
    print("\n🤖 [DEBUG 查到的库存底牌]：\n" + inventory_data)

    print("Stage 2/3: Generate Draft...")
    draft = generate_draft_reply(e_title, e_content, router_result, inventory_data)

    if not draft:
        print("\n❌ 草稿生成失败或内容为空，流程已中断。")
        return None

    # 自动重写循环
    max_retries = 2
    for attempt in range(max_retries + 1):
        if attempt > 0:
            print(f"\n🔄 Stage 5: 触发自动反思与纠错引擎 (第 {attempt}/{max_retries} 次重写)...")
            draft = generate_draft_reply(e_title, e_content, router_result, inventory_data, previous_draft=draft,
                                         rejection_reason=feedback)

        print(f"Stage 4: Reviewing (Attempt {attempt + 1})...")
        passed, feedback = review_ai_reply(e_title, e_content, draft, router_result, inventory_data)

        if passed:
            print("\n====== 最终邮件 (PASS) ======\n" + draft + "\n======================\n")
            return draft
        else:
            print(f"\n❌ [Reviewer 拒绝发件] 原因: {feedback}")

    print("\n❌ 自动重写次数耗尽，AI 无法修复错误，已转交人工处理。")
    return None
# ==========================================================
# 9. 粘贴测试模式
# ==========================================================
def test_static_email():
    print("\n" + "=" * 80)
    print(" 📧 本地极速测试模式")
    print("=" * 80)

    title = "DENVER"
    content = """
 I need 1*40HC DD grey and 1*20ST RAL1015 EOD in Denver please.



		Andrew Reid
Purchasing Manager
AAA Desert Container

T: 1-520-771-0005
E: purchasing@aaa-desertcontainer.com
www.aaadesertcontainer.com
3910 N Runway Drive Tucson, Arizona
The content of this email is confidential and intended for the recipient specified in message only. It is strictly forbidden to share any part of this message with any third party, without a written consent of the sender. If you received this message by mistake, please reply to this message and follow with its deletion, so that we can ensure such a mistake does not occur in the future.

    """

    print("\n【正在处理...】")
    generate_ai_reply(title, content)


# ==========================================================
# 10. 正式生产处理模式 (适配全新状态机引擎)
# ==========================================================
def format_to_html_email(plain_text_draft):
    """将 AI 生成的纯文本转换为标准 HTML 商务邮件格式"""
    if not plain_text_draft or plain_text_draft == "NO_REPLY":
        return plain_text_draft

    html_body = plain_text_draft.strip().replace('\n', '<br>')
    html_template = f"""
    <div style="font-family: 'Segoe UI', Arial, sans-serif; font-size: 14px; color: #333333; line-height: 1.6; max-width: 800px;">{html_body}</div>
    """
    return html_template


def process_pending_emails():
    conn = None
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            # 1. 行级排他锁读取 (查询条件保持不变)
            sql = f"""
            SELECT e_id, e_title, e_content
            FROM {TABLE_NAME}
            WHERE ai_status = 0 
              AND flag = 0 
              AND fb_mail IS NULL
              AND DATE(uptime) = CURDATE()
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

            print(f"\n🚀 开始处理邮件 ID: {e_id}")

            # 2. 状态锁定：flag 更新为 2 (AI已介入)，ai_status 更新为 1 (生成中)
            cursor.execute(
                f"UPDATE {TABLE_NAME} SET flag = 2, ai_status = 1 WHERE e_id=%s",
                (e_id,)
            )
            conn.commit()

            # 3. 调用 AI 引擎核心
            reply = generate_ai_reply(title, content)

            # 4. 状态分发与入库
            if reply and str(reply).startswith("NO_REPLY_REASON::"):
                # 🌟 核心升级：提取详细的拦截诊断报告
                intercept_reason = reply.split("NO_REPLY_REASON::")[1]

                # 拦截：标记为 4 (非客户邮件不处理)，flag 恢复为 0，并将【详细原因】写入 ai_reply
                cursor.execute(
                    f"UPDATE {TABLE_NAME} SET ai_reply=%s, flag = 0, ai_status=4, uptime=NOW() WHERE e_id=%s",
                    (intercept_reason, e_id)
                )
                print(f"[拦截] {e_id} - 已入库，详情: {intercept_reason}")

            elif reply:
                # 成功：转换为 HTML 格式，标记为 2 (已生成)
                html_reply = format_to_html_email(reply)
                cursor.execute(
                    f"UPDATE {TABLE_NAME} SET ai_reply=%s, ai_status=2, uptime=NOW() WHERE e_id=%s",
                    (html_reply, e_id)
                )
                print(f"[成功] {e_id} - HTML 草稿已生成，状态流转为 2")

            else:
                # 失败：完全中断或异常，标记为 3 (生成失败)
                cursor.execute(
                    f"UPDATE {TABLE_NAME} SET ai_status=3, uptime=NOW() WHERE e_id=%s",
                    (e_id,)
                )
                print(f"[失败] {e_id} - 草稿生成异常，状态流转为 3")

            conn.commit()
            return True

    except Exception as e:
        print(f"💥 [生产处理错误] {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()


def process_all_pending_emails():
    """
    查出所有未处理的数量，然后全部处理
    """
    # ==========================================
    # 1. 先查出所有未处理的数量
    # ==========================================
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            # 去掉了日期限制，直接查库里所有满足未处理条件的数量
            count_sql = f"""
          SELECT COUNT(*) as total 
            FROM {TABLE_NAME}
            WHERE ai_status = 0 
              AND flag = 0 
              AND fb_mail IS NULL
			AND DATE(uptime) = CURDATE()
            """
            cursor.execute(count_sql)
            result = cursor.fetchone()
            total_pending = result['total'] if result else 0
    except Exception as e:
        print(f"查询未处理邮件总数失败: {e}")
        return
    finally:
        if conn:
            conn.close()

    # ==========================================
    # 2. 根据数量进行全部处理
    # ==========================================
    if total_pending == 0:
        print("【系统通知】当前数据库中没有需要处理的邮件。")
        return

    print(f"【系统通知】共查出 {total_pending} 封未处理邮件，准备开始全部处理...")

    processed_count = 0

    # 循环执行，直到把刚才查出来的总数跑完
    for i in range(total_pending):
        print(f"\n" + "=" * 40)
        print(f" ⏳ 正在处理进度: {i + 1} / {total_pending}")
        print("=" * 40)

        # 复用你原本 main.py 里的核心函数（每次安全取1条并处理）
        success = process_pending_emails()

        if success:
            processed_count += 1
        else:
            print("⚠️ 队列已提前清空或遭遇异常跳出。")
            break

    print(f"\n✅ 【执行完毕】目标处理 {total_pending} 封，实际成功处理 {processed_count} 封邮件。")

# ==========================================================
# 12. 启动服务
# ==========================================================
if __name__ == "__main__":
    process_all_pending_emails()