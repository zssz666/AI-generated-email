import json
import os
import pymysql
import requests
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

# 全局缓存系统城市列表，避免每次请求都去查数据库
SYSTEM_CITIES_CACHE = []

def fetch_system_cities():
    """
    调用后端的 ListDepot 接口，获取系统中所有支持的唯一城市列表 (对标前端 getCitys)
    """
    global SYSTEM_CITIES_CACHE
    # 如果缓存里已经有了，直接返回，节约性能
    if SYSTEM_CITIES_CACHE:
        return SYSTEM_CITIES_CACHE

    # 替换成您真实的 ListDepot 完整接口地址
    # 注意：根据您的实际部署情况修改 IP 或域名
    api_url = "http://47.109.176.188:81/ListDepot"

    try:
        response = requests.get(api_url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            # 假设返回的数据结构是 { "obj": [ {"dCity": "Shanghai", ...}, ... ] }
            depot_list = data.get("obj", [])

            # Python 版本的去重 (对应您 JS 的 reduce)
            unique_cities = set()
            for item in depot_list:
                city = item.get("dCity")
                if city:
                    unique_cities.add(city.strip())

            # 转为列表并排序
            SYSTEM_CITIES_CACHE = sorted(list(unique_cities))
            print(f"✅ [系统启动] 成功同步系统城市字典，共 {len(SYSTEM_CITIES_CACHE)} 个城市。")
            return SYSTEM_CITIES_CACHE
    except Exception as e:
        print(f"❌ [系统告警] 获取城市列表失败: {e}")

    return []


# 全局缓存系统国家列表 (格式: [{"ISO2": "TR", "eName": "Turkey", "cName": "土耳其"}, ...])
SYSTEM_COUNTRIES_CACHE = []


def fetch_system_countries():
    """
    调用后端的 /getGcountry 接口，动态同步国家字典 (对标前端 getCountryList)
    """
    global SYSTEM_COUNTRIES_CACHE
    if SYSTEM_COUNTRIES_CACHE:
        return SYSTEM_COUNTRIES_CACHE

    api_url = "http://47.109.176.188:81/getGcountry"  # 替换为完整的后端接口地址

    try:
        response = requests.get(api_url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            # 兼容接口返回的数据结构
            country_list = data.get("obj", [])

            valid_countries = []
            for item in country_list:
                iso2 = item.get("ISO2", "").strip().upper()
                ename = item.get("eName", "").strip()
                cname = item.get("cName", "").strip()
                if iso2 and ename:
                    valid_countries.append({
                        "ISO2": iso2,
                        "eName": ename,
                        "cName": cname
                    })

            SYSTEM_COUNTRIES_CACHE = valid_countries
            print(f"✅ [系统启动] 成功同步系统国家字典，共 {len(SYSTEM_COUNTRIES_CACHE)} 个国家。")
            return SYSTEM_COUNTRIES_CACHE
    except Exception as e:
        print(f"❌ [系统告警] 获取国家列表失败: {e}")

    return []
# ==========================================================
# 内部编码与解码映射库
# ==========================================================
HYSUN_CONTAINER_TYPES = {
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
    1: "NEW", 2: "New 1 trip", 3: "New-IICL", 4: "IICL",
    5: "CW", 6: "CW-WWT", 7: "WWT", 8: "ASIS", 9: "CW+"
}


def parse_hysun_idcode(idcode: str):
    """解码 Java 返回的 10 位 SKU"""
    if not idcode or len(idcode) != 10 or not idcode.isdigit(): return "未知规格"
    type_id = int(idcode[4:6])
    cond_id = int(idcode[6:7])
    box_type = HYSUN_CONTAINER_TYPES.get(type_id, f"Type-{type_id}")
    box_cond = HYSUN_CONDITIONS.get(cond_id, f"Cond-{cond_id}")
    return f"{box_type} {box_cond}"


def encode_search_idcode(text: str):
    """
    智能编码器：将 AI 提取的描述(如"40HC IICL")转换为 MySQL LIKE 适用的10位通配符 (如 "____254___")
    """
    if not text: return ""
    text = text.upper().replace("'", "").replace(" ", "")
    type_code = "__"
    cond_code = "_"

    # 1. 模糊匹配箱型 ID
    if "20GP" in text or "20DV" in text or "20DC" in text:
        type_code = "03"
    elif "40GP" in text or "40DV" in text or "40DC" in text:
        type_code = "18"
    elif "40HC" in text or "40HQ" in text:
        type_code = "25"
    elif "45HC" in text or "45HQ" in text:
        type_code = "37"
    elif "20RF" in text:
        type_code = "04"
    elif "40RF" in text:
        type_code = "21"
    elif "40RH" in text:
        type_code = "26"
    elif "40HCDD" in text or "40DOUBLED" in text:
        type_code = "27"

    # 2. 模糊匹配箱况 ID
    if "NEW-IICL" in text or ("NEW" in text and "IICL" in text):
        cond_code = "3"
    elif "IICL" in text:
        cond_code = "4"
    elif "1TRIP" in text or "ONEWAY" in text:
        cond_code = "2"
    elif "NEW" in text:
        cond_code = "1"
    elif "CW+" in text:
        cond_code = "9"
    elif "CWWWT" in text:
        cond_code = "6"
    elif "CW" in text or "CARGOWORTHY" in text:
        cond_code = "5"
    elif "WWT" in text:
        cond_code = "7"
    elif "ASIS" in text:
        cond_code = "8"

    # 如果都没匹配到，返回空字符串，让后端查所有；否则拼接 10位 LIKE 语句
    if type_code == "__" and cond_code == "_":
        return ""

    # [4位颜色] + [2位箱型] + [1位箱况] + [3位配件]
    return f"____{type_code}{cond_code}___"


def get_area_code(location_str: str):
    loc = location_str.lower()
    if any(x in loc for x in ['us', 'usa', 'america', 'canada', 'houston', 'los angeles']): return 1
    if any(x in loc for x in ['asia', 'china', 'shanghai', 'ningbo', 'qingdao']): return 2
    if any(x in loc for x in ['europe', 'liverpool', 'manchester', 'antwerp', 'rotterdam']): return 3
    return 0


def get_iso2_country_code(location_str: str):
    """
    通过系统接口拉取回来的国家字典，智能比对英文名、中文名或 ISO2，
    返回 Java 接口需要的 List 格式，例如: ["TR"] 或 ["DK"]
    """
    if not location_str:
        return []

    loc_clean = location_str.strip().lower()
    countries = fetch_system_countries()

    for item in countries:
        iso2 = item["ISO2"].lower()
        ename = item["eName"].lower()
        cname = item["cName"].lower()

        # 1. 如果完全相等的比对 (如传入 "Turkey" 命中 ename)
        # 2. 或者子串比对 (如传入 "Turkey, Mersin" 中包含 "turkey")
        # 3. 甚至兼容直接传入缩写 "TR" 的情况
        if loc_clean == ename or loc_clean == iso2 or loc_clean == cname:
            return [item["ISO2"]]
        if len(ename) > 2 and ename in loc_clean:
            return [item["ISO2"]]

    return []


# ==========================================================
# API 检索层
# ==========================================================
def query_internal_inventory(entities, email_content):
    api_url = os.getenv("INVENTORY_API_URL")

    raw_type_desc = entities.get("container_type", "")
    location_desc = entities.get("target_location", entities.get("release_code", "")).strip()

    search_idcode = encode_search_idcode(raw_type_desc)

    # ==========================================================
    # 🌟 地理层级与组合路由引擎：大洲 / 国家 / 城市(或国家+城市)
    # ==========================================================
    area_code = 0
    country_codes = []
    d_city_val = ""

    loc_lower = location_desc.lower()

    # 1. 第一层：判断是否为【纯大洲/区域级】(Europe, Asia 等)
    area_map = {
        'us & ca': 1, 'america': 1, 'us': 1, 'usa': 1, 'canada': 1,
        'asia': 2, 'europe': 3, 'others': 4
    }
    matched_area = area_map.get(loc_lower)

    if matched_area:
        area_code = matched_area
        print(f"🌍 [地理判断] 命中【大洲区域级】，使用 area: {area_code}")
    else:
        # 2. 尝试从文本中解析 ISO2 国家代码 (例如从 "Antwerp, Belgium" 中提取出 ["BE"])
        country_codes = get_iso2_country_code(location_desc)

        # 3. 尝试匹配系统中已有的 325 个标准城市
        system_cities = fetch_system_cities()
        matched_city = ""
        for city in system_cities:
            # 如果文本中包含某个标准城市名（例如 "antwerp, belgium" 包含 "antwerp"）
            if city.lower() in loc_lower:
                matched_city = city
                break

        if matched_city:
            # 【情况A：提到城市，或者“国家+城市”】-> 同时传 dCity 和 dCountry(若有)
            d_city_val = matched_city
            print(f"🏙️ [地理判断] 命中【城市/组合级】-> 城市: '{d_city_val}', 国家: {country_codes}")
        elif len(country_codes) > 0:
            # 【情况B：仅提到国家，没提到任何具体城市】-> dCity 留空，只按国家查
            d_city_val = ""
            print(f"🏳️ [地理判断] 命中【纯国家级】-> 仅用国家过滤: {country_codes}")
        else:
            # 【情况C：既没匹配到国家也没匹配到系统城市，直接把原词当城市兜底】
            d_city_val = location_desc
            print(f"🔍 [地理判断] 自由匹配 -> 尝试用 dCity: '{d_city_val}' 模糊搜索")

    # 构建发送给 Java 接口的最终 Payload
    payload = {
        "idCodes": search_idcode,
        "dCity": d_city_val,  # 例如 "Antwerp"
        "dCountry": country_codes,  # 例如 ["BE"]
        "yardName": "",
        "area": area_code,  # 例如 0
        "page": 1,
        "limit": 5,
        "date": [],
        "resource": "", "cargo": "",
        "xcHid": 0, "xcUid": 0, "raioxcHid": 0, "raioxcUid": 0, "inventory": 0
    }

    headers = {"Content-Type": "application/json"}

    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=8)

        if response.status_code == 200:
            raw_text = response.text
            if not raw_text.strip():
                return "【内部查询结果：当前无匹配库存】"

            try:
                res_json = response.json()
            except Exception:
                return "【内部系统返回格式错误】"

            page_data = res_json.get("obj", {}).get("page", [])

            if not page_data:
                return "【内部查询结果：当前区域无匹配库存，请建议客户更换堆场或等待】"

            inventory_text = "【内部系统实时库存底牌】\n"
            valid_count = 0  # 记录有效数据条数

            for item in page_data:
                ddepot = item.get("ddepot", {})
                city = ddepot.get("dCity", "未知城市")
                country = ddepot.get("dCountry", "")
                yard = ddepot.get("dName", "")

                raw_idcode = item.get("idCode", "")
                readable_desc = parse_hysun_idcode(raw_idcode)

                # 现货字段 (oPrince & onground)
                o_price = item.get("oPrince", 0)
                onground = item.get("onground", 0)

                # 在途字段 (uPrice, upcoming, eta)
                u_price = item.get("uPrice", 0)
                upcoming = item.get("upcoming", 0)
                eta = item.get("eta", "")

                # ==========================================
                # 【数据清洗逻辑】：必须价格和数量都大于0才算有效
                # ==========================================
                has_valid_onground = (onground > 0 and o_price > 0)
                has_valid_upcoming = (upcoming > 0 and u_price > 0)

                # 如果既没有有效现货，也没有有效在途，直接丢弃该数据，不给AI看
                if not has_valid_onground and not has_valid_upcoming:
                    continue

                stock_info = []
                if has_valid_onground:
                    stock_info.append(f"现货(On-ground): {onground}个 (底价: ${o_price})")
                if has_valid_upcoming:
                    eta_str = f", 预计到港日(ETA): {eta}" if eta else ""
                    stock_info.append(f"在途(Upcoming): {upcoming}个 (底价: ${u_price}{eta_str})")

                stock_desc = " | ".join(stock_info)

                inventory_text += f"- 📍 [{country}] {city} ({yard}) | 📦 规格: {readable_desc} | {stock_desc}\n"
                valid_count += 1

            # 如果过滤完后一条有效数据都没了：
            if valid_count == 0:
                return "【内部查询结果：查到了数据，但因为价格或数量为0已被系统拦截过滤。请告知客户暂无有效报价。】"

            print("\n🤖 [API 成功联调] 喂给 AI 的库存底牌信息：\n" + inventory_text)
            return inventory_text

        else:
            return f"【查询异常：HTTP {response.status_code}】"

    except Exception as e:
        print("[库存 API 调用异常]", e)
        return "【内部系统查询失败】"


# ==========================================================
# 4. Stage 1: Multi Intent Router
# ==========================================================
def predict_intent(e_title, e_content):
    cfg = get_index_config()
    valid_intents = list(cfg.get("intent_to_module", {}).keys())

    router_schema = cfg.get("router_output_schema", {})
    non_business_cfg = cfg.get("non_business_config", {})
    router_config = cfg.get("router_config", {})

    # ==========================================
    # 🌟 新增：获取动态系统城市列表并转为字符串
    # ==========================================
    valid_cities = fetch_system_cities()
    cities_str = ", ".join(valid_cities) if valid_cities else "Shanghai, Ningbo, Qingdao, Antwerp, Rotterdam"

    router_prompt = f"""你是Hysun企业邮件意图识别引擎。

你的任务：
分析邮件标题和正文，识别主要意图、次要意图、实体信息以及动作指令。

合法意图列表：
{json.dumps(valid_intents, ensure_ascii=False, indent=2)}

非业务邮件规则：
{json.dumps(non_business_cfg, ensure_ascii=False, indent=2)}

路由配置 (优先级与多意图限制)：
{json.dumps(router_config, ensure_ascii=False, indent=2)}

========================
【🚨 地理位置识别与纠错规则】
当前我们系统支持的标准城市列表如下：
[{cities_str}]

在提取实体时，必须在 entities 中输出 "target_location" 字段。
请按以下优先级提取客户邮件中提到的地点：
1. 【城市级】：如果客户提到城市，将其强制对齐并纠错为上方列表中的标准拼写（如 Shangai -> Shanghai）。
2. 【国家/大洲级】：如果客户提到的是国家（如 Turkey, Belgium, Denmark）或大洲（如 Europe, Asia），请直接提取该英文名（例如 output: "Turkey"），绝对不可留空 ""！
3. 只有当邮件完全未提及任何地点时，才允许输出 ""。
========================
必须严格按照以下 JSON Schema 输出，确保 entities 中包含 target_location 字段：
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
            model="deepseek-chat",  # 或者您使用的其他模型
            messages=[
                {"role": "system", "content": router_prompt},
                {"role": "user", "content": f"邮件标题:{e_title}\n\n邮件正文:{e_content}\n\n请输出JSON:"}
            ],
            response_format={"type": "json_object"}, # 确保返回的是JSON
            temperature=0.1 # 调低温度，确保 Router 提取实体的稳定性
        )
        result_json = response.choices[0].message.content.strip()
        return json.loads(result_json)
    except Exception as e:
        print("[Router 预测失败]", e)
        # 降级处理，返回安全的默认 JSON
        return {
            "primary_intent": "UNKNOWN",
            "secondary_intents": [],
            "action": "NO_REPLY",
            "entities": {},
            "risk_level": "HIGH"
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
    if router_result.get("action") == "NO_REPLY" or router_result.get("primary_intent") in ["NON_BUSINESS_EMAIL",
                                                                                            "NON_CUSTOMER_EMAIL",
                                                                                            "LEASE_INQUIRY"]:
        return "NO_REPLY"

    global_rules = load_global_rules()
    response_guard = load_response_guard()
    entity_rules = load_entity_rules()
    module_context = build_skill_context(router_result)

    # --------------------------------------------------------
    # [核心修改] 获取 RAG 数据
    # --------------------------------------------------------
    inventory_data = query_internal_inventory(router_result.get("entities", {}), e_content)
    # 1. 获取动态的城市列表，例如 ["Aarhus", "Antwerp", "Shanghai", ...]
    valid_cities = fetch_system_cities()
    cities_str = ", ".join(valid_cities) if valid_cities else "系统城市库未加载"
    system_prompt = f"""你是Hysun企业资深业务员助手。
    你的任务：根据客户邮件，生成可以直接发送的商务回复。
    ========================
    【实时内部库存与价格数据 (RAG)】
    {inventory_data}
    销售转化处理规则：
    1. 【现货优先策略】：如果上方库存数据中包含“现货(On-ground)”，请优先向客户推介现货，并告知对应的指导价。
    2. 【在途备用策略】：如果上方库存数据中【没有任何现货】，但有“在途(Upcoming)”，你必须明确告知客户：“我们目前没有现货，但有 [数量] 个 [箱型] 将于 [预计到港日 ETA] 到达 [堆场名称/城市]，价格是 [价格]”。
    3. 如果客户缺失信息（如没说具体的箱况），参考现有的库存选项去反问客户（例如：“我们目前有 CW 和 IICL，您需要哪种？”）。
    4. 严禁捏造上述数据中不存在的库存、价格或到港日期！
    ========================
    【全局规则】
    {global_rules}
    【实体识别规则】
    {entity_rules}
    【回复安全控制】
    {response_guard}
    【业务SOP】
    {module_context}
    【地理位置强匹配与纠错规则】
    当前我们系统支持的标准城市列表如下：
    [{cities_str}]
    当客户在邮件中提到城市时（例如他拼写成了 "Shangai"、"Shanghi" 或写了中文"上海"），你必须发挥 AI 的纠错能力，将其强制映射为上方列表中的标准拼写！如果客户提到的地方不在该列表中，则保留原词。
    ========================
    当前邮件分析结果：
    {json.dumps(router_result, ensure_ascii=False, indent=2)}
    生成要求：
    1. 只输出邮件正文。禁止解释、Markdown 及分析过程。
    2. 必须回复邮件中的所有请求。不得添加原邮件没有的信息。
    3. 签名必须符合业务角色(Hysun Sales Team)。
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
    title = "Looking stock in Turkey"

    content = """
Good morning

Hope everything is going well.
We are looking stock in Turkey 20’DV and 40’HC.
If you have something to offer, please send us the stock with prices.
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
