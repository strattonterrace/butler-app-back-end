web: gunicorn butler_api.wsgi:application --bind 0.0.0.0:$PORT --workers 3 --timeout 60
release: python manage.py migrate --noinput
