# syntax=docker/dockerfile:1

FROM python:3.11-slim

RUN --mount=source=requirements.txt,target=/tmp/requirements.txt \
    pip install -r /tmp/requirements.txt

WORKDIR /artifact

# Load queries snapshot
COPY queries queries

# Load corpus snapshot
ADD corpus.tgz .

# Includes stsearch source
COPY --from=stsearch /stsearch stsearch
RUN ln stsearch/target/release/stsearch /bin

# Add benchmarking suite
COPY stbench stbench

ENTRYPOINT [ "python", "-m", "stbench" ]
CMD ["-h"]
