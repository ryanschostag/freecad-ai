FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml /app/pyproject.toml
COPY app /app/app
RUN pip install --no-cache-dir -U pip && pip install --no-cache-dir -e .
EXPOSE 8070
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8070"]
