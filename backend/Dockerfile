FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# Keep the same repository layout used by the application.  ScriptLoader and
# the public-image mount resolve the project root from __file__.
WORKDIR /workspace/backend
COPY backend/requirements.txt /workspace/backend/requirements.txt
RUN pip install \
    --no-cache-dir \
    --timeout 120 \
    --retries 5 \
    --index-url https://mirrors.aliyun.com/pypi/simple \
    -r /workspace/backend/requirements.txt
COPY backend/app /workspace/backend/app
COPY content /workspace/content
COPY public /workspace/public
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
