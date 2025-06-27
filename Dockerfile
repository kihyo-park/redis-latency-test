FROM python:3.9-slim

WORKDIR /redis-latency-test

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "connect.py"]