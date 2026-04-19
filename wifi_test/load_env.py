import os

env = None
import_fn = globals().get("Import")
if callable(import_fn):
    import_fn("env")
    env = globals().get("env")


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


if env is not None:
    project_dir = env["PROJECT_DIR"]
    dotenv_path = os.path.join(project_dir, "src", ".env")
    dotenv = load_dotenv(dotenv_path)

    define_map = {
        "WIFI_SSID": dotenv.get("WIFI_SSID", "PAL3.0"),
        "WIFI_USERNAME": dotenv.get("WIFI_USERNAME", "jain925"),
        "WIFI_PASSWORD": dotenv.get("WIFI_PASSWORD", "YOUR_PASSWORD"),
    }

    for key, value in define_map.items():
        env.Append(CPPDEFINES=[(key, to_cpp_string_literal(value))])
