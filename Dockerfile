FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev
COPY snowden/ snowden/
COPY scripts/ scripts/
CMD ["uv", "run", "python", "-m", "scripts.paper_trade"]
