from uuid import UUID

import asyncio

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from fastapi.responses import StreamingResponse

from app.application.use_cases.streaming.control_stream import (
    GetStreamStatusUseCase,
    StartStreamUseCase,
    StopStreamUseCase,
)
from app.application.use_cases.streaming.manage_stream_source import ManageStreamSourceUseCase
from app.domain.enums import TripwireDirection
from app.domain.value_objects.stream_trigger_config import StreamTriggerConfig
from app.presentation.dependencies import (
    get_manage_stream_source_use_case,
    get_start_stream_use_case,
    get_stop_stream_use_case,
    get_stream_runner,
    get_stream_status_use_case,
)
from app.presentation.schemas import (
    StreamDeviceCreate,
    StreamRtspCreate,
    StreamSourceRead,
    StreamStatusRead,
    StreamTriggerConfigPayload,
    StreamTriggersUpdate,
)

router = APIRouter(tags=["streams"])


def _config_to_payload(config: StreamTriggerConfig) -> StreamTriggerConfigPayload:
    return StreamTriggerConfigPayload(
        timer_enabled=config.timer_enabled,
        timer_interval_seconds=config.timer_interval_seconds,
        tripwire_enabled=config.tripwire_enabled,
        tripwire_line=config.tripwire_line,
        tripwire_classes=list(config.tripwire_classes),
        tripwire_direction=config.tripwire_direction.value,
        tripwire_debounce_seconds=config.tripwire_debounce_seconds,
        uncertainty_range=config.uncertainty_range,
        cooldown_seconds=config.cooldown_seconds,
    )


def _stream_to_read(stream) -> StreamSourceRead:
    return StreamSourceRead(
        id=stream.id,
        project_id=stream.project_id,
        name=stream.name,
        source_type=stream.source_type.value,
        source_uri=stream.source_uri,
        is_active=stream.is_active,
        model_version_id=stream.model_version_id,
        config=_config_to_payload(stream.config),
        captured_frames_count=stream.captured_frames_count,
        created_at=stream.created_at,
    )


def _payload_to_config(payload: StreamTriggerConfigPayload) -> StreamTriggerConfig:
    return StreamTriggerConfig(
        timer_enabled=payload.timer_enabled,
        timer_interval_seconds=payload.timer_interval_seconds,
        tripwire_enabled=payload.tripwire_enabled,
        tripwire_line=payload.tripwire_line,
        tripwire_classes=tuple(payload.tripwire_classes),
        tripwire_direction=TripwireDirection(payload.tripwire_direction),
        tripwire_debounce_seconds=payload.tripwire_debounce_seconds,
        uncertainty_range=payload.uncertainty_range,
        cooldown_seconds=payload.cooldown_seconds,
    )


@router.get("/projects/{project_id}/streams", response_model=list[StreamSourceRead])
async def list_streams(
    project_id: UUID,
    use_case: ManageStreamSourceUseCase = Depends(get_manage_stream_source_use_case),
) -> list[StreamSourceRead]:
    items = await use_case.list_by_project(project_id)
    return [_stream_to_read(item) for item in items]


@router.post(
    "/projects/{project_id}/streams/rtsp",
    response_model=StreamSourceRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_rtsp_stream(
    project_id: UUID,
    payload: StreamRtspCreate,
    use_case: ManageStreamSourceUseCase = Depends(get_manage_stream_source_use_case),
) -> StreamSourceRead:
    stream = await use_case.create_rtsp(project_id, payload.name, payload.rtsp_url)
    return _stream_to_read(stream)


@router.post(
    "/projects/{project_id}/streams/device",
    response_model=StreamSourceRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_device_stream(
    project_id: UUID,
    payload: StreamDeviceCreate,
    use_case: ManageStreamSourceUseCase = Depends(get_manage_stream_source_use_case),
) -> StreamSourceRead:
    stream = await use_case.create_device(project_id, payload.name, payload.device_index)
    return _stream_to_read(stream)


@router.post(
    "/projects/{project_id}/streams/upload-video",
    response_model=StreamSourceRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_video_stream(
    project_id: UUID,
    file: UploadFile = File(...),
    name: str = Form(""),
    use_case: ManageStreamSourceUseCase = Depends(get_manage_stream_source_use_case),
) -> StreamSourceRead:
    data = await file.read()
    stream = await use_case.upload_video(
        project_id,
        name or (file.filename or "video"),
        file.filename or "video.mp4",
        data,
    )
    return _stream_to_read(stream)


@router.put("/streams/{stream_id}/triggers", response_model=StreamSourceRead)
async def update_stream_triggers(
    stream_id: UUID,
    payload: StreamTriggersUpdate,
    use_case: ManageStreamSourceUseCase = Depends(get_manage_stream_source_use_case),
) -> StreamSourceRead:
    stream = await use_case.configure_triggers(
        stream_id,
        _payload_to_config(payload.config),
        model_version_id=payload.model_version_id,
    )
    return _stream_to_read(stream)


@router.delete("/streams/{stream_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_stream(
    stream_id: UUID,
    use_case: ManageStreamSourceUseCase = Depends(get_manage_stream_source_use_case),
) -> Response:
    await use_case.delete(stream_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/streams/{stream_id}/start", response_model=StreamSourceRead)
async def start_stream(
    stream_id: UUID,
    use_case: StartStreamUseCase = Depends(get_start_stream_use_case),
) -> StreamSourceRead:
    stream = await use_case.execute(stream_id)
    return _stream_to_read(stream)


@router.post("/streams/{stream_id}/stop", response_model=StreamSourceRead)
async def stop_stream(
    stream_id: UUID,
    use_case: StopStreamUseCase = Depends(get_stop_stream_use_case),
) -> StreamSourceRead:
    stream = await use_case.execute(stream_id)
    return _stream_to_read(stream)


@router.get("/streams/{stream_id}/status", response_model=StreamStatusRead)
async def stream_status(
    stream_id: UUID,
    use_case: GetStreamStatusUseCase = Depends(get_stream_status_use_case),
) -> StreamStatusRead:
    status_obj = await use_case.execute(stream_id)
    return StreamStatusRead(
        is_running=status_obj.is_running,
        state=status_obj.state,
        fps=status_obj.fps,
        captured_count=status_obj.captured_count,
        last_capture_at=status_obj.last_capture_at,
        error_message=status_obj.error_message,
    )


@router.get("/streams/{stream_id}/live")
async def stream_live(
    stream_id: UUID,
    runner=Depends(get_stream_runner),
):
    async def gen():
        while True:
            jpeg = runner.latest_jpeg(stream_id)
            if jpeg:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                )
            await asyncio.sleep(0.07)

    return StreamingResponse(
        gen(), media_type="multipart/x-mixed-replace; boundary=frame"
    )
