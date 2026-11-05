import io
import sqlite3
import time
from datetime import datetime,timezone,timedelta
from pathlib import Path
from uuid import uuid4
from PIL import Image
from fastapi.testclient import TestClient
from app.main import create_app
from app.application.ports.services.model_trainer import TrainingResult

class Trainer:
    def train(self,config,on_epoch_end=None):
        best=Path(config.output_dir)/'run/weights/best.pt';best.parent.mkdir(parents=True,exist_ok=True);best.write_bytes(b'test')
        if on_epoch_end:on_epoch_end({'epoch':1,'map50':.8})
        return TrainingResult(best_weights_path=str(best),metrics_history=[{'epoch':1,'map50':.8}],map50=.8,map50_95=.6,precision=.9,recall=.8)

def seed(c):
    pid=c.post('/api/v1/projects',json={'name':'Night'}).json()['id']
    c.post(f'/api/v1/projects/{pid}/classes',json={'name':'Car','color_hex':'#123456'})
    data=io.BytesIO();Image.new('RGB',(64,48)).save(data,'PNG')
    images=c.post(f'/api/v1/projects/{pid}/images/upload',files=[('files',(f'{i}.png',data.getvalue(),'image/png')) for i in range(11)]).json()
    for image in images[:10]:assert c.post(f"/api/v1/images/{image['id']}/mark-background").status_code==200
    c.post(f'/api/v1/projects/{pid}/annotation-queue/enqueue',json={'ids':[images[-1]['id']]})
    version=c.post(f'/api/v1/projects/{pid}/dataset-versions',json={'name':'Ready despite queue'})
    assert version.status_code==201,version.text
    assert version.json()['train_count']+version.json()['valid_count']+version.json()['test_count']==10
    return pid,version.json()['id']

def test_deferred_training_persists_and_manual_activation(tmp_path):
    db=tmp_path/'app.db';kwargs={'database_url':f'sqlite+aiosqlite:///{db.as_posix()}','storage_root':tmp_path/'storage','training_trainer':Trainer()}
    future=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    with TestClient(create_app(auth_enabled=False, **kwargs)) as c:
        policy=c.get('/api/v1/compute-schedule').json()
        assert policy['collection_start']=='07:00' and policy['collection_end']=='18:00'
        assert c.put('/api/v1/compute-schedule',json={'collection_start':'25:00'}).status_code==422
        assert c.put('/api/v1/compute-schedule',json={'collection_start':'08:00','collection_end':'18:00','training_start':'19:00','training_end':'07:00'}).status_code==200
        pid,vid=seed(c)
        queued=c.post(f'/api/v1/projects/{pid}/train',json={'dataset_version_id':vid,'not_before':future,'epochs':1,'device':'cpu'}).json()
        assert queued['status']=='QUEUED' and queued['schedule_mode']=='night'
        jid=queued['id']
    with TestClient(create_app(auth_enabled=False, **kwargs)) as c:
        assert c.get('/api/v1/compute-schedule').json()['collection_start']=='08:00'
        assert c.get(f'/api/v1/training-jobs/{jid}').json()['status']=='QUEUED'
        assert c.post(f'/api/v1/training-queue/{jid}/cancel').status_code==200
        assert c.post(f'/api/v1/training-queue/{jid}/cancel').status_code==409
        now=c.post(f'/api/v1/projects/{pid}/train',json={'dataset_version_id':vid,'schedule_mode':'now','epochs':1,'device':'cpu'}).json()
        for _ in range(60):
            current=c.get(f"/api/v1/training-jobs/{now['id']}").json()
            if current['status'] in ['COMPLETED','FAILED']:break
            time.sleep(.05)
        assert current['status']=='COMPLETED',current
        mid=current['model_version_id']
        models=c.get(f'/api/v1/projects/{pid}/models').json()
        assert models[0]['is_active_for_stream'] is False
        assert c.put(f'/api/v1/projects/{pid}/models/{mid}/active',json={'active':True}).status_code==200
        assert c.get(f'/api/v1/projects/{pid}/models').json()[0]['is_active_for_stream'] is True
        assert c.get(f'/api/v1/projects/{pid}/models/{mid}/details').json()['training']['status']=='COMPLETED'
        assert any(j['model_version_id']==mid for j in c.get('/api/v1/training-queue').json())


def test_scheduled_source_is_restored_after_restart(tmp_path,monkeypatch):
    from app.infrastructure.streaming.opencv_stream_runner import FakeStreamRunner
    monkeypatch.setattr('app.infrastructure.compute_schedule.in_window',lambda *args:False)
    db=tmp_path/'restore.db';kwargs={'database_url':f'sqlite+aiosqlite:///{db.as_posix()}','storage_root':tmp_path/'storage'}
    with TestClient(create_app(auth_enabled=False, **kwargs,stream_runner=FakeStreamRunner())) as c:
        pid=c.post('/api/v1/projects',json={'name':'Scheduled camera'}).json()['id']
        stream=c.post(f'/api/v1/projects/{pid}/streams/rtsp',json={'name':'Camera','rtsp_url':'rtsp://127.0.0.1/example'}).json()
        sid=stream['id']
        assert c.put(f'/api/v1/streams/{sid}/triggers',json={'config':{'timer_enabled':True,'track_stable_enabled':False}}).status_code==200
        start=c.post(f'/api/v1/streams/{sid}/start')
        assert start.status_code==200,start.text
        assert start.json()['is_active'] is True
        assert c.get(f'/api/v1/streams/{sid}/status').json()['state']=='scheduled'
    with TestClient(create_app(auth_enabled=False, **kwargs,stream_runner=FakeStreamRunner())) as c:
        assert c.get(f'/api/v1/streams/{sid}/status').json()['state']=='scheduled'
        assert c.post(f'/api/v1/streams/{sid}/stop').json()['is_active'] is False
        assert c.get(f'/api/v1/streams/{sid}/status').json()['state']=='stopped'


def test_auto_label_result_is_queued_unconfirmed_and_preview_is_read_only(tmp_path):
    from tests.e2e.test_training_api import _FakePredictor
    app=create_app(auth_enabled=False, database_url=f"sqlite+aiosqlite:///{(tmp_path/'auto.db').as_posix()}",storage_root=tmp_path/'storage',training_trainer=Trainer(),predictor=_FakePredictor())
    with TestClient(app) as c:
        pid,vid=seed(c)
        job=c.post(f'/api/v1/projects/{pid}/train',json={'dataset_version_id':vid,'schedule_mode':'now','epochs':1,'device':'cpu'}).json()
        for _ in range(100):
            state=c.get(f"/api/v1/training-jobs/{job['id']}").json()
            if state['status'] in ['COMPLETED','FAILED']:break
            time.sleep(.05)
        assert state['status']=='COMPLETED',state
        mid=state['model_version_id']
        data=io.BytesIO();Image.new('RGB',(64,48)).save(data,'PNG')
        image=c.post(f'/api/v1/projects/{pid}/images/upload',files=[('files',('new.png',data.getvalue(),'image/png'))]).json()[0]
        auto=c.post(f'/api/v1/projects/{pid}/models/{mid}/auto-label',json={'all_unannotated':True,'enqueue_for_annotation':True}).json()
        for _ in range(100):
            state=c.get(f"/api/v1/auto-label-jobs/{auto['id']}").json()
            if state['status'] in ['COMPLETED','FAILED']:break
            time.sleep(.05)
        assert state['status']=='COMPLETED',state
        c.portal.call(app.state.compute_schedule.enqueue_completed_auto_labels)
        before=c.get(f"/api/v1/images/{image['id']}").json()
        assert before['status']=='IN_PROGRESS'
        assert before['annotations'][0]['verification_status']=='PENDING_REVIEW'
        preview=c.post(f'/api/v1/projects/{pid}/models/{mid}/preview',json={'image_id':image['id']})
        assert preview.status_code==200,preview.text
        assert preview.json()['boxes'][0]['name']=='Car'
        assert c.get(f"/api/v1/images/{image['id']}").json()['annotations']==before['annotations']
