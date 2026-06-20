import os
from flask import Flask, jsonify, request, Response

from .models import db
from .config import ConfigManager
from .sample_service import SampleService, SampleServiceError
from .location_service import LocationService
from .export_service import ExportService


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
