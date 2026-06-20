from datetime import datetime
from typing import Optional, Tuple, List

from .models import db, Sample, Location, AuditLog
from .config import ConfigManager


class SampleServiceError(Exception):
    def __init__(self, message: str, code: str = "SERVICE_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class SampleService:
    def __init__(self):
        self.config = ConfigManager()

    def _check_permission(self, role: str, permission: str, action: str):
        if not self.config.has_permission(role, permission):
            raise SampleServiceError(
                f"角色 '{role}' 没有权限执行 '{action}' 操作",
                "PERMISSION_DENIED"
            )

    def _check_version(self, sample: Sample, expected_version: int):
        if sample.version != expected_version:
            raise SampleServiceError(
                f"版本冲突：当前版本为 {sample.version}，您提供的版本为 {expected_version}，请刷新后重试",
                "VERSION_CONFLICT"
            )

    def _increment_version(self, sample: Sample) -> int:
        sample.version += 1
        return sample.version

    def _create_audit_log(
        self,
        sample: Sample,
        action: str,
        operator: str,
        operator_role: str,
        reason: Optional[str] = None,
        from_status: Optional[str] = None,
        to_status: Optional[str] = None,
        from_location_id: Optional[int] = None,
        to_location_id: Optional[int] = None,
        remark: Optional[str] = None,
        version: Optional[int] = None
    ) -> AuditLog:
        sequence = sample.audit_logs.count() + 1
        log_version = version if version is not None else sample.version

        log = AuditLog(
            sample_id=sample.id,
            sequence=sequence,
            action=action,
            from_status=from_status,
            to_status=to_status,
            from_location_id=from_location_id,
            to_location_id=to_location_id,
            operator=operator,
            operator_role=operator_role,
            reason=reason,
            version=log_version,
            remark=remark
        )
        db.session.add(log)
        return log

    def register_sample(
        self,
        sample_code: str,
        name: str,
        required_temp_zone: str,
        operator: str,
        operator_role: str,
        sample_type: Optional[str] = None,
        remark: Optional[str] = None
    ) -> Sample:
        self._check_permission(operator_role, "sample.register", "登记样本")

        if not self.config.is_valid_temp_zone(required_temp_zone):
            raise SampleServiceError(
                f"无效的温区代码: {required_temp_zone}，可选温区: {', '.join(self.config.temp_zone_map.keys())}",
                "INVALID_TEMP_ZONE"
            )

        existing = Sample.query.filter_by(sample_code=sample_code, is_deleted=False).first()
        if existing:
            raise SampleServiceError(
                f"样本编号已存在: {sample_code}",
                "SAMPLE_CODE_EXISTS"
            )

        sample = Sample(
            sample_code=sample_code,
            name=name,
            sample_type=sample_type,
            required_temp_zone=required_temp_zone,
            status='REGISTERED',
            created_by=operator,
            remark=remark,
            version=1
        )
        db.session.add(sample)
        db.session.flush()

        self._create_audit_log(
            sample=sample,
            action='REGISTER',
            operator=operator,
            operator_role=operator_role,
            to_status='REGISTERED',
            reason='样本登记',
            remark=remark,
            version=1
        )

        db.session.commit()
        return sample

    def store_in(
        self,
        sample_id: int,
        location_id: int,
        operator: str,
        operator_role: str,
        expected_version: int,
        reason: Optional[str] = None
    ) -> Sample:
        self._check_permission(operator_role, "sample.store_in", "入库")

        sample = Sample.query.filter_by(id=sample_id, is_deleted=False).first()
        if not sample:
            raise SampleServiceError(f"样本不存在: {sample_id}", "SAMPLE_NOT_FOUND")

        self._check_version(sample, expected_version)

        if not self.config.is_action_allowed(sample.status, "store_in"):
            raise SampleServiceError(
                f"当前状态 '{sample.status}' 不允许执行入库操作",
                "INVALID_STATUS_TRANSITION"
            )

        location = Location.query.filter_by(id=location_id, is_active=True).first()
        if not location:
            raise SampleServiceError(f"库位不存在或已停用: {location_id}", "LOCATION_NOT_FOUND")

        if location.temp_zone != sample.required_temp_zone:
            temp_zone_info = self.config.get_temp_zone(sample.required_temp_zone)
            location_temp_info = self.config.get_temp_zone(location.temp_zone)
            raise SampleServiceError(
                f"温区不匹配：样本需要 {temp_zone_info['name']}({temp_zone_info['temp_range']})，"
                f"但库位 '{location.name}' 属于 {location_temp_info['name']}({location_temp_info['temp_range']})。"
                f"请选择温区为 '{sample.required_temp_zone}' 的库位。",
                "TEMP_ZONE_MISMATCH"
            )

        current_samples = Sample.query.filter_by(location_id=location_id, is_deleted=False).count()
        if current_samples >= location.capacity:
            raise SampleServiceError(
                f"库位 '{location.name}' 容量已满 ({location.capacity})",
                "LOCATION_FULL"
            )

        from_status = sample.status
        from_location_id = sample.location_id

        sample.location_id = location_id
        sample.status = 'IN_STORAGE'
        new_version = self._increment_version(sample)

        self._create_audit_log(
            sample=sample,
            action='STORE_IN',
            operator=operator,
            operator_role=operator_role,
            from_status=from_status,
            to_status='IN_STORAGE',
            from_location_id=from_location_id,
            to_location_id=location_id,
            reason=reason or '样本入库',
            version=new_version
        )

        db.session.commit()
        return sample

    def transfer(
        self,
        sample_id: int,
        to_location_id: int,
        operator: str,
        operator_role: str,
        expected_version: int,
        reason: Optional[str] = None
    ) -> Sample:
        self._check_permission(operator_role, "sample.transfer", "转移")

        sample = Sample.query.filter_by(id=sample_id, is_deleted=False).first()
        if not sample:
            raise SampleServiceError(f"样本不存在: {sample_id}", "SAMPLE_NOT_FOUND")

        self._check_version(sample, expected_version)

        if not self.config.is_action_allowed(sample.status, "transfer"):
            raise SampleServiceError(
                f"当前状态 '{sample.status}' 不允许执行转移操作",
                "INVALID_STATUS_TRANSITION"
            )

        if sample.location_id == to_location_id:
            raise SampleServiceError(
                "目标库位与当前库位相同，无需转移",
                "SAME_LOCATION"
            )

        to_location = Location.query.filter_by(id=to_location_id, is_active=True).first()
        if not to_location:
            raise SampleServiceError(f"目标库位不存在或已停用: {to_location_id}", "LOCATION_NOT_FOUND")

        if to_location.temp_zone != sample.required_temp_zone:
            temp_zone_info = self.config.get_temp_zone(sample.required_temp_zone)
            location_temp_info = self.config.get_temp_zone(to_location.temp_zone)
            raise SampleServiceError(
                f"温区不匹配：样本需要 {temp_zone_info['name']}({temp_zone_info['temp_range']})，"
                f"但目标库位 '{to_location.name}' 属于 {location_temp_info['name']}({location_temp_info['temp_range']})。"
                f"请选择温区为 '{sample.required_temp_zone}' 的库位。",
                "TEMP_ZONE_MISMATCH"
            )

        current_samples = Sample.query.filter_by(location_id=to_location_id, is_deleted=False).count()
        if current_samples >= to_location.capacity:
            raise SampleServiceError(
                f"目标库位 '{to_location.name}' 容量已满 ({to_location.capacity})",
                "LOCATION_FULL"
            )

        from_location_id = sample.location_id
        new_version = self._increment_version(sample)
        sample.location_id = to_location_id

        self._create_audit_log(
            sample=sample,
            action='TRANSFER',
            operator=operator,
            operator_role=operator_role,
            from_status=sample.status,
            to_status=sample.status,
            from_location_id=from_location_id,
            to_location_id=to_location_id,
            reason=reason or '库位转移',
            version=new_version
        )

        db.session.commit()
        return sample

    def borrow(
        self,
        sample_id: int,
        operator: str,
        operator_role: str,
        expected_version: int,
        reason: Optional[str] = None,
        remark: Optional[str] = None
    ) -> Sample:
        self._check_permission(operator_role, "sample.borrow", "借出")

        sample = Sample.query.filter_by(id=sample_id, is_deleted=False).first()
        if not sample:
            raise SampleServiceError(f"样本不存在: {sample_id}", "SAMPLE_NOT_FOUND")

        self._check_version(sample, expected_version)

        if not self.config.is_action_allowed(sample.status, "borrow"):
            raise SampleServiceError(
                f"当前状态 '{sample.status}' 不允许执行借出操作",
                "INVALID_STATUS_TRANSITION"
            )

        from_status = sample.status
        from_location_id = sample.location_id
        new_version = self._increment_version(sample)

        sample.status = 'BORROWED'

        self._create_audit_log(
            sample=sample,
            action='BORROW',
            operator=operator,
            operator_role=operator_role,
            from_status=from_status,
            to_status='BORROWED',
            from_location_id=from_location_id,
            to_location_id=None,
            reason=reason or '样本借出',
            remark=remark,
            version=new_version
        )

        db.session.commit()
        return sample

    def return_sample(
        self,
        sample_id: int,
        location_id: int,
        operator: str,
        operator_role: str,
        expected_version: int,
        reason: Optional[str] = None,
        remark: Optional[str] = None
    ) -> Sample:
        self._check_permission(operator_role, "sample.return", "退回")

        sample = Sample.query.filter_by(id=sample_id, is_deleted=False).first()
        if not sample:
            raise SampleServiceError(f"样本不存在: {sample_id}", "SAMPLE_NOT_FOUND")

        self._check_version(sample, expected_version)

        if not self.config.is_action_allowed(sample.status, "return"):
            raise SampleServiceError(
                f"当前状态 '{sample.status}' 不允许执行退回操作",
                "INVALID_STATUS_TRANSITION"
            )

        location = Location.query.filter_by(id=location_id, is_active=True).first()
        if not location:
            raise SampleServiceError(f"库位不存在或已停用: {location_id}", "LOCATION_NOT_FOUND")

        if location.temp_zone != sample.required_temp_zone:
            temp_zone_info = self.config.get_temp_zone(sample.required_temp_zone)
            location_temp_info = self.config.get_temp_zone(location.temp_zone)
            raise SampleServiceError(
                f"温区不匹配：样本需要 {temp_zone_info['name']}({temp_zone_info['temp_range']})，"
                f"但库位 '{location.name}' 属于 {location_temp_info['name']}({location_temp_info['temp_range']})。"
                f"请选择温区为 '{sample.required_temp_zone}' 的库位。",
                "TEMP_ZONE_MISMATCH"
            )

        current_samples = Sample.query.filter_by(location_id=location_id, is_deleted=False).count()
        if current_samples >= location.capacity:
            raise SampleServiceError(
                f"库位 '{location.name}' 容量已满 ({location.capacity})",
                "LOCATION_FULL"
            )

        from_status = sample.status
        new_version = self._increment_version(sample)

        sample.status = 'IN_STORAGE'
        sample.location_id = location_id

        self._create_audit_log(
            sample=sample,
            action='RETURN',
            operator=operator,
            operator_role=operator_role,
            from_status=from_status,
            to_status='IN_STORAGE',
            from_location_id=None,
            to_location_id=location_id,
            reason=reason or '样本退回',
            remark=remark,
            version=new_version
        )

        db.session.commit()
        return sample

    def discard(
        self,
        sample_id: int,
        operator: str,
        operator_role: str,
        expected_version: int,
        reason: str,
        remark: Optional[str] = None
    ) -> Sample:
        self._check_permission(operator_role, "sample.discard", "废弃")

        sample = Sample.query.filter_by(id=sample_id, is_deleted=False).first()
        if not sample:
            raise SampleServiceError(f"样本不存在: {sample_id}", "SAMPLE_NOT_FOUND")

        self._check_version(sample, expected_version)

        if not self.config.is_action_allowed(sample.status, "discard"):
            raise SampleServiceError(
                f"当前状态 '{sample.status}' 不允许执行废弃操作",
                "INVALID_STATUS_TRANSITION"
            )

        if not reason:
            raise SampleServiceError("废弃必须填写原因", "REASON_REQUIRED")

        from_status = sample.status
        from_location_id = sample.location_id
        new_version = self._increment_version(sample)

        sample.status = 'DISCARDED'
        sample.is_deleted = True

        self._create_audit_log(
            sample=sample,
            action='DISCARD',
            operator=operator,
            operator_role=operator_role,
            from_status=from_status,
            to_status='DISCARDED',
            from_location_id=from_location_id,
            to_location_id=None,
            reason=reason,
            remark=remark,
            version=new_version
        )

        db.session.commit()
        return sample

    def get_sample(self, sample_id: int, include_deleted: bool = True) -> Optional[Sample]:
        if include_deleted:
            return Sample.query.filter_by(id=sample_id).first()
        return Sample.query.filter_by(id=sample_id, is_deleted=False).first()

    def get_sample_by_code(self, sample_code: str, include_deleted: bool = False) -> Optional[Sample]:
        if include_deleted:
            return Sample.query.filter_by(sample_code=sample_code).first()
        return Sample.query.filter_by(sample_code=sample_code, is_deleted=False).first()

    def list_samples(
        self,
        status: Optional[str] = None,
        temp_zone: Optional[str] = None,
        page: int = 1,
        per_page: int = 20
    ) -> Tuple[List[Sample], int]:
        query = Sample.query.filter_by(is_deleted=False)

        if status:
            query = query.filter_by(status=status)
        if temp_zone:
            query = query.filter_by(required_temp_zone=temp_zone)

        total = query.count()
        samples = query.order_by(Sample.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
        return samples, total

    def get_audit_logs(self, sample_id: int) -> List[AuditLog]:
        sample = Sample.query.filter_by(id=sample_id).first()
        if not sample:
            raise SampleServiceError(f"样本不存在: {sample_id}", "SAMPLE_NOT_FOUND")
        return sample.audit_logs.order_by(AuditLog.sequence).all()
