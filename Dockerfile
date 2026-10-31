FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends g++ cmake make binutils python3 ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY CMakeLists.txt ./
COPY engine/ engine/
COPY examples/ examples/
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug && cmake --build build -j2
COPY workbench/ workbench/
COPY tests/ tests/
EXPOSE 8765
CMD ["python3", "workbench/server.py", "--bind", "0.0.0.0"]
