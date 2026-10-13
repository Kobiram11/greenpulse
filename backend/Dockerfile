FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
RUN useradd -u 10001 -m app && mkdir -p /app/data && chown app:app /app/data
USER app
CMD ["python", "main.py"]
