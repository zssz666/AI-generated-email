import json
import os
import re
import time
import traceback
from functools import lru_cache
import pymysql
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
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
# 4. Stage 1: Router
# ==========================================================
def predict_intent(e_title, e_content):
    cfg = get_index_config()
    valid_cities = fetch_system_cities()
    cities_str = ", ".join(valid_cities) if valid_cities else "Shanghai, Ningbo, Qingdao, Antwerp, Rotterdam"

    intent_keys = list(cfg.get("intent_to_module", {}).keys())
    if not intent_keys:
        intent_keys = ["STOCK_PRICE_INQUIRY", "NON_BUSINESS_EMAIL", "ORDER_CONFIRM_INVOICE"]

    router_prompt = f"""你是Hysun邮件意图与实体识别引擎。

    【📋 询盘 vs 非询盘判定标准（必须严格遵循）】

    **STOCK_PRICE_INQUIRY（询盘）** — 满足以下 **任意一条** 即判为询盘：
    1. 邮件中明确指定了具体箱型（如 20GP、40HC、20DC、40'HC Used 等）
    2. 邮件中明确询问了某地是否有可用集装箱（如 "available in Vancouver?"、"have stock in Houston?"、"any containers in Europe?"），即使未指定箱型
    3. 邮件中明确指定了数量或地点，并带有采购意向词（need、looking for、quote、purchase、buy）
    4. 邮件中明确询问价格（quote/price/cost）

    **NON_BUSINESS_EMAIL（非询盘）** — 满足以下任意一条：
    1. 仅索要"全部库存清单"或"最新库存表"，但未提及任何具体采购需求（无箱型、无地点、无数量）
    2. 邮件内容仅为市场调研或供应商筛选，未体现具体采购场景
    3. 纯粹的广告、营销、平台通知（如 xChange 通知）、LinkedIn 推广
    4. 发票催款、对账、供应商付款等供应商侧业务

    【🚨 最高优先级判定规则】
    - 如果邮件中**出现了具体箱型名称**（无论是否附带地点/数量），**必须**判为 STOCK_PRICE_INQUIRY。
    - 如果邮件**未出现箱型**，但**明确询问了某地的可用库存**（如 "what do you have in Houston?"），也**必须**判为 STOCK_PRICE_INQUIRY。
    - 只有**既无箱型、也无地点询问、仅索要清单**的，才判为 NON_BUSINESS_EMAIL。

    【实体提取规范】
    {load_entity_rules()}
    - 颜色/箱况：明确指定的颜色(如RAL1015)存入requested_color；明确指定的新旧(如1TRIP, CW)存入requested_condition。
    - 地点：尽可能提取城市名（匹配系统城市列表 [{cities_str}]）或国家/大洲；若完全无地点信息，才允许为空。

    【判定示例 - Few Shot】
    ✅ 询盘 (STOCK_PRICE_INQUIRY):
    - "Please quote 40HC Used in Vancouver." → 有箱型+地点 → 询盘
    - "Do you have any 20GP containers?" → 有箱型 → 询盘
    - "What containers are available in Houston?" → 无箱型但有地点询问 → 询盘
    - "Need 10 units of 40'HC for Edmonton." → 有箱型+数量+地点 → 询盘
    - "We are looking for used 20DC in Canada." → 有箱型+地点 → 询盘

    ❌ 非询盘 (NON_BUSINESS_EMAIL):
    - "Please send me your full inventory list." → 无箱型、无地点询问 → 非询盘
    - "I need to see your updated inventory" → 无箱型、无地点询问 → 非询盘
    - "We're kicking off sales, need your inventory." → 无箱型、无地点询问 → 非询盘
    - "Follow us on LinkedIn for updates" → 广告 → 非询盘
    - "Deal ID 12345, new offer" → 平台通知 → 非询盘

    【核心规则】本系统仅处理客户的集装箱售前询盘 (STOCK_PRICE_INQUIRY)。其他业务（订单确认、发票、付款、对账、售后、租赁、供应商事务）一律拦截并输出 NO_REPLY。

    【输出格式】严格按照以下 JSON Schema：
    {json.dumps(cfg.get("router_output_schema", {}), ensure_ascii=False, separators=(',', ':'))}
    """

    # 重试机制：最多尝试 3 次（包括首次）
    max_retries = 3
    retry_delay = 2  # 秒

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
            # 如果是服务繁忙/超时类错误，且还有重试次数，则等待后重试
            is_retryable = any(keyword in error_msg for keyword in [
                "503", "service_unavailable", "timeout", "busy", "rate_limit"
            ])

            if is_retryable and attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt)  # 指数退避: 2s, 4s, 8s
                print(f"[Router] 服务繁忙 (尝试 {attempt + 1}/{max_retries})，{wait_time}秒后重试...")
                time.sleep(wait_time)
                continue
            else:
                # 非重试类错误 或 重试次数已用完
                print(f"[Router 预测失败] 详情: {e}")
                return {
                    "primary_intent": "UNKNOWN",
                    "secondary_intents": [],
                    "action": "NO_REPLY",
                    "entities": {},
                    "risk_level": "HIGH"
                }


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
# 6. Stage 3: AI邮件生成 (Drafter) 带自我纠错功能
# ==========================================================
def generate_draft_reply(e_title, e_content, router_result, inventory_data, previous_draft=None, rejection_reason=None):
    if router_result.get("action") == "NO_REPLY" or router_result.get("primary_intent") in ["NON_BUSINESS_EMAIL",
                                                                                            "NON_CUSTOMER_EMAIL",
                                                                                            "LEASE_INQUIRY"]:
        return "NO_REPLY"

    no_stock_keywords = ["暂无客户所求", "暂无匹配现货", "无法获取库存", "未明确指定箱型", "无法生成有效查询"]
    if any(kw in inventory_data for kw in no_stock_keywords):
        return """Dear Team,
        Thank you for your inquiry.
        Unfortunately, we currently do not have the requested inventory available in this location. Please let us know if we can assist you with other options.
        Best regards,
        Hysun Team"""

    # 🌟 动态提取客户名字，生成专属问候语
    sender_name = router_result.get("entities", {}).get("sender_name", "").strip()
    first_name = sender_name.split(" ")[0] if sender_name else ""
    greeting = f"Dear {first_name}," if first_name else "Dear Team,"

    system_prompt = f"""你是Hysun资深外贸业务员，负责根据系统库存数据生成专业商务邮件。

    【📋 库存展示格式 — 邮件正文中必须按此结构组织】

    当库存数据包含新箱（NEW / New 1-Trip）和旧箱（CW / CW+ / IICL 等）时，按以下格式展示：

    1. 先用一句自然的话引入，例如：
       "Here is our current stock availability in [地点]:"
       或
       "We currently have the following units available in [地点]:"

    2. 然后直接列出库存详情，不加"新箱："或"旧箱："等标签：

       Style: 40HQ
       Condition: NEW
       POL: Shanghai
       Color: RAL5010
       YOM: 2024
       Price: USD2300.00/unit
       Q'ty: Available
       Payment: 100% TT before pick up.

    3. 【重要】Payment 字段是 Hysun 的标准付款条款，必须固定显示为 "100% TT before pick up."。
       这不是虚构数据，而是公司的标准商务条款，必须在每封报价邮件中展示。

    【格式规则】
    1. 引导句必须包含具体地点（如 "in Haiphong"）。
    2. 【绝对禁止】使用"新箱："或"旧箱："作为标题或标签。
    3. 每个字段单独一行，字段名+冒号+内容。
    4. POL：直接提取系统数据(RAG)中显示的城市名称（例如底牌是 📍 [CA] Winnipeg，POL 字段就写 Winnipeg）。
    5. Color 如果系统数据中是 Mixed，写 "Mixed"；如有明确颜色（如 RAL5010 或 Slate grey），写具体颜色。
    6. YOM 如果系统数据没有，新箱写当前年份，旧箱写年份范围。
    7. Price 必须引用 RAG 中的底价，无价格则写 "Upon request"。
    8. Q'ty 用 "Available" / "Limited availability" / "Available upon request"。绝对不能写具体数字。
    9. 【固定】Payment 必须写 "100% TT before pick up."，这是 Hysun 的标准条款。
    10. 【去重与最低价展示】：如果底层数据返回了多个规格、状态和颜色完全相同的选项，必须只展示价格最低的那一个，绝对禁止重复列出多个相同规格的选项。

    【🚨 绝对红线】
    1. 【问候语格式】：邮件开头必须严格使用 "{greeting}"。【绝对禁止】使用 "Dear Customer"、"Dear Sir/Madam"、"Dear Valued Partner"。
    2. 【价格引用】：只能引用 RAG 中的底价，禁止凭空捏造。
    3. 【数量保密】：绝对不能写具体数字。
    4. 【禁止承诺】：禁止 "lock in"、"guarantee"、"reserve"、"confirm"。
    5. 【禁止虚构】：Payment 字段虽然是固定的，但它是 Hysun 的标准商务条款，不是虚构数据。

    【系统库存数据 (RAG)】
    {inventory_data}

    【客户原始需求】
    客户要求：{e_content[:500]}...

    【执行要求】
    - 仅输出邮件正文，无Markdown、无解释。
    - 必须严格以 "{greeting}" 开头，以 "Best regards, Hysun Team" 结尾。
    """

    # 🌟 动态构建 User Prompt (加入自动纠错机制)
    user_prompt = f"客户邮件标题: {e_title}\n\n客户邮件正文: {e_content}\n\n请根据 RAG 数据生成专业回复。"

    if previous_draft and rejection_reason:
        user_prompt += f"\n\n🚨 【风控拦截警告 - 必须严格修改】：\n你上次生成的草稿被风控系统(Reviewer)严厉拦截！\n拦截原因：{rejection_reason}\n上次的错误草稿：\n{previous_draft}\n\n请务必吸取教训，严格根据以上拦截原因，重新生成一封完美合规的邮件！"

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

        # 兜底修复：确保问候语和签名合规
        if draft:
            # 强制纠正乱叫名字的现象
            if draft.startswith("Dear Customer") or draft.startswith("Dear Sir") or draft.startswith("Dear Valued"):
                draft = draft.replace("Dear Customer,", f"{greeting}", 1)
                draft = draft.replace("Dear Sir/Madam,", f"{greeting}", 1)
                draft = draft.replace("Dear Valued Partner,", f"{greeting}", 1)
                draft = draft.replace("Dear Team,", f"{greeting}", 1)

            # 确保签名存在
            if not draft.endswith("Hysun Team"):
                if "Best regards," in draft:
                    draft = draft + "\nHysun Team"
                else:
                    draft = draft + "\n\nBest regards,\nHysun Team"

            # 禁止承诺性词汇
            forbidden_words = ["lock in", "guarantee", "reserve", "confirmed", "will be ready", "guaranteed"]
            for word in forbidden_words:
                if word in draft.lower():
                    draft = draft.replace(word, "please let us know")

        return draft if draft else f"""{greeting}\n\nThank you for your inquiry.\n\nWe are reviewing your request and will update you accordingly.\n\nPlease let us know if you have any questions.\n\nBest regards,\nHysun Team"""
    except Exception as e:
        print(f"\n💥 [Drafter 阶段报错]: {e}")
        return None


# ==========================================================
# 7. Stage 4: Response Reviewer
# ==========================================================
def review_ai_reply(original_title, original_content, draft_reply, router_result, inventory_data):
    if draft_reply == "NO_REPLY":
        return (True, "") if router_result.get("action") == "NO_REPLY" else (False,
                                                                             "Generated NO_REPLY but Router indicated REPLY")

    review_prompt = f"""你是Hysun邮件质量审核专家(Response Guard)。
    任务：根据合规标准严格审查AI生成的邮件草稿，决定是否允许发送。
    【权威审核标准】
    {load_response_guard()}

    【系统已知事实 (防误判特赦令)】
    1. 以下是系统查出的真实库存底牌。草稿中引用此处的【具体堆场名称、价格、年份、颜色等】绝对合法，属于业务跟单的正常行为，【绝对不可】判为虚构(Hallucination)！
    {inventory_data}
    2. 🚨 【固定商务条款特赦】：草稿中固定出现的 "Payment: 100% TT before pick up." 为 Hysun 公司标准话术，绝对禁止判为虚构！

    【关键业务判定细节】
    1. 客户界定：凡表达"询价/寻箱/求报价/下订单"者均视为合法客户。仅当发件人是"催款/发票供应商"或"索要佣金中介"时，才强制 FAIL。
    2. 遗漏请求豁免：草稿中出现"内部确认中"或"追问缺失信息"等，属于合规防守，不视为遗漏请求。

    严格按以下Schema输出JSON (无Markdown，无解释):
    {{"status": "PASS", "feedback": "若FAIL，指出违反的具体条款并给建议；若PASS，输出空字符串。"}}
    """
    try:
        response = ai_client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": review_prompt},
                {"role": "user",
                 "content": f"原邮件标题：{original_title}\n原邮件正文：{original_content}\n\nAI生成草稿：\n{draft_reply}"}
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
# 8. 最终生成入口 (带自我纠错循环机制)
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

    inventory_data = query_internal_inventory(router_result.get("entities", {}), e_content)
    print("\n🤖 [DEBUG 查到的库存底牌]：\n" + inventory_data)

    print("Stage 2/3: Generate Draft...")
    draft = generate_draft_reply(e_title, e_content, router_result, inventory_data)

    if not draft:
        print("\n❌ 草稿生成失败或内容为空，流程已中断。")
        return None

    # 🌟 核心升级：自动重写循环 (最多允许 Reviewer 打回 2 次)
    max_retries = 2
    for attempt in range(max_retries + 1):
        if attempt > 0:
            print(f"\n🔄 Stage 5: 触发自动反思与纠错引擎 (第 {attempt}/{max_retries} 次重写)...")
            # 把前一次的废稿和骂它的原因喂回去
            draft = generate_draft_reply(e_title, e_content, router_result, inventory_data, previous_draft=draft, rejection_reason=feedback)

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

    title = "Gray 40HC NEW - Tacoma."
    content = """
  Hi, 


Are these units still available?
US	Tacoma	40HC	New 1 trip		RAL7015	FLP/LB/EOD	2025-2026	1	US$3,350	2	2026-08-14	Affordable Storage Containers	1670 Marine View Dr, Tacoma, WA 98422
US	Tacoma	40HC	New 1 trip		RAL7016	FLP/LB	2025-2026	1	US$3,350	0		Tahoma Global Logistics	2102 Alexander Avenue Tacoma, United States


Thank you 


Respectfully,
Thiago Cirino | Inventory Coordinator
USA Containers
📞 Direct: (385)417-4103
🇺🇸 Office: 877-395-6851
usacontainers.co | thiago@usacontainers.co
Respect Truckers | Thank you for your business
 
New to shipping containers? Click here to explore helpful videos on ownership, maintenance, and expert tips to get the most out of your container.
    """

    print("\n【正在处理...】")
    generate_ai_reply(title, content)


if __name__ == "__main__":
    test_static_email()
    # test_preview_emails() # <- 从数据库拉取未处理邮件进行预览

    # process_pending_emails() # <- 生产环境处理入库