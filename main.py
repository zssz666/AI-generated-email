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


# 全局缓存系统箱型列表
SYSTEM_CONTAINER_TYPES_CACHE = {}


def fetch_system_container_types():
    """
    调用后端的 /getAllBoxServlet 接口，动态同步箱型字典 (对标前端 getBoxPile)
    返回字典格式: {"40hcos4d": "31", "20dc": "03", "40hc": "25", ...}
    """
    global SYSTEM_CONTAINER_TYPES_CACHE
    if SYSTEM_CONTAINER_TYPES_CACHE:
        return SYSTEM_CONTAINER_TYPES_CACHE

    api_url = "http://47.109.176.188:81/getAllBoxServlet"  # 请确保替换为真实的完整后端地址

    try:
        response = requests.get(api_url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            box_list = data.get("obj", [])

            valid_boxes = {}
            for item in box_list:
                # 提取 id 和 箱型代码 (例如 id: 31, code: "40HC OS 4D")
                raw_id = item.get("id")
                raw_code = item.get("code", "")

                if raw_id is not None and raw_code:
                    # 将 id 转为 2 位数格式，比如 3 -> "03", 31 -> "31"
                    box_id = str(raw_id).zfill(2)

                    # 极度清洗箱型名字：转小写，去空格，去单引号
                    clean_code = raw_code.lower().replace("'", "").replace(" ", "").replace("-", "")

                    # 存入字典 {"40hcos4d": "31"}
                    valid_boxes[clean_code] = box_id

            SYSTEM_CONTAINER_TYPES_CACHE = valid_boxes
            print(f"✅ [系统启动] 成功同步系统箱型字典，共 {len(SYSTEM_CONTAINER_TYPES_CACHE)} 种箱型。")
            return SYSTEM_CONTAINER_TYPES_CACHE
    except Exception as e:
        print(f"❌ [系统告警] 获取箱型列表失败: {e}")

    return {}


# 全局缓存系统颜色列表
SYSTEM_COLORS_CACHE = {}


def fetch_system_colors():
    """
    调用后端的 getAllColorServlet 接口，动态同步颜色字典。
    """
    global SYSTEM_COLORS_CACHE
    if SYSTEM_COLORS_CACHE:
        return SYSTEM_COLORS_CACHE

    # 【已修复】直接使用你之前的硬编码完整地址
    api_url = "http://47.109.176.188:81/getAllColorServlet"

    try:
        response = requests.get(api_url, timeout=5)
        if response.status_code == 200:
            color_list = response.json().get("obj", [])
            for item in color_list:
                # 获取接口返回的真实字段名
                color_code = item.get("color_code", item.get("str", ""))
                enname = item.get("color_en", item.get("enname", ""))

                # 处理特殊的硬编码颜色
                if color_code == "0000":
                    enname = "Mixed"
                elif color_code == "8888":
                    enname = "Camo"
                elif color_code == "0001":
                    enname = "5010/6032"

                if color_code:
                    SYSTEM_COLORS_CACHE[color_code] = enname

            print(f"✅ [系统启动] 成功同步系统颜色字典，共 {len(SYSTEM_COLORS_CACHE)} 种颜色。")
            return SYSTEM_COLORS_CACHE
    except Exception as e:
        print(f"❌ [系统告警] 获取颜色列表失败: {e}")

    return {}
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

# 根据实际业务逻辑与系统编码严格映射的箱况字典
HYSUN_CONDITIONS = {
    1: "NEW",        # 出厂新箱 (特指：中国境内交货的全新箱)
    2: "New 1 trip", # 出厂1次转运新箱 (特指：海外交货的新箱)
    3: "New-IICL",   # 极优旧箱 (约使用2-9次)
    4: "IICL",       # 优质旧箱 (使用10次以上)
    5: "CW",         # 标准旧箱 (Cargo Worthy)
    6: "CW-WWT",     # 不漏风不漏水
    7: "WWT",        # 无破洞箱
    8: "ASIS",       # 现况箱
    9: "CW+"         # 优质旧箱 (状态优于普通CW)
}


def parse_hysun_idcode(idcode: str):
    """解码 Java 返回的 10 位 SKU，提取颜色、箱型与箱况"""
    if not idcode or len(idcode) != 10 or not idcode.isdigit():
        return "未知规格"

    # 截取前 4 位作为颜色码
    color_code = idcode[0:4]
    type_id = int(idcode[4:6])
    cond_id = int(idcode[6:7])

    box_type = HYSUN_CONTAINER_TYPES.get(type_id, f"Type-{type_id}")
    box_cond = HYSUN_CONDITIONS.get(cond_id, f"Cond-{cond_id}")

    # 动态匹配颜色英文名
    colors_map = fetch_system_colors()
    box_color_en = colors_map.get(color_code, "")

    # 如果有颜色，就拼接到规格后面；如果没有匹配到，就留空
    color_desc = f" | 🎨 颜色: {box_color_en}" if box_color_en else ""

    return f"{box_type} {box_cond}{color_desc}"


def encode_search_idcode(raw_type):
    """
    智能动态箱型转码引擎：基于 getAllBoxServlet 接口动态抓取数据，
    采用“最长优先匹配”杜绝截断漏洞。
    """
    if not raw_type:
        return ""

    # 1. 对客户传入的箱型进行极度清洗
    desc = raw_type.lower().replace("'", "").replace(" ", "").replace("-", "")

    # 2. 统一别名容错 (防止大模型输出全拼，或者客户写了异形词)
    desc = desc.replace("gp", "dc").replace("dv", "dc")
    desc = desc.replace("reefer", "rf").replace("opentop", "ot").replace("openside", "os")
    desc = desc.replace("doubledoor", "dd").replace("flatrack", "fr").replace("hardtop", "ht")

    # 3. 动态获取系统最新箱型字典
    container_map = fetch_system_container_types()
    if not container_map:
        return ""  # 如果接口异常抓不到数据，这里会作为兜底

    # 4. 第一层拦截：尝试完全匹配 (极速命中)
    if desc in container_map:
        return f"____{container_map[desc]}____"

    # 5. 第二层拦截：最长子串匹配 (防截断核心机制)
    # 按字典中箱型名字的长度进行降序排序，先查长名字(如 40hcos4d)，再查短名字(如 40hc)
    sorted_keys = sorted(container_map.keys(), key=len, reverse=True)
    for key in sorted_keys:
        if key in desc:
            return f"____{container_map[key]}____"

    return ""

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

    # 拿到形如 "40HC, 20DC, 40OT" 的字符串，按照逗号切分成列表
    raw_type_desc = entities.get("container_type", "")
    types_to_search = [t.strip() for t in raw_type_desc.replace('，', ',').split(',')] if raw_type_desc else [""]

    location_desc = entities.get("target_location", entities.get("release_code", "")).strip()

    # ==========================================================
    # 🌟 地理层级路由引擎（保持上一版的完美逻辑不变）
    # ==========================================================
    area_code = 0
    country_codes = []
    d_city_val = ""
    loc_lower = location_desc.lower()

    area_map = {'us & ca': 1, 'america': 1, 'us': 1, 'usa': 1, 'canada': 1, 'asia': 2, 'europe': 3, 'others': 4}
    matched_area = area_map.get(loc_lower)

    if matched_area:
        area_code = matched_area
    else:
        country_codes = get_iso2_country_code(location_desc)
        system_cities = fetch_system_cities()
        matched_city = next((city for city in system_cities if city.lower() in loc_lower), "")

        if matched_city:
            d_city_val = matched_city
        elif len(country_codes) > 0:
            d_city_val = ""
        else:
            d_city_val = location_desc

    # ==========================================================
    # 🌟 多箱型循环查询引擎
    # ==========================================================
    inventory_text = "【内部系统实时库存底牌】\n"
    valid_count = 0

    headers = {"Content-Type": "application/json"}

    # 遍历客户询问的每一种箱型，分别向 Java 发起精准检索
    for single_type in types_to_search:
        if not single_type: continue

        search_idcode = encode_search_idcode(single_type)

        payload = {
            "idCodes": search_idcode,
            "dCity": d_city_val,
            "dCountry": country_codes,
            "yardName": "",
            "area": area_code,
            "page": 1,
            "limit": 5,  # 保证每种箱型都能各自获取前 5 条最优报价
            "date": [], "resource": "", "cargo": "",
            "xcHid": 0, "xcUid": 0, "raioxcHid": 0, "raioxcUid": 0, "inventory": 0
        }

        try:
            response = requests.post(api_url, json=payload, headers=headers, timeout=8)
            if response.status_code == 200:
                raw_text = response.text
                if not raw_text.strip(): continue

                try:
                    res_json = response.json()
                except Exception:
                    continue

                page_data = res_json.get("obj", {}).get("page", [])
                if not page_data: continue

                # 遍历处理该箱型的返回数据 (0价格/数量拦截)
                for item in page_data:
                    ddepot = item.get("ddepot", {})
                    city = ddepot.get("dCity", "未知城市")
                    country = ddepot.get("dCountry", "")
                    yard = ddepot.get("dName", "")

                    readable_desc = parse_hysun_idcode(item.get("idCode", ""))
                    o_price, onground = item.get("oPrince", 0), item.get("onground", 0)
                    u_price, upcoming, eta = item.get("uPrice", 0), item.get("upcoming", 0), item.get("eta", "")

                    # 🌟 新增：安全提取 yom (年份) 字段
                    raw_yom = str(item.get("yom", "")).strip()
                    # 过滤掉空值、"0" 或 "None" 等无效年份
                    yom_desc = f" | 📅 年份: {raw_yom}" if raw_yom and raw_yom not in ["0", "None", "null"] else ""

                    has_valid_onground = (onground > 0 and o_price > 0)
                    has_valid_upcoming = (upcoming > 0 and u_price > 0)

                    if not has_valid_onground and not has_valid_upcoming:
                        continue

                    stock_info = []
                    if has_valid_onground: stock_info.append(f"现货(On-ground): {onground}个 (底价: ${o_price})")
                    if has_valid_upcoming:
                        eta_str = f", ETA: {eta}" if eta else ""
                        stock_info.append(f"在途(Upcoming): {upcoming}个 (底价: ${u_price}{eta_str})")

                    stock_desc = " | ".join(stock_info)

                    # 将 yom_desc 无缝拼接到喂给 AI 的底牌数据中
                    inventory_text += f"- 📍 [{country}] {city} ({yard}) | 📦 规格: {readable_desc}{yom_desc} | {stock_desc}\n"
                    valid_count += 1

        except Exception as e:
            print(f"[库存 API 调用异常] 箱型 {single_type}: {e}")

    # 如果所有箱型查完，一条有效数据都没有
    if valid_count == 0:
        return "【内部查询结果：当前区域暂无客户所求的匹配现货或在途库存，请致歉。】"

    print("\n🤖 [API 成功联调] 喂给 AI 的综合库存底牌信息：\n" + inventory_text)
    return inventory_text


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
   ========================
【🚨 实体提取强化规则】
1. 地理位置 (target_location):
   - 当前我们系统支持的标准城市列表如下：[{cities_str}]
   - 【城市级】：强制对齐并纠错为上方列表中的标准拼写（如 Shangai -> Shanghai）。
   - 【国家/大洲级】：直接提取英文名，绝对不可留空 ""！
   - 完全未提及地点时才允许输出 ""。

2. 箱型尺寸 (container_type): 
   - 必须完整包含【数字尺寸】、【箱型英文】以及【特殊属性/后缀】（例如：20'DC, 40'HC OS 4D, 40'OT 等）。
   - 如果包含多个箱型，用逗号分隔。
   - 🛑 绝对禁止丢弃前缀的数字尺寸或客户写的特殊特种箱后缀！
========================

必须严格按照以下 JSON Schema 输出：
{json.dumps(router_schema, ensure_ascii=False, indent=2)}

规则：
1. 【最高指令 - 身份拦截与豁免】：
   - 只要对方在邮件中表达了**“寻找、需求、购买”集装箱**的意图（如 "I need...", "Looking for..."），无论对方签名是采购经理(Purchasing)还是同行贸易公司，一律豁免，视为真实客户(Customer)！
   - 只有当对方试图【向我们推销产品/服务】、【兜售空箱】或【催收账款】时，才判定为 NON_CUSTOMER_EMAIL，并强制输出 NO_REPLY！
2. 【最高指令 - 业务拦截】：系统仅处理“销售(Sale)”业务。如果询问“租赁(Lease/Rent)”，primary_intent 必须是 LEASE_INQUIRY，action 输出 NO_REPLY！
3. 非业务邮件(营销、平台通知) -> NON_BUSINESS_EMAIL -> NO_REPLY。
4. 只有当确定对方是买家且询问买卖业务时，action 允许是 REPLY。
5. 多请求放在 secondary_intents。不要解释，不要输出 Markdown。
    """

    try:
        response = ai_client.chat.completions.create(
            model="deepseek-v4-flash",  # 或者您使用的其他模型
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
    system_prompt = f"""
        你是Hysun企业资深业务员助手。
        你的任务：根据客户邮件，生成可以直接发送的商务回复。

        ========================
        【实时内部库存与价格数据 (RAG)】
        {inventory_data}
        ========================

        【核心销售与防幻觉指令】

        1. 【现货优先策略】：如果上方库存数据中包含“现货(On-ground)”，请优先向客户推介现货，并告知对应的指导价。
        2. 【在途备用策略】：如果上方库存数据中【没有任何现货】，但有“在途(Upcoming)”，告知客户即将到港的数量和时间。
        3. 🚨【库存数量谈判策略（饥饿营销至高指令）】：
       - 除非客户在邮件中**明确提出了具体的购买数量**（例如 "I need 5 units"），否则你**【绝对禁止】主动向客户暴露我们的具体库存数字**！只需告知有现货即可。
       - 即使客户提出了具体数量，但如果我们的库存 **少于** 客户需求，也**绝对禁止暴露真实库存数字**！只需从容告知有货并报价，随后引导客户确认。
       - 只有当客户明确指定了需求数量，且我们的库存大于等于该需求时，才允许在回复中提及能够满足他的对应数量。
        4. 【无货防守】：如果客户询问的箱型查不到任何数据（如 40'OT），明确告知暂无可用库存。严禁捏造不存在的库存、价格或到港日期！

      5. 🚨【严格货品对齐（防指鹿为马与私自降级）】：
       - 严格对比“客户请求的箱型”与“RAG返回的真实箱型箱况”。
       - 🚨【绝对禁止迎合篡改】：你输出的货品规格必须 **100% 照抄 RAG 底牌**！如果底牌是 "CW+"，你写出的报价列表里就必须是 "CW+"，**绝对禁止**为了迎合客户要求的 "CW" 而私自将其删减或降级为 "CW"！

        6. 🚨【属性物理隔离与按需披露（颜色与年份 YOM）】：
       - 🚨【按需披露至高指令】：除非客户在邮件中**明确提到了**对颜色（Color）或年份（YOM）的需求，否则你**【绝对禁止】**在回复中主动提及任何颜色或年份信息！保持报价的干净和简练。
       - 只有当客户明确要求了特定颜色或年份（如 YOM 2022），你才需要去对比底层数据。如果底层数据不符，如实告知实际情况并询问是否接受。
       - ⚠️【特别声明 "Mixed" 颜色】：仅在客户询问颜色且底层为 "Mixed" 时，才解释为 "various colors"。
       - 🚨【绝对防幻觉底线】：如果客户询问了，但数据中没有标注，你【绝对禁止】自行脑补或猜测！必须诚实说明需向堆场进一步核实具体参数。

        7. 💡【箱况精准推介与场景化营销】：
           - 【新箱地域属性】：中国境内现货新箱通常为 "NEW"；海外新箱为 "New 1 trip"（因经过一次海运）。
           - 【高质量旧箱推介】：客户要求“箱况好一点的旧箱”时，优先推荐 "New-IICL" (使用2-9次的极优箱)、"IICL" 或 "CW+"。
           - 🚨【防欺诈底线】：绝不可将 "New-IICL" 当作全新出厂箱卖，必须如实说明是极优状态二手箱。

      8. 📊【精明销售心智与上下文连带推销 (Contextual Upsell)】：
       - 🚨【历史参照物联动】：如果客户在最新邮件中提到了 "same as before", "same color", "matching" 等字眼，你**必须强制阅读邮件历史记录（如 PI 详情）**，找出客户所指的具体属性（如 RAL1015/Light ivory），并**优先从 RAG 底牌中挑选出具有该相同属性的现货**进行推销！
       - 【化解价格分歧的绝招】：如果客户的目标价极低（如 $1500 买 CW），而我们只有高价新箱（如 $3500 的 New 1 trip）。在拒绝低价的同时，**必须利用匹配的属性（如相同的颜色）作为卖点来支撑高价**。例如："We don't have CW at $1500. However, if you are looking for the exact same color matching (Light ivory/Slate grey), we have brand new units available..."
       - 【最低价优先】：在满足上述条件的基础上，尽量挑选符合条件的最低价。

        9. 🏗️【特定堆场防守与同城平替 (Depot Matching)】：
           - 如果客户明确指定了堆场（如 DE WELL DEPOT），而 RAG 返回的是同城其他堆场（如 Zhuoheng depot），**绝对禁止无视客户要求直接报价**！
           - 必须先诚实礼貌地说明指定堆场无货："Currently, we do not have available stock at [指定堆场]." 随后顺势推介同城替代堆场。

      10. 📋【强制输出格式锁 (Strict Template Lock)】🚨：
       - 当你在邮件中列出具体的库存选项时，必须严格遵循以下结构填空。
       - 严禁拼错堆场名称！**严禁篡改 RAG 数据原本的箱型和箱况！**（例如：底牌是 CW+，绝对不能降级写成 CW）。
       - 根据第3条规则，如果不需要/不允许报出具体数量，请直接用 "Available" 代替具体的数字。
       - 强制参考格式（基础版 - 客户未问颜色和年份时使用）：
         - [具体数字 或 Available] units of [100%照抄底层的箱型箱况] on-ground at [严格复制堆场名] depot, at $[单价]/unit
       - 强制参考格式（完整版 - 仅当客户明确询问了对应参数时，才在末尾加上对应的括号）：
         - [具体数字 或 Available] units of [100%照抄底层的箱型箱况] on-ground at [严格复制堆场名] depot, at $[单价]/unit (Color: [颜色说明], YOM: [年份])

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
        当客户在邮件中提到城市时（如 "Shangai" 或中文"上海"），必须强制映射为上方列表中的标准拼写！若不在列表中则保留原词。
        ========================

        当前邮件分析结果：
        {json.dumps(router_result, ensure_ascii=False, indent=2)}

    ========================
    【强制回复逻辑链路 (Execution Pipeline)】🚨 必须严格按以下顺序生成邮件：
    第一步：【处理历史订单】如果邮件涉及 PI、发票或历史订单，必须先在开头确认收到，并提醒付款/索要水单（Wire proof）。
    第二步：【洞察隐藏属性】强制检索原邮件（包含引用的历史邮件），找出客户提及的颜色（如 RAL1015 = Light ivory, RAL7015 = Slate grey），以此作为匹配标准。
    第三步：【执行报价防守】如果客户目标价过低，礼貌拒绝该价格。
    第四步：【精选替代方案】从 RAG 数据中，优先挑选与客户历史颜色匹配的现货；若无颜色要求，则强制挑选同箱型中**价格最低**的 1-2 个选项！绝对禁止罗列全部数据！
    第五步：【套用格式锁】只要客户提到了 color 或 YOM，列出选项时必须 100% 遵守以下完整格式（严禁漏掉括号内的属性）：
    - [Available] units of [100%照抄底层的箱型箱况] on-ground at [严格复制堆场名] depot, at $[单价]/unit (Color: [颜色说明], YOM: [年份])
    ========================
        生成要求：
        1. 只输出邮件正文。禁止解释、Markdown 及分析过程。
        2. 必须回复邮件中的所有请求。不得添加原邮件没有的信息。
        3. 签名必须符合业务角色(Hysun Sales Team)。
        """

    try:
        response = ai_client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"邮件标题:{e_title}\n\n邮件正文:{e_content}\n\n请生成回复。"}
            ],
            temperature=0.2,
            max_tokens=1500
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
    title = "Re: HYSUN: PI No.HM599-042-2607M of 1X20DC RAL1015/1X20DC DD RAL7015 New 1 trip, POL: Dallas."

    content = """
  Thanks. I also need two 40’ HC cw at $1,500 each. Is there a way by chance to get the same color matching. Color isn’t important. If not it’s ok I still need them. Thank you. ~Nick


On Thu, Jul 30, 2026 at 2:22 AM Hysun Support <support@hysuncontainer.com> wrote:

Dear Nick,

 Good day.

 Could you kindly review the enclosed is PI No.HM599-042-2607M of 1X20DC RAL1015/1X20DC DD RAL7015 New 1 trip, POL: Dallas.

 Meantime, it is high appreciated for sharing the bank slip when you finish the payment.

 Any problem, pls feel free to contact me.

 Reminder: All invoices are valid for 3 days. If you need an extension, feel free to contact us. 

 Best Regards 
	Jia Liu
 			Senior Operation

Mail: support@hysuncontainer.com
 			Web: www.hysuncontainer.com
Hysun ECO Container  Co.,Ltd
 			HK Add: RM509, 5/F, The Cloud, 111 Tung Chau Street, Tai Kok Tsui, Kowloon, Hongkong
 			CN Add: Room W1-619, Global Center, 1700# North Tianfu Av, Chengdu City, China(610041)
 			GE Add: Am Hohenberg 27, 27711 OHZ，Niedersachsen，Germany(27711)
***Hysun team offer 7*24 online customer service, pls copy mail to support@hysuncontainer.com if any help needed or inquiry***
 ***Hysun Team offer containers trade and storage service in CN and Asia, USA, CA, EU, and stock in Africa and South America***
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
