# syntax=docker/dockerfile:1
# Spark 3.5.8 (Scala 2.12, Hadoop 3.3.4 client) with Python 3.
FROM apache/spark:3.5.8-python3

# Java libraries, downloaded ONCE at build time (not at every run):
#   - Delta Lake 3.3.2 (built for Spark 3.5)
#   - hadoop-aws 3.3.4 = S3A client matching Spark's Hadoop 3.3.4, + the AWS SDK it was built with
ARG MAVEN=https://repo1.maven.org/maven2
ADD --chmod=644 ${MAVEN}/io/delta/delta-spark_2.12/3.3.2/delta-spark_2.12-3.3.2.jar /opt/spark/jars/
ADD --chmod=644 ${MAVEN}/io/delta/delta-storage/3.3.2/delta-storage-3.3.2.jar /opt/spark/jars/
ADD --chmod=644 ${MAVEN}/org/apache/hadoop/hadoop-aws/3.3.4/hadoop-aws-3.3.4.jar /opt/spark/jars/
ADD --chmod=644 ${MAVEN}/com/amazonaws/aws-java-sdk-bundle/1.12.262/aws-java-sdk-bundle-1.12.262.jar /opt/spark/jars/

USER root
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY run.py ./
# Ubuntu 22.04's pip/setuptools are too old for a PEP 621 pyproject.toml: they built an empty
# "UNKNOWN-0.0.0" package (no code, no boto3). Upgrade them first, then install into a fixed folder.
RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel \
 && python3 -m pip install --no-cache-dir --target /opt/lake-deps . \
 && PYTHONPATH=/opt/lake-deps python3 -c "import kaarangepay_lake, boto3; print('lake deps OK')"
ENV PYTHONPATH=/opt/lake-deps
USER spark

# spark-submit puts PySpark on the Python path and starts the JVM with the right memory.
ENTRYPOINT ["/opt/spark/bin/spark-submit", "--master", "local[*]", "--driver-memory", "2g", "/app/run.py"]
CMD ["silver"]
