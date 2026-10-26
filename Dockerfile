# 运行时零第三方依赖，所以镜像很小；这是个可选交付物，不是必需品。
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY cmon ./cmon
COPY config ./config
COPY pyproject.toml README.md ./

# 默认离线跑一个场景，验证镜像可用；真实使用时挂载 .env 覆盖配置
RUN python -c "import cmon, cmon.pipeline; print('cmon ok')"

CMD ["python", "-m", "cmon", "run", "--scenario", "price-drop", "--offline"]