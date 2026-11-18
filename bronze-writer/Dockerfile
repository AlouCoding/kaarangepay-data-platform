FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
USER nobody
ENTRYPOINT ["bronze-writer"]
CMD ["run"]
