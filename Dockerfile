# 自托管镜像：NAS/服务器容器化部署（x86_64 优先，arm64 best-effort）
# 系统层补三样：CJK 字体（Pillow 图表/headless 渲染缺字即豆腐块）、
# libatomic1（playwright 1.65 内置 node 的硬依赖；缺它 node 起不来，
# `--with-deps` 也就跑不到——实测 exit 127 / libatomic.so.1），
# 其余 chromium 运行时依赖由 `playwright install --with-deps` 自装。
FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk fontconfig \
       libatomic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
# chromium 预装进镜像（首启免下载；ensure_chromium 检测到在场即跳过）
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY . .

# 运行时可变状态全部落卷（config.yaml 以文件挂载，不入镜像）
VOLUME ["/app/data", "/app/logs", "/app/user_data", "/app/debug"]

ENV PYTHONUNBUFFERED=1
# 容器语境服务必须绑 0.0.0.0 才可被 -p 端口映射触达（绑回环曾让
# CI 冒烟 curl 与 NAS compose 双双不可达）；config 显式 host 仍最优先
ENV TM_WEB_HOST=0.0.0.0
EXPOSE 8765

HEALTHCHECK --interval=60s --timeout=10s --start-period=90s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/state', timeout=8)"]

CMD ["python", "main.py"]
