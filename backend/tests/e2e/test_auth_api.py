import io
import sqlite3
from uuid import uuid4
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from app.main import create_app

@pytest.fixture
def auth(tmp_path):
    app=create_app(database_url=f"sqlite+aiosqlite:///{(tmp_path/'app.db').as_posix()}",storage_root=tmp_path/'storage')
    with TestClient(app) as c:
        yield c,tmp_path

def setup(c):
    response=c.post('/api/v1/auth/setup',json={'username':'admin','password':'test-admin-password'})
    assert response.status_code==201,response.text
    return response.json()

def annotator(c,username='worker'):
    response=c.post('/api/v1/auth/users',json={'username':username,'password':'test-worker-password','role':'ANNOTATOR'})
    assert response.status_code==201,response.text
    return response.json()

def login(c,name,password='test-worker-password'):
    response=c.post('/api/v1/auth/login',json={'username':name,'password':password})
    assert response.status_code==200,response.text
    return response.json()

def test_initial_setup_cookie_and_password_storage(auth):
    c,root=auth
    assert c.get('/api/v1/auth/status').json()=={'enabled':True,'needs_setup':True}
    assert c.get('/api/v1/projects').status_code==401
    assert c.get('/docs').status_code==401
    assert c.post('/api/v1/auth/setup',json={'username':'admin','password':'short'}).status_code==422
    response=c.post('/api/v1/auth/setup',json={'username':'Admin','password':'test-admin-password'})
    assert response.status_code==201,response.text
    assert 'httponly' in response.headers['set-cookie'].lower() and 'samesite=strict' in response.headers['set-cookie'].lower()
    assert response.json()['username']=='admin' and response.json()['role']=='ADMIN'
    assert 'password_hash' not in response.json()
    assert c.get('/api/v1/auth/status').json()['needs_setup'] is False
    assert c.post('/api/v1/auth/setup',json={'username':'other','password':'test-other-password'}).status_code==409
    with sqlite3.connect(root/'app.db') as db:
        hashed=db.execute('SELECT password_hash FROM users').fetchone()[0]
    assert hashed.startswith('pbkdf2_sha256$') and 'test-admin-password' not in hashed
    assert c.post('/api/v1/auth/logout').status_code==204
    assert c.get('/api/v1/projects').status_code==401
    assert c.post('/api/v1/auth/login',json={'username':'admin','password':'wrong'}).status_code==401
    login(c,'ADMIN','test-admin-password')
    assert c.get('/api/v1/projects').status_code==200

def test_annotator_routes_and_last_admin_protection(auth):
    c,_=auth;admin=setup(c);worker=annotator(c)
    assert c.patch(f"/api/v1/auth/users/{admin['id']}",json={'role':'ANNOTATOR'}).status_code==409
    pid=c.post('/api/v1/projects',json={'name':'Project'}).json()['id']
    c.post(f'/api/v1/projects/{pid}/classes',json={'name':'Object','color_hex':'#123456'})
    login(c,'worker')
    assert c.get('/api/v1/projects').status_code==200
    assert c.get(f'/api/v1/projects/{pid}').status_code==200
    assert c.get(f'/api/v1/projects/{pid}/classes').status_code==200
    headers={'X-Annotation-Session':str(uuid4())}
    assert c.get(f'/api/v1/projects/{pid}/annotation-queue',headers=headers).status_code==200
    blocked=[('GET','/api/v1/auth/users'),('POST','/api/v1/auth/users'),('GET','/api/v1/training-queue'),('GET','/api/v1/compute-schedule'),('PUT','/api/v1/compute-schedule'),('GET',f'/api/v1/projects/{pid}/models'),('GET',f'/api/v1/projects/{pid}/images'),('GET',f'/api/v1/projects/{pid}/streams'),('POST',f'/api/v1/projects/{pid}/classes'),('POST',f'/api/v1/projects/{pid}/annotation-queue/enqueue'),('POST',f'/api/v1/projects/{pid}/data/query'),('POST',f'/api/v1/projects/{pid}/train'),('DELETE',f'/api/v1/projects/{pid}')]
    for method,path in blocked:
        response=c.request(method,path,json={})
        assert response.status_code==403,(method,path,response.text)

def test_image_permissions_and_user_bound_queue_lease(auth):
    c,_=auth;setup(c);annotator(c);annotator(c,'second')
    pid=c.post('/api/v1/projects',json={'name':'Queue'}).json()['id']
    cid=c.post(f'/api/v1/projects/{pid}/classes',json={'name':'Object','color_hex':'#123456'}).json()['id']
    data=io.BytesIO();Image.new('RGB',(64,48)).save(data,'PNG')
    images=c.post(f'/api/v1/projects/{pid}/images/upload',files=[('files',(f'{i}.png',data.getvalue(),'image/png')) for i in range(2)]).json()
    iid=images[0]['id'];outside=images[1]['id'];base=f'/api/v1/projects/{pid}/annotation-queue'
    c.post(base+'/enqueue',json={'ids':[iid]})
    login(c,'worker');headers={'X-Annotation-Session':str(uuid4())}
    assert c.get(f'/api/v1/images/{outside}').status_code==403
    assert c.get(f'/api/v1/images/{outside}/file').status_code==403
    assert c.get(f'/api/v1/images/{iid}/file').status_code==200
    assert c.post(base+'/claim',json={'image_id':iid},headers=headers).status_code==200
    body={'boxes':[{'class_id':cid,'x_center':.5,'y_center':.5,'width':.2,'height':.2}]}
    write_headers={**headers,'X-Annotation-Revision':'0'}
    login(c,'second')
    assert c.put(f'/api/v1/images/{iid}/annotations',json=body,headers=write_headers).status_code==409
    assert c.post(base+'/claim',json={'image_id':iid},headers=headers).status_code==409
    login(c,'worker')
    saved=c.put(f'/api/v1/images/{iid}/annotations',json=body,headers=write_headers)
    assert saved.status_code==200,saved.text
    assert c.post(base+f'/{iid}/action',json={'action':'finish','revision':1},headers=headers).status_code==200
    assert c.get(f'/api/v1/images/{iid}').status_code==403
    assert c.get(f'/api/v1/images/{iid}/file').status_code==403
    assert c.get(base,headers=headers).json()['items']==[]

def test_disable_and_password_reset_revoke_sessions(auth):
    c,_=auth;setup(c);worker=annotator(c);admin_cookie=c.cookies.get('lblstdio_session')
    login(c,'worker');worker_cookie=c.cookies.get('lblstdio_session')
    c.cookies.set('lblstdio_session',admin_cookie,domain='testserver.local',path='/')
    assert c.patch(f"/api/v1/auth/users/{worker['id']}",json={'password':'new-worker-password'}).status_code==200
    c.cookies.set('lblstdio_session',worker_cookie,domain='testserver.local',path='/')
    assert c.get('/api/v1/auth/me').status_code==401
    assert c.post('/api/v1/auth/login',json={'username':'worker','password':'test-worker-password'}).status_code==401
    login(c,'worker','new-worker-password')
    worker_cookie=c.cookies.get('lblstdio_session')
    c.cookies.set('lblstdio_session',admin_cookie,domain='testserver.local',path='/')
    assert c.patch(f"/api/v1/auth/users/{worker['id']}",json={'is_active':False}).status_code==200
    c.cookies.set('lblstdio_session',worker_cookie,domain='testserver.local',path='/')
    assert c.get('/api/v1/projects').status_code==401
    assert c.post('/api/v1/auth/login',json={'username':'worker','password':'new-worker-password'}).status_code==401

def test_cross_origin_writes_and_tampered_sessions_are_rejected(auth):
    c,_=auth
    assert c.post('/api/v1/auth/setup',json={'username':'admin','password':'test-admin-password'},headers={'Origin':'https://foreign.example'}).status_code==403
    setup(c)
    assert c.post('/api/v1/projects',json={'name':'No'},headers={'Origin':'https://foreign.example'}).status_code==403
    c.cookies.set('lblstdio_session','invalid-token',domain='testserver.local',path='/')
    assert c.get('/api/v1/projects').status_code==401
