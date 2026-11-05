# App with Reverse Proxy and Database

Production-like приложение с инфраструктурой на Docker, Ansible и GitLab CI.

## Архитектура
- Клиент
↓
- Frontend Nginx (статика + SSL)
↓
- Backend Nginx (reverse proxy)
↓
- FastAPI (backend)
↓
- PostgreSQL

Всё поднимается через Docker Compose и полностью автоматизировано Ansible.

## Что реализовано

- **Multi-stage builds** — финальный образ на `python:slim`, минимальный размер
- **Non-root пользователь** внутри контейнера
- **Docker Secrets** — пароли не хранятся в переменных окружения
- **Healthchecks** — backend ждёт готовности PostgreSQL (`pg_isready`)
- **Named volumes** — данные БД сохраняются между перезапусками
- **Ansible roles + Jinja2** — полное развёртывание одной командой
- **GitLab CI** — линтинг, тесты, сборка образов и деплой (DAG через `needs`)

- Cтруктура репозитория
  
├── app/                  # код приложения
├── roles/                # Ansible-роли
├── group_vars/           # переменные
├── playbook.yml          # главный playbook
├── hosts.ini             # inventory
├── .gitlab-ci.yml        # CI/CD пайплайн
└── ansible.cfg


## 📈 Планы по развитию проекта (Roadmap)

*   [x] **IaC (Infrastructure as Code):** Написание Ansible-плейбуков для автоматического развертывания Docker-окружения на удаленных серверах (VPS).
*   [ ] **Observability:** Интеграция Prometheus и Node Exporter для сбора метрик хоста и контейнеров.
*   [ ] **Dashboards:** Настройка Grafana для визуализации утилизации ресурсов (CPU, RAM, Disk I/O) и логирования.

## Запуск проекта:

Для этого понадобиться лишь одна команда

`ansible-playbook playbook.yml`
