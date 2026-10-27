import json
import unicodedata
from difflib import SequenceMatcher
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
    except Exception as e:
        print(f"⚠️ [index.json 加载失败] {e}，将使用内置默认值")
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

QUALITY_PRIORITY_ORDER = [
    "NEW",
    "New 1 trip",
    "New-IICL",
    "IICL",
    "CW+",
    "CW",
    "CW-WWT",
    "WWT",
    "ASIS"
]

# 客户未指明箱况时的销售策略（美元/单箱，不是订单总金额）
BUDGET_GAP_THRESHOLD_USD = 300.0  # 新箱价格 >= 目标单价 + 300 时尝试增报一款
BUDGET_NEAR_RANGE_USD = 300.0     # “价格接近”采用目标单价 ±300 的可解释规则

SPECIAL_KEYWORDS = ["DD", "OS", "RF", "OT", "FR", "HT", "PW", "TK",
                    "OPEN", "DOUBLE", "REEFER", "FLAT", "HARD", "TUNNEL", "SIDE", "TANK",
                    "TRI", "TRIDOOR", "3D", "DOOR", "DOORS"]

SYSTEM_CITIES_CACHE = []
SYSTEM_COUNTRIES_CACHE = []
SYSTEM_CONTAINER_TYPES_CACHE = {}
SYSTEM_CONTAINER_ID_TO_NAME_CACHE = {}
SYSTEM_COLORS_CACHE = {}
_FETCHED = {"cities": False, "countries": False, "types": False, "colors": False}

# 🌟 箱型清单 prompt 缓存：失败不缓存，下次重试
_BOX_LIST_CACHE = {"value": ""}
_FETCHED_BOX_LIST = {"done": False}


def fetch_system_cities():
    global SYSTEM_CITIES_CACHE
    if not _FETCHED["cities"]:
        try:
            resp = global_session.get("http://47.109.176.188:81/ListDepot", timeout=3)
            SYSTEM_CITIES_CACHE = sorted(
                list({i.get("dCity").strip() for i in resp.json().get("obj", []) if i.get("dCity")}))
            _FETCHED["cities"] = True
        except Exception as exc:
            print(f"⚠️ [ERP 城市清单读取失败] {exc}")
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


def get_box_type_prompt_list():
    """
    拉取系统权威箱型清单，格式化为 Router prompt 用的文本。
    格式：编号 | 缩写 | 英文全称 | 中文全称
    🌟 失败不缓存，下次调用会重试。
    """
    global _FETCHED_BOX_LIST
    if _FETCHED_BOX_LIST["done"]:
        return _BOX_LIST_CACHE["value"]

    try:
        resp = global_session.get("http://47.109.176.188:81/getAllBoxServlet", timeout=5)
        lines = []
        for i in resp.json().get("obj", []):
            b_id = str(i.get("id", "")).zfill(2)
            code = (i.get("code") or "").strip()
            if not code:
                continue

            # 兼容多种字段名
            en = ""
            for k in ["enName", "ename", "eName", "english", "en", "EnglishName"]:
                if i.get(k):
                    en = str(i[k]).strip()
                    break
            cn = ""
            for k in ["cName", "cname", "chinese", "cn", "ChineseName", "name"]:
                if i.get(k):
                    cn = str(i[k]).strip()
                    break

            parts = [b_id, code]
            if en:
                parts.append(en)
            if cn:
                parts.append(cn)
            lines.append(" | ".join(parts))

        result = "\n".join(lines)
        if result.strip():
            _BOX_LIST_CACHE["value"] = result
            _FETCHED_BOX_LIST["done"] = True
            print(f"✅ [箱型清单] 已加载 {len(lines)} 条系统箱型供 Router 对齐")
        else:
            print(f"⚠️ [箱型清单] API 返回空，本次不缓存，下次将重试")
        return result
    except Exception as e:
        print(f"⚠️ [箱型清单拉取失败] {e}，本次不缓存，下次将重试")
        return ""


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


def encode_search_idcode(raw_type, color_param="", condition_param="", flp="_", lb="_", eod="_", is_china=False):
    if not raw_type:
        return ""
    color_code = re.search(r'\d{4}', str(color_param)).group() if color_param and re.search(r'\d{4}',
                                                                                            str(color_param)) else "____"
    type_code = "__"

    raw_type_clean = re.sub(r'(?i)(\d+)\s*doors?', r'\1d', str(raw_type))
    raw_type_clean = re.sub(r'(?i)tri[-_\s]*doors?', '3d', raw_type_clean)

    desc = str(raw_type_clean).lower().replace("'", "").replace(" ", "").replace("-", "") \
        .replace("gp", "dc").replace("dv", "dc").replace("reefer", "rf").replace("opentop", "ot") \
        .replace("openside", "os").replace("doubledoor", "dd").replace("flatrack", "fr").replace("hardtop", "ht") \
        .replace("tridoor", "3d")

    desc = re.sub(r'(\d+)(dc)(dd|os|rf|ot|fr|ht|pw|fos|3d)', r'\1\3', desc)

    special_mapping = {"20rf": "20dcrf", "40rf": "40hcrf", "45rf": "45hcrf", "20ot": "20dcot",
                       "40ot": "40dcot", "40hcot": "40hcot", "20fr": "20dcfr", "40fr": "40hcfr",
                       "20ht": "20dcht", "40ht": "40hcht", "20dd": "20dcdd", "40dd": "40hcdd",
                       "20os": "20dcos", "40os": "40hcos", "20pw": "20hcpw", "40pw": "40hcpw",
                       "203d": "20dcos", "20os3d": "20dcos", "20stdduocon": "20dcduocon"}
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

    cond_clean = str(condition_param).upper().replace(" ", "").replace("-", "")
    reverse_cond_map = {
        "NEW": "1", "BRANDNEW": "1", "NEW1TRIP": "2", "1TRIP": "2", "ONEWAY": "2",
        "SINGLETRIP": "2", "NEWIICL": "3", "IICL": "4", "CW+": "9", "CWPLUS": "9",
        "CW": "5", "CARGOWORTHY": "5", "USED": "5", "CWWWT": "6", "WWT": "7",
        "WINDANDWATERTIGHT": "7", "ASIS": "8", "DAMAGED": "8"
    }

    # 🌟 核心防错：非中国大陆区域（海外堆场），新箱必须自动映射为代码 2 (New 1 trip)
    if not is_china and cond_clean in ["NEW", "BRANDNEW"]:
        condition_code = "2"
    else:
        condition_code = reverse_cond_map.get(cond_clean, "_") if condition_param else "_"

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
    t_norm = re.sub(r'(?i)tri[-_\s]*doors?', 'OS 3D', t_norm)
    tc = t_norm.upper().replace(" ", "").replace("-", "")

    q = [t_norm]
    if any(x in tc for x in ["OS", "SIDE", "OPEN", "TRI", "3D"]):
        if "40HC" in tc:
            if "4D" in tc:
                q = ["40HC OS 4D", "40HC OS FOS", "40HC OS 3D", "40HC OS 2D", "40HC OS 1D"]
            elif "FOS" in tc:
                q = ["40HC OS FOS", "40HC OS 4D", "40HC OS 2D"]
            elif "2D" in tc:
                q = ["40HC OS 2D", "40HC OS 4D", "40HC OS FOS"]
            elif "3D" in tc or "TRI" in tc:
                q = ["40HC OS 3D", "40HC OS 4D", "40HC OS FOS", "40HC OS 2D"]
            else:
                q += ["40HC OS 4D", "40HC OS FOS", "40HC OS 3D", "40HC OS 2D", "40HC OS 1D"]
        elif "20DC" in tc or ("20" in tc and "HC" not in tc):
            if "4D" in tc:
                q = ["20DC OS 4D", "20DC OS FOS", "20DC OS 2D"]
            elif "FOS" in tc:
                q = ["20DC OS FOS", "20DC OS 4D", "20DC OS 2D"]
            elif "2D" in tc:
                q = ["20DC OS 2D", "20DC OS 4D", "20DC OS FOS"]
            elif "3D" in tc or "TRI" in tc:
                q = ["20DC OS 3D", "20DC OS 4D", "20DC OS FOS", "20DC OS 2D"]
            else:
                q += ["20DC OS 4D", "20DC OS FOS", "20DC OS 2D"]
        elif "20HC" in tc:
            q.append("20HC OS FOS")

    seen = set()
    return [x for x in q if x.strip()
            and not (x.upper().replace(" ", "") in seen or seen.add(x.upper().replace(" ", "")))]


# ERP 是合法城市名称的唯一数据源。缓存仅保存已经确认的 ERP 城市。
# 每次程序启动时 fetch_system_cities 会重新拉取城市列表；不中断程序运行时需重启以刷新。
RESOLVED_CITY_CACHE = {}


class LocationResolutionError(ValueError):
    """地点无法可信地映射到当前 ERP 主数据。阻断查询并向客户追问。"""


class BroadLocationClarificationRequired(ValueError):
    """广域库存缺少城市，停止本封邮件的库存查询并追问城市。"""


def _normalize_location_name(value):
    """仅执行通用文本规整，不做包含关系匹配/逐单词缩写替换。"""
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^\w]+", " ", value.casefold(), flags=re.UNICODE)
    return " ".join(value.split())


def _city_similarity(query, candidate):
    """仅用于生成 AI 候选，分数本身不能授权报价。"""
    q, c = _normalize_location_name(query), _normalize_location_name(candidate)
    if not q or not c:
        return 0.0
    qt, ct = q.split(), c.split()
    ratio = SequenceMatcher(None, q, c).ratio()
    overlap = len(set(qt) & set(ct)) / max(len(set(qt)), len(set(ct)))
    return max(ratio, overlap * 0.9)


def _ai_select_erp_city(raw_location, candidate_names):
    """AI 只能从 ERP 真实候选项中选择；失败则不匹配，不能猜测城市。"""
    if not candidate_names:
        return None
    system_prompt = (
        "You are a conservative geographical place-name resolver for a container ERP. "
        "Return JSON only: {\"matched\":bool,\"erp_city\":string}. "
        "The erp_city MUST be one of the listed ERP candidate strings, copied verbatim. "
        "Match full geographical place names, common aliases, translations and clear typos only. "
        "Do not infer from an individual word inside a multiword place name. "
        "Do not match a different city merely because its spelling is similar. "
        "If ambiguous or unsure, return matched=false and erp_city empty."
    )
    user_prompt = json.dumps({
        "customer_location": raw_location,
        "erp_candidates": candidate_names,
    }, ensure_ascii=False)
    try:
        reply = ai_client.chat.completions.create(
            model=AI_MODEL,
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": user_prompt}],
            temperature=0.0,
            max_tokens=180,
            response_format={"type": "json_object"},
        )
        raw = (reply.choices[0].message.content or "").strip()
        obj = json.loads(raw)
        if obj.get("matched") is not True:
            return None
        selected = str(obj.get("erp_city") or "").strip()
        # 强制逐字对齐 ERP 候选，不能信任模型自报的 confidence。
        return selected if selected in candidate_names else None
    except Exception as exc:
        print(f"⚠️ [城市 AI 消歧失败] {raw_location!r}: {exc}")
        return None


def resolve_erp_location(location_str):
    """返回结构化地点解析结果；城市必须属于 ERP 列表，否则抛异常。"""
    raw = re.sub(r"\s+", " ", str(location_str or "")).strip()
    if not raw:
        raise LocationResolutionError("未提供提箱城市")

    # 保留原有地区/国家搜索入口；国家不转换成凭空猜测的城市。
    areas = {"us & ca": 1, "america": 1, "us": 1, "usa": 1, "canada": 1,
             "asia": 2, "europe": 3, "others": 4}
    area = areas.get(raw.casefold())
    if area:
        return {"original_location": raw, "erp_location": "", "country_codes": [],
                "area_code": area, "match_status": "MATCHED_AREA", "match_method": "AREA"}

    city_names = [str(c).strip() for c in fetch_system_cities() if str(c).strip()]
    # 如果城市列表获取失败，绝不回退为原始文本直接查询 API。
    if not city_names:
        raise LocationResolutionError("ERP 城市清单获取失败，无法核实提箱地点")

    # 仅识别完整缩写，例如 CHI，不检查 Ho Chi Minh City 中的 Chi。
    abbr = CITY_ABBR_MAPPING.get(raw.upper())
    effective = abbr if abbr else raw
    key = _normalize_location_name(effective)
    index = {}
    for city in city_names:
        index.setdefault(_normalize_location_name(city), []).append(city)

    exact = index.get(key, [])
    if len(exact) == 1:
        selected, method = exact[0], "EXACT" if not abbr else "EXACT_ABBR"
    elif len(exact) > 1:
        raise LocationResolutionError(f"ERP 存在同名城市，无法确定: {raw}")
    else:
        cached = RESOLVED_CITY_CACHE.get(key)
        if cached in city_names:
            selected, method = cached, "CACHE"
        else:
            scored = sorted(
                ((_city_similarity(effective, name), name) for name in city_names),
                key=lambda item: item[0], reverse=True
            )
            strong = [(score, name) for score, name in scored if score >= 0.58]
            if not strong:
                # 完全不同的历史名称/外语别名（例如 Saigon -> Ho Chi Minh）
                # 可能没有字符串相似度。仅当 ERP 城市列表规模可控时，
                # 让 AI 在真实 ERP 城市全集中选，绝不允许生成清单外城市。
                if len(city_names) <= 500:
                    selected = _ai_select_erp_city(raw, city_names)
                    method = "AI_VERIFIED_ALIAS" if selected else "UNRESOLVED"
                else:
                    selected, method = None, "UNRESOLVED"
                    print(f"⚠️ [ERP 城市候选过多] {len(city_names)} 条，拒绝无候选地名的自动猜测")
            else:
                # 唯一的多词名称前缀 + City 等行政后缀可直接匹配：
                # Ho Chi Minh City -> Ho Chi Minh (须 ERP 确实存在此候选)。
                near = [name for score, name in strong if score >= strong[0][0] - 0.12]
                q_words = key.split()
                unique_prefix = [name for name in near
                                 if len(_normalize_location_name(name).split()) >= 2
                                 and len(q_words) == len(_normalize_location_name(name).split()) + 1
                                 and q_words[:-1] == _normalize_location_name(name).split()
                                 and q_words[-1] in ("city", "town")]
                if len(unique_prefix) == 1 and len(near) == 1:
                    selected, method = unique_prefix[0], "ERP_UNIQUE_NAME"
                else:
                    candidates = [name for _, name in strong[:8]]
                    selected = _ai_select_erp_city(raw, candidates)
                    method = "AI_VERIFIED" if selected else "UNRESOLVED"

            if selected:
                RESOLVED_CITY_CACHE[key] = selected

    if selected:
        # 防御性检查：最终只接受来自 ERP 的真实城市。
        if selected not in city_names:
            raise LocationResolutionError(f"解析出非 ERP 城市: {selected}")
        result = {"original_location": raw, "erp_location": selected,
                  "country_codes": [], "area_code": 0,
                  "match_status": "MATCHED", "match_method": method}
        print(f"📍 [ERP 城市已确认] {raw!r} -> {selected!r} ({method})")
        return result

    # 城市没匹配到时，只允许严格的国家全称/国家 ISO2；不能用字符串包含判断。
    countries = fetch_system_countries()
    matching_countries = sorted({item.get("ISO2") for item in countries
        if _normalize_location_name(raw) in {
            _normalize_location_name(item.get("eName")),
            _normalize_location_name(item.get("cName")),
            _normalize_location_name(item.get("ISO2"))
        } and item.get("ISO2")})
    if len(matching_countries) == 1:
        code = matching_countries[0]
        print(f"📍 [ERP 国家已确认] {raw!r} -> {code}")
        return {"original_location": raw, "erp_location": "", "country_codes": [code],
                "area_code": 0, "match_status": "MATCHED_COUNTRY", "match_method": "COUNTRY"}
    raise LocationResolutionError(f"无法在 ERP 城市主数据中确认地点: {raw}")


def _city_lookup_params(city_location):
    """兼容库存工具原返回结构；禁止无验证地点流入 dCity 查询参数。"""
    raw = str(city_location or "").strip()
    # 只清理可明确识别的尾部箱型属性，不扫描真实城市名中的每个单词。
    cleaned = re.sub(
        r"(?i)(?:\s+(?:FOS|OS|DD|HC|DC|GP|HQ|CW|NEW|USED|4D|2D|3D|DOORS?|TRIDOOR))+$",
        "", raw
    ).strip() or raw
    res = resolve_erp_location(cleaned)
    return cleaned if not res["erp_location"] else res["erp_location"], res["area_code"], res["country_codes"], res["erp_location"]


def _row_city_or_none(item):
    """返回库存行中明确的城市字段；不将堆场名、仓库名视为城市。"""
    for key in ("dCity", "dcity", "city", "City", "depotCity", "yardCity"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _is_china_location(city_location, country_codes):
    """仅中国大陆堆场按 NEW 搜索；不能把整个 Asia 区域视为中国。"""
    low = str(city_location or "").strip().lower()
    if "CN" in (country_codes or []) or low in ("china", "mainland china", "中国", "中国大陆"):
        return True
    china_cities = ("shanghai", "ningbo", "qingdao", "tianjin", "shenzhen", "guangzhou",
                    "xiamen", "dalian", "chengdu", "chongqing", "wuhan", "nanjing", "suzhou")
    return any(re.search(rf"\b{city}\b", low) for city in china_cities)


def _parse_expected_unit_price_usd(value):
    """仅接受 Router 明确提取的 USD 单箱目标价；不猜测总价、区间或其他货币。"""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        amount = float(value)
    else:
        cleaned = str(value).strip()
        match = re.fullmatch(r"(?i)(?:USD\s*)?(?:US\$|\$)?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:USD)?", cleaned)
        if not match:
            return None
        amount = float(match.group(1).replace(",", ""))
    return round(amount, 2) if 0 < amount <= 1_000_000 and amount == amount else None


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
# 🌟 3.7 核心三级级联查找状态机 (新旧双报价并发 + 海外代码自适应)
# ==========================================================
def _query_single_stock(target_city, target_type, target_cond, color_code, api_url, headers, query_cache=None):
    city_location, area_code, country_codes, d_city_val = _city_lookup_params(target_city)
    is_china = _is_china_location(city_location, country_codes)

    # 规范化箱况输入
    cond_str = str(target_cond).strip()
    if cond_str.upper() in ["NEW", "BRANDNEW"]:
        cond_str = "NEW" if is_china else "New 1 trip"
    elif cond_str.upper() in ["USED", "CARGOWORTHY"]:
        cond_str = "CW"

    cache_key = (str(target_city).lower(), str(target_type).lower(), str(cond_str).lower(), str(color_code))
    if query_cache is not None and cache_key in query_cache:
        return query_cache[cache_key]

    search_idcode = encode_search_idcode(target_type, color_code, cond_str, is_china=is_china)
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
        print(f"[API请求异常] {city_location} {target_type} {cond_str} {color_code}: {e}")
        if query_cache is not None:
            query_cache[cache_key] = (None, [])
        return None, []

    best_ground = None
    transit_lines = []

    for item in page_data:
        # ERP 若明确返回城市，则逐行核验，防止后端返回不相关地区库存。
        # dCity 缺失时只能证实查询过滤条件，不能声称已经逐条验证了库存地点。
        actual_city = _row_city_or_none(item)
        if d_city_val:
            if actual_city and _normalize_location_name(actual_city) != _normalize_location_name(d_city_val):
                print(f"🚫 [跨城市库存拦截] 期望={d_city_val!r} 实际={actual_city!r}")
                continue
        elif not actual_city:
            print("📍 [需求城市待确认] 广域库存记录缺少实际城市，停止本封邮件的库存查询。")
            raise BroadLocationClarificationRequired(city_location)
        o_price = _num(item, *PRICE_KEYS)
        u_price = float(item.get("uPrice") or 0)
        onground = int(_num(item, *ONGROUND_KEYS))
        upcoming = int(_num(item, *UPCOMING_KEYS))
        eta = (item.get("eta") or "").strip()

        id_code = str(item.get("idCode") or "")
        # 库存 API 查询必须逐条复核实际箱况；不能把返回的旧箱误当成 NEW 报价。
        expected_digit = {
            "NEW": "1",
            "NEW1TRIP": "2",
            "NEWIICL": "3",
            "IICL": "4",
            "CW": "5",
            "CWWWT": "6",
            "WWT": "7",
            "ASIS": "8",
            "CW+": "9",
        }.get(cond_str.upper().replace(" ", "").replace("-", ""))
        if expected_digit and (len(id_code) != 10 or not id_code.isdigit()
                               or id_code[6] != expected_digit):
            continue

        box_type, box_cond, color_desc = parse_idcode_details(id_code)

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

        if box_cond == "CW+":
            cond_display = "CW"
        elif box_cond == "NEW":
            cond_display = "NEW"
        elif box_cond == "New 1 trip":
            cond_display = "New 1-Trip"
        else:
            cond_display = box_cond

        common = {
            "type": box_type,
            "erp_condition": box_cond,
            "cond": cond_display,
            "pol": d_city_val or actual_city,
            "color": color_desc,
            "yom": yom_val
        }

        if onground > 0 and o_price > 0:
            ground_q = {**common, "price": f"USD{o_price:.2f}/unit", "raw_price": o_price, "qty": onground}
            if best_ground is None or o_price < best_ground["raw_price"]:
                best_ground = ground_q
            elif o_price == best_ground["raw_price"]:
                # 🌟 相同最低价时，累加同城有效现货总台数
                best_ground["qty"] += onground

        if upcoming > 0:
            t_price_str = f"USD{u_price:.2f}/unit" if u_price > 0 else "待确认"
            transit_lines.append({**common, "price": t_price_str, "raw_price": u_price, "qty": upcoming, "eta": eta})

    result = (best_ground, transit_lines)
    if query_cache is not None:
        query_cache[cache_key] = result
    return result


def _search_condition_candidate(target_city, single_type, cand_cond, requested_color, api_url, headers, query_cache):
    """针对单一确定的箱况执行严格匹配与变体展开"""
    type_variants = expand_special_variants(single_type)
    color_codes = resolve_color_codes(requested_color)
    step1_colors = color_codes if (color_codes or not requested_color) else []

    for idx, t in enumerate(type_variants):
        is_variant = (idx > 0) or (t.upper().replace(" ", "") != single_type.upper().replace(" ", ""))
        for c in (step1_colors if step1_colors else [""]):
            g, t_lines = _query_single_stock(target_city, t, cand_cond, c, api_url, headers, query_cache=query_cache)
            if g or t_lines:
                stock_desc = "现货" if g and not t_lines else ("在途货源" if not g and t_lines else "现货+在途")
                cond_name = g["cond"] if g else (t_lines[0]["cond"] if t_lines else cand_cond)
                if is_variant:
                    print(
                        f"🔄 [特种箱平替触发] 提箱地: {target_city} | 原需求 '{single_type}' ({cand_cond}) 无货 | 顺推变体: '{t}' ({cond_name}, {stock_desc})")
                else:
                    print(
                        f"🎯 [箱型精确匹配] 提箱地: {target_city} | 精确命中客户需求箱型: '{t}' (箱况: {cond_name}, {stock_desc})")
                return {
                    "match_type": "ALT_VARIANT" if is_variant else "EXACT",
                    "orig_type": single_type,
                    "found_type": t,
                    "is_variant": is_variant,
                    "ground_quote": g,
                    "transit_quotes": t_lines
                }
    return None


def _find_budget_alternative(target_city, single_type, requested_color, new_ground,
                             expected_unit_price, api_url, headers, query_cache):
    """新箱确实比预算贵 >=300 美元时，额外推荐一个真实可售、比新箱便宜的现货。

    先选同箱型且在目标价 ±300 内的方案，优先 CW，再选 IICL / WWT。
    如果没有接近预算的方案，仅允许一个更便宜的 CW 供客户参考。
    不使用 ASIS、在途未确认价或其他城市/未要求的颜色。
    """
    new_price = float((new_ground or {}).get("raw_price") or 0)
    if not expected_unit_price or new_price - expected_unit_price < BUDGET_GAP_THRESHOLD_USD:
        return None

    candidates = []
    for condition in ("CW", "IICL", "WWT"):
        res = _search_condition_candidate(target_city, single_type, condition, requested_color,
                                          api_url, headers, query_cache)
        if not res or not res.get("ground_quote"):
            continue
        quote = res["ground_quote"]
        price = float(quote.get("raw_price") or 0)
        if not (0 < price < new_price):
            continue
        candidates.append((condition, res, price))

    def sort_key(item):
        condition, quote, price = item
        return (bool(quote.get("is_variant")), condition != "CW",
                abs(price - expected_unit_price), price)

    nearby = [x for x in candidates if abs(x[2] - expected_unit_price) <= BUDGET_NEAR_RANGE_USD]
    if nearby:
        chosen = min(nearby, key=sort_key)
    else:
        cw_options = [x for x in candidates if x[0] == "CW"]
        if not cw_options:
            return None
        chosen = min(cw_options, key=sort_key)

    _, found, price = chosen
    answer = {
        **found,
        "match_type": "BUDGET_ALTERNATIVE",
        "expected_unit_price": expected_unit_price,
        "new_price": new_price,
        "budget_difference": round(price - expected_unit_price, 2),
        "new_price_gap": round(new_price - expected_unit_price, 2),
    }
    print(f"💰 [新箱预算补充推荐] {target_city} {single_type}: "
          f"预算USD{expected_unit_price:.2f}, 新箱USD{new_price:.2f}, "
          f"备选{answer['ground_quote']['cond']} USD{price:.2f}")
    return answer


def _attach_budget_alternative(result, target_city, single_type, requested_condition,
                               requested_color, expected_unit_price, api_url, headers, query_cache):
    """仅在客户【没有明确指定箱况】时追加预算备选，不覆盖新箱主报价。"""
    if (requested_condition or "").strip() or expected_unit_price is None:
        return result
    original = (result.get("all_results") or [None])[0]
    if not original or not original.get("ground_quote"):
        return result
    new_ground = original["ground_quote"]
    # 新箱的库存数据必须确认属于新箱；旧箱或在途不参与这个价格差触发器。
    if str(new_ground.get("cond", "")).upper() not in ("NEW", "NEW 1-TRIP"):
        return result
    alternative = _find_budget_alternative(target_city, single_type, requested_color,
                                           new_ground, expected_unit_price, api_url, headers, query_cache)
    if alternative:
        result["all_results"] = [*result.get("all_results", []), alternative]
    return result


def normalize_requested_condition(value, is_china=False):
    raw = str(value or "").strip()
    key = re.sub(r"[\s\-_/]", "", raw.upper())

    aliases = {
        "NEW": "NEW" if is_china else "New 1 trip",
        "BRANDNEW": "NEW" if is_china else "New 1 trip",
        "NEW1TRIP": "New 1 trip",
        "1TRIP": "New 1 trip",
        "ONEWAY": "New 1 trip",
        "SINGLETRIP": "New 1 trip",
        "NEWIICL": "New-IICL",
        "IICL": "IICL",
        "CW+": "CW+",
        "CWPLUS": "CW+",
        "CW": "CW",
        "USED": "CW",
        "CARGOWORTHY": "CW",
        "CWWWT": "CW-WWT",
        "WWT": "WWT",
        "WINDANDWATERTIGHT": "WWT",
        "ASIS": "ASIS",
    }

    return aliases.get(key, raw)



def _find_best_quote_cascading(target_city, single_type, requested_condition, requested_color,
                               api_url, headers, query_cache=None, expected_unit_price=None):
    """
    三步级联检索：
    - 支持客户提供备选箱况 (如 New or used) 时，同时输出新箱与旧箱双重有效报价
    - Step 1: 严格精确匹配
    - Step 2: 保持箱况放宽到其它可用颜色
    - Step 3: 推荐相近箱况
    """
    city_location, area_code, country_codes, _ = _city_lookup_params(target_city)
    is_china = _is_china_location(city_location, country_codes)

    type_variants = expand_special_variants(single_type)
    if len(type_variants) > 1:
        print(
            f"🔍 [特种箱探测队列] 提箱城市: {target_city} | 原始要求箱型: '{single_type}' | 候选探测顺序: {' ➔ '.join(type_variants)}")

    req_cond_raw = (requested_condition or "").strip()
    raw_tokens = [c.strip() for c in re.split(r'\bOR\b|/|或|\bAND\b|[,，]', req_cond_raw, flags=re.I) if c.strip()]

    # 规范化客户的候选箱况列表
    mapped_conds = []

    for rc in raw_tokens:
        target = normalize_requested_condition(rc, is_china)
        if target not in mapped_conds:
            mapped_conds.append(target)

    # 无论普通箱还是特种箱，客户未指定箱况时一律先查新箱。
    condition_unspecified = not req_cond_raw
    if not mapped_conds:
        mapped_conds = ["NEW" if is_china else "New 1 trip"]

    # ==========================================================
    # Step 1: 严格精确匹配 (支持 New or used 新旧双重报价)
    # ==========================================================
    matched_quotes = []
    for mc in mapped_conds:
        q = _search_condition_candidate(target_city, single_type, mc, requested_color, api_url, headers, query_cache)
        if q:
            matched_quotes.append(q)

    if matched_quotes:
        if condition_unspecified:
            for q in matched_quotes:
                if not q.get("is_variant"):
                    q["match_type"] = "DEFAULT_NEW"
        result = {
            "match_type": matched_quotes[0]["match_type"],
            "ground_quote": matched_quotes[0]["ground_quote"],
            "transit_quotes": matched_quotes[0]["transit_quotes"],
            "all_results": matched_quotes
        }
        return _attach_budget_alternative(result, target_city, single_type, requested_condition,
                                          requested_color, expected_unit_price, api_url, headers, query_cache)

    # ==========================================================
    # Step 2: 保持箱型箱况，放宽到其它可用颜色 (Alternative Colors)
    # ==========================================================
    if requested_color:
        for mc in mapped_conds:
            for idx, t in enumerate(type_variants):
                is_variant = (idx > 0) or (t.upper().replace(" ", "") != single_type.upper().replace(" ", ""))
                g, t_lines = _query_single_stock(target_city, t, mc, "", api_url, headers, query_cache=query_cache)
                if g or t_lines:
                    stock_desc = "现货" if g and not t_lines else ("在途货源" if not g and t_lines else "现货+在途")
                    found_col = g["color"] if g else (t_lines[0]["color"] if t_lines else "Available Color")
                    if is_variant:
                        print(
                            f"🔄 [特种箱+颜色双平替] 提箱地: {target_city} | 原需求: '{single_type}' ({requested_color}) 无货 | 顺推变体: '{t}' 替代颜色: '{found_col}' ({stock_desc})")
                    else:
                        print(
                            f"🎨 [颜色平替触发] 提箱地: {target_city} | 箱型: '{t}' | 原颜色 '{requested_color}' 无货 | 替代颜色: '{found_col}' ({stock_desc})")

                    res_obj = {
                        "match_type": "ALT_COLOR",
                        "orig_type": single_type,
                        "found_type": t,
                        "is_variant": is_variant,
                        "orig_color": requested_color,
                        "found_color": found_col,
                        "ground_quote": g,
                        "transit_quotes": t_lines
                    }
                    result = {**res_obj, "all_results": [res_obj]}
                    return _attach_budget_alternative(result, target_city, single_type, requested_condition,
                                                      requested_color, expected_unit_price, api_url, headers,
                                                      query_cache)

    # ==========================================================
    # Step 3: 推荐相近箱况 (Alternative Conditions)
    # ==========================================================
    cand_conditions = []

    for original_cond in mapped_conds:
        fallbacks = get_condition_fallbacks(
            original_cond,
            is_china=is_china
        )

        for candidate in fallbacks:
            if (
                    candidate not in mapped_conds
                    and candidate not in cand_conditions
            ):
                cand_conditions.append(candidate)

    print(
        f"📦 [箱况逐级推荐] 原始={mapped_conds} "
        f"候选顺序={' -> '.join(cand_conditions)}"
    )
    for alt_cond in cand_conditions:
        q = _search_condition_candidate(target_city, single_type, alt_cond, requested_color, api_url, headers,
                                        query_cache)
        if q:
            g = q["ground_quote"]
            t_lines = q["transit_quotes"]
            found_c = g["cond"] if g else (t_lines[0]["cond"] if t_lines else alt_cond)
            found_col = g["color"] if g else (t_lines[0]["color"] if t_lines else "Mixed")
            stock_desc = "现货" if g and not t_lines else ("在途货源" if not g and t_lines else "现货+在途")

            if q["is_variant"]:
                print(
                    f"🔄 [特种箱+箱况双平替] 提箱地: {target_city} | 原需求: '{single_type}' ({req_cond_raw}) 无货 | 顺推变体: '{q['found_type']}' 替代箱况: '{found_c}' ({stock_desc})")
            else:
                print(
                    f"📦 [箱况平替触发] 提箱地: {target_city} | 箱型: '{q['found_type']}' | 原箱况 '{req_cond_raw}' 无货 | 替代箱况: '{found_c}' ({stock_desc})")
            public_cw_match = (
                    not condition_unspecified
                    and len(mapped_conds) == 1
                    and mapped_conds[0] == "CW"
                    and alt_cond == "CW+"
            )

            if public_cw_match:
                match_type = (
                    "ALT_VARIANT" if q["is_variant"] else "EXACT"
                )
            else:
                match_type = (
                    "DEFAULT_NEW_UNAVAILABLE"
                    if condition_unspecified
                    else "ALT_CONDITION"
                )
            res_obj = {
                "match_type": match_type,
                "orig_type": single_type,
                "found_type": q["found_type"],
                "is_variant": q["is_variant"],
                "orig_cond": req_cond_raw if req_cond_raw else "未指定箱况（系统默认优先新箱）",
                "found_cond": found_c,
                "found_color": found_col,
                "ground_quote": g,
                "transit_quotes": t_lines
            }
            return {**res_obj, "all_results": [res_obj]}

    print(
        f"❌ [库存无匹配] 提箱地: {target_city} | 原始要求: '{single_type}' (箱况: '{req_cond_raw}', 颜色: '{requested_color}') 经三步级联查找均无现货与在途。")
    return {"match_type": "OUT_OF_STOCK", "ground_quote": None, "transit_quotes": [], "all_results": []}


def get_condition_fallbacks(condition, is_china=False):
    """
    根据品质等级生成替代箱况顺序。
    NEW / New 1 trip / New-IICL：向下推荐
    IICL 及以下：向上推荐
    """
    if condition not in QUALITY_PRIORITY_ORDER:
        return []

    idx = QUALITY_PRIORITY_ORDER.index(condition)

    if idx <= 2:
        # 新箱系列缺货：逐级向下
        candidates = QUALITY_PRIORITY_ORDER[idx + 1:]
    else:
        # 旧箱系列缺货：逐级向上
        candidates = list(reversed(
            QUALITY_PRIORITY_ORDER[:idx]
        ))

    # 海外 NEW 按现有系统业务规则映射为 New 1 trip
    # 避免重复查询同一个 ERP 箱况编码
    if not is_china:
        candidates = [c for c in candidates if c != "NEW"]

    return candidates


# ==========================================================
# 🌟 4. RAG 库存检索层 (多箱型强制解耦 + 双报价合并渲染)
# ==========================================================
def _extract_field(key_names, *dicts):
    """安全解析：按优先级从多个字典中提取首个非空的字段值"""
    for d in dicts:
        if isinstance(d, dict):
            for k in key_names:
                val = d.get(k)
                if val is not None and str(val).strip() != "" and str(val).lower() != "null":
                    return val
    return None


def query_internal_inventory(entities, email_content):
    api_url = os.getenv("INVENTORY_API_URL")
    headers = {"Content-Type": "application/json"}
    query_cache = {}

    line_items = entities.get("line_items") if isinstance(entities, dict) else []
    shared_budget = _parse_expected_unit_price_usd(
        _extract_field(["expected_unit_price_usd"], entities))

    items = []
    if line_items:
        for li in line_items:
            if isinstance(li, dict):
                try:
                    q = int(str(li.get("quantity") or 0).strip() or 0)
                except (ValueError, TypeError):
                    q = 0
                raw_t = (li.get("container_type") or li.get("type") or "").strip()
                split_types = [t.strip() for t in re.split(r'[,/，、]|\bOR\b|\bAND\b|\b及\b', raw_t, flags=re.I) if
                               t.strip()]
                # 多箱型询盘必须逐条关联目标价；不能把某一箱型预算套到另一箱型。
                budget = _parse_expected_unit_price_usd(li.get("expected_unit_price_usd"))
                if budget is None and len(line_items) == 1 and len(split_types) == 1:
                    budget = shared_budget
                for st in (split_types or [""]):
                    items.append({"type": st,
                                  "cond": (li.get("condition") or "").strip(),
                                  "color": (li.get("color") or "").strip(),
                                  "loc": (li.get("location") or "").strip(),
                                  "qty": max(q, 0), "expected_unit_price": budget})
    else:
        raw_types_str = str(_extract_field(["container_type", "type"], entities) or "")
        raw_types = [t.strip() for t in re.split(r'[,/，、]|\bOR\b|\bAND\b|\b及\b', raw_types_str, flags=re.I) if
                     t.strip()]
        raw_loc = str(_extract_field(["target_location", "location", "city"], entities) or "").strip()
        raw_cond = str(_extract_field(["requested_condition", "condition"], entities) or "").strip()
        raw_col = str(_extract_field(["requested_color", "color"], entities) or "").strip()

        qty_val = _extract_field(["requested_quantity", "quantity", "qty"], entities)
        try:
            flat_qty = int(str(qty_val or 0).strip() or 0)
        except (ValueError, TypeError):
            flat_qty = 0

        if not raw_types and not raw_loc:
            return ("【内部系统强制阻断】：客户未提供明确的 箱型 (Container Type)、"
                    "地点。请直接用客户的语言生成邮件，询问缺失的具体信息。")

        for t in (raw_types or [""]):
            items.append({"type": t, "cond": raw_cond, "color": raw_col,
                          "loc": raw_loc, "qty": max(flat_qty, 0),
                          "expected_unit_price": shared_budget if len(raw_types) == 1 else None})

    rows, nostock, need_ask = [], [], []
    for it in items:
        ctype, cond, colname, locdesc = it["type"], it["cond"], it["color"], it["loc"]
        m_req = it.get("qty") or 0
        expected_unit_price = it.get("expected_unit_price")
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
            try:
                resolved = resolve_erp_location(city)
                # 按标准 ERP 城市查询，避免重复的 AI 城市消歧。
                erp_city = resolved["erp_location"] or city
                res = _find_best_quote_cascading(erp_city, ctype, cond, colname, api_url, headers,
                                                 query_cache=query_cache, expected_unit_price=expected_unit_price)
            except BroadLocationClarificationRequired as exc:
                # 不保留此前的报价或无货结论，也不再查询其余箱况、箱型和地点。
                return (f"[LOCATION_CLARIFICATION]\nLocation: {exc}\n"
                        "【内部系统强制阻断】：本次广域库存查询缺少可确认的实际城市，已停止查询。\n"
                        "【已授权业务规则】：我们在该国家或地区的多个港口有库存。"
                        "请用客户的语言说明这一点，并请客户告知需求城市，收到后提供最新报价。"
                        "仅追问需求城市，不追问已有箱型、箱况，不输出任何报价块、价格、"
                        "数量、堆场名称或具体港口名单；不能说无货，不披露内部字段问题。")
            except LocationResolutionError as exc:
                print(f"🚫 [地点待确认，禁止报价] {city!r}: {exc}")
                need_ask.append(f"{ctype} 的提箱地点 '{city}'（请确认城市名称）")
                continue
            if res.get("all_results"):
                avail.append((city, res))
            else:
                unavail.append(city)

        for _, res in avail:
            sub_results = res.get("all_results") or [res]
            for sub_res in sub_results:
                g = sub_res.get("ground_quote")
                t_list = sub_res.get("transit_quotes") or []
                m_type = sub_res.get("match_type")

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
                    if m_type == "DEFAULT_NEW":
                        rows.append(f"- [DEFAULT_NEW] (客户没有指定箱况；优先报价新箱，不表示客户明确要求新箱) "
                                    f"Style: {g['type']} | Condition: {g['cond']} | POL: {g['pol']} | "
                                    f"Color: {g['color']} | YOM: {g['yom']} | Price: {g['price']} | "
                                    f"Stock_Qty: {qty_display} | Payment: 100% TT before pick up.")
                    elif m_type == "BUDGET_ALTERNATIVE":
                        qualifier = (f"相近规格 {sub_res['found_type']}，请说明规格不同；" if sub_res.get('is_variant') else "")
                        rows.append(f"- [BUDGET_ALTERNATIVE] (客户未指定箱况；其明确的单箱目标价 "
                                    f"USD{sub_res['expected_unit_price']:.2f}，新箱现货单价 "
                                    f"USD{sub_res['new_price']:.2f} 比目标价高出至少USD300；"
                                    f"保留新箱报价，另外提供一款更经济的现货供考虑；{qualifier}"
                                    f"并非客户指定此箱况，勿承诺满足预算) "
                                    f"Style: {g['type']} | Condition: {g['cond']} | POL: {g['pol']} | "
                                    f"Color: {g['color']} | YOM: {g['yom']} | Price: {g['price']} | "
                                    f"Stock_Qty: {qty_display} | Payment: 100% TT before pick up.")
                    elif m_type == "DEFAULT_NEW_UNAVAILABLE":
                        rows.append(f"- [DEFAULT_NEW_UNAVAILABLE] (客户未指定箱况；系统默认优先查新箱但暂无可报价新箱，"
                                    f"提供下列箱况作参考，不能说客户指定了新箱；"
                                    f"{'此外规格顺推为 ' + sub_res['found_type'] if sub_res.get('is_variant') else ''}) "
                                    f"Style: {g['type']} | Condition: {g['cond']} | POL: {g['pol']} | "
                                    f"Color: {g['color']} | YOM: {g['yom']} | Price: {g['price']} | "
                                    f"Stock_Qty: {qty_display} | Payment: 100% TT before pick up.")
                    elif m_type == "EXACT":
                        rows.append(f"- [EXACT] Style: {g['type']} | Condition: {g['cond']} | POL: {g['pol']} | "
                                    f"Color: {g['color']} | YOM: {g['yom']} | Price: {g['price']} | "
                                    f"Stock_Qty: {qty_display} | Payment: 100% TT before pick up.")
                    elif m_type == "ALT_VARIANT":
                        rows.append(
                            f"- [ALT_VARIANT] (说明：客户指定的特种规格 '{sub_res['orig_type']}' 在 {g['pol']} 严格筛选无货，顺推推荐相近规格 '{sub_res['found_type']}') "
                            f"Style: {g['type']} | Condition: {g['cond']} | POL: {g['pol']} | "
                            f"Color: {g['color']} | YOM: {g['yom']} | Price: {g['price']} | "
                            f"Stock_Qty: {qty_display} | Payment: 100% TT before pick up.")
                    elif m_type == "ALT_COLOR":
                        prefix = f"(说明：特种规格原要 '{sub_res['orig_type']}' 顺推推荐 '{sub_res['found_type']}，且" if sub_res.get(
                            "is_variant") else "(说明："
                        rows.append(
                            f"- [ALT_COLOR] {prefix}客户指定的颜色 '{sub_res['orig_color']}' 在 {g['pol']} 严格筛选无现货，推荐其它可用颜色 '{sub_res['found_color']}') "
                            f"Style: {g['type']} | Condition: {g['cond']} | POL: {g['pol']} | "
                            f"Color: {g['color']} | YOM: {g['yom']} | Price: {g['price']} | "
                            f"Stock_Qty: {qty_display} | Payment: 100% TT before pick up.")
                    elif m_type == "ALT_CONDITION":
                        prefix = f"(说明：特种规格原要 '{sub_res['orig_type']}' 顺推推荐 '{sub_res['found_type']}，且" if sub_res.get(
                            "is_variant") else "(说明："
                        rows.append(
                            f"- [ALT_CONDITION] {prefix}客户指定的箱况 '{sub_res['orig_cond']}' 在 {g['pol']} 严格筛选无现货，推荐替代箱况 '{sub_res['found_cond']}') "
                            f"Style: {g['type']} | Condition: {g['cond']} | POL: {g['pol']} | "
                            f"Color: {g['color']} | YOM: {g['yom']} | Price: {g['price']} | "
                            f"Stock_Qty: {qty_display} | Payment: 100% TT before pick up.")

                if show_transit and t_list:
                    if sub_res.get("is_variant"):
                        rows.append(
                            f"===【在途补充 - 特种箱平替推荐 (客户原需求 '{sub_res['orig_type']}' 暂无货，顺推相近规格 '{sub_res['found_type']}')】===")
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
    rcfg = cfg.get("router_config", {})

    abbr_list_str = ", ".join([f"{k}({v})" for k, v in CITY_ABBR_MAPPING.items()])
    schema_str = json.dumps(cfg.get("router_output_schema", {}), ensure_ascii=False, separators=(',', ':'))
    router_template = load_skill_file(cfg.get("router_engine_file", "00_router_engine.md"))

    # 🌟 拉取系统箱型清单
    box_type_list = get_box_type_prompt_list()

    router_prompt = (router_template
                     .replace("{{abbr_list}}", abbr_list_str)
                     .replace("{{entity_rules}}", load_entity_rules())
                     .replace("{{box_type_list}}", box_type_list)
                     .replace("{{schema}}", schema_str))

    # 🌟 从配置读取 Router 参数
    max_retries = max(1, int(rcfg.get("max_retries", 3)))
    backoff_base = int(rcfg.get("retry_backoff_base", 2))
    temperature = float(rcfg.get("temperature", 0.0))
    max_tokens = int(rcfg.get("max_tokens", 8000))

    for attempt in range(max_retries):
        try:
            response = ai_client.chat.completions.create(
                model=AI_MODEL,
                messages=[{"role": "system", "content": router_prompt},
                          {"role": "user", "content": f"邮件标题:{e_title}\n\n邮件正文:{e_content}\n\n请输出JSON:"}],
                temperature=temperature,
                max_tokens=max_tokens
            )
            raw = response.choices[0].message.content.strip()
            if match := re.search(r'\{.*\}', raw, re.DOTALL):
                raw = match.group()
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError("Router 返回结果必须是 JSON 对象")
            intent = result.get("primary_intent")
            if not isinstance(intent, str) or intent not in cfg.get("intent_to_module", {}):
                raise ValueError("Router 缺少有效的已注册 primary_intent")
            if result.get("action") not in ("REPLY", "NO_REPLY"):
                raise ValueError("Router action 必须是 REPLY 或 NO_REPLY")
            if (intent == "STOCK_PRICE_INQUIRY" and result["action"] == "REPLY"
                    and not isinstance(result.get("entities"), dict)):
                raise ValueError("Router 销售询盘的 entities 必须是 JSON 对象")
            return result
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(backoff_base * (2 ** attempt))
                continue
            # 技术故障不是业务性 NO_REPLY：交给单封处理入口记录 ai_status=3。
            raise RuntimeError(
                f"Router 分类失败，已尝试 {max_retries} 次: {type(e).__name__}: {e}"
            ) from e


# ==========================================================
# 🌟 6. Stage 3: AI邮件生成 (Drafter)
# ==========================================================
def _extract_rag_rows(inventory_data):
    pat = re.compile(
        r"-\s*(?:\[[A-Z_]+\][^\n|]*?)?\s*Style:\s*(.*?)\s*\|\s*Condition:\s*(.*?)\s*\|\s*POL:\s*(.*?)\s*\|\s*Color:\s*(.*?)\s*\|"
        r"\s*YOM:\s*(.*?)\s*\|\s*Price:\s*(.*?)\s*\|\s*Stock_Qty:\s*(\d+|Available)\s*\|\s*Payment:\s*([^\n|]*)")
    return [tuple(g.strip() for g in m.groups()) for m in pat.finditer(inventory_data)]


def _safe_fallback_draft(e_content, inventory_data):
    """确定性中英双语兜底：自动去重相同规格报价块"""
    is_chinese = any('\u4e00' <= char <= '\u9fff' for char in e_content)

    if "[LOCATION_CLARIFICATION]" in inventory_data:
        match = re.search(r"(?m)^Location:\s*([^\n]+)", inventory_data)
        location = match.group(1).strip() if match else ""
        if is_chinese:
            return (f"感谢您的询盘。我们在{location or '该国家或地区'}的多个港口有库存。"
                    "请告知您的需求城市，我们将为您提供最新报价。")
        return (f"Thank you for your inquiry. We have containers available at multiple ports "
                f"in {location or 'the requested country or region'}. Could you please let us know "
                "your required pickup city? We will then provide our latest quotation.")

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
    seen_specs = set()

    for style, cond, pol, color, yom, price, qty, pay in rows:
        spec_key = (style.lower(), cond.lower(), pol.lower(), color.lower())
        if spec_key in seen_specs:
            continue
        seen_specs.add(spec_key)

        qt = f"{qty} unit" if qty == "1" else (f"{qty} units" if qty.isdigit() else "Available")
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
                + ("If it would help, we'd be happy to find out for you whether nearby ports have the containers you need in spot stock, or whether any containers are due to arrive soon."
                   if has_ns else " Could you kindly share more details so we can check further?"))

    if is_chinese:
        if "[ALT_VARIANT]" in inventory_data:
            body = "感谢您的询盘。严格按照您的要求，目前暂无您指定门扇/特种规格的现货。作为替代参考方案，我们为您推荐如下相近规格现货：\n\n"
        elif "[ALT_COLOR]" in inventory_data:
            body = "感谢您的询盘。严格按照您的要求，目前暂无您指定颜色的现货。如果您考虑其它颜色，我们为您推荐如下可用现货：\n\n"
        elif "[ALT_CONDITION]" in inventory_data:
            body = "感谢您的询盘。严格按照您的要求，目前暂无您指定箱况的现货。作为替代参考方案，我们为您推荐如下可用现货：\n\n"
        elif "[DEFAULT_NEW_UNAVAILABLE]" in inventory_data:
            body = "感谢您的询盘。我们优先查询了新箱，但目前没有合适的新箱库存。以下是可供参考的其他箱况：\n\n"
        elif "[BUDGET_ALTERNATIVE]" in inventory_data:
            body = "感谢您的询盘。我们优先提供新箱报价，同时附上一款更经济的现货方案供您比较：\n\n"
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
        elif "[DEFAULT_NEW_UNAVAILABLE]" in inventory_data:
            body = ("Thank you for your inquiry. We checked new containers first, but currently have no "
                    "matching new stock. Here is another available condition for your consideration:\n\n")
        elif "[BUDGET_ALTERNATIVE]" in inventory_data:
            body = ("Thank you for your inquiry. Please find our new-container quotation and an additional "
                    "more economical option for your consideration:\n\n")
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

    cfg = get_index_config()
    dcfg = cfg.get("drafter_config", {})

    sales_sop = load_skill_file(cfg.get("sales_inquiry_file", "01_sales_inquiry.md"))

    if "[LOCATION_CLARIFICATION]" in inventory_data:
        scenario_rules = """[SCENARIO: LOCATION CLARIFICATION]
    The authorized business policy is that we have containers available at multiple ports
    in the requested country or region. State this positively, ask ONLY for the required
    pickup city, and say we will provide our latest quotation once the city is received.
    Use the customer's language. Do not claim specific requested items/conditions are
    confirmed, name ports or depots, disclose internal data issues, or apologize for no stock.
    NO quote blocks, prices, quantities, Subject, greeting, or signature."""
    elif rag_missing_info(inventory_data):
        scenario_rules = """[SCENARIO: MISSING INFORMATION]
    1. Output ONLY a polite request asking the customer to clarify the missing details listed in the stock data.
    2. Structure (STRICT):
       - Opening line: "Thank you for your inquiry." (中文: "感谢您的询盘。")
       - Then politely request the missing details listed in the stock data (e.g. pickup location / container type).
       - Closing line: "Once received, we will revert with our best offer immediately." (中文: "收到信息后，我们将第一时间为您提供最优报价。")
    3. ZERO TOLERANCE: NO quote blocks, NO "best offer" opening phrase, NO Subject, NO Dear, NO Signatures."""
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
       - If valid items are [DEFAULT_NEW]: customer did NOT specify the condition. The system selected NEW / New 1-Trip as the FIRST offer; do not assert the customer requested new.
       - If [BUDGET_ALTERNATIVE] occurs: customer gave an explicit USD target price per unit and the quoted new price is at least USD300 above it. ALWAYS include BOTH the NEW quote block and ONE cheaper budget-conscious alternative block (CW preferred or another qualified condition). Do not claim a discount or promise that the alternative meets budget; copy actual prices. When any variant differs, disclose this honestly. Use a positive comparison instead of an out-of-stock apology.
       - If [DEFAULT_NEW_UNAVAILABLE] occurs: the customer did not specify condition, but the default new stock was unavailable; offer the available used grade without saying the customer had explicitly required new.
       - If valid items are [EXACT]:
         Opening MUST be: "Thank you for your inquiry. Please find our best offer below:" (中文: "感谢您的询盘，请查阅我们的最优报价：")
       - If an item is tagged [ALT_VARIANT] or mentions special variant fallback (e.g. 2-door/tridoor out of stock, offering 4-door):
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
       - For each UNIQUE container specification (Style + Condition + POL + Color), output EXACTLY ONE standard quote block (Style/Condition/POL/Color/YOM/Price/Q'ty/Payment).
       - NEVER output duplicate quote blocks for the same container specification. If there are multiple transit batches with different ETAs/quantities for the same container, display ONE quote block and explain the arrival batches in the narrative below.
       - Q'ty: specific number (e.g. "1 unit" or "N units") if Stock_Qty >= customer's requested quantity, otherwise "Available".
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

    # 🌟 从配置读取 Drafter 参数
    temp_normal = float(dcfg.get("temperature", 0.1))
    temp_on_retry = float(dcfg.get("temperature_on_retry", 0.0))
    max_tokens = int(dcfg.get("max_tokens", 5000))
    max_retries = int(dcfg.get("max_retries", 3))

    temperature = temp_on_retry if rejection_reason else temp_normal
    last_err = ""
    for attempt in range(max_retries):
        try:
            response = ai_client.chat.completions.create(
                model=AI_MODEL,
                messages=[{"role": "system", "content": system_prompt},
                          {"role": "user", "content": user_prompt}],
                temperature=temperature, max_tokens=max_tokens
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

    if "[BUDGET_ALTERNATIVE]" in inventory_data:
        # 不能只输出新箱或只输出便宜箱：两个实际价格与箱况必须都在草稿中。
        budget_rows = _extract_rag_rows(inventory_data)
        if len(budget_rows) < 2 or len(re.findall(r"(?im)^\s*Style\s*:", draft_reply)) < 2:
            return False, "Budget alternative requires BOTH the new and the cheaper quote blocks."
        for style, cond, pol, color, yom, price, qty, pay in budget_rows:
            if not re.search(rf"(?im)^\s*Condition\s*:\s*{re.escape(cond)}\s*$", draft_reply):
                return False, f"Budget alternative missing quoted condition: {cond}"
            if not re.search(rf"(?im)^\s*Price\s*:\s*{re.escape(price)}\s*$", draft_reply):
                return False, f"Budget alternative missing quoted price: {price}"

    # 同时验证箱型+箱况+地点，阻止多箱型/多城市邮件交换了 POL 后混报。
    # 仅对标准现货报价块执行；单独的在途数据格式不同，不可误作现货。
    verified_rows = _extract_rag_rows(inventory_data)
    if verified_rows:
        expected = {(_normalize_location_name(style), _normalize_location_name(cond),
                     _normalize_location_name(pol))
                    for style, cond, pol, *_ in verified_rows}
        quoted = re.findall(
            r"(?im)^\s*Style\s*:\s*([^\n]+)\n\s*Condition\s*:\s*([^\n]+)"
            r"\n\s*POL\s*:\s*([^\n]+)", draft_reply
        )
        actual = {tuple(_normalize_location_name(value) for value in triple) for triple in quoted}
        if not expected or not actual:
            return False, "Missing verifiable Style / Condition / POL quotation block."
        if not actual.issubset(expected):
            return False, "Draft Style/Condition/POL combination differs from verified ERP inventory."
        if not expected.issubset(actual):
            return False, "Draft omitted a verified quote block (Style/Condition/POL)."

    # 🌟 大小写不敏感
    if re.search(r'cargo\s+worthy', draft_reply, re.IGNORECASE):
        return False, "Forbidden long name 'Cargo Worthy' found. Must use 'CW'."
    if re.search(r'^\s*\*\*[A-Za-z\s]+\*\*\s*$', draft_reply, re.MULTILINE):
        return False, "Forbidden bold header (**City**) found."
    if re.search(r'\b(Dear|Subject:|\[Your\b)', draft_reply, re.IGNORECASE):
        return False, "Draft contains forbidden email headers or signature placeholders."
    if "|" in draft_reply:
        return False, "Draft contains forbidden Markdown table syntax (|)."

    # 2. 场景一致性校验
    lower_draft = draft_reply.lower()
    if "[LOCATION_CLARIFICATION]" in inventory_data:
        if re.search(r"(?i)style\s*:|price\s*:|q['’]?ty\s*:|payment\s*:|USD\s*\d|\$\s*\d", draft_reply):
            return False, "Location clarification must ask for pickup city without quotation details."
        if re.search(r"(?i)out of stock|no (?:matching |available )?stock|do not have|don't have|unavailable|暂无|无货|没有库存", draft_reply):
            return False, "Location clarification must not be described as no stock."
    elif rag_all_nostock(inventory_data):
        if re.search(r"style\s*:|q['’]?ty\s*:|payment\s*:", draft_reply, re.IGNORECASE):
            return False, "Out-of-stock scenario but draft contains quote clauses (hallucinated offer)."
        if "please find our best offer below" in lower_draft or "请查阅我们的最优报价" in draft_reply:
            return False, "Contradictory quotation opening in out-of-stock reply."
    elif rag_has_quotes(inventory_data):
        if ("please find our best offer below" in lower_draft or "recommend" in lower_draft
            or "请查阅" in draft_reply or "推荐" in draft_reply) \
                and not re.search(r"style\s*:", draft_reply, re.I):
            return False, "Quotation/recommendation opening present but no Style quote block found."

    # 3. LLM 审核员
    cfg = get_index_config()
    rcfg = cfg.get("reviewer_config", {})

    sales_sop = load_skill_file(cfg.get("sales_inquiry_file", "01_sales_inquiry.md"))
    reviewer_template = load_skill_file(cfg.get("response_guard_file", "02_response_guard.md"))
    review_prompt = (reviewer_template.replace("{sales_sop}", sales_sop).replace("{inventory_data}", inventory_data))

    try:
        # 🌟 强化隔离标签：防止审核员误把客户邮件中的 Dear/落款 当成草稿违规
        user_msg = (
            f"==================================================\n"
            f"【CUSTOMER ORIGINAL EMAIL (FOR CONTEXT & FACT-CHECKING ONLY - DO NOT VALIDATE THIS)】\n"
            f"Title: {original_title}\n"
            f"Body:\n{original_content}\n"
            f"==================================================\n"
            f"【AI DRAFT REPLY (CRITICAL: VALIDATE ONLY THIS PART)】\n"
            f"{draft_reply}\n"
            f"=================================================="
        )
        response = ai_client.chat.completions.create(
            model=AI_MODEL,
            messages=[{"role": "system", "content": review_prompt},
                      {"role": "user", "content": user_msg}],
            temperature=float(rcfg.get("temperature", 0.0)),
            max_tokens=int(rcfg.get("max_tokens", 1000)),
            response_format={"type": "json_object"}
        )
        raw = (response.choices[0].message.content or "").strip()
        if not raw:
            raise ValueError("Reviewer 返回空内容")
        if match := re.search(r'\{.*\}', raw, re.DOTALL):
            raw = match.group()
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Reviewer 返回非 JSON 对象")
        return str(data.get("status", "FAIL")).upper() == "PASS", str(data.get("feedback", ""))
    except Exception as e:
        print(f"❌ [Reviewer 异常，审核不通过] {type(e).__name__}: {e}")
        return False, f"Reviewer 执行异常: {e}"


# ==========================================================
# 8. 统一入口与执行调度
# ==========================================================
# 注：STRATEGIC_BULK_INQUIRY 在 generate_ai_reply 中已单独提前处理并 return，
#     不需要再放入本集合。
ALLOWED_REPLIER_INTENTS = {"STOCK_PRICE_INQUIRY"}


def _build_noreply_reason(e_title, e_content, router_result):
    # 🌟 优先使用 Router 已给出的 intercept_reason，避免重复调用 AI
    router_reason = (router_result.get("intercept_reason") or "").strip()
    if router_reason and router_reason not in ("Router 解析超时拦截",):
        return router_reason

    p_intent = router_result.get("primary_intent", "UNKNOWN")
    s_intents = router_result.get("secondary_intents", []) or []

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


def _ai_judge_new_customer(sender_email, e_title, e_content):
    """
    判断发件人是否为新客户。
    业务规则：老客户已建档，系统中 s_email 字段显示为联系人姓名（如 'Tai Le'）；
             新客户未建档，s_email 字段显示为完整邮箱地址（如 'tai.le@royal-intermodal.com.vn'）。
    """
    email_val = str(sender_email or "").strip()
    if not email_val:
        return False

    # 规则兜底：能解析为完整邮箱地址 → 大概率新客户
    is_email_format = bool(re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email_val))

    try:
        response = ai_client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content":
                    "你是 Hysun Container 的客户身份识别助手。\n"
                    "已知业务事实：\n"
                    "1) 老客户都是已经建档的客户，邮件系统中 s_email 字段存的是联系人姓名，例如 'Tai Le'、'Zhang Wei'。\n"
                    "2) 新客户尚未建档，s_email 字段存的是完整邮箱地址，例如 'tai.le@royal-intermodal.com.vn'。\n"
                    "请根据给定的 s_email 值判断该发件人是【新客户】还是【老客户】。\n"
                    "注意：若 s_email 是完整邮箱地址格式（含 @ 与域名），应判为新客户；"
                    "若是纯人名（不含 @），应判为老客户。\n"
                    "只输出 JSON：{\"is_new_customer\": true/false, \"reason\": \"简短中文原因\"}"},
                {"role": "user", "content":
                    f"s_email 字段值：{email_val}\n"
                    f"邮件标题：{e_title}\n"
                    f"邮件正文摘要：{str(e_content)[:300]}"}
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
            max_tokens=200
        )
        raw = (response.choices[0].message.content or "").strip()
        if match := re.search(r'\{.*\}', raw, re.DOTALL):
            raw = match.group()
        data = json.loads(raw)
        is_new = bool(data.get("is_new_customer", is_email_format))
        print(f"🧭 [新客户判定] s_email='{email_val}' → "
              f"{'新客户' if is_new else '老客户'}（{data.get('reason', '')}）")
        return is_new
    except Exception as e:
        print(f"⚠️ [新客户 AI 判定异常] {e}，改用邮箱格式兜底规则 → "
              f"{'新客户' if is_email_format else '老客户'}")
        return is_email_format


def generate_manager_handover_draft(e_title, e_content, router_result=None):
    """大宗合作/需人工评估询盘的标准收件回执"""
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


def generate_ai_reply(e_title, e_content, flag, sender_email=""):
    print("📥 [DEBUG 接收到的原始邮件]")
    print(f"【标题】: {e_title}\n【正文】:\n{e_content}\n【发件人】: {sender_email}\n" + "=" * 50 + "\n")

    print("Stage 1: Intent Router...")
    router_result = predict_intent(e_title, e_content)
    print("Router Result:", json.dumps(router_result, ensure_ascii=False))

    p_intent = str(router_result.get("primary_intent") or "UNKNOWN").strip()

    # 1. 战略大宗合作优先走人工转交回复
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

    # 3. 散单现货库存级联检索
    ent_data = router_result.get("entities")
    if not isinstance(ent_data, dict) or not ent_data:
        ent_data = router_result

    inventory_data = query_internal_inventory(ent_data, f"{e_title}\n{e_content}")

    # ==========================================================
    # 🌟 群发静默逻辑改造：flag=3 且全无货时，由 AI 判断是否新客户
    #    - 新客户：破例继续生成回复（不静默）
    #    - 老客户：返回 NO_REPLY，并在 process_pending_emails 中写 ai_status=8
    # ==========================================================
    if rag_all_nostock(inventory_data):
        is_new_customer = _ai_judge_new_customer(sender_email, e_title, e_content)
        if is_new_customer:
            print(f"\n🌟 [新客无货破例] s_email='{sender_email}' 判定为新客户，跳过静默，继续生成致歉回复...")
            # 不 return，落到下面继续走 Drafter
        else:
            print(f"\n🚫 [老客无货静默] s_email='{sender_email}' 判定为老客户且无库存，跳过发送（ai_status=8）。")
            return "NO_REPLY_REASON::GROUP_NO_STOCK_SKIP::老客户无库存，跳过发送"

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
    """处理一封邮件；已处理（含已记录失败）返回 True，无邮件或队列故障返回 False。"""
    conn = None
    e_id = None
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(
                f"UPDATE {TABLE_NAME} SET ai_status = 0 "
                f"WHERE ai_status = 1"  # DATE(uptime) = CURDATE()
            )
            conn.commit()

            # 🌟 新增 s_email 字段
            cursor.execute(
                f"SELECT e_id, e_title, e_content, flag, s_email FROM {TABLE_NAME} "
                f"WHERE ai_status = 0 AND flag IN (2, 3) AND fb_mail IS NULL "
                f"AND uptime > DATE_ADD(NOW(), INTERVAL -24 HOUR) ORDER BY uptime DESC LIMIT 1 FOR UPDATE;"
            )
            email = cursor.fetchone()
            if not email:
                return False

            e_id = email["e_id"]
            title = email.get("e_title", "")
            content = email.get("e_content", "")
            flag = email.get("flag", 2)
            sender_email = (email.get("s_email") or "").strip()  # 🌟 新增
            cursor.execute(f"UPDATE {TABLE_NAME} SET ai_status = 1 WHERE e_id=%s", (e_id,))
            conn.commit()

            print("\n" + "=" * 50 + f"\n【id】: {e_id}\n【s_email】: {sender_email}")

            # 🌟 传入 sender_email
            reply = generate_ai_reply(title, content, flag, sender_email)

            if reply and str(reply).startswith("NO_REPLY_REASON::"):
                reason_body = reply.split("::", 1)[1]

                # 🌟 群发无货且非新客户 → ai_status = 9（不发送）
                if reason_body.startswith("GROUP_NO_STOCK_SKIP::"):
                    skip_reason = reason_body.split("::", 1)[1]
                    cursor.execute(
                        f"UPDATE {TABLE_NAME} SET ai_reply=%s, ai_status=9, uptime=NOW() WHERE e_id=%s",
                        (skip_reason, e_id)
                    )
                else:
                    cursor.execute(
                        f"UPDATE {TABLE_NAME} SET ai_reply=%s, ai_status=4, uptime=NOW() WHERE e_id=%s",
                        (reason_body, e_id)
                    )

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
        if conn and e_id is not None:
            try:
                conn.rollback()
                with conn.cursor() as err_cursor:
                    err_cursor.execute(
                        f"UPDATE {TABLE_NAME} SET ai_reply=%s, ai_status=3, uptime=NOW() WHERE e_id=%s",
                        (f"系统运行异常: {str(e)[:200]}", e_id)
                    )
                conn.commit()
                print(f"⚠️ 邮件ID: {e_id} 已记录失败，继续处理下一封邮件。")
                return True
            except Exception as record_error:
                print(f"💥 [失败状态写入失败] 邮件ID: {e_id}, 错误: {record_error}，停止本轮批处理。")
                try:
                    conn.rollback()
                except Exception:
                    pass
        else:
            print("💥 无法领取邮件，停止本轮批处理。")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception as close_error:
                print(f"⚠️ [数据库连接关闭异常] {close_error}")


def process_all_pending_emails():
    processed_count = 0
    while process_pending_emails():
        processed_count += 1
    print(f"\n✅ 本轮结束，共处理 {processed_count} 封邮件（含已记录失败的邮件）。")


def test_static_email():
    title = "Purchase new containers"
    content = """Dear sir,
We are purchasing new empty containers from China, please quote your best rate as below :-
 
 
	New Container
	Used container
20ft Container
	USD…….
	USD…….
40ft Container
	USD…….
	USD…….
40ft HQ Container
	USD…….
	USD…….
Open top 
	USD…….
	USD…….
 
 
We are waiting your prompt reply.
 


Regards,
 Dinesh Chand 
Team Member,
Contracts & Procurement - Aluminium Smelter
Email: Dinesh.Chand@energy-mgt.com

 The email, including attachment(s) thereto, is intended for the confidential use of the designated recipient(s). If you are not an intended recipient, please delete the email and immediately notify the Company. The Company strictly prohibits unauthorized reading, dissemination, distribution, or copying of the same. The contents of the email, unless expressly stated otherwise, are for information purposes only and should not be regarded as an offer or acceptance of an offer or any confirmation thereon. Views expressed by an individual do not necessarily reflect the views of the Company. The email, including attachment(s) thereto, may contain viruses and other shortcomings. The Company does not guarantee the security of any information transmitted through email and is not liable for any interception, corruption, or delays. The Company reserves the right to review and retain copies of the email. Anyone communicating with the Company accepts the risks and the consequences thereon."""
    generate_ai_reply(title, content, 3, 'Dinesh.Chand@energy-mgt.com')


if __name__ == "__main__":
    # test_static_email()
    process_all_pending_emails()
