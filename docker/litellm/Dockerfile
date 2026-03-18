FROM python:3.11-slim
WORKDIR /app
COPY run_litellm.py /app/
COPY preload_models.py /app/
COPY run.sh /app/
RUN apt-get update && apt-get install -y --no-install-recommends \
		git \
		wget \
	&& rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir fastapi uvicorn litellm httpx huggingface_hub
RUN chmod +x /app/run.sh
EXPOSE 11435
ENTRYPOINT ["/app/run.sh"]
