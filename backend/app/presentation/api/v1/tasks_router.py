from datetime import timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import case, select

from app.infrastructure.db.tables import (
    AnnotationAuditJobRow, AutoLabelJobRow, DataImportRow, ProjectRow, TrainingJobRow,
)
from app.presentation.dependencies import get_session

router = APIRouter(tags=['tasks'])


def _time(value):
    if value is None: return None
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)).isoformat()


def _status(status):
    return {
        'PENDING': 'QUEUED', 'QUEUED': 'QUEUED', 'CHECKING': 'RUNNING',
        'RUNNING': 'RUNNING', 'PREVIEW': 'ACTION_REQUIRED',
        'COMPLETED': 'COMPLETED', 'FAILED': 'FAILED',
        'CANCELLED': 'CANCELLED', 'ROLLED_BACK': 'CANCELLED',
    }.get(status, status)


@router.get('/tasks')
async def list_tasks(request: Request, limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0, le=5000), session=Depends(get_session)):
    """Present durable task types together without changing their lifecycle."""
    results = []
    for table in (TrainingJobRow, AutoLabelJobRow, AnnotationAuditJobRow, DataImportRow):
        query = select(table, ProjectRow.name).join(ProjectRow, ProjectRow.id == table.project_id)
        active = table.status.in_(['PENDING', 'QUEUED', 'CHECKING', 'RUNNING', 'CANCELLING', 'PREVIEW'])
        rows = (await session.execute(query.order_by(case((active, 0), else_=1), table.created_at.desc(), table.id.desc()).limit(offset + limit + 1))).all()
        for row, name in rows:
            base = {'id': row.id, 'project_id': row.project_id, 'project_name': name,
                    'status': _status(row.status), 'raw_status': row.status,
                    'created_at': _time(row.created_at), 'finished_at': _time(getattr(row, 'finished_at', None)),
                    'error': getattr(row, 'error_message', None) or getattr(row, 'error', None)}
            if isinstance(row, TrainingJobRow):
                base.update(kind='training', title='Обучение модели', processed=row.current_epoch, total=row.epochs,
                            unit='эпох', result_id=row.model_version_id, schedule_mode=row.schedule_mode,
                            not_before=_time(row.not_before), stopped_early=bool(row.stopped_early))
            elif isinstance(row, AutoLabelJobRow):
                base.update(kind='auto_label', title='Авторазметка', processed=row.total_images_processed,
                            total=len(row.image_ids_json or []), unit='кадров', predictions=row.total_predictions_generated,
                            result_id=row.model_version_id)
            elif isinstance(row, AnnotationAuditJobRow):
                base.update(kind='audit', title='Проверка разметки', processed=row.processed_images,
                            total=row.total_images, unit='кадров', suspicious=row.suspicious_images)
            else:
                detail = request.app.state.data_imports.display_job(row)
                kind = 'dataset' if row.kind == 'dataset_build' else 'quality' if row.kind == 'quality' else 'import'
                title = 'Создание датасета: ' + row.name if kind == 'dataset' else 'Анализ качества изображений' if kind == 'quality' else 'Импорт: ' + row.name
                base.update(kind=kind, import_kind=row.kind, title=title,
                            processed=detail['processed'], total=detail['total'], unit='кадров' if kind == 'dataset' else 'файлов', summary=row.summary or {})
            results.append(base)
    results.sort(key=lambda item: (item['status'] in {'RUNNING', 'QUEUED', 'ACTION_REQUIRED'}, item['created_at'] or '', item['id']), reverse=True)
    return {'items': results[offset:offset + limit], 'has_more': len(results) > offset + limit}
