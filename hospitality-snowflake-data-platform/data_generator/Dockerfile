FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY data_generator ./data_generator
RUN pip install --no-cache-dir '.[parquet]'
ENTRYPOINT ["sh", "-c", "python -m data_generator.generate_file_data --scale $DATA_SCALE --seed $DATA_SEED"]

