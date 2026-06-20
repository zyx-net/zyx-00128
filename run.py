from app import create_app

app = create_app()

if __name__ == '__main__':
    print("=" * 60)
    print("实验室样本交接系统启动中...")
    print("服务地址: http://localhost:5000")
    print("API文档:   http://localhost:5000/api/docs")
    print("健康检查: http://localhost:5000/api/health")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=False)
