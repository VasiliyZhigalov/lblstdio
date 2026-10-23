from datetime import datetime
from pathlib import Path
from uuid import UUID
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, update
from app.presentation.dependencies import get_session
from app.infrastructure.db.tables import TrainingJobRow, ModelVersionRow, ProjectRow, DatasetVersionRow
from app.infrastructure.db.repositories.training_job_repository import _from_row
from app.presentation.api.v1.training_router import _job_to_read

router=APIRouter(tags=["model-lab"])

class Policy(BaseModel):
    collection_start: str=Field(default="07:00",pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    collection_end: str=Field(default="18:00",pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    training_start: str=Field(default="18:00",pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    training_end: str=Field(default="07:00",pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    @model_validator(mode="after")
    def windows(self):
        if self.collection_start==self.collection_end or self.training_start==self.training_end:
            raise ValueError("Начало и конец окна должны различаться")
        return self

@router.get("/compute-schedule")
async def schedule(request: Request):
    scheduler=request.app.state.compute_schedule
    return {**scheduler.settings,"server_time":datetime.now().astimezone().isoformat(),"timezone":str(datetime.now().astimezone().tzinfo),"gpu_busy":scheduler.streams.training,"error":scheduler.error}

@router.put("/compute-schedule")
async def save_schedule(payload: Policy,request: Request):
    await request.app.state.compute_schedule.save(payload.model_dump())
    return await schedule(request)

class Active(BaseModel):
    active: bool

@router.put("/projects/{project_id}/models/{model_id}/active")
async def activate(project_id: UUID,model_id: UUID,payload: Active,request: Request,session=Depends(get_session)):
    model=await session.get(ModelVersionRow,str(model_id))
    if not model or model.project_id!=str(project_id):raise HTTPException(404,"Модель не найдена")
    if payload.active and not Path(request.app.state.storage.get_absolute_path(model.weights_path)).is_file():raise HTTPException(422,"Файл весов модели отсутствует")
    model.is_active_for_stream=int(payload.active)
    await session.commit()
    return {"id":model.id,"is_active_for_stream":bool(model.is_active_for_stream)}

@router.get("/training-queue")
async def queue(project_id: UUID | None=None,session=Depends(get_session)):
    q=select(TrainingJobRow,ProjectRow.name).join(ProjectRow,ProjectRow.id==TrainingJobRow.project_id)
    if project_id:q=q.where(TrainingJobRow.project_id==str(project_id))
    rows=(await session.execute(q.order_by(TrainingJobRow.created_at.desc()).limit(100))).all()
    return [{**_job_to_read(_from_row(row)).model_dump(mode="json"),"project_name":name} for row,name in rows]

@router.post("/training-queue/{job_id}/cancel")
async def cancel(job_id: UUID,session=Depends(get_session)):
    result=await session.execute(update(TrainingJobRow).where(TrainingJobRow.id==str(job_id),TrainingJobRow.status=="QUEUED").values(status="FAILED",error_message="Отменено пользователем до запуска",finished_at=datetime.now().astimezone()))
    if not result.rowcount:raise HTTPException(409,"Можно отменить только ожидающее задание")
    await session.commit()
    return {"cancelled":True}

@router.get("/projects/{project_id}/models/{model_id}/details")
async def details(project_id: UUID,model_id: UUID,session=Depends(get_session)):
    model=await session.get(ModelVersionRow,str(model_id))
    if not model or model.project_id!=str(project_id):raise HTTPException(404,"Модель не найдена")
    job=await session.get(TrainingJobRow,model.training_job_id) if model.training_job_id else None
    dataset=await session.get(DatasetVersionRow,model.dataset_version_id) if model.dataset_version_id else None
    return {"training":_job_to_read(_from_row(job)).model_dump(mode="json") if job else None,"dataset": {"id":dataset.id,"name":dataset.name,"version_number":dataset.version_number,"test_count":dataset.test_count} if dataset else None,"test_metrics":model.test_metrics,"class_metadata":model.class_metadata}


class Preview(BaseModel):
    image_id: UUID
    confidence_threshold: float=Field(default=.45,ge=.01,le=.95)
    iou_threshold: float=Field(default=.7,ge=.01,le=.95)

@router.post("/projects/{project_id}/models/{model_id}/preview")
async def preview(project_id: UUID,model_id: UUID,payload: Preview,request: Request,session=Depends(get_session)):
    import asyncio
    from app.infrastructure.db.tables import ImageRow, ClassRow
    model=await session.get(ModelVersionRow,str(model_id))
    image=await session.get(ImageRow,str(payload.image_id))
    project=await session.get(ProjectRow,str(project_id))
    if not model or model.project_id!=str(project_id) or not image or image.project_id!=str(project_id) or image.deleted_at:raise HTTPException(404,"Модель или изображение не найдены в проекте")
    storage=request.app.state.storage
    weights=storage.get_absolute_path(model.weights_path);path=storage.get_absolute_path(image.file_path)
    if not Path(weights).is_file() or not Path(path).is_file():raise HTTPException(422,"Файл весов или изображения отсутствует")
    classes=list(await session.scalars(select(ClassRow).where(ClassRow.project_id==str(project_id))))
    by_index={c.index_id:c.name for c in classes};by_id={c.id:c.name for c in classes}
    mapping=(model.class_metadata or {}).get('class_mapping') or {}
    def name(index):return by_id.get(mapping.get(str(index)),by_index.get(index,str(index)))
    async with request.app.state.compute_schedule.inference_slot(None):
        if project.task_type=='CLASSIFICATION':
            result=await asyncio.to_thread(request.app.state.classification_predictor.predict,weights,[path],payload.confidence_threshold)
            label=result.get(path)
            return {"boxes":[],"label":{"name":name(label.class_index),"confidence":label.confidence} if label else None}
        result=await asyncio.to_thread(request.app.state.model_predictor.predict,weights,[path],payload.confidence_threshold,payload.iou_threshold)
        return {"boxes":[{"name":name(b.class_index),"confidence":b.confidence,"x_center":b.x_center,"y_center":b.y_center,"width":b.width,"height":b.height} for b in result.get(path,[])]}
