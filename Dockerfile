FROM python:3.11-slim

WORKDIR /app

COPY . .

# Avoid caching issues with dependencies
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Use `python3` to ensure version is correct
CMD ["python3", "bot.py"]
