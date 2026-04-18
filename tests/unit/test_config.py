from pathlib import Path

from trading.runtime.config import AppSettings, load_yaml_config


def test_app_settings_defaults_to_local_config_dir():
    settings = AppSettings()

    assert settings.app_name == "crypto-ai-trader"
    assert settings.app_env == "local"
    assert settings.config_dir == Path("config")


def test_load_yaml_config_reads_mapping(tmp_path):
    config_file = tmp_path / "sample.yaml"
    config_file.write_text("trade_mode: paper_auto\nsymbols:\n  - BTCUSDT\n", encoding="utf-8")

    loaded = load_yaml_config(config_file)

    assert loaded == {"trade_mode": "paper_auto", "symbols": ["BTCUSDT"]}
