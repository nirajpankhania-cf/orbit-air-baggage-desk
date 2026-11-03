# STRETCH GOAL 4
# Builds an image that runs the test suite during the build and then
# serves the CLI as its entrypoint.
#
#   docker build -t orbit-air .                 # fails if tests or lint fail
#   docker run --rm orbit-air list              # run any command
#   docker run --rm orbit-air --now 2026-11-02T14:00:00 escalate
#   docker run --rm --entrypoint pytest orbit-air -q   # run the tests again

FROM python:3.12-slim

WORKDIR /app

COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY . .

RUN ruff check . && pytest -q

ENTRYPOINT ["python", "main.py"]
CMD ["--help"]
