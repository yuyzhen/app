import os
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WIDGET = ROOT / "weather_widget.py"
REQUIRED_FILES = [
    ROOT / "run.bat",
    ROOT / "README.md",
    ROOT / "LICENSE",
    ROOT / "THIRD_PARTY_NOTICES.md",
]

BASE_DATE = datetime.now(timezone.utc).date()

SAMPLE_MET = {
    "properties": {
        "timeseries": [
            {
                "time": f"{BASE_DATE.isoformat()}T00:00:00Z",
                "data": {
                    "instant": {"details": {"air_temperature": 29.4, "relative_humidity": 72, "wind_speed": 6.0}},
                    "next_1_hours": {"summary": {"symbol_code": "cloudy"}, "details": {"precipitation_amount": 0.0}},
                },
            },
            {
                "time": f"{BASE_DATE.isoformat()}T06:00:00Z",
                "data": {
                    "instant": {"details": {"air_temperature": 31.2, "relative_humidity": 68, "wind_speed": 5.0}},
                    "next_1_hours": {"summary": {"symbol_code": "partlycloudy_day"}, "details": {"precipitation_amount": 0.2}},
                },
            },
            {
                "time": f"{(BASE_DATE + timedelta(days=1)).isoformat()}T06:00:00Z",
                "data": {
                    "instant": {"details": {"air_temperature": 30.0, "relative_humidity": 70, "wind_speed": 4.0}},
                    "next_6_hours": {"summary": {"symbol_code": "rain"}, "details": {"precipitation_amount": 4.5}},
                },
            },
            {
                "time": f"{(BASE_DATE + timedelta(days=2)).isoformat()}T06:00:00Z",
                "data": {
                    "instant": {"details": {"air_temperature": 28.0, "relative_humidity": 80, "wind_speed": 7.0}},
                    "next_6_hours": {"summary": {"symbol_code": "lightrain"}, "details": {"precipitation_amount": 2.0}},
                },
            },
            {
                "time": f"{(BASE_DATE + timedelta(days=3)).isoformat()}T06:00:00Z",
                "data": {
                    "instant": {"details": {"air_temperature": 32.0, "relative_humidity": 60, "wind_speed": 3.0}},
                    "next_6_hours": {"summary": {"symbol_code": "fair_day"}, "details": {"precipitation_amount": 0.0}},
                },
            },
            {
                "time": f"{(BASE_DATE + timedelta(days=4)).isoformat()}T06:00:00Z",
                "data": {
                    "instant": {"details": {"air_temperature": 33.0, "relative_humidity": 55, "wind_speed": 4.0}},
                    "next_6_hours": {"summary": {"symbol_code": "clearsky_day"}, "details": {"precipitation_amount": 0.0}},
                },
            },
        ]
    }
}


def load_widget_module():
    spec = importlib.util.spec_from_file_location("weather_widget", WIDGET)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    missing = [path.name for path in REQUIRED_FILES if not path.exists()]
    if missing:
        raise SystemExit(f"Missing required files: {', '.join(missing)}")

    module = load_widget_module()
    data = module.normalize_met_payload(SAMPLE_MET)
    assert data["schema"] == 2
    assert data["source"] == "MET Norway Locationforecast"
    assert data["license"] == "CC BY 4.0"
    assert data["current"]["temperature_2m"] == 29.4
    assert len(data["daily"]) == 5
    assert module.is_valid_user_agent("ExampleWeather/1.0 github.com/example/weather")
    assert not module.is_valid_user_agent("ExampleWeather/1.0")

    if os.environ.get("WEATHER_WIDGET_VERIFY_LIVE"):
        module.save_user_agent(os.environ.get("WEATHER_WIDGET_USER_AGENT", "VerifyWidget/1.0 github.com/example/weather"))
        live = module.fetch_weather()
        assert live["schema"] == 2
        assert live["current"]["temperature_2m"] is not None

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "MET Norway" in readme
    assert "CC BY 4.0" in notices
    assert "MIT License" in license_text

    print("OK: widget normalization, docs, licenses, and commercial distribution guardrails verified.")


if __name__ == "__main__":
    main()
