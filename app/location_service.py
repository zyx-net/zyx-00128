from typing import List, Optional
from .models import db, Location
from .config import ConfigManager
from .sample_service import SampleServiceError


class LocationService:
    def __init__(self):
        self.config = ConfigManager()

    def initialize_locations_from_config(self):
        for loc_config in self.config.locations:
            existing = Location.query.filter_by(code=loc_config['code']).first()
            if not existing:
                location = Location(
                    code=loc_config['code'],
                    name=loc_config['name'],
                    temp_zone=loc_config['temp_zone'],
                    capacity=loc_config.get('capacity', 100),
                    description=loc_config.get('description', '')
                )
                db.session.add(location)
        db.session.commit()

    def get_location(self, location_id: int) -> Optional[Location]:
        return Location.query.filter_by(id=location_id, is_active=True).first()

    def get_location_by_code(self, code: str) -> Optional[Location]:
        return Location.query.filter_by(code=code, is_active=True).first()

    def list_locations(
        self,
        temp_zone: Optional[str] = None,
        include_inactive: bool = False
    ) -> List[Location]:
        query = Location.query
        if not include_inactive:
            query = query.filter_by(is_active=True)
        if temp_zone:
            query = query.filter_by(temp_zone=temp_zone)
        return query.order_by(Location.id).all()

    def create_location(
        self,
        code: str,
        name: str,
        temp_zone: str,
        capacity: int = 100,
        description: Optional[str] = None,
        operator_role: str = 'ADMIN'
    ) -> Location:
        if not self.config.has_permission(operator_role, "location.manage"):
            raise SampleServiceError(
                f"角色 '{operator_role}' 没有权限管理库位",
                "PERMISSION_DENIED"
            )

        if not self.config.is_valid_temp_zone(temp_zone):
            raise SampleServiceError(
                f"无效的温区代码: {temp_zone}",
                "INVALID_TEMP_ZONE"
            )

        existing = Location.query.filter_by(code=code).first()
        if existing:
            raise SampleServiceError(f"库位编号已存在: {code}", "LOCATION_EXISTS")

        location = Location(
            code=code,
            name=name,
            temp_zone=temp_zone,
            capacity=capacity,
            description=description
        )
        db.session.add(location)
        db.session.commit()
        return location
