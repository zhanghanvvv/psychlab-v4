"""配置管理器，负责读写 JSON 配置文件。"""

import json
from pathlib import Path
from typing import Any


class ConfigManager:
    """应用配置管理，加载/保存 JSON 配置。"""

    _instance = None
    _config: dict = {}

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config_path: str = "config/app_settings.json"):
        if not self._config:
            self._config_path = Path(config_path)
            self.load()

    def load(self) -> dict:
        """从文件加载配置。"""
        if self._config_path.exists():
            with open(self._config_path, "r", encoding="utf-8") as f:
                self._config = json.load(f)
        else:
            self._config = {}
        return self._config

    def save(self) -> None:
        """保存配置到文件。"""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=4, ensure_ascii=False)

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项，支持点号分隔的路径（如 'sensor_defaults.ECG.filter_low'）。"""
        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def set(self, key: str, value: Any) -> None:
        """设置配置项，支持点号分隔路径。"""
        keys = key.split(".")
        config = self._config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value

    @property
    def config(self) -> dict:
        """返回完整配置字典。"""
        return self._config
