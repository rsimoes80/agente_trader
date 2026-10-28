FROM python:3.14-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY diagnostic_server.py /app/
COPY src /app/src
CMD ["python", "-u", "diagnostic_server.py"]
