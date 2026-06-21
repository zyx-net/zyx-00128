import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from .models import db, Sample, Location, UndoRecord, AuditLog
from .sample_service import SampleService, SampleServiceError
from .config import ConfigManager


class UndoService:
    def __init__(self):
        self.config = ConfigManager()
        self.sample_service = SampleService()

    def _gen_undo_token(self) -> str:
        return "UNDO-" + uuid.uuid4().hex[:16].upper()

    def create_undo_record(
        self,
        sample: Sample,
        audit_log: AuditLog,
        original_action: str,
        operator: str,
        operator_role: str,
        from_status: Optional[str] = None,
        to_status: Optional[str] = None,
        from_location_id: Optional[int] = None,
        to_location_id: Optional[int] = None,
        allowed_roles: Optional[List[str]] = None
    ) -> Optional[UndoRecord]:
        if not self.config.is_action_undoable(original_action):
            return None

        undo_window = self.config.get_undo_window_minutes()
        expires_at = datetime.utcnow() + timedelta(minutes=undo_window)

        undo_token = self._gen_undo_token()

        if allowed_roles is None:
            allowed_roles = self.config.get_undo_required_roles()

        undo_record = UndoRecord(
            sample_id=sample.id,
            audit_log_id=audit_log.id,
            undo_token=undo_token,
            from_status=from_status,
            to_status=to_status,
            from_location_id=from_location_id,
            to_location_id=to_location_id,
            original_action=original_action,
            can_undo=True,
            undone=False,
            operator=operator,
            operator_role=operator_role,
            allowed_roles=','.join(allowed_roles) if allowed_roles else None,
            expires_at=expires_at
        )
        db.session.add(undo_record)
        return undo_record

    def invalidate_undo_records(self, sample_id: int):
        UndoRecord.query.filter(
            UndoRecord.sample_id == sample_id,
            UndoRecord.can_undo == True,
            UndoRecord.undone == False
        ).update({'can_undo': False}, synchronize_session=False)

    def list_available_undo(
        self,
        sample_id: Optional[int] = None,
        operator: Optional[str] = None,
        operator_role: Optional[str] = None,
        page: int = 1,
        per_page: int = 20
    ):
        now = datetime.utcnow()
        query = UndoRecord.query.filter(
            UndoRecord.can_undo == True,
            UndoRecord.undone == False,
            (UndoRecord.expires_at.is_(None)) | (UndoRecord.expires_at > now)
        )

        if sample_id:
            query = query.filter(UndoRecord.sample_id == sample_id)

        query = query.order_by(UndoRecord.id.desc())
        total = query.count()
        records = query.offset((page - 1) * per_page).limit(per_page).all()
        return records, total

    def get_undo_record(self, undo_token: str) -> Optional[UndoRecord]:
        return UndoRecord.query.filter_by(undo_token=undo_token).first()

    def _validate_undo(
        self,
        undo: UndoRecord,
        operator: str,
        operator_role: str,
        current_sample: Sample,
        skip_latest_check: bool = False
    ):
        sample = current_sample

        if undo.undone:
            raise SampleServiceError("该操作已被撤销，无法重复撤销", "ALREADY_UNDONE")
        if not undo.can_undo:
            raise SampleServiceError("该撤销链路已被新操作覆盖，无法撤销", "UNDO_INVALIDATED")
        if undo.expires_at and undo.expires_at < datetime.utcnow():
            raise SampleServiceError("撤销窗口已过期，无法撤销", "UNDO_EXPIRED")
        if sample.id != undo.sample_id:
            raise SampleServiceError("样本ID不匹配", "SAMPLE_MISMATCH")

        if not skip_latest_check:
            last_log = AuditLog.query.filter_by(sample_id=sample.id).order_by(AuditLog.sequence.desc()).first()
            if last_log and last_log.id != undo.audit_log_id:
                raise SampleServiceError(
                    f"样本状态已变更（当前最新操作: {last_log.action}），撤销链路已失效。"
                    f"请先撤销后续操作，或使用级联撤销。",
                    "UNDO_NOT_LATEST"
                )

        if self.config.require_same_operator_for_undo() and undo.operator != operator:
            raise SampleServiceError(
                f"只能由原操作人 '{undo.operator}' 撤销此操作",
                "OPERATOR_MISMATCH"
            )

        if not self.config.has_undo_permission(operator_role):
            required = self.config.get_undo_required_roles()
            raise SampleServiceError(
                f"角色 '{operator_role}' 没有撤销权限，需要角色: {', '.join(required)}",
                "PERMISSION_DENIED"
            )

        if undo.to_status and sample.status != undo.to_status:
            raise SampleServiceError(
                f"样本当前状态为 '{sample.status}'，撤销目标状态不匹配，"
                f"期望撤销前状态为 '{undo.to_status}'",
                "STATUS_MISMATCH"
            )

    def execute_undo(
        self,
        undo_token: str,
        operator: str,
        operator_role: str,
        reason: Optional[str] = None,
        skip_latest_check: bool = False
    ) -> Sample:
        undo = self.get_undo_record(undo_token)
        if not undo:
            raise SampleServiceError(f"撤销记录不存在: {undo_token}", "UNDO_NOT_FOUND")

        sample = Sample.query.filter_by(id=undo.sample_id, is_deleted=False).first()
        if not sample:
            raise SampleServiceError(f"样本不存在或已删除: {undo.sample_id}", "SAMPLE_NOT_FOUND")

        self._validate_undo(undo, operator, operator_role, sample, skip_latest_check=skip_latest_check)

        undo.undone = True
        undo.undone_at = datetime.utcnow()
        undo.undone_by = operator
        undo.can_undo = False

        original_from_status = undo.from_status
        original_to_status = undo.to_status
        original_from_loc = undo.from_location_id
        original_to_loc = undo.to_location_id
        original_action = undo.original_action

        new_version = self.sample_service._increment_version(sample)

        if original_action == 'REGISTER':
            sample.is_deleted = True
            sample.status = 'REGISTERED'
            self.sample_service._create_audit_log(
                sample=sample,
                action='UNDO_REGISTER',
                operator=operator,
                operator_role=operator_role,
                from_status=original_to_status or 'REGISTERED',
                to_status='REGISTERED',
                from_location_id=original_to_loc,
                to_location_id=original_from_loc,
                reason=reason or f"撤销登记操作（原操作人: {undo.operator}）",
                remark=f"撤销Token: {undo_token}",
                version=new_version
            )
        else:
            if original_from_status:
                sample.status = original_from_status
            if original_action in ('STORE_IN', 'BORROW') and original_from_loc is not None:
                sample.location_id = original_from_loc
            elif original_action == 'STORE_IN':
                sample.location_id = None
            elif original_action == 'RETURN' and original_from_loc is None:
                sample.location_id = None
            elif original_action in ('TRANSFER', 'RETURN'):
                sample.location_id = original_from_loc

            self.sample_service._create_audit_log(
                sample=sample,
                action=f'UNDO_{original_action}',
                operator=operator,
                operator_role=operator_role,
                from_status=original_to_status,
                to_status=original_from_status,
                from_location_id=original_to_loc,
                to_location_id=original_from_loc,
                reason=reason or f"撤销{original_action}操作（原操作人: {undo.operator}）",
                remark=f"撤销Token: {undo_token}",
                version=new_version
            )

        db.session.commit()
        return sample

    def execute_cascading_undo(
        self,
        undo_token: str,
        operator: str,
        operator_role: str,
        reason: Optional[str] = None
    ) -> List[Sample]:
        if not self.config.is_cascading_undo():
            raise SampleServiceError("级联撤销未启用", "CASCADING_UNDO_DISABLED")

        undo = self.get_undo_record(undo_token)
        if not undo:
            raise SampleServiceError(f"撤销记录不存在: {undo_token}", "UNDO_NOT_FOUND")

        sample_id = undo.sample_id
        audit_log_id = undo.audit_log_id

        later_undos = UndoRecord.query.filter(
            UndoRecord.sample_id == sample_id,
            UndoRecord.audit_log_id >= audit_log_id,
            UndoRecord.can_undo == True,
            UndoRecord.undone == False
        ).order_by(UndoRecord.audit_log_id.desc()).all()

        if not later_undos:
            return [self.execute_undo(undo_token, operator, operator_role, reason)]

        results = []
        for u in later_undos:
            try:
                s = self.execute_undo(u.undo_token, operator, operator_role, reason, skip_latest_check=True)
                results.append(s)
            except SampleServiceError:
                continue

        return results
