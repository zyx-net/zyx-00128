import csv
import io
from typing import List

from .models import Sample, AuditLog
from .sample_service import SampleService, SampleServiceError
from .config import ConfigManager


class ExportService:
    def __init__(self):
        self.sample_service = SampleService()
        self.config = ConfigManager()

    def export_sample_chain_csv(self, sample_id: int, operator_role: str) -> str:
        if not self.config.has_permission(operator_role, "sample.export"):
            raise SampleServiceError(
                f"角色 '{operator_role}' 没有权限导出样本交接链",
                "PERMISSION_DENIED"
            )

        sample = Sample.query.filter_by(id=sample_id).first()
        if not sample:
            raise SampleServiceError(f"样本不存在: {sample_id}", "SAMPLE_NOT_FOUND")

        audit_logs = sample.audit_logs.order_by(AuditLog.sequence).all()

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            '样本编号', sample.sample_code,
            '样本名称', sample.name,
            '样本类型', sample.sample_type or '',
            '所需温区', self.config.get_temp_zone(sample.required_temp_zone)['name'] if self.config.get_temp_zone(sample.required_temp_zone) else sample.required_temp_zone,
            '当前状态', self.config.get_status_label(sample.status),
            '当前版本', sample.version
        ])
        writer.writerow([])

        writer.writerow([
            '序号',
            '操作类型',
            '原状态',
            '新状态',
            '原库位',
            '新库位',
            '操作人',
            '操作角色',
            '原因',
            '版本号',
            '备注',
            '操作时间'
        ])

        for log in audit_logs:
            writer.writerow(log.to_csv_row())

        return output.getvalue()

    def export_samples_csv(self, operator_role: str, status: str = None, temp_zone: str = None) -> str:
        if not self.config.has_permission(operator_role, "sample.export"):
            raise SampleServiceError(
                f"角色 '{operator_role}' 没有权限导出样本数据",
                "PERMISSION_DENIED"
            )

        samples, _ = self.sample_service.list_samples(status=status, temp_zone=temp_zone, page=1, per_page=10000)

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            '样本编号',
            '样本名称',
            '样本类型',
            '所需温区',
            '当前状态',
            '当前库位',
            '版本号',
            '创建人',
            '创建时间',
            '更新时间',
            '备注'
        ])

        for sample in samples:
            temp_zone_name = self.config.get_temp_zone(sample.required_temp_zone)['name'] if self.config.get_temp_zone(sample.required_temp_zone) else sample.required_temp_zone
            status_label = self.config.get_status_label(sample.status)
            writer.writerow([
                sample.sample_code,
                sample.name,
                sample.sample_type or '',
                temp_zone_name,
                status_label,
                sample.location.name if sample.location else '',
                sample.version,
                sample.created_by,
                sample.created_at.isoformat() if sample.created_at else '',
                sample.updated_at.isoformat() if sample.updated_at else '',
                sample.remark or ''
            ])

        return output.getvalue()
