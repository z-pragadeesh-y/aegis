FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir filelock
COPY execute_action.py /app/execute_action.py
CMD ["python", "execute_action.py"]
