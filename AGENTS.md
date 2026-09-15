# AGENTS.md — lblstdio

Active Learning CV-платформа: разметка изображений, версии датасетов, обучение YOLO, авторазметка и верификация (HITL).

## Каталог

```
lblstdio/
├── backend/app/
│   ├── domain/           # сущности, VO, enums, доменные сервисы
│   ├── application/      # use cases, ports (репозитории, ML, storage)
│   ├── infrastructure/   # DB, ML (Ultralytics), storage, SIFT
│   └── presentation/     # FastAPI routers, schemas, dependencies
├── backend/tests/        # unit / integration / e2e
├── frontend/             # vanilla JS UI (canvas, api, components)
└── docs/                 # arh.md, back.md, front.md, model.md, plan.md
```

| Слой | Куда смотреть |
|------|----------------|
| API | `backend/app/presentation/api/v1/` |
| Бизнес-логика | `backend/app/application/use_cases/` |
| Контракты | `backend/app/application/ports/` |
| Домен | `backend/app/domain/` |
| ML | `backend/app/infrastructure/ml/` |
| UI | `frontend/js/` |

Архитектура: Clean Architecture / hexagonal — зависимости внутрь, к `domain`.

## Brainstorming и планы

При skill **brainstorming**:

- **Мелкие задачи** (багфикс, точечный рефакторинг, один endpoint/компонент, правка тестов) — **не** писать отдельную спецификацию и **не** составлять formal plan. Это избыточно: сразу реализация.
- Спеки и планы — только для крупных фич, архитектурных изменений или многошаговых задач с неочевидным дизайном.

## Практика для агентов

- Менять только то, что нужно для задачи; не трогать незатронутый код и не плодить лишние markdown-файлы.
- Коммиты и PR — только по явной просьбе пользователя.
- Тесты рядом с существующей структурой `backend/tests/`.
- Подробности продукта и потока: `docs/arh.md`.
