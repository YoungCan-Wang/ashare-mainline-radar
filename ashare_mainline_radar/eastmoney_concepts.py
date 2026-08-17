"""East Money concept/industry board helpers for theme basket curation.

The radar scores only themes listed in `theme_baskets.json`. That file is a
curated *tradable mainline* catalog (~20 themes), not a dump of every East Money
concept. These helpers refresh baskets from BK boards and keep leader seeds stable.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# Browser-like headers: GitHub-hosted runners with a bot UA commonly get HTTP 502
# from East Money clist (push2.eastmoney.com).
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_UA,
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "application/json, text/javascript, */*;q=0.1",
}
BOARD_LIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
TRANSIENT_HTTP_CODES = {429, 502, 503, 504}
BOARD_FS = {
    "concept": "m:90+t:3+f:!50",
    "industry": "m:90+t:2+f:!50",
}


def _preset(
    name: str,
    *,
    valuation_style: str,
    keywords: list[str],
    policy_keywords: list[str],
    seed_symbols: list[str],
    vehicles: list[str],
    boards: list[dict[str, str]],
    per_board_cap: int = 4,
    max_symbols: int = 12,
    vehicle_name_keywords: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "valuation_style": valuation_style,
        "keywords": keywords,
        "policy_keywords": policy_keywords,
        "seed_symbols": seed_symbols,
        "vehicles": vehicles,
        "vehicle_name_keywords": vehicle_name_keywords or [],
        "boards": boards,
        "per_board_cap": per_board_cap,
        "max_symbols": max_symbols,
        "exclude_prefixes": ("920",),
    }


# Curated tradable mainlines. Prefer broad rotation narratives over tiny EM concepts.
THEME_PRESETS: dict[str, dict[str, Any]] = {
    "大消费": _preset(
        "大消费",
        valuation_style="balanced",
        keywords=["大消费", "白酒", "食品饮料", "家电", "旅游", "免税", "零售", "乳业", "扩内需", "服务消费"],
        policy_keywords=["扩内需", "提振消费", "服务消费", "消费品以旧换新", "家电以旧换新", "文旅消费", "促消费"],
        seed_symbols=[
            "600519.SH",
            "000858.SZ",
            "600809.SH",
            "000568.SZ",
            "600887.SH",
            "605499.SH",
            "603288.SH",
            "000333.SZ",
            "000651.SZ",
            "600690.SH",
            "601888.SH",
            "600415.SH",
        ],
        vehicles=["159928.SZ", "512690.SH"],
        boards=[
            {"code": "BK0896", "name": "白酒", "kind": "concept"},
            {"code": "BK0438", "name": "食品饮料", "kind": "industry"},
            {"code": "BK0456", "name": "家用电器", "kind": "industry"},
            {"code": "BK0485", "name": "旅游酒店", "kind": "industry"},
            {"code": "BK1711", "name": "消费风格", "kind": "concept"},
            {"code": "BK0482", "name": "商业百货", "kind": "industry"},
        ],
    ),
    "光伏与储能": _preset(
        "光伏与储能",
        valuation_style="cyclical",
        keywords=["光伏", "储能", "硅料", "组件", "逆变器", "电站", "新能源", "绿电"],
        policy_keywords=["新型储能", "光伏发电", "可再生能源", "绿色低碳", "碳中和", "电力市场化"],
        seed_symbols=[
            "601012.SH",
            "600438.SH",
            "300274.SZ",
            "002459.SZ",
            "688599.SH",
            "605117.SH",
            "300763.SZ",
            "002335.SZ",
            "688223.SH",
            "002865.SZ",
            "300751.SZ",
            "600732.SH",
        ],
        vehicles=["515790.SH", "159857.SZ"],
        boards=[
            {"code": "BK0588", "name": "光伏概念", "kind": "concept"},
            {"code": "BK0989", "name": "储能概念", "kind": "concept"},
        ],
    ),
    "新能源车": _preset(
        "新能源车",
        valuation_style="growth",
        keywords=["新能源车", "电动车", "智能驾驶", "整车", "汽车零部件", "充电", "自动驾驶"],
        policy_keywords=["新能源汽车", "智能网联汽车", "以旧换新", "充电基础设施", "汽车产业"],
        seed_symbols=[
            "002594.SZ",
            "601127.SH",
            "000625.SZ",
            "601633.SH",
            "601689.SH",
            "603596.SH",
            "002920.SZ",
            "600699.SH",
            "002050.SZ",
            "603179.SH",
            "601799.SH",
            "300450.SZ",
        ],
        vehicles=["516110.SH", "159637.SZ"],
        boards=[
            {"code": "BK0900", "name": "新能源车", "kind": "concept"},
            {"code": "BK1029", "name": "汽车整车", "kind": "concept"},
        ],
    ),
    "电网设备": _preset(
        "电网设备",
        valuation_style="cyclical",
        keywords=["电网", "特高压", "变压器", "电力设备", "配电网", "智能电网"],
        policy_keywords=["新型电力系统", "特高压", "电网改造", "配电网", "智能电网"],
        seed_symbols=[
            "600406.SH",
            "600089.SH",
            "601179.SH",
            "000400.SZ",
            "002028.SZ",
            "600312.SH",
            "603606.SH",
            "600131.SH",
            "601727.SH",
        ],
        vehicles=[],
        boards=[
            {"code": "BK0918", "name": "特高压", "kind": "concept"},
            {"code": "BK1647", "name": "电网概念", "kind": "concept"},
            {"code": "BK0581", "name": "智能电网", "kind": "concept"},
        ],
    ),
    "电力运营": _preset(
        "电力运营",
        valuation_style="income",
        keywords=["电力运营", "发电", "水电", "火电", "核电", "绿电"],
        policy_keywords=["电力保供", "电力市场化", "煤电", "绿色电力", "能源安全"],
        seed_symbols=[
            "600900.SH",
            "600011.SH",
            "600886.SH",
            "600027.SH",
            "601985.SH",
            "003816.SZ",
            "600795.SH",
            "600642.SH",
            "600674.SH",
            "600025.SH",
            "000543.SZ",
            "000027.SZ",
        ],
        vehicles=["159611.SZ", "561560.SH"],
        vehicle_name_keywords=["电力"],
        boards=[
            {"code": "BK1024", "name": "绿色电力", "kind": "concept"},
        ],
    ),
    "信创软件": _preset(
        "信创软件",
        valuation_style="growth",
        keywords=["信创", "国产软件", "操作系统", "数据库", "办公软件", "信息安全", "国产替代"],
        policy_keywords=["信创", "数字政府", "网络安全", "关键软件", "信息技术应用创新"],
        seed_symbols=[
            "688111.SH",
            "600536.SH",
            "600588.SH",
            "002368.SZ",
            "000938.SZ",
            "002153.SZ",
            "300454.SZ",
            "688023.SH",
            "002212.SZ",
            "300496.SZ",
            "600845.SH",
            "300339.SZ",
        ],
        vehicles=["159852.SZ", "562060.SH"],
        boards=[
            {"code": "BK1104", "name": "信创", "kind": "concept"},
            {"code": "BK0696", "name": "国产软件", "kind": "concept"},
        ],
    ),
    "房地产链": _preset(
        "房地产链",
        valuation_style="cyclical",
        keywords=["房地产", "地产", "物业", "收储", "保交楼", "房价", "住房"],
        policy_keywords=["房地产", "保障性住房", "城中村改造", "存量房收购", "住房城乡建设"],
        seed_symbols=[
            "600048.SH",
            "000002.SZ",
            "001979.SZ",
            "600383.SH",
            "002244.SZ",
            "001914.SZ",
            "600325.SH",
            "000069.SZ",
            "600606.SH",
            "001286.SZ",
            "000961.SZ",
            "600208.SH",
        ],
        vehicles=["512200.SH", "159768.SZ"],
        boards=[
            {"code": "BK1346", "name": "住宅开发", "kind": "industry"},
            {"code": "BK1343", "name": "物业管理", "kind": "industry"},
            {"code": "BK1714", "name": "金融地产风格", "kind": "concept"},
        ],
    ),
    "保险": _preset(
        "保险",
        valuation_style="financial",
        keywords=["保险", "寿险", "财险", "代理人", "负债端", "投资端"],
        policy_keywords=["保险业", "长期资金", "养老金", "商业健康保险", "保险资金"],
        seed_symbols=[
            "601318.SH",
            "601601.SH",
            "601628.SH",
            "601336.SH",
            "601319.SH",
            "000627.SZ",
            "601366.SH",
            "600291.SH",
        ],
        vehicles=["512070.SH"],
        boards=[
            {"code": "BK1358", "name": "保险Ⅲ", "kind": "industry"},
            {"code": "BK0604", "name": "参股保险", "kind": "concept"},
        ],
        max_symbols=10,
    ),
    "航运港口": _preset(
        "航运港口",
        valuation_style="cyclical",
        keywords=["航运", "港口", "集运", "油运", "干散货", "运价", "BDI"],
        policy_keywords=["航运", "港口", "物流枢纽", "海洋经济", "供应链"],
        seed_symbols=[
            "601919.SH",
            "601872.SH",
            "600026.SH",
            "600018.SH",
            "601298.SH",
            "601000.SH",
            "601018.SH",
            "601880.SH",
            "600717.SH",
            "603128.SH",
            "601975.SH",
            "600798.SH",
        ],
        vehicles=["516550.SH", "159866.SZ"],
        boards=[
            {"code": "BK1482", "name": "航运", "kind": "industry"},
            {"code": "BK1481", "name": "港口", "kind": "industry"},
        ],
    ),
    "传媒游戏": _preset(
        "传媒游戏",
        valuation_style="growth",
        keywords=["游戏", "传媒", "短剧", "影视", "广告", "版号", "内容"],
        policy_keywords=["数字文化", "网络游戏", "文化产业", "广播电视", "网络视听"],
        seed_symbols=[
            "002555.SZ",
            "002624.SZ",
            "603444.SH",
            "002027.SZ",
            "300413.SZ",
            "002558.SZ",
            "300251.SZ",
            "002602.SZ",
            "603533.SH",
            "300133.SZ",
            "002739.SZ",
            "300182.SZ",
        ],
        vehicles=["159869.SZ", "516010.SH"],
        boards=[
            {"code": "BK0509", "name": "网络游戏", "kind": "concept"},
            {"code": "BK1151", "name": "短剧互动游戏", "kind": "concept"},
        ],
    ),
    "农业种植": _preset(
        "农业种植",
        valuation_style="cyclical",
        keywords=["农业", "种植", "种业", "养殖", "饲料", "粮食", "猪肉"],
        policy_keywords=["种业振兴", "粮食安全", "农业现代化", "乡村振兴", "农产品"],
        seed_symbols=[
            "002714.SZ",
            "300498.SZ",
            "000998.SZ",
            "600598.SH",
            "002041.SZ",
            "002385.SZ",
            "000876.SZ",
            "002311.SZ",
            "600737.SH",
            "600371.SH",
            "300087.SZ",
            "002891.SZ",
        ],
        vehicles=["159825.SZ", "159698.SZ"],
        boards=[
            {"code": "BK0888", "name": "农业种植", "kind": "concept"},
            {"code": "BK1518", "name": "种子", "kind": "industry"},
            {"code": "BK1512", "name": "生猪养殖", "kind": "industry"},
        ],
    ),
    "医疗器械": _preset(
        "医疗器械",
        valuation_style="growth",
        keywords=["医疗器械", "IVD", "影像", "高值耗材", "设备更新", "集采"],
        policy_keywords=["医疗器械", "设备更新", "集中采购", "高性能医疗器械", "健康产业"],
        seed_symbols=[
            "300760.SZ",
            "688271.SH",
            "300633.SZ",
            "688617.SH",
            "300003.SZ",
            "002223.SZ",
            "300529.SZ",
            "688050.SH",
            "300832.SZ",
            "688351.SH",
            "300396.SZ",
            "002901.SZ",
        ],
        vehicles=["159883.SZ"],
        vehicle_name_keywords=["医疗器械"],
        boards=[
            {"code": "BK0668", "name": "医疗器械概念", "kind": "concept"},
            {"code": "BK1605", "name": "医疗设备", "kind": "industry"},
            {"code": "BK1603", "name": "体外诊断", "kind": "industry"},
        ],
    ),
    "工程机械": _preset(
        "工程机械",
        valuation_style="cyclical",
        keywords=["工程机械", "挖机", "起重机", "液压", "基建", "设备更新"],
        policy_keywords=["设备更新", "基础设施建设", "重大工程", "先进制造"],
        seed_symbols=[
            "600031.SH",
            "000425.SZ",
            "000157.SZ",
            "601100.SH",
            "600761.SH",
            "000528.SZ",
            "603298.SH",
            "002097.SZ",
            "000680.SZ",
            "600815.SH",
            "002204.SZ",
            "603338.SH",
        ],
        vehicles=["159667.SZ", "561700.SH"],
        boards=[
            {"code": "BK0991", "name": "工程机械概念", "kind": "concept"},
            {"code": "BK1393", "name": "工程机械整机", "kind": "industry"},
        ],
    ),
}


def code_to_symbol(code: str) -> str:
    """Map a 6-digit A-share code to TickFlow-style SYMBOL.EXCHANGE."""
    text = str(code).strip().upper()
    if "." in text:
        return text
    if text.startswith(("5", "6", "9")):
        return f"{text}.SH"
    if text.startswith(("0", "1", "2", "3")):
        return f"{text}.SZ"
    return f"{text}.SZ"


def _request_json(url: str, timeout: float = 45.0, retries: int = 3) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers=DEFAULT_HEADERS)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError(f"unexpected East Money payload type: {type(payload)!r}")
            return payload
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt + 1 >= retries:
                break
            backoff = 2.4 if _is_transient_http(exc) else 1.2
            time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"East Money request failed for {url}: {last_error}") from last_error


def _is_transient_http(exc: BaseException) -> bool:
    return isinstance(exc, urllib.error.HTTPError) and exc.code in TRANSIENT_HTTP_CODES


def fetch_board_list(kind: str = "concept", pages: int = 8, page_size: int = 100) -> list[dict[str, Any]]:
    """Return East Money board rows with code/name/change fields."""
    fs = BOARD_FS.get(kind)
    if not fs:
        raise ValueError(f"unsupported board kind: {kind}")
    rows: list[dict[str, Any]] = []
    for page in range(1, pages + 1):
        query = urllib.parse.urlencode(
            {
                "pn": page,
                "pz": page_size,
                "po": 1,
                "np": 1,
                "fltt": 2,
                "invt": 2,
                "fid": "f12",
                "fs": fs,
                "fields": "f12,f14,f3,f104,f105",
            }
        )
        payload = _request_json(f"{BOARD_LIST_URL}?{query}")
        diff = ((payload.get("data") or {}).get("diff")) or []
        if not diff:
            break
        for item in diff:
            rows.append(
                {
                    "code": str(item.get("f12") or ""),
                    "name": str(item.get("f14") or ""),
                    "change_pct": item.get("f3"),
                    "up_count": item.get("f104"),
                    "down_count": item.get("f105"),
                    "kind": kind,
                }
            )
        if len(diff) < page_size:
            break
        time.sleep(0.2)
    return rows


def fetch_board_constituents(board_code: str, pages: int = 5, page_size: int = 100) -> list[dict[str, Any]]:
    """Return constituents for an East Money BK board, richest amount first."""
    code = str(board_code).strip().upper()
    if not code.startswith("BK"):
        raise ValueError(f"board code must look like BK0896, got {board_code!r}")
    rows: list[dict[str, Any]] = []
    for page in range(1, pages + 1):
        query = urllib.parse.urlencode(
            {
                "pn": page,
                "pz": page_size,
                "po": 1,
                "np": 1,
                "fltt": 2,
                "invt": 2,
                "fid": "f6",
                "fs": f"b:{code}+f:!50",
                "fields": "f12,f14,f2,f3,f6,f20,f8",
            }
        )
        payload = _request_json(f"{BOARD_LIST_URL}?{query}")
        diff = ((payload.get("data") or {}).get("diff")) or []
        if not diff:
            break
        for item in diff:
            amount = item.get("f6")
            market_cap = item.get("f20")
            rows.append(
                {
                    "code": str(item.get("f12") or ""),
                    "symbol": code_to_symbol(str(item.get("f12") or "")),
                    "name": str(item.get("f14") or ""),
                    "change_pct": item.get("f3"),
                    "amount": float(amount) if amount not in (None, "-") else 0.0,
                    "market_cap": float(market_cap) if market_cap not in (None, "-") else 0.0,
                    "turnover": item.get("f8"),
                    "board": code,
                }
            )
        if len(diff) < page_size:
            break
        time.sleep(0.2)
    rows.sort(key=lambda item: item["amount"], reverse=True)
    return rows


def select_scoring_symbols(
    constituents_by_board: dict[str, list[dict[str, Any]]],
    *,
    per_board_cap: int = 4,
    max_symbols: int = 12,
    exclude_prefixes: tuple[str, ...] = (),
    seed_symbols: list[str] | None = None,
) -> list[str]:
    """Pick a diversified, liquid scoring basket across source boards."""
    selected: list[str] = []
    seen: set[str] = set()
    for symbol in seed_symbols or []:
        if symbol in seen:
            continue
        selected.append(symbol)
        seen.add(symbol)
        if len(selected) >= max_symbols:
            return selected

    board_counts: dict[str, int] = {board: 0 for board in constituents_by_board}

    # Round-robin by board rank so one mega-board cannot monopolize the basket.
    rank = 0
    while len(selected) < max_symbols:
        progressed = False
        for board, rows in constituents_by_board.items():
            if board_counts[board] >= per_board_cap:
                continue
            if rank >= len(rows):
                continue
            row = rows[rank]
            symbol = str(row["symbol"])
            code = str(row["code"])
            if any(code.startswith(prefix) for prefix in exclude_prefixes):
                continue
            if symbol in seen:
                continue
            if symbol.endswith(".BJ") or code.startswith("8") or code.startswith("4"):
                continue
            selected.append(symbol)
            seen.add(symbol)
            board_counts[board] += 1
            progressed = True
            if len(selected) >= max_symbols:
                break
        if not progressed:
            break
        rank += 1
    return selected


def offline_theme_from_preset(preset_name: str, *, as_of: str | None = None) -> dict[str, Any]:
    """Build a theme dict from seed symbols only (no network)."""
    preset = THEME_PRESETS.get(preset_name)
    if not preset:
        known = ", ".join(sorted(THEME_PRESETS))
        raise KeyError(f"unknown preset {preset_name!r}; known: {known}")
    max_symbols = int(preset.get("max_symbols", 12))
    seeds = list(dict.fromkeys(preset.get("seed_symbols", [])))[:max_symbols]
    board_labels = [f"{board['name']}({board['code']})" for board in preset.get("boards", [])]
    source_date = as_of or time.strftime("%Y-%m-%d")
    return {
        "name": preset["name"],
        "valuation_style": preset["valuation_style"],
        "keywords": list(preset["keywords"]),
        "policy_keywords": list(preset["policy_keywords"]),
        "symbols": seeds,
        "vehicles": list(preset.get("vehicles", [])),
        "vehicle_name_keywords": list(preset.get("vehicle_name_keywords", [])),
        "source": f"eastmoney boards: {', '.join(board_labels)}; curated {source_date}",
    }


def build_theme_from_preset(
    preset_name: str,
    *,
    as_of: str | None = None,
    fetch_constituents=None,
) -> dict[str, Any]:
    """Materialize a theme dict from a preset and live East Money constituents.

    A single flaky board (HTTP 502/503/timeout after retries) must not abort the
    preset: that board contributes no live fill, and seed_symbols still lead.
    """
    preset = THEME_PRESETS.get(preset_name)
    if not preset:
        known = ", ".join(sorted(THEME_PRESETS))
        raise KeyError(f"unknown preset {preset_name!r}; known: {known}")

    fetch = fetch_constituents or fetch_board_constituents
    constituents_by_board: dict[str, list[dict[str, Any]]] = {}
    board_labels: list[str] = []
    for board in preset["boards"]:
        code = str(board["code"])
        label = str(board["name"])
        board_labels.append(f"{label}({code})")
        try:
            constituents_by_board[code] = fetch(code, pages=2)
        except (RuntimeError, OSError, TimeoutError, ValueError) as exc:
            print(
                f"warning: East Money board {code} ({label}) fetch failed; "
                f"continuing with seed/other-board fill: {exc}",
                file=sys.stderr,
            )
            constituents_by_board[code] = []

    symbols = select_scoring_symbols(
        constituents_by_board,
        per_board_cap=int(preset.get("per_board_cap", 4)),
        max_symbols=int(preset.get("max_symbols", 12)),
        exclude_prefixes=tuple(preset.get("exclude_prefixes", ())),
        seed_symbols=list(preset.get("seed_symbols", [])),
    )
    source_date = as_of or time.strftime("%Y-%m-%d")
    return {
        "name": preset["name"],
        "valuation_style": preset["valuation_style"],
        "keywords": list(preset["keywords"]),
        "policy_keywords": list(preset["policy_keywords"]),
        "symbols": symbols,
        "vehicles": list(preset.get("vehicles", [])),
        "vehicle_name_keywords": list(preset.get("vehicle_name_keywords", [])),
        "source": f"eastmoney boards: {', '.join(board_labels)}; curated {source_date}",
    }


def upsert_theme(theme_config: dict[str, Any], theme: dict[str, Any]) -> dict[str, Any]:
    """Insert or replace a theme by name; return the mutated config."""
    themes = list(theme_config.get("themes") or [])
    name = str(theme["name"])
    replaced = False
    for index, existing in enumerate(themes):
        if str(existing.get("name")) == name:
            merged = dict(existing)
            merged.update(theme)
            themes[index] = merged
            replaced = True
            break
    if not replaced:
        themes.append(theme)
    updated = dict(theme_config)
    updated["themes"] = themes
    return updated


def filter_boards(boards: list[dict[str, Any]], keywords: list[str]) -> list[dict[str, Any]]:
    keys = [key for key in keywords if key]
    if not keys:
        return boards
    hits: list[dict[str, Any]] = []
    for board in boards:
        name = str(board.get("name") or "")
        if any(key in name for key in keys):
            hits.append(board)
    hits.sort(key=lambda item: float(item.get("change_pct") or 0.0), reverse=True)
    return hits
