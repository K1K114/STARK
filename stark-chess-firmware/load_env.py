"""Pre-build: inject WiFi + STARK server + LED strip settings from p4_vision/.env (esp32-p4-vision only)."""
import os

env = None
import_fn = globals().get("Import")
if callable(import_fn):
    import_fn("env")
    env = globals().get("env")

if env is None:
    raise SystemExit(0)


def load_dotenv(path):
    values = {}
    if not os.path.exists(path):
        return values

    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            values[key] = value

    return values


def to_cpp_string_literal(value):
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return '\\"' + escaped + '\\"'


pioenv = env.get("PIOENV", "")
if pioenv != "esp32-p4-vision":
    raise SystemExit(0)

project_dir = env["PROJECT_DIR"]
dotenv_path = os.path.join(project_dir, "p4_vision", ".env")
dotenv = load_dotenv(dotenv_path)

ssid = dotenv.get("WIFI_SSID", "PAL3.0")
user = dotenv.get("WIFI_USERNAME", dotenv.get("WIFI_USER", "user"))
password = dotenv.get("WIFI_PASSWORD", "password")
host = dotenv.get("STARK_SERVER_HOST", "192.168.1.100")
port_str = dotenv.get("STARK_SERVER_PORT", "8000")
led_pin = dotenv.get("LED_DATA_PIN", "39")
neo_count = dotenv.get("NEOPIXEL_COUNT", "48")

try:
    port = int(port_str)
except ValueError:
    port = 8000

try:
    led_pin_i = int(led_pin)
except ValueError:
    led_pin_i = 39

try:
    neo_count_i = int(neo_count)
except ValueError:
    neo_count_i = 48

env.Append(
    CPPDEFINES=[
        ("WIFI_SSID", to_cpp_string_literal(ssid)),
        ("WIFI_USERNAME", to_cpp_string_literal(user)),
        ("WIFI_PASSWORD", to_cpp_string_literal(password)),
        ("STARK_SERVER_HOST", to_cpp_string_literal(host)),
        ("STARK_SERVER_PORT", port),
        ("LED_DATA_PIN", led_pin_i),
        ("NEOPIXEL_COUNT", neo_count_i),
    ]
)
