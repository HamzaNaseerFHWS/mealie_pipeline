FROM python:3.12-slim
WORKDIR /app
COPY bot.py .
ENV PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8765
CMD ["python", "bot.py"]
