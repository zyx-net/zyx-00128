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

    @property
    def import_strategy(self) -> Dict[str, Any]:
        return self._config.get('import_strategy', {})

    def get_default_import_strategy(self) -> str:
        return self.import_strategy.get('default_strategy', 'FAIL_ON_DUPLICATE')

    def is_valid_import_strategy(self, strategy: str) -> bool:
        return strategy in self.import_strategy.get('allowed_strategies', [])

    def get_default_import_mode(self) -> str:
        return self.import_strategy.get('default_mode', 'REGISTER')

    def is_valid_import_mode(self, mode: str) -> bool:
        return mode in self.import_strategy.get('allowed_modes', [])

    def get_batch_code_prefix(self) -> str:
        return self.import_strategy.get('batch_code_prefix', 'IMP')

    def get_import_undo_window(self) -> int:
        return self.import_strategy.get('undo_window_minutes', 30)

    def get_max_batch_size(self) -> int:
        return self.import_strategy.get('max_batch_size', 1000)

    def is_import_idempotent(self) -> bool:
        return self.import_strategy.get('idempotent_by_batch_code', True)

    def require_version_on_update(self) -> bool:
        return self.import_strategy.get('require_version_on_update', True)

    @property
    def undo_policy(self) -> Dict[str, Any]:
        return self._config.get('undo_policy', {})

    def is_action_undoable(self, action: str) -> bool:
        undoable = self.undo_policy.get('undoable_actions', [])
        non_undoable = self.undo_policy.get('non_undoable_actions', [])
        if action in non_undoable:
            return False
        return action in undoable

    def require_same_operator_for_undo(self) -> bool:
        return self.undo_policy.get('require_same_operator', False)

    def get_undo_required_roles(self) -> List[str]:
        return self.undo_policy.get('require_roles', [])

    def has_undo_permission(self, role: str) -> bool:
        required = self.get_undo_required_roles()
        if not required:
            return True
        return role in required

    def get_undo_window_minutes(self) -> int:
        return self.undo_policy.get('undo_window_minutes', 30)

    def is_cascading_undo(self) -> bool:
        return self.undo_policy.get('cascading_undo', True)
