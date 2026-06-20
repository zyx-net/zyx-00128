import os
import yaml
from typing import Dict, List, Any, Optional


class ConfigManager:
    _instance = None
    _config = None
    _config_path = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._config is None:
            self._load_config()

    def _load_config(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_dir = os.path.join(base_dir, 'config')
        config_file = os.path.join(config_dir, 'config.yaml')

        if not os.path.exists(config_file):
            raise FileNotFoundError(f"Config file not found: {config_file}")

        self._config_path = config_file
        with open(config_file, 'r', encoding='utf-8') as f:
            self._config = yaml.safe_load(f)

    def reload(self):
        self._config = None
        self._load_config()

    @property
    def temp_zones(self) -> List[Dict[str, Any]]:
        return self._config.get('temp_zones', [])

    @property
    def temp_zone_map(self) -> Dict[str, Dict[str, Any]]:
        return {tz['code']: tz for tz in self.temp_zones}

    def get_temp_zone(self, code: str) -> Optional[Dict[str, Any]]:
        return self.temp_zone_map.get(code)

    def is_valid_temp_zone(self, code: str) -> bool:
        return code in self.temp_zone_map

    @property
    def roles(self) -> List[Dict[str, Any]]:
        return self._config.get('roles', [])

    @property
    def role_map(self) -> Dict[str, Dict[str, Any]]:
        return {r['code']: r for r in self.roles}

    def get_role(self, code: str) -> Optional[Dict[str, Any]]:
        return self.role_map.get(code)

    def has_permission(self, role_code: str, permission: str) -> bool:
        role = self.get_role(role_code)
        if not role:
            return False
        return permission in role.get('permissions', [])

    @property
    def status_flow(self) -> Dict[str, Dict[str, Any]]:
        return self._config.get('status_flow', {})

    def get_status_label(self, status: str) -> str:
        return self.status_flow.get(status, {}).get('label', status)

    def can_transition(self, from_status: str, to_status: str) -> bool:
        flow = self.status_flow.get(from_status, {})
        return to_status in flow.get('allowed_next', [])

    def is_action_allowed(self, status: str, action: str) -> bool:
        flow = self.status_flow.get(status, {})
        return action in flow.get('allowed_actions', [])

    @property
    def locations(self) -> List[Dict[str, Any]]:
        return self._config.get('locations', [])

    @property
    def location_map(self) -> Dict[str, Dict[str, Any]]:
        return {loc['code']: loc for loc in self.locations}

    def get_location_config(self, code: str) -> Optional[Dict[str, Any]]:
        return self.location_map.get(code)
