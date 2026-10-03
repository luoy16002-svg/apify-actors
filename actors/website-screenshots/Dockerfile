FROM apify/actor-python-playwright:3.13-1.55.0

WORKDIR /usr/src/app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY --chown=myuser:myuser requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY --chown=myuser:myuser . ./
CMD ["python", "-m", "src"]
