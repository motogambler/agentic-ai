FROM python:3.11-slim
WORKDIR /app
COPY run_litellm.py /app/
RUN pip install --no-cache-dir fastapi uvicorn litellm httpx
EXPOSE 11435
CMD ["uvicorn", "run_litellm:app", "--host", "0.0.0.0", "--port", "11435"]
