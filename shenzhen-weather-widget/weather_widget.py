import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont, messagebox, simpledialog

LATITUDE = 22.5429
LONGITUDE = 114.0596
TIMEZONE = timezone(timedelta(hours=8), "Asia/Shanghai")
REFRESH_MS = 15 * 60 * 1000
ERROR_BACKOFF_STEPS_MS = [60 * 1000, 5 * 60 * 1000, 15 * 60 * 1000, 30 * 60 * 1000]
FULL_SIZE = (460, 350)
COMPACT_SIZE = (460, 238)
MIN_PYTHON = (3, 10)

CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SzWeatherWidget"
CACHE_FILE = CONFIG_DIR / "last.json"
GEOMETRY_FILE = CONFIG_DIR / "geometry.txt"
HTTP_META_FILE = CONFIG_DIR / "http_meta.json"
UA_FILE = CONFIG_DIR / "user_agent.txt"
ICON_FILE = Path(__file__).with_name("weather_widget.ico")

DEFAULT_USER_AGENT = "YourProductWeather/1.0 github.com/yourcompany/weather"
APP_USER_AGENT = os.environ.get("WEATHER_WIDGET_USER_AGENT", "").strip()

MET_PARAMS = urllib.parse.urlencode({"lat": f"{LATITUDE:.4f}", "lon": f"{LONGITUDE:.4f}"})
MET_URL = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?{MET_PARAMS}"

SYMBOL_MAP = {
    "clearsky": ("sun", "晴"),
    "fair": ("partly", "晴间多云"),
    "partlycloudy": ("partly", "局部多云"),
    "cloudy": ("cloud", "多云"),
    "fog": ("fog", "雾"),
    "lightrain": ("rain", "小雨"),
    "rain": ("rain", "中雨"),
    "heavyrain": ("rain", "大雨"),
    "lightsleet": ("snow", "小雨夹雪"),
    "sleet": ("snow", "雨夹雪"),
    "heavysleet": ("snow", "强雨夹雪"),
    "lightsnow": ("snow", "小雪"),
    "snow": ("snow", "雪"),
    "heavysnow": ("snow", "大雪"),
    "lightrainshowers": ("rain", "小阵雨"),
    "rainshowers": ("rain", "阵雨"),
    "heavyrainshowers": ("rain", "强阵雨"),
    "lightsleetshowers": ("snow", "小阵雨夹雪"),
    "sleetshowers": ("snow", "阵雨夹雪"),
    "heavysleetshowers": ("snow", "强阵雨夹雪"),
    "lightsnowshowers": ("snow", "小阵雪"),
    "snowshowers": ("snow", "阵雪"),
    "heavysnowshowers": ("snow", "强阵雪"),
    "lightrainandthunder": ("storm", "小雷雨"),
    "rainandthunder": ("storm", "雷雨"),
    "heavyrainandthunder": ("storm", "强雷雨"),
    "lightsleetandthunder": ("storm", "雷雨夹雪"),
    "sleetandthunder": ("storm", "雷雨夹雪"),
    "heavysleetandthunder": ("storm", "强雷雨夹雪"),
    "lightsnowandthunder": ("storm", "雷雪"),
    "snowandthunder": ("storm", "雷雪"),
    "heavysnowandthunder": ("storm", "强雷雪"),
}

WEEKDAYS = "一二三四五六日"
BG = "#0b1220"
CARD = "#17233a"
CARD_2 = "#20314f"
CARD_3 = "#25395c"
TEXT = "#f8fbff"
MUTED = "#9fb0cc"
SUBTLE = "#6d7d99"
ACCENT = "#7dd3fc"
ACCENT_2 = "#c4b5fd"
DANGER = "#fb7185"
WINDOW_TRANSPARENT = "#010203"


def ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def is_valid_user_agent(value):
    if not value or "github.com/yourcompany/weather" in value:
        return False
    # api.met.no allows contact information; this widget requires a URL/domain
    # form because Windows PowerShell's -UserAgent rejects many email-shaped
    # strings, while domain/project URLs work across both network paths.
    return bool(re.search(r"\b[a-z0-9-]+\.[a-z]{2,}\b", value, re.I))


def load_user_agent():
    global APP_USER_AGENT
    if APP_USER_AGENT:
        return APP_USER_AGENT
    try:
        APP_USER_AGENT = UA_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        APP_USER_AGENT = ""
    return APP_USER_AGENT


def save_user_agent(value):
    global APP_USER_AGENT
    ensure_config_dir()
    APP_USER_AGENT = value.strip()
    UA_FILE.write_text(APP_USER_AGENT, encoding="utf-8")


def ensure_user_agent_interactive(root=None):
    current = load_user_agent()
    if is_valid_user_agent(current):
        return current
    message = (
        "请填写产品名称和联系网址，用于合规获取天气数据。\n\n"
        "示例：YourCompanyWeather/1.0 github.com/yourcompany/weather\n\n"
        "该信息会保存在本机，仅作为天气请求的应用标识。"
    )
    while True:
        value = simpledialog.askstring("设置产品标识", message, parent=root, initialvalue=current or DEFAULT_USER_AGENT)
        if value is None:
            raise SystemExit("MET Norway requires an identifiable application label with contact info.")
        value = value.strip()
        if is_valid_user_agent(value):
            save_user_agent(value)
            return value
        message = "产品标识需要包含项目网站或联系网页。\n\n例如：YourCompanyWeather/1.0 github.com/yourcompany/weather"


def load_http_meta():
    try:
        return json.loads(HTTP_META_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_http_meta(headers):
    ensure_config_dir()
    meta = {}
    for key in ("ETag", "Last-Modified", "Expires"):
        value = headers.get(key)
        if value:
            meta[key] = value
    HTTP_META_FILE.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def fresh_cache_available():
    meta = load_http_meta()
    expires = meta.get("Expires")
    if not expires:
        return False
    try:
        return parsedate_to_datetime(expires).timestamp() > time.time()
    except (TypeError, ValueError, OSError):
        return False


def fetch_json(url):
    headers = {
        "User-Agent": load_user_agent(),
        "Accept": "application/json",
        "Accept-Encoding": "identity",
    }
    meta = load_http_meta()
    if meta.get("ETag"):
        headers["If-None-Match"] = meta["ETag"]
    if meta.get("Last-Modified"):
        headers["If-Modified-Since"] = meta["Last-Modified"]
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            save_http_meta(response.headers)
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            cached, _saved_at = load_cache()
            if cached:
                return {"__normalized__": cached}
        raise


def fetch_json_with_powershell(url):
    meta = load_http_meta()
    conditional_headers = ""
    if meta.get("ETag"):
        conditional_headers += "$headers['If-None-Match']=$env:WEATHER_WIDGET_ETAG; "
    if meta.get("Last-Modified"):
        conditional_headers += "$headers['If-Modified-Since']=$env:WEATHER_WIDGET_LAST_MODIFIED; "
    script = (
        "$ProgressPreference='SilentlyContinue'; "
        "$headers=@{'Accept'='application/json'}; "
        + conditional_headers
        + "$r=Invoke-WebRequest -UseBasicParsing -Uri $env:WEATHER_WIDGET_URL -Headers $headers -UserAgent $env:WEATHER_WIDGET_EFFECTIVE_UA -TimeoutSec 15; "
        "$meta=@{}; if($r.Headers.ETag){$meta.ETag=$r.Headers.ETag}; if($r.Headers.'Last-Modified'){$meta.'Last-Modified'=$r.Headers.'Last-Modified'}; if($r.Headers.Expires){$meta.Expires=$r.Headers.Expires}; "
        "$payload=@{meta=$meta; content=$r.Content} | ConvertTo-Json -Compress -Depth 5; "
        "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
        "[Console]::Out.Write($payload)"
    )
    env = os.environ.copy()
    env["WEATHER_WIDGET_URL"] = url
    env["WEATHER_WIDGET_EFFECTIVE_UA"] = load_user_agent()
    env["WEATHER_WIDGET_ETAG"] = meta.get("ETag", "")
    env["WEATHER_WIDGET_LAST_MODIFIED"] = meta.get("Last-Modified", "")
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        if "304" in stderr:
            cached, _saved_at = load_cache()
            if cached:
                return {"__normalized__": cached}
        raise OSError(stderr or "PowerShell weather request failed")
    payload = json.loads(completed.stdout)
    if isinstance(payload, dict):
        save_http_meta(payload.get("meta", {}))
        return json.loads(payload.get("content", "{}"))
    return payload


def fetch_weather():
    if fresh_cache_available():
        cached, _saved_at = load_cache()
        if cached:
            cached = dict(cached)
            cached["from_cache"] = True
            return cached
    try:
        raw = fetch_json(MET_URL)
    except urllib.error.URLError:
        raw = fetch_json_with_powershell(MET_URL)
    if isinstance(raw, dict) and "__normalized__" in raw:
        cached = dict(raw["__normalized__"])
        cached["from_cache"] = True
        return cached
    return normalize_met_payload(raw)


def normalize_met_payload(raw):
    series = raw.get("properties", {}).get("timeseries", [])
    if not series:
        raise ValueError("weather response has no timeseries")

    current_point = series[0]
    current_details = current_point.get("data", {}).get("instant", {}).get("details", {})
    current_symbol = symbol_for_point(current_point)
    temp = current_details.get("air_temperature")
    humidity = current_details.get("relative_humidity")
    wind = current_details.get("wind_speed")

    normalized = {
        "schema": 2,
        "source": "MET Norway Locationforecast",
        "license": "CC BY 4.0",
        "attribution": "Weather data from MET Norway",
        "fetched_at": datetime.now(TIMEZONE).isoformat(timespec="seconds"),
        "current": {
            "temperature_2m": temp,
            "relative_humidity_2m": humidity,
            "apparent_temperature": apparent_temperature(temp, humidity, wind),
            "wind_speed_10m": ms_to_kmh(wind),
            "symbol_code": current_symbol,
        },
        "daily": build_daily_forecast(series),
    }
    return normalized


def build_daily_forecast(series):
    grouped = defaultdict(list)
    for point in series:
        local_time = parse_met_time(point.get("time"))
        if not local_time:
            continue
        grouped[local_time.date()].append((local_time, point))

    days = []
    today = datetime.now(TIMEZONE).date()
    for day in sorted(grouped):
        if day < today:
            continue
        points = grouped[day]
        temps = []
        precip = 0.0
        symbols = []
        midday_symbol = None
        for local_time, point in points:
            data = point.get("data", {})
            details = data.get("instant", {}).get("details", {})
            temp = details.get("air_temperature")
            if isinstance(temp, (int, float)):
                temps.append(float(temp))
            amount = precipitation_for_point(data)
            if isinstance(amount, (int, float)):
                precip += float(amount)
            symbol = symbol_for_point(point)
            if symbol:
                symbols.append(symbol)
                if 10 <= local_time.hour <= 16 and midday_symbol is None:
                    midday_symbol = symbol
        if temps:
            days.append(
                {
                    "date": day.isoformat(),
                    "symbol_code": midday_symbol or most_common_symbol(symbols),
                    "temperature_2m_max": max(temps),
                    "temperature_2m_min": min(temps),
                    "precipitation_amount": precip,
                }
            )
        if len(days) == 5:
            break
    return days


def parse_met_time(value):
    if not value:
        return None
    value = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(value).astimezone(TIMEZONE)
    except ValueError:
        return None


def symbol_for_point(point):
    data = point.get("data", {})
    for key in ("next_1_hours", "next_6_hours", "next_12_hours"):
        symbol = data.get(key, {}).get("summary", {}).get("symbol_code")
        if symbol:
            return symbol.rsplit("_", 1)[0]
    return "cloudy"


def precipitation_for_point(data):
    for key in ("next_1_hours", "next_6_hours", "next_12_hours"):
        details = data.get(key, {}).get("details", {})
        if "precipitation_amount" in details:
            return details["precipitation_amount"]
    return 0.0


def most_common_symbol(symbols):
    if not symbols:
        return "cloudy"
    return Counter(symbols).most_common(1)[0][0]


def apparent_temperature(temp_c, humidity, wind_ms):
    try:
        temp_c = float(temp_c)
        humidity = float(humidity)
        wind_kmh = max(ms_to_kmh(wind_ms), 0)
    except (TypeError, ValueError):
        return temp_c
    if temp_c >= 27 and humidity >= 40:
        temp_f = temp_c * 9 / 5 + 32
        heat_index = (
            -42.379
            + 2.04901523 * temp_f
            + 10.14333127 * humidity
            - 0.22475541 * temp_f * humidity
            - 0.00683783 * temp_f * temp_f
            - 0.05481717 * humidity * humidity
            + 0.00122874 * temp_f * temp_f * humidity
            + 0.00085282 * temp_f * humidity * humidity
            - 0.00000199 * temp_f * temp_f * humidity * humidity
        )
        return (heat_index - 32) * 5 / 9
    if temp_c <= 10 and wind_kmh > 4.8:
        return 13.12 + 0.6215 * temp_c - 11.37 * wind_kmh ** 0.16 + 0.3965 * temp_c * wind_kmh ** 0.16
    return temp_c


def ms_to_kmh(value):
    try:
        return float(value) * 3.6
    except (TypeError, ValueError):
        return None


def save_cache(data):
    ensure_config_dir()
    payload = {"saved_at": time.time(), "data": data}
    CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def load_cache():
    try:
        payload = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        data = payload.get("data")
        if not isinstance(data, dict) or data.get("schema") != 2:
            return None, 0
        return data, float(payload.get("saved_at", 0))
    except (OSError, ValueError, TypeError):
        return None, 0


def save_geometry(geometry):
    ensure_config_dir()
    GEOMETRY_FILE.write_text(geometry, encoding="utf-8")


def load_geometry():
    try:
        geometry = GEOMETRY_FILE.read_text(encoding="utf-8").strip()
        if geometry:
            return geometry
    except OSError:
        pass
    width, height = FULL_SIZE
    return f"{width}x{height}+80+80"


def split_position(geometry):
    parts = geometry.replace("-", "+-").split("+")
    if len(parts) >= 3:
        return f"+{parts[-2]}+{parts[-1]}"
    return "+80+80"


def symbol_icon(symbol):
    return SYMBOL_MAP.get(str(symbol), ("cloud", "未知"))


def short_condition(text):
    return str(text).replace("晴间多云", "晴云").replace("局部多云", "多云").replace("强", "")[:3]


def format_age(saved_at):
    if not saved_at:
        return ""
    seconds = max(0, int(time.time() - saved_at))
    if seconds < 60:
        return "刚刚"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}分钟前"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}小时前"
    return f"{hours // 24}天前"


def day_label(date_text, _index=None):
    try:
        date = datetime.fromisoformat(date_text).date()
    except ValueError:
        return date_text[5:]
    today = datetime.now(TIMEZONE).date()
    delta = (date - today).days
    if delta == 0:
        return "今天"
    if delta == 1:
        return "明天"
    if delta < 0:
        return date.strftime("%m/%d")
    return "周" + WEEKDAYS[date.weekday()]


def filter_current_days(daily):
    today = datetime.now(TIMEZONE).date()
    result = []
    for item in daily:
        try:
            date = datetime.fromisoformat(item.get("date", "")).date()
        except ValueError:
            date = today
        if date >= today:
            result.append(item)
    return result


def virtual_screen_bounds(root=None):
    if os.name == "nt":
        try:
            user32 = ctypes.windll.user32
            left = user32.GetSystemMetrics(76)
            top = user32.GetSystemMetrics(77)
            width = user32.GetSystemMetrics(78)
            height = user32.GetSystemMetrics(79)
            if width and height:
                return left, top, left + width, top + height
        except Exception:
            pass
    if root is not None:
        return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()
    return 0, 0, 1920, 1080


def set_dpi_awareness():
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def rounded_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
    radius = min(radius, (x2 - x1) / 2, (y2 - y1) / 2)
    points = [
        x1 + radius,
        y1,
        x2 - radius,
        y1,
        x2,
        y1,
        x2,
        y1 + radius,
        x2,
        y2 - radius,
        x2,
        y2,
        x2 - radius,
        y2,
        x1 + radius,
        y2,
        x1,
        y2,
        x1,
        y2 - radius,
        x1,
        y1 + radius,
        x1,
        y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


def draw_cloud(canvas, cx, cy, size, tag):
    fill = "#e5f0ff"
    outline = "#c8d9f2"
    canvas.create_oval(cx - size * 0.48, cy - size * 0.03, cx - size * 0.08, cy + size * 0.34, fill=fill, outline=outline, width=1, tags=tag)
    canvas.create_oval(cx - size * 0.22, cy - size * 0.28, cx + size * 0.24, cy + size * 0.26, fill=fill, outline=outline, width=1, tags=tag)
    canvas.create_oval(cx + size * 0.06, cy - size * 0.08, cx + size * 0.52, cy + size * 0.34, fill=fill, outline=outline, width=1, tags=tag)
    rounded_rect(canvas, cx - size * 0.52, cy + size * 0.08, cx + size * 0.52, cy + size * 0.38, size * 0.12, fill=fill, outline=outline, width=1, tags=tag)


def draw_sun(canvas, cx, cy, size, tag):
    ray = size * 0.44
    inner = size * 0.24
    for dx, dy in ((0, -1), (0.7, -0.7), (1, 0), (0.7, 0.7), (0, 1), (-0.7, 0.7), (-1, 0), (-0.7, -0.7)):
        canvas.create_line(cx + dx * inner, cy + dy * inner, cx + dx * ray, cy + dy * ray, fill="#facc15", width=max(1, int(size * 0.06)), capstyle="round", tags=tag)
    canvas.create_oval(cx - size * 0.25, cy - size * 0.25, cx + size * 0.25, cy + size * 0.25, fill="#fde047", outline="#f59e0b", width=1, tags=tag)


def draw_weather_icon(canvas, kind, cx, cy, size, tag="weather-icon"):
    kind = kind or "cloud"
    if kind == "sun":
        draw_sun(canvas, cx, cy, size, tag)
    elif kind == "partly":
        draw_sun(canvas, cx - size * 0.18, cy - size * 0.13, size * 0.78, tag)
        draw_cloud(canvas, cx + size * 0.08, cy + size * 0.06, size * 0.88, tag)
    elif kind == "rain":
        draw_cloud(canvas, cx, cy - size * 0.08, size, tag)
        for dx in (-0.24, 0, 0.24):
            canvas.create_line(cx + size * dx, cy + size * 0.42, cx + size * (dx - 0.08), cy + size * 0.66, fill="#38bdf8", width=max(1, int(size * 0.06)), capstyle="round", tags=tag)
    elif kind == "storm":
        draw_cloud(canvas, cx, cy - size * 0.08, size, tag)
        points = [cx - size * 0.03, cy + size * 0.25, cx + size * 0.14, cy + size * 0.25, cx + size * 0.02, cy + size * 0.58, cx + size * 0.22, cy + size * 0.58, cx - size * 0.08, cy + size * 0.93]
        canvas.create_polygon(points, fill="#facc15", outline="#f59e0b", tags=tag)
    elif kind == "snow":
        draw_cloud(canvas, cx, cy - size * 0.08, size, tag)
        for dx in (-0.22, 0.18):
            x = cx + size * dx
            y = cy + size * 0.55
            r = size * 0.11
            canvas.create_line(x - r, y, x + r, y, fill="#bae6fd", width=1, tags=tag)
            canvas.create_line(x, y - r, x, y + r, fill="#bae6fd", width=1, tags=tag)
            canvas.create_line(x - r * 0.7, y - r * 0.7, x + r * 0.7, y + r * 0.7, fill="#bae6fd", width=1, tags=tag)
            canvas.create_line(x - r * 0.7, y + r * 0.7, x + r * 0.7, y - r * 0.7, fill="#bae6fd", width=1, tags=tag)
    elif kind == "fog":
        draw_cloud(canvas, cx, cy - size * 0.1, size, tag)
        for i in range(3):
            y = cy + size * (0.38 + i * 0.15)
            canvas.create_line(cx - size * 0.42, y, cx + size * 0.42, y, fill="#cbd5e1", width=max(1, int(size * 0.045)), capstyle="round", tags=tag)
    else:
        draw_cloud(canvas, cx, cy, size, tag)


class WeatherWidget:
    def __init__(self, root):
        self.root = root
        self.topmost = True
        self.compact = False
        self.drag_offset_x = 0
        self.drag_offset_y = 0
        self.refreshing = False
        self.error_count = 0
        self.bound_widgets = []

        self.city_var = tk.StringVar(value="深圳")
        self.subtitle_var = tk.StringVar(value="Shenzhen · 实时天气")
        self.status_var = tk.StringVar(value="正在获取天气…")
        self.icon_kind = "partly"
        self.temp_var = tk.StringVar(value="--°")
        self.condition_var = tk.StringVar(value="加载中")
        self.feels_var = tk.StringVar(value="体感 --°")
        self.humidity_var = tk.StringVar(value="湿度 --%")
        self.wind_var = tk.StringVar(value="风速 -- km/h")
        self.footer_var = tk.StringVar(value="MET Norway · CC BY 4.0")
        self.forecast_vars = [tk.StringVar(value="--\n--\n--/--°") for _ in range(5)]

        self._configure_window()
        self._build_ui()
        self._bind_events()

        ensure_user_agent_interactive(self.root)
        cached, saved_at = load_cache()
        if cached:
            self._apply_payload(cached, cached=True, saved_at=saved_at)
        self.refresh()
        self._schedule_refresh()

    def _configure_window(self):
        self.root.title("深圳天气")
        self.root.geometry(self._normalized_geometry(load_geometry(), FULL_SIZE))
        self.root.minsize(*COMPACT_SIZE)
        self.root.overrideredirect(True)
        self.root.configure(bg=WINDOW_TRANSPARENT)
        self.root.attributes("-topmost", self.topmost)
        self.root.attributes("-alpha", 0.98)
        if os.name == "nt":
            try:
                self.root.attributes("-transparentcolor", WINDOW_TRANSPARENT)
            except tk.TclError:
                pass
        self._set_windows_app_id()
        self._set_window_icon()

    def _set_windows_app_id(self):
        if os.name != "nt":
            return
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ShenzhenWeatherWidget.Desktop.1")
        except Exception:
            pass

    def _set_window_icon(self):
        if ICON_FILE.exists():
            try:
                self.root.iconbitmap(str(ICON_FILE))
            except tk.TclError:
                pass

    def _normalized_geometry(self, geometry, size):
        width, height = size
        position = split_position(geometry)
        try:
            x_text, y_text = position[1:].split("+")
            x = int(x_text)
            y = int(y_text)
        except ValueError:
            x, y = 80, 80
        left, top, right, bottom = virtual_screen_bounds(self.root)
        x = min(max(x, left), max(right - width, left))
        y = min(max(y, top), max(bottom - height, top))
        return f"{width}x{height}+{x}+{y}"

    def _build_ui(self):
        self.canvas = tk.Canvas(self.root, bg=WINDOW_TRANSPARENT, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.bound_widgets.append(self.canvas)
        self._draw_background(*FULL_SIZE)

        self._label(self.city_var, 26, 21, 18, "bold", TEXT)
        self._label(self.subtitle_var, 27, 50, 9, "normal", MUTED)
        self.status_label = self._label(self.status_var, 26, 318, 8, "normal", SUBTLE, bg="#111b2d", width=210)
        self.footer_label = self._label(self.footer_var, 434, 318, 8, "normal", SUBTLE, anchor="ne", bg="#111b2d", width=176)

        self.refresh_button = self._text_button("↻", 348, 22, ACCENT, lambda: self.refresh(force=True))
        self.pin_button = self._text_button("置顶", 378, 23, ACCENT_2, self._toggle_topmost, size=9, family="Microsoft YaHei UI")
        self.close_button = self._text_button("×", 433, 19, DANGER, self.close, size=15)

        draw_weather_icon(self.canvas, self.icon_kind, 70, 118, 62)
        self._label(self.temp_var, 120, 78, 48, "bold", TEXT, family="Segoe UI", bg=CARD_2)
        self._label(self.condition_var, 128, 137, 13, "bold", ACCENT, bg=CARD_2)

        self._metric(self.feels_var, 28, 168, 120)
        self._metric(self.humidity_var, 170, 168, 120)
        self._metric(self.wind_var, 312, 168, 120)

        self.forecast_positions = []
        self.forecast_labels = []
        for i, var in enumerate(self.forecast_vars):
            x = 31 + i * 84
            self.forecast_positions.append(x)
            label = self._label(var, x, 228, 8, "normal", TEXT, anchor="nw", justify="center", bg="#121c2f", width=78)
            self.forecast_labels.append(label)

    def _draw_background(self, width, height):
        self.canvas.delete("shape")
        rounded_rect(self.canvas, 10, 10, width - 10, height - 10, 28, fill=CARD, outline="#2f456b", width=1, tags="shape")
        self.canvas.create_polygon(18, 260, width - 18, 226, width - 18, height - 18, 18, height - 18, fill="#111b2d", outline="", tags="shape")
        rounded_rect(self.canvas, 20, 72, width - 20, 158, 24, fill=CARD_2, outline="", tags="shape")
        rounded_rect(self.canvas, 28, 166, 148, 196, 14, fill=CARD_3, outline="", tags="shape")
        rounded_rect(self.canvas, 170, 166, 290, 196, 14, fill=CARD_3, outline="", tags="shape")
        rounded_rect(self.canvas, 312, 166, 432, 196, 14, fill=CARD_3, outline="", tags="shape")
        if not self.compact:
            for i in range(5):
                x1 = 23 + i * 84
                rounded_rect(self.canvas, x1, 214, x1 + 78, 302, 16, fill="#121c2f", outline="#263a5d", width=1, tags="shape")
        self.canvas.create_oval(width - 136, -76, width + 44, 96, fill="#1e40af", outline="", tags="shape")
        self.canvas.create_oval(-62, height - 94, 80, height + 58, fill="#0e7490", outline="", tags="shape")
        self.canvas.tag_lower("shape")

    def _label(self, variable, x, y, size, weight, color, family="Microsoft YaHei UI", anchor="nw", justify="left", bg=CARD, width=None):
        label = tk.Label(
            self.canvas,
            textvariable=variable,
            bg=bg,
            fg=color,
            font=(family, size, weight),
            justify=justify,
            bd=0,
            highlightthickness=0,
        )
        if width:
            label.place(x=x, y=y, anchor=anchor, width=width)
        else:
            label.place(x=x, y=y, anchor=anchor)
        self.bound_widgets.append(label)
        return label

    def _metric(self, variable, x, y, width):
        label = tk.Label(
            self.canvas,
            textvariable=variable,
            bg=CARD_3,
            fg=TEXT,
            font=("Microsoft YaHei UI", 8, "bold"),
            bd=0,
            anchor="center",
        )
        label.place(x=x, y=y + 6, width=width)
        self.bound_widgets.append(label)
        return label

    def _text_button(self, text, x, y, color, command, size=14, family="Segoe UI"):
        label = tk.Label(
            self.canvas,
            text=text,
            bg=CARD,
            fg=color,
            cursor="hand2",
            font=(family, size, "bold"),
            bd=0,
        )
        label.place(x=x, y=y)
        label.bind("<Button-1>", lambda _event: command())
        label.bind("<Button-3>", self._show_menu)
        return label

    def _bind_events(self):
        for widget in self.bound_widgets:
            widget.bind("<ButtonPress-1>", self._start_drag, add="+")
            widget.bind("<B1-Motion>", self._drag, add="+")
            widget.bind("<ButtonRelease-1>", self._save_current_geometry, add="+")
            widget.bind("<Button-3>", self._show_menu, add="+")
            widget.bind("<Double-Button-1>", self._toggle_compact, add="+")
        self.root.bind("<Escape>", lambda _event: self.close())
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _start_drag(self, event):
        self.drag_offset_x = event.x_root - self.root.winfo_x()
        self.drag_offset_y = event.y_root - self.root.winfo_y()

    def _drag(self, event):
        x = event.x_root - self.drag_offset_x
        y = event.y_root - self.drag_offset_y
        self.root.geometry(f"+{x}+{y}")

    def _save_current_geometry(self, _event=None):
        save_geometry(self.root.geometry())

    def _show_menu(self, event):
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="立即刷新", command=lambda: self.refresh(force=True))
        menu.add_command(label="取消置顶" if self.topmost else "保持置顶", command=self._toggle_topmost)
        menu.add_command(label="紧凑模式" if not self.compact else "完整模式", command=self._toggle_compact)
        menu.add_command(label="数据来源与许可", command=self._show_about)
        menu.add_separator()
        menu.add_command(label="退出", command=self.close)
        menu.tk_popup(event.x_root, event.y_root)

    def _toggle_topmost(self):
        self.topmost = not self.topmost
        self.root.attributes("-topmost", self.topmost)
        self.pin_button.configure(fg=ACCENT_2 if self.topmost else SUBTLE, text="置顶" if self.topmost else "普通")

    def _show_about(self):
        messagebox.showinfo(
            "数据来源与许可",
            "天气数据：MET Norway Locationforecast API\n"
            "许可协议：CC BY 4.0\n\n"
            "代码许可：MIT License\n"
            "商用分发时请保留数据归属，不要暗示 MET Norway、Yr 或 NRK 认可你的产品。",
        )

    def _toggle_compact(self, _event=None):
        self.compact = not self.compact
        size = COMPACT_SIZE if self.compact else FULL_SIZE
        self.root.geometry(self._normalized_geometry(self.root.geometry(), size))
        width, height = size
        self.canvas.configure(width=width, height=height)
        self._draw_background(width, height)
        for x, label in zip(self.forecast_positions, self.forecast_labels):
            if self.compact:
                label.place_forget()
            else:
                label.place(x=x, y=228, width=78)
        if self.compact:
            self.status_label.place(x=26, y=216, width=260)
            self.footer_label.place_forget()
        else:
            self.status_label.place(x=26, y=318, width=210)
            self.footer_label.place(x=434, y=318, anchor="ne", width=176)
        self._save_current_geometry()

    def refresh(self, force=False):
        if self.refreshing and not force:
            return
        self.refreshing = True
        self.status_var.set("正在刷新…")
        thread = threading.Thread(target=self._fetch_in_background, daemon=True)
        thread.start()

    def _fetch_in_background(self):
        try:
            payload = fetch_weather()
        except (OSError, urllib.error.URLError, TimeoutError, ValueError, subprocess.SubprocessError) as exc:
            self.root.after(0, self._apply_error, str(exc))
            return
        self.root.after(0, self._apply_success, payload)

    def _apply_success(self, payload):
        self.refreshing = False
        self.error_count = 0
        if payload.get("from_cache"):
            cached, saved_at = load_cache()
            self._apply_payload(cached or payload, cached=True, saved_at=saved_at)
            return
        save_cache(payload)
        self._apply_payload(payload)

    def _apply_error(self, message):
        self.refreshing = False
        cached, saved_at = load_cache()
        if cached:
            self._apply_payload(cached, cached=True, saved_at=saved_at, error=message)
        else:
            self.status_var.set("离线 · 无法获取数据，点击 ↻ 重试")
            self.condition_var.set("获取失败")
            self.feels_var.set("检查网络")
            self.humidity_var.set("或代理")
            self.wind_var.set("稍后重试")
            self.footer_var.set("MET Norway 暂不可用")
        delay = ERROR_BACKOFF_STEPS_MS[min(self.error_count, len(ERROR_BACKOFF_STEPS_MS) - 1)]
        self.error_count += 1
        self.root.after(delay, self.refresh)

    def _apply_payload(self, payload, cached=False, saved_at=0, error=None):
        current = payload.get("current", {})
        daily = filter_current_days(payload.get("daily", []))
        symbol = current.get("symbol_code", "cloudy")
        icon_kind, condition = symbol_icon(symbol)
        temperature = current.get("temperature_2m")
        apparent = current.get("apparent_temperature")
        humidity = current.get("relative_humidity_2m")
        wind = current.get("wind_speed_10m")

        self.icon_kind = icon_kind
        self.canvas.delete("weather-icon")
        draw_weather_icon(self.canvas, self.icon_kind, 70, 118, 62)
        self.temp_var.set(self._fmt_degree(temperature))
        self.condition_var.set(condition)
        self.feels_var.set(f"体感 {self._fmt_degree(apparent)}")
        self.humidity_var.set(f"湿度 {self._fmt_value(humidity, '%')}")
        self.wind_var.set(f"风速 {self._fmt_value(wind, ' km/h')}")

        for i, var in enumerate(self.forecast_vars):
            if i < len(daily):
                item = daily[i]
                _kind, day_condition = symbol_icon(item.get("symbol_code"))
                high = self._fmt_number(item.get("temperature_2m_max"))
                low = self._fmt_number(item.get("temperature_2m_min"))
                rain = self._fmt_number(item.get("precipitation_amount"))
                var.set(f"{day_label(item.get('date', ''), i)} {short_condition(day_condition)}\n{low}-{high}°\n{rain}mm")
            else:
                var.set("--\n--\n--/--°")

        now_text = datetime.now().strftime("%H:%M")
        if cached:
            age = format_age(saved_at)
            self.status_var.set(f"缓存 · {age}" + (" · 离线" if error else ""))
            self.footer_var.set("MET Norway · CC BY 4.0 · 缓存")
        else:
            self.status_var.set(f"已更新 {now_text}")
            self.footer_var.set("MET Norway · CC BY 4.0")

    def _schedule_refresh(self):
        self.root.after(REFRESH_MS, self._scheduled_refresh)

    def _scheduled_refresh(self):
        self.refresh()
        self._schedule_refresh()

    def close(self):
        self._save_current_geometry()
        self.root.destroy()

    @staticmethod
    def _fmt_number(value):
        try:
            return str(round(float(value)))
        except (TypeError, ValueError):
            return "--"

    def _fmt_degree(self, value):
        return self._fmt_number(value) + "°"

    def _fmt_value(self, value, suffix):
        return self._fmt_number(value) + suffix


def main():
    if sys.version_info < MIN_PYTHON:
        raise SystemExit("Shenzhen Weather Widget requires Python 3.10 or newer.")
    set_dpi_awareness()
    root = tk.Tk()
    try:
        default_font = tkfont.nametofont("TkDefaultFont")
        default_font.configure(family="Microsoft YaHei UI", size=9)
    except tk.TclError:
        pass
    WeatherWidget(root)
    root.mainloop()


if __name__ == "__main__":
    main()
