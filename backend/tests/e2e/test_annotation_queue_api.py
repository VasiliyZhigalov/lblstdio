import io
from uuid import uuid4
from datetime import datetime, timedelta, timezone
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from app.main import create_app


@pytest.fixture
def fixture(tmp_path):
    app = create_app(database_url=f"sqlite+aiosqlite:///{(tmp_path/'app.db').as_posix()}", storage_root=tmp_path/'storage')
    with TestClient(app) as c:
        pid = c.post('/api/v1/projects', json={'name':'Queue'}).json()['id']
        cid = c.post(f'/api/v1/projects/{pid}/classes', json={'name':'Car','color_hex':'#123456'}).json()['id']
        data=io.BytesIO();Image.new('RGB',(64,48)).save(data,'PNG')
        images=c.post(f'/api/v1/projects/{pid}/images/upload',files=[('files',(f'{i}.png',data.getvalue(),'image/png')) for i in range(3)]).json()
        yield c,pid,cid,[i['id'] for i in images],tmp_path


def headers(token, revision=None):
    return {'X-Annotation-Session':token,**({'X-Annotation-Revision':str(revision)} if revision is not None else {})}


def test_queue_claim_revision_finish_and_other_session_protection(fixture):
    c,pid,cid,ids,_=fixture
    base=f'/api/v1/projects/{pid}/annotation-queue'
    a,b=str(uuid4()),str(uuid4())
    assert c.post(base+'/enqueue',json={'ids':ids}).json()['updated']==3
    task=c.post(base+'/claim',json={},headers=headers(a)).json()
    image=task['image_id']
    assert task['mine'] and not task['readonly']
    assert c.post(base+'/claim',json={},headers=headers(a)).json()['image_id']==image
    other=c.post(base+'/claim',json={},headers=headers(b)).json()
    assert other['image_id']!=image
    assert c.post(base+'/claim',json={'image_id':image},headers=headers(b)).status_code==409
    path=f'/api/v1/images/{image}/annotations'
    payload={'boxes':[{'class_id':cid,'x_center':.5,'y_center':.5,'width':.3,'height':.3}]}
    assert c.put(path,json=payload,headers=headers(b,0)).status_code==409
    good=c.put(path,json=payload,headers=headers(a,0))
    assert good.status_code==200,good.text
    assert good.headers['X-Annotation-Revision']=='1'
    assert c.get(f'/api/v1/images/{image}').json()['status']=='IN_PROGRESS'
    assert c.put(path,json=payload,headers=headers(a,0)).status_code==409
    action=base+f'/{image}/action'
    assert c.post(action,json={'action':'finish','revision':0},headers=headers(a)).status_code==409
    done=c.post(action,json={'action':'finish','revision':1},headers=headers(a))
    assert done.status_code==200 and done.json()['state']=='DONE',done.text
    assert c.get(f'/api/v1/images/{image}').json()['status']=='VERIFIED'
    assert c.put(path,json=payload,headers=headers(a,2)).status_code==409
    assert c.post(base+'/claim',json={'image_id':image},headers=headers(a)).status_code==409
    listing=c.get(base,headers=headers(a)).json()
    assert image not in [item['image_id'] for item in listing['items']]
    assert c.get(base+'?state=DONE',headers=headers(a)).json()['items']==[]
    assert c.post(base+'/enqueue',json={'ids':[image]}).json()['updated']==1
    assert not c.post(base+'/claim',json={'image_id':image},headers=headers(a)).json()['readonly']


def test_finish_needs_objects_skip_reason_and_live_tasks_survive_bulk(fixture):
    c,pid,cid,ids,_=fixture
    a=str(uuid4());base=f'/api/v1/projects/{pid}/annotation-queue'
    c.post(base+'/enqueue',json={'ids':ids})
    task=c.post(base+'/claim',json={},headers=headers(a)).json();image=task['image_id']
    assert c.post(base+f'/{image}/action',json={'action':'finish','revision':0},headers=headers(a)).status_code==422
    assert c.post(base+'/enqueue',json={'ids':[image]}).json()['updated']==0
    assert c.post(f'/api/v1/projects/{pid}/data/actions',json={'action':'trash','ids':[image]}).json()['updated']==0
    skip=c.post(base+f'/{image}/action',json={'action':'skip','revision':0},headers=headers(a))
    assert skip.status_code==200 and skip.json()['state']=='QUEUED'
    assert skip.json()['reason'] is None
    next_task=c.post(base+'/claim',json={},headers=headers(a)).json()
    assert next_task['image_id'] != image


def test_expired_lease_blocks_old_writer_and_can_be_reclaimed(fixture):
    import sqlite3
    c,pid,cid,ids,tmp=fixture
    a,b=str(uuid4()),str(uuid4());base=f'/api/v1/projects/{pid}/annotation-queue'
    c.post(base+'/enqueue',json={'ids':ids})
    task=c.post(base+'/claim',json={},headers=headers(a)).json();image=task['image_id']
    with sqlite3.connect(tmp/'app.db') as db: db.execute('UPDATE annotation_tasks SET lease_until=? WHERE image_id=?',((datetime.now(timezone.utc)-timedelta(seconds=1)).replace(tzinfo=None).isoformat(' '),image))
    assert c.post(base+f'/{image}/action',json={'action':'heartbeat','revision':0},headers=headers(a)).status_code==409
    assert c.post(base+'/claim',json={'image_id':image},headers=headers(b)).status_code==200
    assert c.post(base+f'/{image}/action',json={'action':'release','revision':0},headers=headers(a)).status_code==409


def test_concurrent_claims_receive_different_frames(fixture):
    from concurrent.futures import ThreadPoolExecutor
    c,pid,cid,ids,_=fixture
    base=f'/api/v1/projects/{pid}/annotation-queue'
    c.post(base+'/enqueue',json={'ids':ids})
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(lambda _:c.post(base+'/claim',json={},headers=headers(str(uuid4()))), range(3)))
    assert all(r.status_code==200 for r in results),[(r.status_code,r.text) for r in results]
    assert len({r.json()['image_id'] for r in results})==3


def test_classification_label_clear_preserves_revision_header(fixture):
    c,_,_,_,_=fixture
    pid=c.post('/api/v1/projects',json={'name':'Classification','task_type':'CLASSIFICATION'}).json()['id']
    cid=c.post(f'/api/v1/projects/{pid}/classes',json={'name':'On','color_hex':'#123456'}).json()['id']
    data=io.BytesIO();Image.new('RGB',(64,48)).save(data,'PNG')
    image=c.post(f'/api/v1/projects/{pid}/images/upload',files=[('files',('one.png',data.getvalue(),'image/png'))]).json()[0]['id']
    actor=str(uuid4());base=f'/api/v1/projects/{pid}/annotation-queue'
    c.post(base+'/enqueue',json={'ids':[image]})
    c.post(base+'/claim',json={},headers=headers(actor))
    path=f'/api/v1/images/{image}/label'
    first=c.put(path,json={'class_id':cid},headers=headers(actor,0))
    assert first.status_code==200 and first.headers['X-Annotation-Revision']=='1'
    cleared=c.delete(path,headers=headers(actor,1))
    assert cleared.status_code==204 and cleared.headers['X-Annotation-Revision']=='2'
    assert c.put(path,json={'class_id':cid},headers=headers(actor,2)).status_code==200
    assert c.post(base+f'/{image}/action',json={'action':'finish','revision':3},headers=headers(actor)).json()['state']=='DONE'


def test_finish_confirms_all_model_proposals_together(fixture):
    import sqlite3
    c,pid,cid,ids,root=fixture
    actor=str(uuid4()); image=ids[0]; base=f'/api/v1/projects/{pid}/annotation-queue'
    c.post(base+'/enqueue',json={'ids':[image]})
    c.post(base+'/claim',json={},headers=headers(actor))
    boxes=[{'class_id':cid,'x_center':x,'y_center':.5,'width':.2,'height':.2} for x in [.25,.75]]
    assert c.put(f'/api/v1/images/{image}/annotations',json={'boxes':boxes},headers=headers(actor,0)).status_code==200
    with sqlite3.connect(root/'app.db') as db:
        db.execute("UPDATE annotations SET verification_status='PENDING_REVIEW' WHERE image_id=?",(image,))
    result=c.post(base+f'/{image}/action',json={'action':'finish','revision':1},headers=headers(actor))
    assert result.status_code==200,result.text
    with sqlite3.connect(root/'app.db') as db:
        statuses=db.execute("SELECT verification_status FROM annotations WHERE image_id=?",(image,)).fetchall()
    assert statuses==[('VERIFIED',),('VERIFIED',)]


@pytest.mark.parametrize('action', ['clear', 'trash'])
def test_queue_clear_and_trash_remove_task_and_protect_ownership(fixture, action):
    import sqlite3
    c,pid,cid,ids,root=fixture
    actor,other=str(uuid4()),str(uuid4()); image=ids[0]
    base=f'/api/v1/projects/{pid}/annotation-queue'
    c.post(base+'/enqueue',json={'ids':[image]})
    c.post(base+'/claim',json={},headers=headers(actor))
    payload={'boxes':[{'class_id':cid,'x_center':.5,'y_center':.5,'width':.3,'height':.3}]}
    assert c.put(f'/api/v1/images/{image}/annotations',json=payload,headers=headers(actor,0)).status_code==200
    path=base+f'/{image}/action'
    assert c.post(path,json={'action':action,'revision':1},headers=headers(other)).status_code==409
    assert c.post(path,json={'action':action,'revision':0},headers=headers(actor)).status_code==409
    result=c.post(path,json={'action':action,'revision':1},headers=headers(actor))
    assert result.status_code==200,result.text
    assert result.json()['state']=='REMOVED'
    with sqlite3.connect(root/'app.db') as db:
        assert db.execute('SELECT count(*) FROM annotation_tasks WHERE image_id=?',(image,)).fetchone()[0]==0
        status,background,deleted=db.execute('SELECT status,is_background,deleted_at FROM images WHERE id=?',(image,)).fetchone()
        boxes=db.execute('SELECT count(*) FROM annotations WHERE image_id=?',(image,)).fetchone()[0]
    if action=='clear':
        assert status=='UNANNOTATED' and not background and deleted is None and boxes==0
    else:
        assert deleted is not None and boxes==1
    assert c.post(base+'/claim',json={},headers=headers(actor)).json()['image_id'] is None


def test_background_confirms_empty_frame_and_removes_proposals(fixture):
    import sqlite3
    c,pid,cid,ids,root=fixture
    actor=str(uuid4()); image=ids[0]; base=f'/api/v1/projects/{pid}/annotation-queue'
    c.post(base+'/enqueue',json={'ids':[image]})
    c.post(base+'/claim',json={},headers=headers(actor))
    boxes=[{'class_id':cid,'x_center':.5,'y_center':.5,'width':.2,'height':.2}]
    assert c.put(f'/api/v1/images/{image}/annotations',json={'boxes':boxes},headers=headers(actor,0)).status_code==200
    result=c.post(base+f'/{image}/action',json={'action':'background','revision':1},headers=headers(actor))
    assert result.status_code==200,result.text
    assert result.json()['state']=='DONE'
    with sqlite3.connect(root/'app.db') as db:
        assert db.execute('SELECT status,is_background FROM images WHERE id=?',(image,)).fetchone()==('VERIFIED',1)
        assert db.execute('SELECT count(*) FROM annotations WHERE image_id=?',(image,)).fetchone()[0]==0
