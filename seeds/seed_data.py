import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.sample_service import SampleService
from app.location_service import LocationService


def seed_data():
    app = create_app()

    with app.app_context():
        sample_service = SampleService()
        location_service = LocationService()

        print("=" * 60)
        print("开始加载种子数据...")
        print("=" * 60)

        samples = [
            {
                'sample_code': 'SMP-2026-0001',
                'name': '血液样本A1',
                'sample_type': '血液',
                'required_temp_zone': 'REFRIGERATED',
                'operator': '张三',
                'operator_role': 'LAB_TECHNICIAN',
                'remark': '患者A的血常规检测样本'
            },
            {
                'sample_code': 'SMP-2026-0002',
                'name': '血清样本B2',
                'sample_type': '血清',
                'required_temp_zone': 'FROZEN',
                'operator': '李四',
                'operator_role': 'LAB_TECHNICIAN',
                'remark': '生化检测样本'
            },
            {
                'sample_code': 'SMP-2026-0003',
                'name': 'DNA样本C3',
                'sample_type': 'DNA',
                'required_temp_zone': 'DEEP_FROZEN',
                'operator': '王五',
                'operator_role': 'LAB_TECHNICIAN',
                'remark': '基因检测样本，需深冻保存'
            },
            {
                'sample_code': 'SMP-2026-0004',
                'name': '尿液样本D4',
                'sample_type': '尿液',
                'required_temp_zone': 'AMBIENT',
                'operator': '赵六',
                'operator_role': 'LAB_TECHNICIAN',
                'remark': '常规尿检样本'
            }
        ]

        created_samples = []
        for s in samples:
            try:
                sample = sample_service.register_sample(
                    sample_code=s['sample_code'],
                    name=s['name'],
                    sample_type=s['sample_type'],
                    required_temp_zone=s['required_temp_zone'],
                    operator=s['operator'],
                    operator_role=s['operator_role'],
                    remark=s['remark']
                )
                created_samples.append(sample)
                print(f"✓ 已创建样本: {sample.sample_code} - {sample.name}")
            except Exception as e:
                print(f"✗ 创建样本 {s['sample_code']} 失败: {e}")

        print()
        print("=" * 60)
        locations = location_service.list_locations()
        print(f"已加载库位: {len(locations)} 个")
        for loc in locations:
            print(f"  - {loc.code}: {loc.name} ({loc.temp_zone})")

        print()
        print("=" * 60)
        print("种子数据加载完成！")
        print(f"  样本数量: {len(created_samples)}")
        print(f"  库位数量: {len(locations)}")
        print("=" * 60)
        print()
        print("示例流程提示:")
        print(f"  1. 样本 SMP-2026-0001 (冷藏) 可入库到 REF-001 或 REF-002")
        print(f"  2. 样本 SMP-2026-0002 (冷冻) 可入库到 FRZ-001")
        print(f"  3. 样本 SMP-2026-0003 (深冻) 可入库到 DEEP-001")
        print(f"  4. 样本 SMP-2026-0004 (常温) 可入库到 AMB-001 或 AMB-002")


if __name__ == '__main__':
    seed_data()
