from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4
import pytest
from app.infrastructure.compute_schedule import in_window, ScheduledStreamRunner
from app.application.ports.services.stream_runner import StreamStatus

@pytest.mark.parametrize("hour,minute,collection,training",[(6,59,False,True),(7,0,True,False),(17,59,True,False),(18,0,False,True),(23,59,False,True),(0,0,False,True)])
def test_window_boundaries(hour,minute,collection,training):
    at=datetime(2026,10,22,hour,minute)
    assert in_window('07:00','18:00',at)==collection
    assert in_window('18:00','07:00',at)==training

class Runner:
    def __init__(self):self.status={};self.starts=0;self.stops=0
    def start(self,stream,weights,**kwargs):self.status[stream.id]=StreamStatus(True,'running');self.starts+=1
    def stop(self,sid):self.status[sid]=StreamStatus(False,'stopped');self.stops+=1
    def get_status(self,sid):return self.status.get(sid,StreamStatus(False,'stopped'))
    def wait_until_ready(self,sid,timeout=30):return self.get_status(sid)
    def update_triggers(self,*args,**kwargs):pass

def test_stream_waits_then_resumes_without_mutating_runner_status(monkeypatch):
    import app.infrastructure.compute_schedule as mod
    raw=Runner();runner=ScheduledStreamRunner(raw,{'collection_start':'07:00','collection_end':'18:00'})
    stream=SimpleNamespace(id=uuid4(),project_id=uuid4())
    allowed=False
    monkeypatch.setattr(mod,'in_window',lambda *args:allowed)
    runner.start(stream,'weights')
    assert runner.get_status(stream.id).state=='scheduled'
    assert raw.get_status(stream.id).state=='stopped'
    allowed=True;runner.reconcile()
    assert raw.starts==1 and runner.get_status(stream.id).is_running
    runner.training=True;runner.reconcile()
    assert runner.get_status(stream.id).state=='waiting_gpu'
    assert raw.get_status(stream.id).state=='stopped'
    runner.training=False;runner.reconcile()
    assert raw.starts==2
    runner.stop(stream.id);runner.reconcile()
    assert raw.starts==2


@pytest.mark.asyncio
async def test_gpu_admission_serializes_jobs_and_resumes_collection(monkeypatch):
    import asyncio
    import app.infrastructure.compute_schedule as mod
    from app.infrastructure.compute_schedule import ComputeSchedule
    monkeypatch.setattr(mod,'in_window',lambda *args:True)
    raw=Runner();scheduler=ComputeSchedule(None,raw)
    stream=SimpleNamespace(id=uuid4(),project_id=uuid4())
    scheduler.streams.start(stream,'weights')
    started=asyncio.Event();entered=asyncio.Event()
    async def second():
        started.set()
        async with scheduler.inference_slot(None):entered.set()
    async with scheduler.inference_slot(None):
        assert not raw.get_status(stream.id).is_running
        assert scheduler.streams.get_status(stream.id).state=='waiting_gpu'
        task=asyncio.create_task(second())
        await started.wait()
        assert not entered.is_set()
    await task
    assert entered.is_set()
    assert raw.get_status(stream.id).is_running
    assert scheduler.streams.training is False
