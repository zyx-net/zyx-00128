import csv
import io
import json
import os
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

from .models import db, Sample, Location, ImportBatch, ImportRecord, UndoRecord, AuditLog
from .sample_service import SampleService, SampleServiceError
from .config import ConfigManager


class ImportService:
    CSV_HEADERS = [
        'sample_code', 'name', 'sample_type', 'required_temp_zone',
        'version', 'location_code', 'status', 'remark'
    ]

    def __init__(self):
        self.config = ConfigManager()
        self.sample_service = SampleService()

    def _gen_batch_code(self) -> str:
        prefix = self.config.get_batch_code_prefix()
        ts = datetime.utcnow().strftime('%Y%m%d%H%M%S')
        rand = uuid.uuid4().hex[:6].upper()
        return f"{prefix}-{ts}-{rand}"

    def _parse_csv(self, csv_content: str) -> List[Dict[str, Any]]:
        if not csv_content or not csv_content.strip():
            raise SampleServiceError("CSV内容为空", "EMPTY_CSV")

        try:
            content = csv_content.lstrip('\ufeff')
            reader = csv.DictReader(io.StringIO(content))
            rows = []
            for i, row in enumerate(reader, start=2):
                cleaned = {}
                for k, v in row.items():
                    if k is not None:
                        cleaned[k.strip()] = v.strip() if isinstance(v, str) else v
                if any(cleaned.values()):
                    cleaned['__line__'] = i
                    rows.append(cleaned)
            return rows
        except Exception as e:
            raise SampleServiceError(f"CSV解析失败: {str(e)}", "CSV_PARSE_ERROR")

    def _validate_row(self, row: Dict[str, Any], import_mode: str, strategy: str) -> Tuple[bool, Optional[str], Optional[str]]:
        sample_code = row.get('sample_code', '').strip()
        name = row.get('name', '').strip()
        temp_zone = row.get('required_temp_zone', '').strip()

        if not sample_code:
            return False, "MISSING_REQUIRED_FIELD", "缺少必填字段 sample_code（样本编号）"
        if import_mode != 'UPDATE_ONLY' and not name:
            return False, "MISSING_REQUIRED_FIELD", f"样本 {sample_code} 缺少必填字段 name（样本名称）"
        if import_mode != 'UPDATE_ONLY' and not temp_zone:
            return False, "MISSING_REQUIRED_FIELD", f"样本 {sample_code} 缺少必填字段 required_temp_zone（温区）"
        if temp_zone and not self.config.is_valid_temp_zone(temp_zone):
            return False, "INVALID_TEMP_ZONE", f"样本 {sample_code} 温区无效: {temp_zone}"

        version_str = row.get('version', '').strip()
        if import_mode in ('UPDATE_ONLY', 'REGISTER_OR_UPDATE') and self.config.require_version_on_update():
            if version_str:
                try:
                    int(version_str)
                except ValueError:
                    return False, "INVALID_VERSION", f"样本 {sample_code} 版本号格式错误: {version_str}"

        return True, None, None

    def _row_to_sample_data(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            'sample_code': row.get('sample_code', '').strip(),
            'name': row.get('name', '').strip(),
            'sample_type': row.get('sample_type', '').strip() or None,
            'required_temp_zone': row.get('required_temp_zone', '').strip(),
            'remark': row.get('remark', '').strip() or None,
        }

    def import_csv(
        self,
        csv_content: str,
        operator: str,
        operator_role: str,
        import_mode: Optional[str] = None,
        strategy: Optional[str] = None,
        batch_code: Optional[str] = None,
        file_name: Optional[str] = None,
        remark: Optional[str] = None
    ) -> ImportBatch:
        self.sample_service._check_permission(operator_role, "sample.register", "批量导入")

        import_mode = import_mode or self.config.get_default_import_mode()
        strategy = strategy or self.config.get_default_import_strategy()

        if not self.config.is_valid_import_mode(import_mode):
            raise SampleServiceError(f"无效的导入模式: {import_mode}", "INVALID_IMPORT_MODE")
        if not self.config.is_valid_import_strategy(strategy):
            raise SampleServiceError(f"无效的导入策略: {strategy}", "INVALID_IMPORT_STRATEGY")

        if batch_code and self.config.is_import_idempotent():
            existing_batch = ImportBatch.query.filter_by(batch_code=batch_code).first()
            if existing_batch:
                return existing_batch

        rows = self._parse_csv(csv_content)
        max_size = self.config.get_max_batch_size()
        if len(rows) > max_size:
            raise SampleServiceError(
                f"批次过大: {len(rows)} 条，最大允许 {max_size} 条",
                "BATCH_TOO_LARGE"
            )

        final_batch_code = batch_code or self._gen_batch_code()

        batch = ImportBatch(
            batch_code=final_batch_code,
            total_count=len(rows),
            success_count=0,
            failed_count=0,
            skipped_count=0,
            status='PROCESSING',
            operator=operator,
            operator_role=operator_role,
            import_mode=import_mode,
            strategy=strategy,
            file_name=file_name,
            remark=remark
        )
        db.session.add(batch)
        db.session.flush()

        success_count = 0
        failed_count = 0
        skipped_count = 0
        error_records = []

        for row in rows:
            line_num = row.get('__line__', 0)
            row_data = {k: v for k, v in row.items() if k != '__line__'}
            sample_code = row.get('sample_code', '').strip()
            action_taken = None
            result_status = 'SUCCESS'
            error_code = None
            error_message = None
            sample_id = None
            retryable = True

            try:
                ok, ec, em = self._validate_row(row, import_mode, strategy)
                if not ok:
                    raise SampleServiceError(em or "校验失败", ec or "VALIDATION_ERROR")

                existing = Sample.query.filter_by(sample_code=sample_code, is_deleted=False).first()

                if existing:
                    if import_mode == 'REGISTER':
                        if strategy == 'FAIL_ON_DUPLICATE':
                            raise SampleServiceError(
                                f"样本编号已存在: {sample_code}",
                                "SAMPLE_CODE_EXISTS"
                            )
                        elif strategy == 'SKIP_DUPLICATE':
                            result_status = 'SKIPPED'
                            skipped_count += 1
                            retryable = False
                            import_record = ImportRecord(
                                batch_id=batch.id,
                                line_number=line_num,
                                sample_code=sample_code,
                                action='SKIP',
                                result=result_status,
                                error_code='DUPLICATE_SKIPPED',
                                error_message=f'样本编号 {sample_code} 已存在，根据策略跳过',
                                sample_id=existing.id,
                                row_data=json.dumps(row_data, ensure_ascii=False),
                                retryable=retryable
                            )
                            db.session.add(import_record)
                            continue
                        elif strategy == 'UPDATE_IF_EXISTS':
                            action_taken = 'UPDATE'
                            sample = self._update_existing_sample(existing, row, operator, operator_role)
                            sample_id = sample.id
                    elif import_mode == 'UPDATE_ONLY':
                        action_taken = 'UPDATE'
                        sample = self._update_existing_sample(existing, row, operator, operator_role)
                        sample_id = sample.id
                    elif import_mode == 'REGISTER_OR_UPDATE':
                        if strategy == 'FAIL_ON_DUPLICATE':
                            raise SampleServiceError(
                                f"样本编号已存在: {sample_code}",
                                "SAMPLE_CODE_EXISTS"
                            )
                        elif strategy == 'SKIP_DUPLICATE':
                            result_status = 'SKIPPED'
                            skipped_count += 1
                            retryable = False
                            import_record = ImportRecord(
                                batch_id=batch.id,
                                line_number=line_num,
                                sample_code=sample_code,
                                action='SKIP',
                                result=result_status,
                                error_code='DUPLICATE_SKIPPED',
                                error_message=f'样本编号 {sample_code} 已存在，根据策略跳过',
                                sample_id=existing.id,
                                row_data=json.dumps(row_data, ensure_ascii=False),
                                retryable=retryable
                            )
                            db.session.add(import_record)
                            continue
                        elif strategy == 'UPDATE_IF_EXISTS':
                            action_taken = 'UPDATE'
                            sample = self._update_existing_sample(existing, row, operator, operator_role)
                            sample_id = sample.id
                else:
                    if import_mode == 'UPDATE_ONLY':
                        raise SampleServiceError(
                            f"UPDATE_ONLY 模式下样本不存在: {sample_code}",
                            "SAMPLE_NOT_FOUND"
                        )
                    else:
                        action_taken = 'REGISTER'
                        sample_data = self._row_to_sample_data(row)
                        sample = self.sample_service.register_sample(
                            **sample_data,
                            operator=operator,
                            operator_role=operator_role
                        )
                        sample_id = sample.id

                        location_code = row.get('location_code', '').strip()
                        if location_code:
                            loc = Location.query.filter_by(code=location_code, is_active=True).first()
                            if not loc:
                                raise SampleServiceError(f"库位不存在: {location_code}", "LOCATION_NOT_FOUND")
                            if loc.temp_zone != sample.required_temp_zone:
                                temp_zone_info = self.config.get_temp_zone(sample.required_temp_zone)
                                location_temp_info = self.config.get_temp_zone(loc.temp_zone)
                                raise SampleServiceError(
                                    f"温区不匹配：样本需要 {temp_zone_info['name']}，但库位 '{loc.name}' 属于 {location_temp_info['name']}",
                                    "TEMP_ZONE_MISMATCH"
                                )
                            sample = self.sample_service.store_in(
                                sample_id=sample.id,
                                location_id=loc.id,
                                operator=operator,
                                operator_role=operator_role,
                                expected_version=sample.version,
                                reason='批量导入入库'
                            )
                            action_taken = 'REGISTER+STORE_IN'

                success_count += 1

            except SampleServiceError as e:
                result_status = 'FAILED'
                failed_count += 1
                error_code = e.code
                error_message = e.message
                retryable = self._is_retryable_error(e.code)
                error_records.append({
                    'line_number': line_num,
                    'sample_code': sample_code,
                    'error_code': error_code,
                    'error_message': error_message,
                    'row_data': row_data
                })
            except Exception as e:
                result_status = 'FAILED'
                failed_count += 1
                error_code = 'UNKNOWN_ERROR'
                error_message = f"未知错误: {str(e)}"
                retryable = True
                error_records.append({
                    'line_number': line_num,
                    'sample_code': sample_code,
                    'error_code': error_code,
                    'error_message': error_message,
                    'row_data': row_data
                })

            import_record = ImportRecord(
                batch_id=batch.id,
                line_number=line_num,
                sample_code=sample_code,
                action=action_taken,
                result=result_status,
                error_code=error_code,
                error_message=error_message,
                sample_id=sample_id,
                row_data=json.dumps(row_data, ensure_ascii=False),
                retryable=retryable
            )
            db.session.add(import_record)

        error_csv_path = None
        if error_records:
            error_csv_path = self._write_error_csv(final_batch_code, error_records)

        batch.success_count = success_count
        batch.failed_count = failed_count
        batch.skipped_count = skipped_count
        batch.status = 'COMPLETED' if failed_count == 0 else 'COMPLETED_WITH_ERRORS'
        batch.finished_at = datetime.utcnow()
        batch.error_csv_path = error_csv_path

        db.session.commit()
        return batch

    def _update_existing_sample(
        self,
        existing: Sample,
        row: Dict[str, Any],
        operator: str,
        operator_role: str
    ) -> Sample:
        version_str = row.get('version', '').strip()
        if self.config.require_version_on_update() and version_str:
            expected_version = int(version_str)
            self.sample_service._check_version(existing, expected_version)

        new_name = row.get('name', '').strip()
        new_type = row.get('sample_type', '').strip() or None
        new_temp_zone = row.get('required_temp_zone', '').strip()
        new_remark = row.get('remark', '').strip() or None
        location_code = row.get('location_code', '').strip()
        new_status = row.get('status', '').strip()

        from_status = existing.status
        from_location_id = existing.location_id
        changes = []

        if new_name and new_name != existing.name:
            existing.name = new_name
            changes.append(f"名称更新为 {new_name}")
        if new_type is not None and new_type != existing.sample_type:
            existing.sample_type = new_type
            changes.append(f"类型更新为 {new_type}")
        if new_temp_zone and new_temp_zone != existing.required_temp_zone:
            if not self.config.is_valid_temp_zone(new_temp_zone):
                raise SampleServiceError(f"无效温区: {new_temp_zone}", "INVALID_TEMP_ZONE")
            if existing.location_id:
                loc = Location.query.filter_by(id=existing.location_id).first()
                if loc and loc.temp_zone != new_temp_zone:
                    raise SampleServiceError(
                        f"温区变更与当前库位不匹配，需要先调整库位",
                        "TEMP_ZONE_CONFLICT_WITH_LOCATION"
                    )
            existing.required_temp_zone = new_temp_zone
            changes.append(f"温区更新为 {new_temp_zone}")
        if new_remark is not None:
            existing.remark = new_remark
            changes.append("备注已更新")

        new_version = self.sample_service._increment_version(existing)

        if changes:
            self.sample_service._create_audit_log(
                sample=existing,
                action='UPDATE',
                operator=operator,
                operator_role=operator_role,
                from_status=from_status,
                to_status=existing.status,
                from_location_id=from_location_id,
                to_location_id=existing.location_id,
                reason='批量导入更新: ' + '; '.join(changes),
                version=new_version
            )

        if location_code:
            loc = Location.query.filter_by(code=location_code, is_active=True).first()
            if not loc:
                raise SampleServiceError(f"库位不存在: {location_code}", "LOCATION_NOT_FOUND")
            if loc.temp_zone != existing.required_temp_zone:
                temp_zone_info = self.config.get_temp_zone(existing.required_temp_zone)
                location_temp_info = self.config.get_temp_zone(loc.temp_zone)
                raise SampleServiceError(
                    f"温区不匹配：样本需要 {temp_zone_info['name']}，但库位 '{loc.name}' 属于 {location_temp_info['name']}",
                    "TEMP_ZONE_MISMATCH"
                )
            if existing.status == 'REGISTERED':
                return self.sample_service.store_in(
                    sample_id=existing.id,
                    location_id=loc.id,
                    operator=operator,
                    operator_role=operator_role,
                    expected_version=new_version,
                    reason='批量导入入库'
                )
            elif existing.status == 'IN_STORAGE' and existing.location_id != loc.id:
                return self.sample_service.transfer(
                    sample_id=existing.id,
                    to_location_id=loc.id,
                    operator=operator,
                    operator_role=operator_role,
                    expected_version=new_version,
                    reason='批量导入转移'
                )

        db.session.commit()
        return existing

    def _is_retryable_error(self, error_code: str) -> bool:
        non_retryable = {
            'MISSING_REQUIRED_FIELD',
            'INVALID_TEMP_ZONE',
            'INVALID_VERSION',
            'INVALID_IMPORT_MODE',
            'INVALID_IMPORT_STRATEGY',
            'PERMISSION_DENIED',
        }
        return error_code not in non_retryable

    def _write_error_csv(self, batch_code: str, error_records: List[Dict[str, Any]]) -> str:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        error_dir = os.path.join(base_dir, 'data', 'import_errors')
        os.makedirs(error_dir, exist_ok=True)
        file_path = os.path.join(error_dir, f'{batch_code}_errors.csv')

        headers = self.CSV_HEADERS + ['error_code', 'error_message']

        with open(file_path, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for rec in error_records:
                row_data = rec.get('row_data', {})
                out_row = {}
                for h in self.CSV_HEADERS:
                    out_row[h] = row_data.get(h, '')
                out_row['error_code'] = rec.get('error_code', '')
                out_row['error_message'] = rec.get('error_message', '')
                writer.writerow(out_row)

        return file_path

    def get_batch(self, batch_id: int) -> Optional[ImportBatch]:
        return ImportBatch.query.filter_by(id=batch_id).first()

    def get_batch_by_code(self, batch_code: str) -> Optional[ImportBatch]:
        return ImportBatch.query.filter_by(batch_code=batch_code).first()

    def list_batches(
        self,
        status: Optional[str] = None,
        page: int = 1,
        per_page: int = 20
    ) -> Tuple[List[ImportBatch], int]:
        query = ImportBatch.query
        if status:
            query = query.filter_by(status=status)
        total = query.count()
        batches = query.order_by(ImportBatch.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
        return batches, total

    def get_batch_records(
        self,
        batch_id: int,
        result: Optional[str] = None,
        retryable_only: bool = False,
        page: int = 1,
        per_page: int = 100
    ) -> Tuple[List[ImportRecord], int]:
        query = ImportRecord.query.filter_by(batch_id=batch_id)
        if result:
            query = query.filter_by(result=result)
        if retryable_only:
            query = query.filter_by(retryable=True)
        total = query.count()
        records = query.order_by(ImportRecord.line_number).offset((page - 1) * per_page).limit(per_page).all()
        return records, total

    def generate_error_csv_content(self, batch_id: int) -> str:
        records, _ = self.get_batch_records(batch_id, result='FAILED', retryable_only=True, page=1, per_page=10000)

        output = io.StringIO()
        headers = self.CSV_HEADERS + ['error_code', 'error_message']
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()

        for rec in records:
            try:
                row_data = json.loads(rec.row_data) if rec.row_data else {}
            except (json.JSONDecodeError, TypeError):
                row_data = {}
            out_row = {}
            for h in self.CSV_HEADERS:
                out_row[h] = row_data.get(h, '')
            out_row['error_code'] = rec.error_code or ''
            out_row['error_message'] = rec.error_message or ''
            writer.writerow(out_row)

        return output.getvalue()

    def retry_failed_records(
        self,
        batch_id: int,
        operator: str,
        operator_role: str
    ) -> ImportBatch:
        batch = self.get_batch(batch_id)
        if not batch:
            raise SampleServiceError(f"导入批次不存在: {batch_id}", "BATCH_NOT_FOUND")

        failed_records, _ = self.get_batch_records(batch_id, result='FAILED', retryable_only=True, page=1, per_page=10000)
        if not failed_records:
            raise SampleServiceError("没有可重试的失败记录", "NO_RETRYABLE_RECORDS")

        rows = []
        for rec in failed_records:
            try:
                row_data = json.loads(rec.row_data) if rec.row_data else {}
            except (json.JSONDecodeError, TypeError):
                row_data = {}
            row_data['__line__'] = rec.line_number
            rows.append(row_data)

        csv_content = self._rows_to_csv(rows)
        new_batch_code = f"{batch.batch_code}-R{datetime.utcnow().strftime('%H%M%S')}"

        return self.import_csv(
            csv_content=csv_content,
            operator=operator,
            operator_role=operator_role,
            import_mode=batch.import_mode,
            strategy=batch.strategy,
            batch_code=new_batch_code,
            file_name=f'retry_{batch.file_name or batch.batch_code}',
            remark=f"重试批次 {batch.batch_code} 的失败记录"
        )

    def _rows_to_csv(self, rows: List[Dict[str, Any]]) -> str:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=self.CSV_HEADERS, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return output.getvalue()
