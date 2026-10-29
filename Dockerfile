FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159
WORKDIR /app
COPY sources.py catalog.py matching.py server.py ./
COPY plugins/plex/ plugins/plex/
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 CACHE_PATH=/data/cache.db
RUN mkdir -p /data && chown 10001:10001 /data
USER 10001:10001
EXPOSE 3000
CMD ["python", "server.py"]
