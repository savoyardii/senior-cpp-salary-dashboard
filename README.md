# C++ salary market dashboard

Публичный интерактивный обзор вакансий Senior C++ для России, Лондона и Швейцарии.

## Автоматическое обновление

GitHub Actions запускает обновление каждый понедельник в 09:00 по Москве, а также после изменений в `main` и вручную из вкладки Actions. Workflow собирает вакансии, применяет правила фильтрации и дедупликации кодом, пересобирает страницу, коммитит новый снимок и публикует GitHub Pages. ИИ при сборе и расчётах не используется.

Для Headcount Labs и SuperJob в `Settings → Secrets and variables → Actions` нужны secrets:

- `HEADCOUNTLABS_API_KEY`
- `SUPERJOB_APP_SECRET`

Если ключи не заданы, workflow продолжит обновлять публичные источники без этих API, сохраняя последний успешный снимок API.

## Локальный запуск

```sh
python3 work/api_connector/refresh.py
```

API-ключи задаются в `work/api_connector/.env` на локальном устройстве или через переменные окружения. Файл `.env` исключён из Git.
