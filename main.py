import json
import os
import re
import sys
import time
from functools import lru_cache
from datetime import datetime

import pymysql
import requests
from dotenv import load_dotenv
from openai import OpenAI
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==========================================================
# 0. 自动化日志系统 (控制台与文件双写)
# ==========================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

today_str = datetime.now().strftime("%Y-%m-%d")
log_filename = os.path.join(LOGS_DIR, f"邮件监控系统{today_str}日志.log")


class DualLogger(object):
    def __init__(self, filename):
        self.terminal = sys.stdout
        self.log = open(filename, "a", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()

    def flush(self):
        self.terminal.flush()
        self.log.flush()


sys.stdout = DualLogger(log_filename)
sys.stderr = sys.stdout

print(
    f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 系统启动，本次运行日志实时保存至: logs/邮件监控系统{today_str}日志.log\n")

# ==========================================================
# 1. 环境配置 & 数据库
# ==========================================================
load_dotenv()

ai_client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    timeout=45.0
)
AI_MODEL = "deepseek-flash"

global_session = requests.Session()
retries = Retry(total=2, backoff_factor=0.5, status_forcelist=[502, 503, 504])
global_session.mount('http://', HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10))

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
SKILLS_DIR = os.path.join(BASE_DIR, "skills")


# ==========================================================
# 2. 基础字典与缓存加载
# ==========================================================
@lru_cache(maxsize=1)
def get_index_config():
    try:
        with open(os.path.join(SKILLS_DIR, "index.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


@lru_cache(maxsize=None)
def load_skill_file(filename):
    if not filename:
        return ""
    path = os.path.join(SKILLS_DIR, "modules", filename)
    if not os.path.exists(path):
        path = os.path.join(SKILLS_DIR, filename)
    if not os.path.exists(path):
        print(f"\n❌ [致命错误] 找不到技能文件: {filename}，请检查 skills/modules 文件夹！")
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"\n❌ [致命错误] 读取技能文件失败 {path}: {e}")
        return ""


def load_entity_rules():
    return load_skill_file(get_index_config().get("entity_rules_file", "entity_rules.md"))


CITY_ABBR_MAPPING = {"ATL": "Atlanta", "BAL": "Baltimore", "BOS": "Boston", "CHA": "Charleston",
                     "CHI": "Chicago", "CHR": "Charlotte", "CIN": "Cincinnati", "CLE": "Cleveland",
                     "COL": "Columbus", "DAL": "Dallas", "DET": "Detroit", "HOU": "Houston",
                     "JAC": "Jacksonville", "KAN": "Kansas City", "LAX": "Los Angeles",
                     "LOU": "Louisville", "MEM": "Memphis", "MIA": "Miami", "MOB": "Mobile",
                     "NAS": "Nashville", "NEO": "New Orleans", "NRF": "Norfolk", "NYC": "New York City",
                     "OAK": "Oakland", "SAV": "Savannah", "SEA": "Seattle", "SLC": "Salt Lake City",
                     "TAC": "Tacoma", "TPA": "Tampa", "CAL": "Calgary", "EDM": "Edmonton",
                     "MON": "Montreal", "MTL": "Montreal", "PRU": "Prince Rupert", "TOR": "Toronto",
                     "VAN": "Vancouver", "OMA": "Omaha", "IND": "Indianapolis", "DEN": "Denver",
                     "WIN": "Winnipeg", "PNW": "Portland", "ELP": "El Paso", "STL": "Saint Louis",
                     "MSP": "Minneapolis"}

US_CA_STATE_ABBR = {"AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN",
                    "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV",
                    "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN",
                    "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "ON", "QC", "BC", "AB", "MB", "SK",
                    "NS", "NB", "NL", "PE"}

HYSUN_CONDITIONS = {1: "NEW", 2: "New 1 trip", 3: "New-IICL", 4: "IICL", 5: "CW", 6: "CW-WWT",
                    7: "WWT", 8: "ASIS", 9: "CW+"}

QUALITY_PRIORITY_ORDER = ["NEW", "New 1 trip", "New-IICL", "IICL", "CW+", "CW", "WWT", "ASIS"]

SPECIAL_KEYWORDS = ["DD", "OS", "RF", "OT", "FR", "HT", "PW", "TK",
                    "OPEN", "DOUBLE", "REEFER", "FLAT", "HARD", "TUNNEL", "SIDE", "TANK"]

SYSTEM_CITIES_CACHE = []
SYSTEM_COUNTRIES_CACHE = []
SYSTEM_CONTAINER_TYPES_CACHE = {}
SYSTEM_CONTAINER_ID_TO_NAME_CACHE = {}
SYSTEM_COLORS_CACHE = {}
_FETCHED = {"cities": False, "countries": False, "types": False, "colors": False}


def fetch_system_cities():
    global SYSTEM_CITIES_CACHE
    if not _FETCHED["cities"]:
        try:
            resp = global_session.get("http://47.109.176.188:81/ListDepot", timeout=3)
            SYSTEM_CITIES_CACHE = sorted(
                list({i.get("dCity").strip() for i in resp.json().get("obj", []) if i.get("dCity")}))
            _FETCHED["cities"] = True
        except:
            pass
    return SYSTEM_CITIES_CACHE


def fetch_system_countries():
    global SYSTEM_COUNTRIES_CACHE
    if not _FETCHED["countries"]:
        try:
            resp = global_session.get("http://47.109.176.188:81/getGcountry", timeout=3)
            SYSTEM_COUNTRIES_CACHE = [{"ISO2": i.get("ISO2", "").strip().upper(),
                                       "eName": i.get("eName", "").strip(),
                                       "cName": i.get("cName", "").strip()}
                                      for i in resp.json().get("obj", []) if i.get("ISO2") and i.get("eName")]
            _FETCHED["countries"] = True
        except:
            pass
    return SYSTEM_COUNTRIES_CACHE


def fetch_system_container_types():
    global SYSTEM_CONTAINER_TYPES_CACHE, SYSTEM_CONTAINER_ID_TO_NAME_CACHE
    if not _FETCHED["types"]:
        try:
            resp = global_session.get("http://47.109.176.188:81/getAllBoxServlet", timeout=3)
            for i in resp.json().get("obj", []):
                if i.get("id") is not None and i.get("code"):
                    b_id = str(i["id"]).zfill(2)
                    c_code = i["code"].lower().replace("'", "").replace(" ", "").replace("-", "")
                    SYSTEM_CONTAINER_TYPES_CACHE[c_code] = b_id
                    SYSTEM_CONTAINER_ID_TO_NAME_CACHE[b_id] = i["code"].strip()
            _FETCHED["types"] = True
        except:
            pass
    return SYSTEM_CONTAINER_TYPES_CACHE


def fetch_system_colors():
    global SYSTEM_COLORS_CACHE
    if not _FETCHED["colors"]:
        try:
            resp = global_session.get("http://47.109.176.188:81/getAllColorServlet", timeout=3)
            for i in resp.json().get("obj", []):
                c_code = i.get("color_code", i.get("str", ""))
                e_name = i.get("color_en", i.get("enname", ""))
                if c_code == "0000":
                    e_name = "Mixed"
                elif c_code == "8888":
                    e_name = "Camo"
                elif c_code == "0001":
                    e_name = "5010/6032"
                if c_code:
                    SYSTEM_COLORS_CACHE[c_code] = e_name
            _FETCHED["colors"] = True
        except:
            pass
    return SYSTEM_COLORS_CACHE


# ==========================================================
# 3. 辅助解析层
# ==========================================================
def parse_idcode_details(idcode: str):
    if not idcode or len(idcode) != 10 or not idcode.isdigit():
        return "40HC", "CW", "Mixed"
    color_code, type_id, cond_id = idcode[0:4], int(idcode[4:6]), int(idcode[6:7])
    fetch_system_container_types()
    box_type = SYSTEM_CONTAINER_ID_TO_NAME_CACHE.get(str(type_id).zfill(2), "40HC")
    box_cond = HYSUN_CONDITIONS.get(cond_id, "CW")
    box_color_en = fetch_system_colors().get(color_code, "Mixed")
    box_color_desc = f"{box_color_en} (RAL{color_code})" if color_code.isdigit() \
                                                            and color_code not in ["0000", "8888",
                                                                                   "0001"] else box_color_en
    return box_type, box_cond, box_color_desc


def encode_search_idcode(raw_type, color_param="", condition_param="", flp="_", lb="_", eod="_"):
    if not raw_type:
        return ""
    color_code = re.search(r'\d{4}', str(color_param)).group() if color_param and re.search(r'\d{4}',
                                                                                            str(color_param)) else "____"
    type_code = "__"

    raw_type_clean = re.sub(r'(?i)(\d+)\s*doors?', r'\1d', str(raw_type))
    desc = str(raw_type_clean).lower().replace("'", "").replace(" ", "").replace("-", "") \
        .replace("gp", "dc").replace("dv", "dc").replace("reefer", "rf").replace("opentop", "ot") \
        .replace("openside", "os").replace("doubledoor", "dd").replace("flatrack", "fr").replace("hardtop", "ht")

    desc = re.sub(r'(\d+)(dc)(dd|os|rf|ot|fr|ht|pw|fos)', r'\1\3', desc)

    special_mapping = {"20rf": "20dcrf", "40rf": "40hcrf", "45rf": "45hcrf", "20ot": "20dcot",
                       "40ot": "40dcot", "40hcot": "40hcot", "20fr": "20dcfr", "40fr": "40hcfr",
                       "20ht": "20dcht", "40ht": "40hcht", "20dd": "20dcdd", "40dd": "40hcdd",
                       "20os": "20dcos", "40os": "40hcos", "20pw": "20hcpw", "40pw": "40hcpw"}
    desc = special_mapping.get(desc, desc)

    container_map = fetch_system_container_types()
    if container_map:
        if desc in container_map:
            type_code = container_map[desc]
        else:
            for key in sorted(container_map.keys(), key=len, reverse=True):
                if key in desc:
                    type_code = container_map[key]
                    break

    reverse_cond_map = {"NEW": "1", "BRANDNEW": "1", "NEW1TRIP": "2", "1TRIP": "2", "ONEWAY": "2",
                        "SINGLETRIP": "2", "NEWIICL": "3", "IICL": "4", "CW+": "9", "CWPLUS": "9",
                        "CW": "5", "CARGOWORTHY": "5", "CWWWT": "6", "WWT": "7",
                        "WINDANDWATERTIGHT": "7", "ASIS": "8", "DAMAGED": "8"}
    condition_code = reverse_cond_map.get(str(condition_param).upper().replace(" ", "").replace("-", ""), "_") \
        if condition_param else "_"

    return f"{color_code}{type_code}{condition_code}{flp}{lb}{eod}"


def get_iso2_country_code(location_str: str):
    if not location_str:
        return []
    loc_clean = location_str.strip().lower()
    for item in fetch_system_countries():
        if loc_clean in (item["eName"].lower(), item["ISO2"].lower(), item["cName"].lower()) \
                or (len(item["eName"]) > 2 and item["eName"].lower() in loc_clean):
            return [item["ISO2"]]
    return []


def parse_locations_and_relation(loc_str: str):
    if not loc_str:
        return [], "SINGLE"
    normalized_loc = loc_str
    for abbr in US_CA_STATE_ABBR:
        normalized_loc = re.sub(rf'[,，]\s*({abbr})\b', r' \1', normalized_loc, flags=re.IGNORECASE)
    if re.search(r'\bOR\b|或者|\bEITHER\b', normalized_loc, re.IGNORECASE):
        relation, raw_cities = "OR", re.split(r'\bOR\b|或者|\beither\b', normalized_loc, flags=re.IGNORECASE)
    elif re.search(r'\bAND\b|和|&|\+|\bBOTH\b|/|[,，]', normalized_loc, re.IGNORECASE):
        relation, raw_cities = "AND", re.split(r'\bAND\b|和|&|\+|\bboth\b|/|[,，]', normalized_loc, flags=re.IGNORECASE)
    else:
        relation, raw_cities = "SINGLE", [normalized_loc]
    cleaned_cities = [re.sub(r'\s+[A-Z]{2}$', '', c.strip().strip(".,;:!?()[]"), flags=re.IGNORECASE).strip()
                      for c in raw_cities if c.strip().strip(".,;:!?()[]")]
    seen = set()
    final_cities = [x for x in cleaned_cities if not (x.lower() in seen or seen.add(x.lower()))]
    return (final_cities, relation) if final_cities else ([loc_str.strip()], "SINGLE")


def clean_draft_text(draft: str) -> str:
    """统一防脱敏清洗函数：清洗中英文邮件主题、称呼与落款"""
    draft = re.sub(r'(?i)^\s*\*\*[A-Za-z\s]+\*\*\s*\n+', '', draft, flags=re.MULTILINE)
    draft = re.sub(r'(?i)^\s*\*\*?Subject:?.*?\n+', '', draft, flags=re.MULTILINE)

    # 英文称呼过滤
    draft = re.sub(r'(?i)^\s*Dear\s+[^,\n]+,?\n+', '', draft, flags=re.MULTILINE)
    # 中文称呼过滤
    draft = re.sub(r'^\s*(?:尊敬的[^\n，,：:]+[，,：:]|您好[！!，,：:]?|你好[！!，,：:]?)\s*\n+', '', draft, flags=re.MULTILINE)

    # 中英文落款过滤
    _SIGNOFF = (
        r'thank you and best regards|thanks and regards|thank you and regards|'
        r'best regards|kind regards|warmest regards|warm regards|'
        r'sincerely yours|yours sincerely|sincerely|regards|best wishes|'
        r'祝好|此致敬礼|顺祝商祺|祝商祺|顺祝冬安|顺祝秋安|顺颂商祺|敬祝商祺'
    )
    draft = re.sub(rf'(?im)^[ \t]*({_SIGNOFF})[^\n]*\n?[\s\S]*$', '', draft)
    draft = re.sub(r'\[Your\s+[^\]]+\]', '', draft, flags=re.IGNORECASE)
    return draft.strip()


def rag_has_quotes(inv):      return "Price: USD" in inv


def rag_has_nostock(inv):     return "[NOSTOCK]" in inv


def rag_missing_info(inv):    return ("强制阻断" in inv) or ("未提供明确的" in inv)


def rag_all_nostock(inv):     return rag_has_nostock(inv) and not rag_has_quotes(inv)


def resolve_color_codes(color_name: str):
    """将客户颜色名称解析为系统4位颜色代码列表；无法识别返回 [] 表示非标冷门色"""
    name = (color_name or "").strip()
    if not name:
        return []
    m = re.search(r'(\d{4})', name)
    if m:
        return [m.group(1)]
    colors = fetch_system_colors()
    low = name.lower()
    exact, partial = [], []
    for code, en in colors.items():
        if not en:
            continue
        el = en.lower()
        if el == low:
            exact.append(code)
        elif low in el or el in low:
            partial.append(code)
    return (exact + partial)[:8]


def expand_special_variants(single_type: str):
    """客户点名的门扇变体永远第一位，其余细分变体仅作缺货平替顺推"""
    t = (single_type or "").strip()
    t_norm = re.sub(r'(?i)(\d+)\s*doors?', r'\1D', t)
    tc = t_norm.upper().replace(" ", "").replace("-", "")

    q = [t_norm]
    if any(x in tc for x in ["OS", "SIDE", "OPEN"]):
        if "40HC" in tc:
            if "4D" in tc:
                q = ["40HC OS 4D", "40HC OS FOS", "40HC OS 3D", "40HC OS 2D", "40HC OS 1D"]
            elif "FOS" in tc:
                q = ["40HC OS FOS", "40HC OS 4D", "40HC OS 2D"]
            elif "2D" in tc:
                q = ["40HC OS 2D", "40HC OS 4D", "40HC OS FOS"]
            else:
                q += ["40HC OS 4D", "40HC OS FOS", "40HC OS 3D", "40HC OS 2D", "40HC OS 1D"]
        elif "20DC" in tc:
            if "4D" in tc:
                q = ["20DC OS 4D", "20DC OS FOS", "20DC OS 2D"]
            elif "FOS" in tc:
                q = ["20DC OS FOS", "20DC OS 4D", "20DC OS 2D"]
            else:
                q += ["20DC OS 4D", "20DC OS FOS", "20DC OS 2D"]
        elif "20HC" in tc:
            q.append("20HC OS FOS")

    seen = set()
    return [x for x in q if x.strip()
            and not (x.upper().replace(" ", "") in seen or seen.add(x.upper().replace(" ", "")))]


def _city_lookup_params(city_location):
    city_loc = CITY_ABBR_MAPPING.get(city_location.upper(), city_location)
    area_code = {'us & ca': 1, 'america': 1, 'us': 1, 'usa': 1, 'canada': 1,
                 'asia': 2, 'europe': 3, 'others': 4}.get(city_loc.lower(), 0)
    country_codes, d_city_val = [], ""
    if not area_code:
        country_codes = get_iso2_country_code(city_loc)
        d_city_val = next((c for c in fetch_system_cities() if c.lower() in city_loc.lower()), "")
        if not d_city_val and not country_codes:
            d_city_val = city_loc
    return city_loc, area_code, country_codes, d_city_val


def _num(item, *keys):
    for k in keys:
        try:
            v = float(item.get(k))
        except (TypeError, ValueError):
            continue
        if v > 0:
            return v
    return 0.0


PRICE_KEYS = ("oPrice", "oPrince", "price", "Price")
ONGROUND_KEYS = ("onground", "onGround", "Pick Up")
UPCOMING_KEYS = ("upcoming", "upComing", "UpComing")


# ==========================================================
# 🌟 3.7 核心三级级联查找状态机 (带轻量缓存 + 变体平替全量日志)
# ==========================================================
def _query_single_stock(target_city, target_type, target_cond, color_code, api_url, headers, query_cache=None):
    cache_key = (str(target_city).lower(), str(target_type).lower(), str(target_cond).lower(), str(color_code))
    if query_cache is not None and cache_key in query_cache:
        return query_cache[cache_key]

    city_location, area_code, country_codes, d_city_val = _city_lookup_params(target_city)
    is_china = (area_code == 2 or any(cn in city_location.lower() for cn in
                                      ["shanghai", "ningbo", "qingdao", "tianjin", "shenzhen", "guangzhou", "xiamen",
                                       "dalian"]))

    search_idcode = encode_search_idcode(target_type, color_code, target_cond)
    payload = {"idCodes": search_idcode, "dCity": d_city_val, "dCountry": country_codes,
               "yardName": "", "area": area_code, "page": 1, "limit": 10, "date": [],
               "resource": "", "cargo": "", "xcHid": 0, "xcUid": 0,
               "raioxcHid": 0, "raioxcUid": 0, "inventory": 0}

    try:
        response = global_session.post(api_url, json=payload, headers=headers, timeout=5)
        if not (response.status_code == 200 and response.text.strip()):
            if query_cache is not None:
                query_cache[cache_key] = (None, [])
            return None, []
        page_data = response.json().get("obj", {}).get("page", [])
    except Exception as e:
        print(f"[API请求异常] {city_location} {target_type} {target_cond} {color_code}: {e}")
        if query_cache is not None:
            query_cache[cache_key] = (None, [])
        return None, []

    best_ground = None
    transit_lines = []

    for item in page_data:
        o_price = _num(item, *PRICE_KEYS)
        u_price = float(item.get("uPrice") or 0)
        onground = int(_num(item, *ONGROUND_KEYS))
        upcoming = int(_num(item, *UPCOMING_KEYS))
        eta = (item.get("eta") or "").strip()

        box_type, box_cond, color_desc = parse_idcode_details(item.get("idCode", ""))

        search_kw = target_type.upper().replace("REEFER", "RF").replace("GP", "DC") \
            .replace("OPENTOP", "OT").replace("OPENSIDE", "OS").replace("FLATRACK", "FR") \
            .replace("HARDTOP", "HT").replace("DOUBLEDOOR", "DD")
        bt_up = box_type.upper()
        is_valid_type = True
        for size in ["10", "20", "40", "45", "53"]:
            if size in search_kw and size not in bt_up:
                is_valid_type = False
        if "HC" in search_kw and "HC" not in bt_up:
            is_valid_type = False
        for flag in ["RF", "OT", "OS", "DD", "FR", "HT", "PW", "TK"]:
            if (flag in search_kw) != (flag in bt_up):
                is_valid_type = False
        if not is_valid_type:
            continue

        raw_yom = str(item.get("yom") or "").strip()
        yom_val = raw_yom if raw_yom and raw_yom not in ["0", "None", "null"] \
            else ("2025-2026" if "NEW" in box_cond.upper() else "2008-2012")

        cond_display = "NEW" if is_china and "NEW" in box_cond.upper() and "IICL" not in box_cond.upper() \
            else ("New 1-Trip" if "NEW" in box_cond.upper() and "IICL" not in box_cond.upper()
                  else ("CW" if box_cond.upper() in ["CW", "CARGOWORTHY"] else box_cond))

        common = {
            "type": box_type,
            "cond": cond_display,
            "pol": d_city_val or city_location,
            "color": color_desc,
            "yom": yom_val
        }

        if onground > 0 and o_price > 0:
            ground_q = {**common, "price": f"USD{o_price:.2f}/unit", "raw_price": o_price, "qty": onground}
            if best_ground is None or o_price < best_ground["raw_price"]:
                best_ground = ground_q

        if upcoming > 0:
            t_price_str = f"USD{u_price:.2f}/unit" if u_price > 0 else "待确认"
            transit_lines.append({**common, "price": t_price_str, "raw_price": u_price, "qty": upcoming, "eta": eta})

    result = (best_ground, transit_lines)
    if query_cache is not None:
        query_cache[cache_key] = result
    return result


def _find_best_quote_cascading(target_city, single_type, requested_condition, requested_color,
                               api_url, headers, query_cache=None):
    """
    三步级联检索：
    - Step 1: 严格精确匹配 (Type + Condition + Color)
    - Step 2: 保持箱型箱况，放宽到其它可用颜色 (Type + Condition + 其它颜色)
    - Step 3: 推荐相近箱况 (Type + 相近箱况 + 优先原色/通配颜色)
    """
    type_variants = expand_special_variants(single_type)
    color_codes = resolve_color_codes(requested_color)

    req_cond = (requested_condition or "").strip()
    if not req_cond and any(kw in single_type.upper() for kw in SPECIAL_KEYWORDS):
        req_cond = "New 1 trip"

    # 🌟 控制台 & 日志输出：特种箱顺推队列展示
    if len(type_variants) > 1:
        print(
            f"🔍 [特种箱探测队列] 提箱城市: {target_city} | 原始要求箱型: '{single_type}' | 候选探测顺序: {' ➔ '.join(type_variants)}")

    # ==========================================================
    # Step 1: 严格精确匹配 (Strict Match)
    # ==========================================================
    if requested_color and not color_codes:
        step1_colors = []
    else:
        step1_colors = color_codes if color_codes else [""]

    for idx, t in enumerate(type_variants):
        is_variant = (idx > 0) or (t.upper().replace(" ", "") != single_type.upper().replace(" ", ""))
        for c in step1_colors:
            g, t_lines = _query_single_stock(target_city, t, req_cond, c, api_url, headers, query_cache=query_cache)
            if g or t_lines:
                stock_desc = "现货" if g and not t_lines else ("在途货源" if not g and t_lines else "现货+在途")
                # 🌟 控制台 & 日志明确输出变体平替
                if is_variant:
                    print(
                        f"🔄 [特种箱平替触发] 提箱地: {target_city} | 客户原需求 '{single_type}' 无货 | 顺推命中相近变体: '{t}' ({stock_desc})")
                else:
                    print(f"🎯 [箱型精确匹配] 提箱地: {target_city} | 精确命中客户需求箱型: '{t}' ({stock_desc})")

                return {
                    "match_type": "ALT_VARIANT" if is_variant else "EXACT",
                    "orig_type": single_type,
                    "found_type": t,
                    "is_variant": is_variant,
                    "ground_quote": g,
                    "transit_quotes": t_lines
                }

    # ==========================================================
    # Step 2: 保持箱型箱况，放宽到其它可用颜色 (Alternative Colors)
    # ==========================================================
    if requested_color:
        for idx, t in enumerate(type_variants):
            is_variant = (idx > 0) or (t.upper().replace(" ", "") != single_type.upper().replace(" ", ""))
            g, t_lines = _query_single_stock(target_city, t, req_cond, "", api_url, headers, query_cache=query_cache)
            if g or t_lines:
                stock_desc = "现货" if g and not t_lines else ("在途货源" if not g and t_lines else "现货+在途")
                found_col = g["color"] if g else (t_lines[0]["color"] if t_lines else "Available Color")
                if is_variant:
                    print(
                        f"🔄 [特种箱+颜色双平替] 提箱地: {target_city} | 原需求: '{single_type}' ({requested_color}) 无货 | 顺推变体: '{t}' 替代颜色: '{found_col}' ({stock_desc})")
                else:
                    print(
                        f"🎨 [颜色平替触发] 提箱地: {target_city} | 箱型: '{t}' | 原颜色 '{requested_color}' 无货 | 替代颜色: '{found_col}' ({stock_desc})")

                return {
                    "match_type": "ALT_COLOR",
                    "orig_type": single_type,
                    "found_type": t,
                    "is_variant": is_variant,
                    "orig_color": requested_color,
                    "found_color": found_col,
                    "ground_quote": g,
                    "transit_quotes": t_lines
                }

    # ==========================================================
    # Step 3: 推荐相近箱况 (Alternative Conditions)
    # ==========================================================
    cond_clean = req_cond.upper().replace(" ", "").replace("-", "")
    if any(k in cond_clean for k in ["CW", "USED", "WWT", "ASIS", "CARGOWORTHY"]):
        cand_conditions = ["New 1 trip", "NEW", "IICL"]
    else:
        cand_conditions = ["CW", "WWT", "IICL"]

    for alt_cond in cand_conditions:
        for idx, t in enumerate(type_variants):
            is_variant = (idx > 0) or (t.upper().replace(" ", "") != single_type.upper().replace(" ", ""))
            step3_colors = (color_codes + [""]) if color_codes else [""]
            for c in step3_colors:
                g, t_lines = _query_single_stock(target_city, t, alt_cond, c, api_url, headers, query_cache=query_cache)
                if g or t_lines:
                    stock_desc = "现货" if g and not t_lines else ("在途货源" if not g and t_lines else "现货+在途")
                    found_c = g["cond"] if g else (t_lines[0]["cond"] if t_lines else alt_cond)
                    found_col = g["color"] if g else (t_lines[0]["color"] if t_lines else "Mixed")
                    if is_variant:
                        print(
                            f"🔄 [特种箱+箱况双平替] 提箱地: {target_city} | 原需求: '{single_type}' ({req_cond}) 无货 | 顺推变体: '{t}' 替代箱况: '{found_c}' ({stock_desc})")
                    else:
                        print(
                            f"📦 [箱况平替触发] 提箱地: {target_city} | 箱型: '{t}' | 原箱况 '{req_cond}' 无货 | 替代箱况: '{found_c}' ({stock_desc})")

                    return {
                        "match_type": "ALT_CONDITION",
                        "orig_type": single_type,
                        "found_type": t,
                        "is_variant": is_variant,
                        "orig_cond": req_cond if req_cond else "Original Condition",
                        "found_cond": found_c,
                        "found_color": found_col,
                        "ground_quote": g,
                        "transit_quotes": t_lines
                    }

    print(
        f"❌ [库存无匹配] 提箱地: {target_city} | 原始要求: '{single_type}' (箱况: '{req_cond}', 颜色: '{requested_color}') 经三步级联查找均无现货与在途。")
    return {"match_type": "OUT_OF_STOCK", "ground_quote": None, "transit_quotes": []}


# ==========================================================
# 🌟 4. RAG 库存检索层 (在途展示修复 + 特种箱平替标签强化)
# ==========================================================
def query_internal_inventory(entities, email_content):
    api_url = os.getenv("INVENTORY_API_URL")
    headers = {"Content-Type": "application/json"}
    line_items = entities.get("line_items") or []

    query_cache = {}

    items = []
    if line_items:
        for li in line_items:
            if isinstance(li, dict):
                try:
                    q = int(str(li.get("quantity") or 0).strip() or 0)
                except (ValueError, TypeError):
                    q = 0
                items.append({"type": (li.get("container_type") or "").strip(),
                              "cond": (li.get("condition") or "").strip(),
                              "color": (li.get("color") or "").strip(),
                              "loc": (li.get("location") or "").strip(),
                              "qty": max(q, 0)})
    else:
        raw_types = [t.strip() for t in str(entities.get("container_type") or "")
        .replace('，', ',').split(',') if t.strip()]
        raw_loc = str(entities.get("target_location") or "").strip()
        raw_cond = str(entities.get("requested_condition") or "").strip()
        raw_col = str(entities.get("requested_color") or "").strip()
        try:
            flat_qty = int(str(entities.get("requested_quantity") or 0).strip() or 0)
        except (ValueError, TypeError):
            flat_qty = 0
        if not raw_types and not raw_loc:
            return ("【内部系统强制阻断】：客户未提供明确的 箱型 (Container Type)、"
                    "箱况、地点。请直接用客户的语言生成邮件，询问缺失的具体信息。")
        for t in (raw_types or [""]):
            cond = raw_cond
            if not cond and t and any(kw in t.upper() for kw in SPECIAL_KEYWORDS):
                cond = "New 1 trip"
            items.append({"type": t, "cond": cond, "color": raw_col,
                          "loc": raw_loc, "qty": max(flat_qty, 0)})

    rows, nostock, need_ask = [], [], []
    for it in items:
        ctype, cond, colname, locdesc = it["type"], it["cond"], it["color"], it["loc"]
        m_req = it.get("qty") or 0
        tag = f"{ctype} {cond} {colname}".strip()

        if not ctype:
            need_ask.append("缺少箱型")
            continue
        if not locdesc:
            need_ask.append(f"{ctype} 的提箱地点 (Target Location)")
            continue

        cities, relation = parse_locations_and_relation(locdesc)
        avail, unavail = [], []
        for city in cities:
            res = _find_best_quote_cascading(city, ctype, cond, colname, api_url, headers, query_cache=query_cache)
            if res.get("ground_quote") or res.get("transit_quotes"):
                avail.append((city, res))
            else:
                unavail.append(city)

        for _, res in avail:
            g = res.get("ground_quote")
            t_list = res.get("transit_quotes") or []
            m_type = res.get("match_type")

            # 在途颜色过滤
            req_color_code = ""
            if colname:
                m_c = re.search(r'\d{4}', colname)
                if m_c:
                    req_color_code = m_c.group()
            if req_color_code:
                t_list = [t for t in t_list if req_color_code in t.get("color", "")]

            ground_qty = g["qty"] if g else 0
            show_transit = (ground_qty == 0) or (m_req > 0 and ground_qty < m_req)
            qty_display = str(ground_qty) if (m_req > 0 and ground_qty >= m_req) else "Available"

            if g:
                if m_type == "EXACT":
                    rows.append(f"- [EXACT] Style: {g['type']} | Condition: {g['cond']} | POL: {g['pol']} | "
                                f"Color: {g['color']} | YOM: {g['yom']} | Price: {g['price']} | "
                                f"Stock_Qty: {qty_display} | Payment: 100% TT before pick up.")
                elif m_type == "ALT_VARIANT":
                    rows.append(
                        f"- [ALT_VARIANT] (说明：客户指定的特种规格 '{res['orig_type']}' 在 {g['pol']} 严格筛选无货，顺推推荐相近规格 '{res['found_type']}') "
                        f"Style: {g['type']} | Condition: {g['cond']} | POL: {g['pol']} | "
                        f"Color: {g['color']} | YOM: {g['yom']} | Price: {g['price']} | "
                        f"Stock_Qty: {qty_display} | Payment: 100% TT before pick up.")
                elif m_type == "ALT_COLOR":
                    prefix = f"(说明：特种规格原要 '{res['orig_type']}' 顺推推荐 '{res['found_type']}，且" if res.get(
                        "is_variant") else "(说明："
                    rows.append(
                        f"- [ALT_COLOR] {prefix}客户指定的颜色 '{res['orig_color']}' 在 {g['pol']} 严格筛选无现货，推荐其它可用颜色 '{res['found_color']}') "
                        f"Style: {g['type']} | Condition: {g['cond']} | POL: {g['pol']} | "
                        f"Color: {g['color']} | YOM: {g['yom']} | Price: {g['price']} | "
                        f"Stock_Qty: {qty_display} | Payment: 100% TT before pick up.")
                elif m_type == "ALT_CONDITION":
                    prefix = f"(说明：特种规格原要 '{res['orig_type']}' 顺推推荐 '{res['found_type']}，且" if res.get(
                        "is_variant") else "(说明："
                    rows.append(
                        f"- [ALT_CONDITION] {prefix}客户指定的箱况 '{res['orig_cond']}' 在 {g['pol']} 严格筛选无现货，推荐替代箱况 '{res['found_cond']}') "
                        f"Style: {g['type']} | Condition: {g['cond']} | POL: {g['pol']} | "
                        f"Color: {g['color']} | YOM: {g['yom']} | Price: {g['price']} | "
                        f"Stock_Qty: {qty_display} | Payment: 100% TT before pick up.")

            if show_transit and t_list:
                # 🌟 在途标题区显式打印顺推信息
                if res.get("is_variant"):
                    rows.append(
                        f"===【在途补充 - 特种箱平替推荐 (客户原需求 '{res['orig_type']}' 暂无货，顺推相近规格 '{res['found_type']}')】===")
                else:
                    rows.append("===【在途补充】===")
                for t in t_list:
                    rows.append(f"- [TRANSIT] Style: {t['type']} | Condition: {t['cond']} | "
                                f"POL: {t['pol']} | Color: {t['color']} | YOM: {t['yom']} | "
                                f"ETA: {t['eta']} | Q'ty: {t['qty']} units | Price: {t['price']}")

        if unavail and (relation != "OR" or not avail):
            nostock.append(f"[NOSTOCK] {'/'.join(unavail)} | {tag}")

    if not rows and need_ask:
        return ("【内部系统强制阻断】：客户询盘缺少明确的 " + "、".join(need_ask) +
                "。无需查询库存，请直接用客户的语言生成邮件，询问缺失的具体信息。")

    rag = ""
    if rows:
        rag += "【系统整理后的有效报价底牌】\n"
        if len(items) > 1:
            rag += "(本邮件为多项分列询盘：每条报价严格对应其原始箱型/颜色/地点，严禁跨行交叉混配！)\n"
        rag += "\n".join(rows) + "\n"
    if nostock:
        rag += "\n".join(nostock) + ("\n【调度指令-无货项】：上述需求暂无匹配库存，绝对禁止编造其报价，"
                                     "请如实致歉并说明正在与堆场核实中。\n")
    if rows and need_ask:
        rag += "\n【补充追问】：请在邮件末尾礼貌请客户补充——" + "；".join(need_ask) + "。\n"
        for a in need_ask:
            rag += f"[ASK] {a}\n"

    if not rag:
        return "【内部查询结果：当前区域暂无客户所求的匹配现货或在途库存，请致歉并说明正在核实。】"
    return rag


# ==========================================================
# 5. Stage 1: Router
# ==========================================================
def predict_intent(e_title, e_content):
    cfg = get_index_config()
    abbr_list_str = ", ".join([f"{k}({v})" for k, v in CITY_ABBR_MAPPING.items()])
    schema_str = json.dumps(cfg.get("router_output_schema", {}), ensure_ascii=False, separators=(',', ':'))
    router_template = load_skill_file("00_router_engine.md")
    router_prompt = (router_template
                     .replace("{{abbr_list}}", abbr_list_str)
                     .replace("{{entity_rules}}", load_entity_rules())
                     .replace("{{schema}}", schema_str))
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = ai_client.chat.completions.create(
                model=AI_MODEL,
                messages=[{"role": "system", "content": router_prompt},
                          {"role": "user", "content": f"邮件标题:{e_title}\n\n邮件正文:{e_content}\n\n请输出JSON:"}],
                temperature=0.0,
                max_tokens=8000
            )
            raw = response.choices[0].message.content.strip()
            if match := re.search(r'\{.*\}', raw, re.DOTALL):
                raw = match.group()
            return json.loads(raw)
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 * (2 ** attempt))
                continue
            return {"primary_intent": "UNKNOWN", "action": "NO_REPLY",
                    "intercept_reason": "Router 解析超时拦截"}


# ==========================================================
# 🌟 6. Stage 3: AI邮件生成 (Drafter)
# ==========================================================
def _extract_rag_rows(inventory_data):
    pat = re.compile(
        r"-\s*(?:\[[A-Z_]+\][^\n|]*?)?\s*Style:\s*(.*?)\s*\|\s*Condition:\s*(.*?)\s*\|\s*POL:\s*(.*?)\s*\|\s*Color:\s*(.*?)\s*\|"
        r"\s*YOM:\s*(.*?)\s*\|\s*Price:\s*(.*?)\s*\|\s*Stock_Qty:\s*(\d+|Available)\s*\|\s*Payment:\s*([^\n|]*)")
    return [tuple(g.strip() for g in m.groups()) for m in pat.finditer(inventory_data)]


def _safe_fallback_draft(e_content, inventory_data):
    """确定性中英双语兜底：避免中文邮件触发 Reviewer 语言不一致拦截"""
    is_chinese = any('\u4e00' <= char <= '\u9fff' for char in e_content)

    if rag_missing_info(inventory_data):
        if is_chinese:
            return ("感谢您的询盘。为了能给您提供准确的报价，请问能否请您补充以下细节？\n\n"
                    "- 所需箱型（如 20DC, 40HC）\n"
                    "- 箱况要求（新箱 / 适货旧箱 CW）\n"
                    "- 提箱地点\n\n"
                    "收到您的具体信息后，我们将在第一时间为您提供最优报价。")
        return ("Thank you for your inquiry. To prepare an accurate quotation, could you please kindly "
                "confirm the following details?\n\n- Container type (e.g., 20DC, 40HC)\n"
                "- Condition (New / Used CW)\n- Pickup location\n\n"
                "Once received, we will revert with our best offer immediately.")

    rows = _extract_rag_rows(inventory_data)
    blocks = []
    for style, cond, pol, color, yom, price, qty, pay in rows:
        qt = f"{qty} units" if qty.isdigit() else "Available"
        blocks.append(f"Style: {style}\nCondition: {cond}\nPOL: {pol}\nColor: {color}\n"
                      f"YOM: {yom}\nPrice: {price}\nQ'ty: {qt}\nPayment: {pay}")

    if not blocks:
        has_ns = "[NOSTOCK]" in inventory_data
        if is_chinese:
            return ("感谢您的询盘。十分抱歉，目前在您所要求的地区暂无完全匹配上述规格的现货库存。"
                    + (
                        " 我们正在与堆场进一步核实最新到港情况，稍后有更新会第一时间答复您。" if has_ns else " 请问您是否有其它规格或地点可以考虑？"))
        return ("Thank you for your inquiry. We sincerely apologize that we currently do not have "
                "matching stock for the specifications you requested."
                + (" We are verifying availability with our depots and will revert as soon as possible."
                   if has_ns else " Could you kindly share more details so we can check further?"))

    if is_chinese:
        if "[ALT_VARIANT]" in inventory_data:
            body = "感谢您的询盘。严格按照您的要求，目前暂无您指定门扇/特种规格的现货。作为替代参考方案，我们为您推荐如下相近规格现货：\n\n"
        elif "[ALT_COLOR]" in inventory_data:
            body = "感谢您的询盘。严格按照您的要求，目前暂无您指定颜色的现货。如果您考虑其它颜色，我们为您推荐如下可用现货：\n\n"
        elif "[ALT_CONDITION]" in inventory_data:
            body = "感谢您的询盘。严格按照您的要求，目前暂无您指定箱况的现货。作为替代参考方案，我们为您推荐如下可用现货：\n\n"
        else:
            body = "感谢您的询盘，请查阅我们的最优报价：\n\n"
    else:
        if "[ALT_VARIANT]" in inventory_data:
            body = ("Thank you for your inquiry. Please note that containers strictly matching your requested "
                    "special door/variant specification are currently unavailable. However, as an alternative option, "
                    "we are pleased to recommend the following available option:\n\n")
        elif "[ALT_COLOR]" in inventory_data:
            body = ("Thank you for your inquiry. Please note that containers strictly matching your requested "
                    "color are currently unavailable. However, if you would consider an alternative color, "
                    "we are pleased to recommend the following available option:\n\n")
        elif "[ALT_CONDITION]" in inventory_data:
            body = ("Thank you for your inquiry. Please note that containers strictly matching your requested "
                    "condition are currently unavailable. However, as an alternative option, we are pleased to "
                    "recommend the following available containers:\n\n")
        else:
            body = "Thank you for your inquiry. Please find our best offer below:\n\n"

    body += "\n\n".join(blocks)

    asks = re.findall(r'^\[ASK\]\s*(.+)$', inventory_data, re.M)
    if asks:
        ask_text = "；".join(asks) if is_chinese else "; ".join(asks)
        body += f"\n\n{'另外，能否请您协助确认：' if is_chinese else 'Additionally, could you please kindly confirm: '}{ask_text}?"

    nostock_lines = re.findall(r'^\[NOSTOCK\]\s*(.+)$', inventory_data, re.M)
    if nostock_lines:
        cleaned = [ln.replace('|', ' - ').strip() for ln in nostock_lines]
        if is_chinese:
            body += f"\n\n关于以下规格（{'；'.join(cleaned)}），目前暂无现货，我们正在与堆场核实并会及时更新。"
        else:
            body += ("\n\nRegarding the following specifications ("
                     + "; ".join(cleaned) + "), we do not have matching stock at the "
                                            "moment. We are verifying availability with our depots and will "
                                            "update you as soon as possible.")

    body += "\n\n如需推进订单或有任何疑问，请随时联系我们。" if is_chinese else "\n\nPlease let us know if you would like to proceed."
    return body


def generate_draft_reply(e_title, e_content, router_result, inventory_data,
                         previous_draft=None, rejection_reason=None):
    if router_result.get("action") == "NO_REPLY":
        return "NO_REPLY"

    sales_sop = load_skill_file("01_sales_inquiry.md")

    if rag_missing_info(inventory_data):
        scenario_rules = """[SCENARIO: MISSING INFORMATION]
1. Output ONLY a polite request asking the customer to clarify the missing details listed in the stock data.
2. ZERO TOLERANCE: NO quote blocks, NO "best offer" opening, NO Subject, NO Dear, NO Signatures."""
    elif rag_all_nostock(inventory_data):
        scenario_rules = """[SCENARIO: FULLY OUT OF STOCK]
1. Output a polite apology — we do not have matching stock for ANY requested specification and are verifying with our depots.
2. Body MUST be exactly this shape (may polish wording slightly, do NOT add/remove sections):
   "Thank you for your inquiry. We sincerely apologize that we currently do not have matching stock for the specifications you requested. We are verifying availability with our depots and will revert as soon as possible."
   Closing line: "Please let us know if you need any other assistance."
3. ZERO TOLERANCE: NO quote blocks, NO Price, NO Q'ty, NO "Please find our best offer below", NO Subject, NO Dear, NO Signatures."""
    else:
        scenario_rules = """[SCENARIO: QUOTATION & RECOMMENDATION]
    1. Opening line & Explanatory Wording (STRICT COMPLIANCE):
       - If all items are [EXACT]:
         Opening MUST be: "Thank you for your inquiry. Please find our best offer below:" (中文: "感谢您的询盘，请查阅我们的最优报价：")
       - If an item is tagged [ALT_VARIANT] or mentions special variant fallback (e.g. 2-door out of stock, offering 4-door):
         You MUST explicitly state that strictly per customer's requirements the requested door/variant specification is unavailable, then introduce the recommended specification as an alternative:
         "Thank you for your inquiry. Please note that containers strictly matching your requested specification are currently unavailable. However, as an alternative option, we are pleased to recommend the following available option:"
         (中文询盘: "感谢您的询盘。严格按照您的要求，目前暂无您指定门扇/特种规格的现货。作为替代参考方案，我们为您推荐如下相近规格现货：")
       - If an item is tagged [ALT_COLOR] (requested color out of stock):
         You MUST explicitly state that strictly per customer's requirements the requested color is unavailable, then introduce the recommended color:
         "Thank you for your inquiry. Please note that containers strictly matching your requested color are currently unavailable. However, if you would consider an alternative color, we are pleased to recommend the following available option:"
         (中文询盘: "感谢您的询盘。严格按照您的要求，目前暂无您指定的颜色现货。如果您考虑其它颜色，我们为您推荐如下可用现货：")
       - If an item is tagged [ALT_CONDITION] (requested condition out of stock):
         You MUST explicitly state that strictly per customer's requirements the requested condition is unavailable, then introduce the recommended condition:
         "Thank you for your inquiry. Please note that containers in your requested condition are currently unavailable. However, as an alternative option, we are pleased to recommend the following available containers:"
         (中文询盘: "感谢您的询盘。严格按照您的要求，目前暂无您指定箱况的现货。如果您考虑其它箱况作为替代，我们为您推荐如下现货：")
    2. Quote Block Rules (NO DUPLICATES):
       - For each UNIQUE container specification (Style + POL + Condition + Color), output EXACTLY ONE standard quote block.
       - NEVER output duplicate quote blocks for the same container specification. If there are multiple transit batches with different ETAs/quantities for the same container, display ONE quote block and explain the arrival batches in the narrative below.
       - Payment line copied EXACTLY: "Payment: 100% TT before pick up."
    3. Collateral requests handling (CRITICAL):
       - If customer asks for sales contacts, purchase agreement/proforma, or specific depot location: state in ONE sentence that our sales team will provide the proforma invoice/agreement and specific release details immediately upon your confirmation of the offer.
       - If customer asks for lease/rental rate: politely clarify that we specialize in direct container sales rather than short-term lease.
    4. Closing line MUST be: "Please let us know if you would like to proceed." (中文: "如需推进订单或有任何疑问，请随时联系我们。")
    5. ZERO TOLERANCE: NO bold city headers, NO Subject, NO Dear, NO Signatures, NEVER invent depot names, NEVER invent phone numbers/person names."""

    system_prompt = f"""You are a professional sales representative at Hysun Container. Strictly follow the Sales SOP, the verified stock data and the scenario rules. NEVER return an empty answer; if unsure, quote the stock data verbatim.

    LANGUAGE MIRROR: Reply in the customer's dominant business language (English inquiry → English, Chinese → Chinese). EXCEPTION: inside quote blocks, keep all field labels (Style/Condition/POL/Color/YOM/Price/Q'ty/Payment) and the Payment clause "Payment: 100% TT before pick up." EXACTLY in English as shown — only narrative sentences are mirrored.

    {sales_sop}
==================================================
【VERIFIED STOCK DATA (RAG)】
==================================================
{inventory_data}
==================================================
{scenario_rules}
=================================================="""

    user_prompt = (f"Customer Title: {e_title}\n\nCustomer Body: {e_content}\n\n"
                   f"Please generate the clean email body:")
    if previous_draft and rejection_reason:
        user_prompt = (f"QA REJECTED the previous draft.\nREASON: {rejection_reason}\n\n"
                       f"PREVIOUS DRAFT:\n{previous_draft}\n\n"
                       f"Rewrite the full email fixing ONLY the reported problem, keeping all other "
                       f"required clauses. Do NOT return an empty message.")

    temperature = 0.0 if rejection_reason else 0.1
    last_err = ""
    for attempt in range(3):
        try:
            response = ai_client.chat.completions.create(
                model=AI_MODEL,
                messages=[{"role": "system", "content": system_prompt},
                          {"role": "user", "content": user_prompt}],
                temperature=temperature, max_tokens=5000
            )
            raw_out = (response.choices[0].message.content or "").strip()
            draft = clean_draft_text(raw_out)
            if draft and len(draft) >= 15:
                return draft
            last_err = f"第{attempt + 1}次生成异常(原始{len(raw_out)}字符→清洗后{len(draft)}字符)"
        except Exception as e:
            last_err = f"Drafter 异常: {e}"
        print(f"⚠️ [Drafter] {last_err}，重试中...")
        time.sleep(1 + attempt)

    print(f"💥 [Drafter] 重试耗尽({last_err})，切换确定性兜底模板。")
    return _safe_fallback_draft(e_content, inventory_data)


# ==========================================================
# 🌟 7. Stage 4: Reviewer
# ==========================================================
def review_ai_reply(original_title, original_content, draft_reply, router_result, inventory_data):
    if draft_reply == "NO_REPLY":
        return (True, "") if router_result.get("action") == "NO_REPLY" \
            else (False, "Router said REPLY but got NO_REPLY")

    # 1. Python 代码级硬校验
    if rag_has_quotes(inventory_data):
        if not re.search(r'(?:Payment|付款方式)\s*:.*?100%\s*T/?T', draft_reply, re.IGNORECASE):
            return False, "Missing mandatory clause: 'Payment: 100% TT before pick up.'"
        if not re.search(r"(?:Q['’]?ty|数量)\s*:\s*(\d+|Available|现货)", draft_reply, re.IGNORECASE):
            return False, "Missing mandatory clause: 'Q\\'ty' must be a specific number or 'Available'."

    if "Cargo Worthy" in draft_reply:
        return False, "Forbidden long name 'Cargo Worthy' found. Must use 'CW'."
    if re.search(r'^\s*\*\*[A-Za-z\s]+\*\*\s*$', draft_reply, re.MULTILINE):
        return False, "Forbidden bold header (**City**) found."
    if re.search(r'\b(Dear|Subject:|\[Your\b)', draft_reply, re.IGNORECASE):
        return False, "Draft contains forbidden email headers or signature placeholders."
    if "|" in draft_reply:
        return False, "Draft contains forbidden Markdown table syntax (|)."

    # 2. 场景一致性校验
    lower_draft = draft_reply.lower()
    if rag_all_nostock(inventory_data):
        if re.search(r"style\s*:|q['’]?ty\s*:|payment\s*:", draft_reply, re.IGNORECASE):
            return False, "Out-of-stock scenario but draft contains quote clauses (hallucinated offer)."
        if "please find our best offer below" in lower_draft or "请查阅我们的最优报价" in draft_reply:
            return False, "Contradictory quotation opening in out-of-stock reply."
    elif rag_has_quotes(inventory_data):
        if (
                "please find our best offer below" in lower_draft or "recommend" in lower_draft or "请查阅" in draft_reply or "推荐" in draft_reply) \
                and not re.search(r"style\s*:", draft_reply, re.I):
            return False, "Quotation/recommendation opening present but no Style quote block found."

    # 3. LLM 审核员
    sales_sop = load_skill_file("01_sales_inquiry.md")
    reviewer_template = load_skill_file("02_response_guard.md")
    review_prompt = reviewer_template.format(sales_sop=sales_sop, inventory_data=inventory_data)
    try:
        response = ai_client.chat.completions.create(
            model=AI_MODEL,
            messages=[{"role": "system", "content": review_prompt},
                      {"role": "user", "content": f"AI Draft:\n{draft_reply}"}],
            temperature=0, response_format={"type": "json_object"}
        )
        raw = response.choices[0].message.content.strip()
        if match := re.search(r'\{.*\}', raw, re.DOTALL):
            raw = match.group()
        data = json.loads(raw)
        return data.get("status", "FAIL").upper() == "PASS", data.get("feedback", "")
    except Exception as e:
        print(f"[Reviewer 异常] {e}")
        return True, ""


# ==========================================================
# 8. 统一入口与执行调度
# ==========================================================
ALLOWED_REPLIER_INTENTS = {"STOCK_PRICE_INQUIRY", "STRATEGIC_BULK_INQUIRY"}


def _build_noreply_reason(e_title, e_content, router_result):
    p_intent = router_result.get("primary_intent", "UNKNOWN")
    s_intents = router_result.get("secondary_intents", []) or []

    if p_intent in ("DEDICATED_CONTACT_REQUEST", "STRATEGIC_BULK_INQUIRY"):
        return "客户索要专属对接人或大宗/定制合作，需人工业务经理线下介入。"

    try:
        response = ai_client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content":
                    "你是邮件分类助手。系统已判定以下邮件无需自动回复。"
                    "请根据邮件内容用一句简洁的中文（15~40字）说明不自动回复的具体原因。"
                    "若为垃圾营销/系统通知注明其性质；若为重要大宗/特殊需求注明需人工跟进。"
                    "只输出原因本身，禁止输出任何前缀、引号或多余标点。"},
                {"role": "user", "content":
                    f"邮件标题：{e_title}\n\n邮件正文：{e_content}\n\n"
                    f"系统识别的意图标签：{p_intent}"
                    f"{', ' + ', '.join(s_intents) if s_intents else ''}"}
            ],
            temperature=0.0, max_tokens=1000
        )
        reason = (response.choices[0].message.content or "").strip()
        reason = reason.strip('"“”\'').strip()
        reason = re.sub(r'^(原因[：:]\s*)', '', reason)
        if reason:
            return reason
    except Exception as e:
        print(f"⚠️ [NO_REPLY原因生成异常] {e}")
    return f"系统判定为{p_intent}，转人工或无需自动回复。"


def generate_manager_handover_draft(e_title, e_content, router_result=None):
    """
    大宗合作/需人工评估询盘的标准收件回执
    """
    system_prompt = """You are a professional email assistant at Hysun Container.
Write a concise, polite, and well-formatted business acknowledgment email.

【Core Content (1 Short Paragraph Only)】
Thank the customer for their email and inquiry, and state that we will review their requirements and respond at our earliest convenience.

【Strict Prohibitions - ZERO TOLERANCE】
1. NO PARROTING: Absolutely DO NOT echo customer details (such as TEU quantities, company names, business models, or corridors).
2. NO COMMERCIAL PROMISES: Do NOT claim we can supply, do NOT promise prices or lead times. Keep it strictly as an administrative receipt.
3. CONCISE: Keep the entire text to 1-2 concise sentences (under 35 words).

【Formatting & Language】
1. Output 1 single, clean paragraph.
2. Output the bare email body ONLY (NO Subject, NO "Dear...", NO sign-offs/signatures).
3. Strictly mirror the customer's email language."""

    user_prompt = f"Customer Email Title: {e_title}\n\nCustomer Email Body:\n{e_content}\n\nPlease generate the concise email body:"

    for attempt in range(2):
        try:
            response = ai_client.chat.completions.create(
                model=AI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.0,
                max_tokens=150
            )
            raw_out = (response.choices[0].message.content or "").strip()
            draft = clean_draft_text(raw_out)
            if draft and len(draft) >= 10:
                return draft
        except Exception as e:
            print(f"⚠️ [Handover Draft 生成异常 第{attempt + 1}次] {e}")
            time.sleep(1)

    is_chinese = any('\u4e00' <= char <= '\u9fff' for char in e_content)
    if is_chinese:
        return "感谢您的来信与询盘。我们正在评估您的具体需求，并将尽快与您取得联系并予以答复。"
    return "Thank you for your email and inquiry. We will review your requirements and respond to you at our earliest convenience."


def generate_ai_reply(e_title, e_content, flag):
    print("📥 [DEBUG 接收到的原始邮件]")
    print(f"【标题】: {e_title}\n【正文】:\n{e_content}\n" + "=" * 50 + "\n")

    print("Stage 1: Intent Router...")
    router_result = predict_intent(e_title, e_content)
    print("Router Result:", json.dumps(router_result, ensure_ascii=False))

    p_intent = str(router_result.get("primary_intent") or "UNKNOWN").strip()

    # 1. 战略大宗合作优先走人工转交回复（不被 NO_REPLY 拦截）
    if p_intent == "STRATEGIC_BULK_INQUIRY":
        print("\n🤝 [大宗/长线合作询盘] 匹配战略合作意图，生成业务经理对接草稿...")
        handover_draft = generate_manager_handover_draft(e_title, e_content, router_result)
        print("\n====== 最终经理转交邮件 ======\n" + handover_draft + "\n==========================\n")
        return handover_draft

    # 2. 拦截检查
    if router_result.get("action") == "NO_REPLY":
        specific_reason = _build_noreply_reason(e_title, e_content, router_result)
        print(f"\n🚫 [提前拦截] {specific_reason}")
        return f"NO_REPLY_REASON::{specific_reason}"

    if p_intent not in ALLOWED_REPLIER_INTENTS:
        specific_reason = _build_noreply_reason(e_title, e_content, router_result)
        print(f"\n🚫 [范围外拦截] {specific_reason}")
        return f"NO_REPLY_REASON::{specific_reason}"

    # 3. 散单现货库存级联检索 (STOCK_PRICE_INQUIRY)
    inventory_data = query_internal_inventory(router_result.get("entities", {}), f"{e_title}\n{e_content}")
    if flag == 3 and rag_all_nostock(inventory_data):
        print(f"\n🚫 [群发静默] 群发邮件(flag=3)且无可用库存，系统自动放弃回复。")
        return "NO_REPLY_REASON::群发邮件无现货"

    print("\n🤖 [DEBUG 查到的库存底牌]：\n" + inventory_data)

    print("Stage 2/3: Generate Draft...")
    draft = generate_draft_reply(e_title, e_content, router_result, inventory_data)

    feedback = ""
    for attempt in range(2):
        print(f"Stage 4: Reviewing (Attempt {attempt + 1})...")
        passed, feedback = review_ai_reply(e_title, e_content, draft, router_result, inventory_data)
        if passed:
            print("\n====== 最终邮件 (PASS) ======\n" + draft + "\n======================\n")
            return draft
        else:
            print(f"❌ [Reviewer 打回] 原因: {feedback}")
            print(f"--- 🚫 遭拒草稿内容 ---\n{draft}\n-------------------------------")
            draft = generate_draft_reply(e_title, e_content, router_result, inventory_data,
                                         previous_draft=draft, rejection_reason=feedback)

    print(f"⚠️ [Drafter] 审核未通过，切换安全确定性兜底模板...")
    safe_draft = _safe_fallback_draft(e_content, inventory_data)
    passed, _ = review_ai_reply(e_title, e_content, safe_draft, router_result, inventory_data)
    if passed:
        return safe_draft

    print(f"\n💥 [致命警告] 兜底质检亦未通过，硬性阻断！")
    return f"REVIEW_FAILED::{feedback}"


def process_pending_emails():
    conn = None
    e_id = None
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(
                f"UPDATE {TABLE_NAME} SET ai_status = 0 "
                f"WHERE ai_status = 1 AND uptime < DATE_SUB(NOW(), INTERVAL 30 MINUTE);"
            )
            conn.commit()

            cursor.execute(
                f"SELECT e_id, e_title, e_content, flag FROM {TABLE_NAME} "
                f"WHERE ai_status = 0 AND flag IN (2, 3) AND fb_mail IS NULL "
                f"AND DATE(uptime) = CURDATE() ORDER BY uptime DESC LIMIT 1 FOR UPDATE;"
            )
            email = cursor.fetchone()
            if not email:
                return False

            e_id = email["e_id"]
            title = email.get("e_title", "")
            content = email.get("e_content", "")
            flag = email.get("flag", 2)
            cursor.execute(f"UPDATE {TABLE_NAME} SET ai_status = 1 WHERE e_id=%s", (e_id,))
            conn.commit()

            print("\n" + "=" * 50 + f"\n【id】: {e_id}")
            reply = generate_ai_reply(title, content, flag)

            if reply and str(reply).startswith("NO_REPLY_REASON::"):
                cursor.execute(f"UPDATE {TABLE_NAME} SET ai_reply=%s, ai_status=4, uptime=NOW() WHERE e_id=%s",
                               (reply.split("::", 1)[1], e_id))
            elif reply and str(reply).startswith("REVIEW_FAILED::"):
                cursor.execute(f"UPDATE {TABLE_NAME} SET ai_reply=%s, ai_status=3, uptime=NOW() WHERE e_id=%s",
                               (f"审核打回: {reply.split('::', 1)[1]}", e_id))
            elif reply:
                cursor.execute(f"UPDATE {TABLE_NAME} SET ai_reply=%s, ai_status=2, uptime=NOW() WHERE e_id=%s",
                               (reply, e_id))
            else:
                cursor.execute(f"UPDATE {TABLE_NAME} SET ai_reply='生成失败', ai_status=3, uptime=NOW() WHERE e_id=%s",
                               (e_id,))
            conn.commit()
            return True
    except Exception as e:
        print(f"💥 [生产处理错误] 邮件ID: {e_id}, 错误: {e}")
        if conn and e_id:
            try:
                with conn.cursor() as err_cursor:
                    err_cursor.execute(
                        f"UPDATE {TABLE_NAME} SET ai_reply=%s, ai_status=3, uptime=NOW() WHERE e_id=%s",
                        (f"系统运行异常: {str(e)[:200]}", e_id)
                    )
                conn.commit()
            except:
                conn.rollback()
        return False
    finally:
        if conn:
            conn.close()


def process_all_pending_emails():
    processed_count = 0
    while process_pending_emails():
        processed_count += 1
    print(f"\n✅ 处理完成，共处理 {processed_count} 封邮件。")


def test_static_email():
    title = "NEED TRIDOOR IN MTL"
    content = """Hello,


 Price for 


 20TRIDOOR in Montreal


 thanks!"""
    generate_ai_reply(title, content, 2)


if __name__ == "__main__":
    # test_static_email()
    process_all_pending_emails()