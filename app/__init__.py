import os
from flask import Flask, jsonify, request, Response

from .models import db
from .config import ConfigManager
from .sample_service import SampleService, SampleServiceError
from .location_service import LocationService
from .export_service import ExportService
from .import_service import ImportService
from .undo_service import UndoService


def create_app():
    app = Flask(__name__)

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, 'data', 'sample_lab.db')
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['JSON_AS_ASCII'] = False

    db.init_app(app)

    with app.app_context():
        db.create_all()
        loc_service = LocationService()
        loc_service.initialize_locations_from_config()

    sample_service = SampleService()
    location_service = LocationService()
    export_service = ExportService()
    import_service = ImportService()
    undo_service = UndoService()
    config_manager = ConfigManager()

    @app.errorhandler(SampleServiceError)
    def handle_service_error(error):
        return jsonify({
            'success': False,
            'error': error.code,
            'message': error.message
        }), 400

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({
            'success': False,
            'error': 'NOT_FOUND',
            'message': '接口不存在'
        }), 404

    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({
            'success': False,
            'error': 'INTERNAL_ERROR',
            'message': '服务器内部错误'
        }), 500

    @app.route('/api/health', methods=['GET'])
    def health_check():
        return jsonify({
            'success': True,
            'data': {
                'status': 'ok',
                'service': '实验室样本交接系统'
            }
        })

    @app.route('/api/config/temp-zones', methods=['GET'])
    def get_temp_zones():
        return jsonify({
            'success': True,
            'data': config_manager.temp_zones
        })

    @app.route('/api/config/roles', methods=['GET'])
    def get_roles():
        return jsonify({
            'success': True,
            'data': config_manager.roles
        })

    @app.route('/api/config/status-flow', methods=['GET'])
    def get_status_flow():
        return jsonify({
            'success': True,
            'data': config_manager.status_flow
        })

    @app.route('/api/locations', methods=['GET'])
    def list_locations():
        temp_zone = request.args.get('temp_zone')
        include_inactive = request.args.get('include_inactive', 'false').lower() == 'true'
        locations = location_service.list_locations(
            temp_zone=temp_zone,
            include_inactive=include_inactive
        )
        return jsonify({
            'success': True,
            'data': [loc.to_dict() for loc in locations]
        })

    @app.route('/api/locations', methods=['POST'])
    def create_location():
        data = request.get_json() or {}
        operator_role = data.get('operator_role', 'ADMIN')
        location = location_service.create_location(
            code=data['code'],
            name=data['name'],
            temp_zone=data['temp_zone'],
            capacity=data.get('capacity', 100),
            description=data.get('description'),
            operator_role=operator_role
        )
        return jsonify({
            'success': True,
            'data': location.to_dict()
        }), 201

    @app.route('/api/locations/<int:location_id>', methods=['GET'])
    def get_location(location_id):
        location = location_service.get_location(location_id)
        if not location:
            return jsonify({
                'success': False,
                'error': 'LOCATION_NOT_FOUND',
                'message': f'库位不存在: {location_id}'
            }), 404
        return jsonify({
            'success': True,
            'data': location.to_dict()
        })

    @app.route('/api/samples', methods=['GET'])
    def list_samples():
        status = request.args.get('status')
        temp_zone = request.args.get('temp_zone')
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))

        samples, total = sample_service.list_samples(
            status=status,
            temp_zone=temp_zone,
            page=page,
            per_page=per_page
        )
        return jsonify({
            'success': True,
            'data': [s.to_dict() for s in samples],
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'pages': (total + per_page - 1) // per_page
            }
        })

    @app.route('/api/samples/<int:sample_id>', methods=['GET'])
    def get_sample(sample_id):
        sample = sample_service.get_sample(sample_id)
        if not sample:
            return jsonify({
                'success': False,
                'error': 'SAMPLE_NOT_FOUND',
                'message': f'样本不存在: {sample_id}'
            }), 404
        return jsonify({
            'success': True,
            'data': sample.to_dict()
        })

    @app.route('/api/samples/code/<sample_code>', methods=['GET'])
    def get_sample_by_code(sample_code):
        sample = sample_service.get_sample_by_code(sample_code)
        if not sample:
            return jsonify({
                'success': False,
                'error': 'SAMPLE_NOT_FOUND',
                'message': f'样本不存在: {sample_code}'
            }), 404
        return jsonify({
            'success': True,
            'data': sample.to_dict()
        })

    @app.route('/api/samples', methods=['POST'])
    def register_sample():
        data = request.get_json() or {}
        sample = sample_service.register_sample(
            sample_code=data['sample_code'],
            name=data['name'],
            required_temp_zone=data['required_temp_zone'],
            operator=data.get('operator', 'system'),
            operator_role=data.get('operator_role', 'LAB_TECHNICIAN'),
            sample_type=data.get('sample_type'),
            remark=data.get('remark')
        )
        return jsonify({
            'success': True,
            'data': sample.to_dict()
        }), 201

    @app.route('/api/samples/<int:sample_id>/store-in', methods=['POST'])
    def store_in_sample(sample_id):
        data = request.get_json() or {}
        sample = sample_service.store_in(
            sample_id=sample_id,
            location_id=data['location_id'],
            operator=data.get('operator', 'system'),
            operator_role=data.get('operator_role', 'LAB_TECHNICIAN'),
            expected_version=data['expected_version'],
            reason=data.get('reason')
        )
        return jsonify({
            'success': True,
            'data': sample.to_dict()
        })

    @app.route('/api/samples/<int:sample_id>/transfer', methods=['POST'])
    def transfer_sample(sample_id):
        data = request.get_json() or {}
        sample = sample_service.transfer(
            sample_id=sample_id,
            to_location_id=data['to_location_id'],
            operator=data.get('operator', 'system'),
            operator_role=data.get('operator_role', 'LAB_TECHNICIAN'),
            expected_version=data['expected_version'],
            reason=data.get('reason')
        )
        return jsonify({
            'success': True,
            'data': sample.to_dict()
        })

    @app.route('/api/samples/<int:sample_id>/borrow', methods=['POST'])
    def borrow_sample(sample_id):
        data = request.get_json() or {}
        sample = sample_service.borrow(
            sample_id=sample_id,
            operator=data.get('operator', 'system'),
            operator_role=data.get('operator_role', 'LAB_TECHNICIAN'),
            expected_version=data['expected_version'],
            reason=data.get('reason'),
            remark=data.get('remark')
        )
        return jsonify({
            'success': True,
            'data': sample.to_dict()
        })

    @app.route('/api/samples/<int:sample_id>/return', methods=['POST'])
    def return_sample(sample_id):
        data = request.get_json() or {}
        sample = sample_service.return_sample(
            sample_id=sample_id,
            location_id=data['location_id'],
            operator=data.get('operator', 'system'),
            operator_role=data.get('operator_role', 'LAB_TECHNICIAN'),
            expected_version=data['expected_version'],
            reason=data.get('reason'),
            remark=data.get('remark')
        )
        return jsonify({
            'success': True,
            'data': sample.to_dict()
        })

    @app.route('/api/samples/<int:sample_id>/discard', methods=['POST'])
    def discard_sample(sample_id):
        data = request.get_json() or {}
        sample = sample_service.discard(
            sample_id=sample_id,
            operator=data.get('operator', 'system'),
            operator_role=data.get('operator_role', 'LAB_MANAGER'),
            expected_version=data['expected_version'],
            reason=data['reason'],
            remark=data.get('remark')
        )
        return jsonify({
            'success': True,
            'data': sample.to_dict()
        })

    @app.route('/api/samples/<int:sample_id>/audit-logs', methods=['GET'])
    def get_audit_logs(sample_id):
        logs = sample_service.get_audit_logs(sample_id)
        return jsonify({
            'success': True,
            'data': [log.to_dict() for log in logs]
        })

    @app.route('/api/samples/<int:sample_id>/export-chain', methods=['GET'])
    def export_sample_chain(sample_id):
        import urllib.parse
        operator_role = request.args.get('role', 'LAB_TECHNICIAN')
        csv_content = export_service.export_sample_chain_csv(sample_id, operator_role)

        sample = sample_service.get_sample(sample_id)
        filename = f'{sample.sample_code}_chain.csv'

        return Response(
            csv_content.encode('utf-8-sig'),
            mimetype='text/csv; charset=utf-8',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Type': 'text/csv; charset=utf-8'
            }
        )

    @app.route('/api/samples/export', methods=['GET'])
    def export_samples():
        operator_role = request.args.get('role', 'LAB_TECHNICIAN')
        status = request.args.get('status')
        temp_zone = request.args.get('temp_zone')
        csv_content = export_service.export_samples_csv(operator_role, status, temp_zone)

        return Response(
            csv_content.encode('utf-8-sig'),
            mimetype='text/csv; charset=utf-8',
            headers={
                'Content-Disposition': 'attachment; filename="samples_list.csv"',
                'Content-Type': 'text/csv; charset=utf-8'
            }
        )

    @app.route('/api/samples/import/csv', methods=['POST'])
    def import_samples_csv():
        data = request.get_json() or {}
        csv_content = data.get('csv_content') or data.get('csv')
        if not csv_content:
            return jsonify({
                'success': False,
                'error': 'MISSING_CSV',
                'message': '缺少 CSV 内容（csv_content 字段）'
            }), 400
        batch = import_service.import_csv(
            csv_content=csv_content,
            operator=data.get('operator', 'system'),
            operator_role=data.get('operator_role', 'LAB_TECHNICIAN'),
            import_mode=data.get('import_mode'),
            strategy=data.get('strategy'),
            batch_code=data.get('batch_code'),
            file_name=data.get('file_name'),
            remark=data.get('remark')
        )
        records, _ = import_service.get_batch_records(batch.id, page=1, per_page=10000)
        return jsonify({
            'success': True,
            'data': {
                'batch': batch.to_dict(),
                'records': [r.to_dict() for r in records]
            }
        }), 201

    @app.route('/api/import/batches', methods=['GET'])
    def list_import_batches():
        status = request.args.get('status')
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        batches, total = import_service.list_batches(status=status, page=page, per_page=per_page)
        return jsonify({
            'success': True,
            'data': [b.to_dict() for b in batches],
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'pages': (total + per_page - 1) // per_page
            }
        })

    @app.route('/api/import/batches/<int:batch_id>', methods=['GET'])
    def get_import_batch(batch_id):
        batch = import_service.get_batch(batch_id)
        if not batch:
            return jsonify({
                'success': False,
                'error': 'BATCH_NOT_FOUND',
                'message': f'导入批次不存在: {batch_id}'
            }), 404
        return jsonify({
            'success': True,
            'data': batch.to_dict()
        })

    @app.route('/api/import/batches/code/<batch_code>', methods=['GET'])
    def get_import_batch_by_code(batch_code):
        batch = import_service.get_batch_by_code(batch_code)
        if not batch:
            return jsonify({
                'success': False,
                'error': 'BATCH_NOT_FOUND',
                'message': f'导入批次不存在: {batch_code}'
            }), 404
        return jsonify({
            'success': True,
            'data': batch.to_dict()
        })

    @app.route('/api/import/batches/<int:batch_id>/records', methods=['GET'])
    def get_import_batch_records(batch_id):
        batch = import_service.get_batch(batch_id)
        if not batch:
            return jsonify({
                'success': False,
                'error': 'BATCH_NOT_FOUND',
                'message': f'导入批次不存在: {batch_id}'
            }), 404
        result_filter = request.args.get('result')
        retryable_only = request.args.get('retryable_only', 'false').lower() == 'true'
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 100))
        records, total = import_service.get_batch_records(
            batch_id=batch_id,
            result=result_filter,
            retryable_only=retryable_only,
            page=page,
            per_page=per_page
        )
        return jsonify({
            'success': True,
            'data': [r.to_dict() for r in records],
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'pages': (total + per_page - 1) // per_page
            }
        })

    @app.route('/api/import/batches/<int:batch_id>/errors/csv', methods=['GET'])
    def download_batch_errors_csv(batch_id):
        batch = import_service.get_batch(batch_id)
        if not batch:
            return jsonify({
                'success': False,
                'error': 'BATCH_NOT_FOUND',
                'message': f'导入批次不存在: {batch_id}'
            }), 404
        csv_content = import_service.generate_error_csv_content(batch_id)
        filename = f'{batch.batch_code}_errors.csv'
        return Response(
            csv_content.encode('utf-8-sig'),
            mimetype='text/csv; charset=utf-8',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Type': 'text/csv; charset=utf-8'
            }
        )

    @app.route('/api/import/batches/<int:batch_id>/retry', methods=['POST'])
    def retry_failed_imports(batch_id):
        data = request.get_json() or {}
        new_batch = import_service.retry_failed_records(
            batch_id=batch_id,
            operator=data.get('operator', 'system'),
            operator_role=data.get('operator_role', 'LAB_TECHNICIAN')
        )
        records, _ = import_service.get_batch_records(new_batch.id, page=1, per_page=10000)
        return jsonify({
            'success': True,
            'data': {
                'batch': new_batch.to_dict(),
                'records': [r.to_dict() for r in records]
            }
        }), 201

    @app.route('/api/import/template.csv', methods=['GET'])
    def download_import_template():
        import csv
        import io
        headers = import_service.CSV_HEADERS
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        writer.writerow({
            'sample_code': 'SAMPLE-001',
            'name': '示例样本-血液',
            'sample_type': '血液',
            'required_temp_zone': 'REFRIGERATED',
            'version': '',
            'location_code': 'REF-001',
            'status': '',
            'remark': '这是示例行，请删除后填入实际数据'
        })
        csv_content = output.getvalue()
        return Response(
            csv_content.encode('utf-8-sig'),
            mimetype='text/csv; charset=utf-8',
            headers={
                'Content-Disposition': 'attachment; filename="import_template.csv"',
                'Content-Type': 'text/csv; charset=utf-8'
            }
        )

    @app.route('/api/undo/available', methods=['GET'])
    def list_available_undo():
        sample_id = request.args.get('sample_id', type=int)
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        records, total = undo_service.list_available_undo(
            sample_id=sample_id,
            page=page,
            per_page=per_page
        )
        return jsonify({
            'success': True,
            'data': [r.to_dict() for r in records],
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'pages': (total + per_page - 1) // per_page
            }
        })

    @app.route('/api/undo/<undo_token>', methods=['GET'])
    def get_undo_record(undo_token):
        undo = undo_service.get_undo_record(undo_token)
        if not undo:
            return jsonify({
                'success': False,
                'error': 'UNDO_NOT_FOUND',
                'message': f'撤销记录不存在: {undo_token}'
            }), 404
        return jsonify({
            'success': True,
            'data': undo.to_dict()
        })

    @app.route('/api/undo/<undo_token>', methods=['POST'])
    def execute_undo(undo_token):
        data = request.get_json() or {}
        cascading = data.get('cascading', False)
        if cascading:
            samples = undo_service.execute_cascading_undo(
                undo_token=undo_token,
                operator=data.get('operator', 'system'),
                operator_role=data.get('operator_role', 'LAB_MANAGER'),
                reason=data.get('reason')
            )
            return jsonify({
                'success': True,
                'data': {
                    'cascading': True,
                    'count': len(samples),
                    'samples': [s.to_dict() for s in samples]
                }
            })
        else:
            sample = undo_service.execute_undo(
                undo_token=undo_token,
                operator=data.get('operator', 'system'),
                operator_role=data.get('operator_role', 'LAB_MANAGER'),
                reason=data.get('reason')
            )
            return jsonify({
                'success': True,
                'data': {
                    'cascading': False,
                    'sample': sample.to_dict()
                }
            })

    @app.route('/api/samples/<int:sample_id>/undo-chain', methods=['GET'])
    def get_sample_undo_chain(sample_id):
        records, total = undo_service.list_available_undo(
            sample_id=sample_id,
            page=1,
            per_page=100
        )
        return jsonify({
            'success': True,
            'data': [r.to_dict() for r in records],
            'total': total
        })

    @app.route('/api/docs', methods=['GET'])
    def api_docs():
        docs = {
            'title': '实验室样本交接系统 API 文档',
            'version': '1.0.0',
            'base_url': '/api',
            'endpoints': {
                '健康检查': {
                    'GET /api/health': '检查服务状态'
                },
                '配置信息': {
                    'GET /api/config/temp-zones': '获取温区配置列表',
                    'GET /api/config/roles': '获取角色配置列表',
                    'GET /api/config/status-flow': '获取状态流转规则'
                },
                '库位管理': {
                    'GET /api/locations': '获取库位列表（支持 ?temp_zone= 筛选）',
                    'GET /api/locations/<id>': '获取单个库位详情',
                    'POST /api/locations': '创建新库位'
                },
                '样本管理': {
                    'GET /api/samples': '获取样本列表（支持 ?status=&temp_zone=&page=&per_page=）',
                    'GET /api/samples/<id>': '获取单个样本详情',
                    'GET /api/samples/code/<code>': '通过样本编号获取样本',
                    'POST /api/samples': '登记新样本'
                },
                '样本状态流转': {
                    'POST /api/samples/<id>/store-in': '样本入库',
                    'POST /api/samples/<id>/transfer': '样本转移库位',
                    'POST /api/samples/<id>/borrow': '样本借出',
                    'POST /api/samples/<id>/return': '样本退回',
                    'POST /api/samples/<id>/discard': '样本废弃'
                },
                '审计日志': {
                    'GET /api/samples/<id>/audit-logs': '获取样本审计日志'
                },
                '数据导出': {
                    'GET /api/samples/<id>/export-chain': '导出样本交接链CSV',
                    'GET /api/samples/export': '导出样本列表CSV'
                },
                '批量导入': {
                    'POST /api/samples/import/csv': 'CSV批量导入样本（支持登记+更新）',
                    'GET /api/import/template.csv': '下载导入模板CSV',
                    'GET /api/import/batches': '查询导入批次列表',
                    'GET /api/import/batches/<id>': '查询单个导入批次详情',
                    'GET /api/import/batches/code/<code>': '按批次号查询',
                    'GET /api/import/batches/<id>/records': '查询批次明细记录',
                    'GET /api/import/batches/<id>/errors/csv': '下载批次错误清单CSV',
                    'POST /api/import/batches/<id>/retry': '重跑批次中的失败记录'
                },
                '撤销链路': {
                    'GET /api/undo/available': '查询可撤销的操作列表',
                    'GET /api/samples/<id>/undo-chain': '查询某样本的可撤销链路',
                    'GET /api/undo/<token>': '查询单个撤销记录',
                    'POST /api/undo/<token>': '执行撤销（支持cascading参数级联撤销）'
                }
            },
            '通用请求头': {
                'Content-Type': 'application/json'
            },
            '通用响应格式': {
                'success': 'boolean, 请求是否成功',
                'data': '响应数据',
                'error': '错误码（失败时）',
                'message': '错误信息（失败时）'
            },
            '状态说明': {
                'REGISTERED': '已登记 - 样本刚创建，尚未入库',
                'IN_STORAGE': '在库 - 样本在库位中存放',
                'BORROWED': '已借出 - 样本被借出使用',
                'DISCARDED': '已废弃 - 样本已被废弃'
            },
            '操作角色': {
                'ADMIN': '系统管理员 - 全部权限',
                'LAB_TECHNICIAN': '实验员 - 登记/入库/转移/借出/退回',
                'LAB_MANAGER': '实验室主管 - 含废弃权限',
                'GUEST': '访客 - 仅查看'
            },
            '温区类型': {
                'AMBIENT': '常温区 (15°C ~ 25°C)',
                'REFRIGERATED': '冷藏区 (2°C ~ 8°C)',
                'FROZEN': '冷冻区 (-10°C ~ -20°C)',
                'DEEP_FROZEN': '深冻区 (-70°C ~ -80°C)'
            },
            '版本控制说明': '每次状态变更会递增版本号，提交操作时需传入 expected_version，若与当前版本不匹配则返回 VERSION_CONFLICT 错误，确保并发安全。'
        }
        return jsonify({
            'success': True,
            'data': docs
        })

    return app
