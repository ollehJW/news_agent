import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend import auth
from backend.main import app

HEADERS = {'X-WiaNews-Request': '1'}


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path_patch = patch.object(auth, 'DB_PATH', Path(self.temp.name)/'app.db')
        self.path_patch.start()
        self.client = TestClient(app, headers=HEADERS)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.path_patch.stop()
        self.temp.cleanup()

    def login(self, employee='admin', password='admin123', client=None):
        return (client or self.client).post('/api/auth/login', json={'employee_id': employee, 'password': password})

    def create(self, employee='1001'):
        self.assertEqual(self.login().status_code, 200)
        options=self.client.get('/api/admin/options').json()
        body={'employee_id': employee, 'full_name': '테스트 사용자', 'team_id': options['teams'][0]['team_id'],
              'role_id': next(r['role_id'] for r in options['roles'] if r['name']=='매니저'), 'email':'test@example.org'}
        response=self.client.post('/api/admin/users',json=body)
        self.assertEqual(response.status_code,201,response.text)
        return response.json(),body

    def test_bootstrap_hash_and_idempotence(self):
        with auth.database() as db:
            row=db.execute('SELECT * FROM users').fetchone()
            self.assertTrue(auth.verify_password('admin123',row['password_hash']))
            self.assertNotEqual(row['password_hash'],'admin123')
            uid=row['user_id']
        auth.init_db()
        with auth.database() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT user_id FROM users').fetchone()[0],uid)
        response=self.login()
        self.assertEqual(response.status_code,200)
        self.assertNotIn('password_hash',response.json())
        self.assertIn('HttpOnly',response.headers['set-cookie'])
        self.assertIn('SameSite=strict',response.headers['set-cookie'])
        self.assertIsNotNone(response.json()['last_login_at'])
        with auth.database() as db:
            self.assertNotEqual(db.execute('SELECT token_hash FROM sessions').fetchone()[0],self.client.cookies.get(auth.COOKIE))

    def test_mandatory_password_change_and_revocation(self):
        created,_=self.create()
        user=TestClient(app,headers=HEADERS)
        second=TestClient(app,headers=HEADERS)
        self.assertTrue(self.login('1001',auth.INITIAL_PASSWORD,user).json()['must_change_password'])
        self.login('1001',auth.INITIAL_PASSWORD,second)
        old=user.cookies.get(auth.COOKIE)
        for endpoint in ['/api/admin/users','/api/admin/options']:
            self.assertEqual(user.get(endpoint).status_code,403)
        for endpoint in ['/api/domains/recommend','/api/domains/recommend/stream']:
            self.assertEqual(user.post(endpoint,json={'topic':'AI'}).status_code,403)
        self.assertEqual(user.post('/api/auth/password',json={'current_password':'wrong','new_password':'Changed123!'}).status_code,400)
        self.assertEqual(user.post('/api/auth/password',json={'current_password':auth.INITIAL_PASSWORD,'new_password':auth.INITIAL_PASSWORD}).status_code,422)
        response=user.post('/api/auth/password',json={'current_password':auth.INITIAL_PASSWORD,'new_password':'Changed123!'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertFalse(response.json()['must_change_password'])
        self.assertNotEqual(old,user.cookies.get(auth.COOKIE))
        self.assertEqual(second.get('/api/auth/me').status_code,401)
        self.assertEqual(self.login('1001',auth.INITIAL_PASSWORD,second).status_code,401)
        self.assertEqual(self.login('1001','Changed123!',second).status_code,200)
        self.assertEqual(user.get('/api/admin/users').status_code,403)
        self.assertEqual(user.post('/api/admin/users',json={}).status_code,403)
        with patch('backend.main.recommend_domains',side_effect=auth.HTTPException(503,'test')) as call:
            self.assertEqual(user.post('/api/domains/recommend',json={'topic':'AI'}).status_code,503)
            call.assert_called_once()
        user.post('/api/auth/logout')
        self.assertEqual(user.get('/api/auth/me').status_code,401)

    def test_validation_and_unique_employee(self):
        created,body=self.create()
        self.assertEqual(self.client.post('/api/admin/users',json=body).status_code,409)
        self.assertEqual(self.client.post('/api/admin/users',json={**body,'employee_id':'1009','team_id':'missing'}).status_code,400)
        self.assertEqual(self.client.post('/api/admin/users',json={**body,'employee_id':'1009','full_name':'  '}).status_code,422)
        self.assertEqual(self.client.post('/api/admin/users',json={**body,'employee_id':'1009','email':'invalid'}).status_code,422)
        self.assertEqual(self.client.post('/api/admin/teams',json={'name':'플랫폼팀'}).status_code,201)
        self.assertEqual(self.client.post('/api/admin/teams',json={'name':'플랫폼팀'}).status_code,409)
        self.assertEqual(self.client.post('/api/domains/recommend',json={'topic':'AI'}).status_code,403)
        self.assertNotIn('password_hash',self.client.get('/api/admin/users').text)
        with auth.database() as db:
            self.assertTrue(auth.verify_password(auth.INITIAL_PASSWORD,db.execute('SELECT password_hash FROM users WHERE user_id=?',(created['user_id'],)).fetchone()[0]))

    def test_anonymous_csrf_expiry_and_disabled_account(self):
        self.assertEqual(self.client.get('/api/admin/users').status_code,401)
        self.assertEqual(TestClient(app).post('/api/auth/login',json={'employee_id':'admin','password':'admin123'}).status_code,403)
        self.login()
        with auth.database() as db:db.execute('UPDATE sessions SET expires_at=?',(time.time()-1,))
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)
        self.login()
        with auth.database() as db:db.execute('UPDATE users SET is_active=0')
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)
        self.assertEqual(self.login().status_code,401)

    def test_rate_limit(self):
        for _ in range(10):self.assertEqual(self.login(password='wrong').status_code,401)
        self.assertEqual(self.login().status_code,429)

    def test_legacy_migration_preserves_permissions_passwords_and_sessions(self):
        created, _ = self.create()
        with auth.database() as db:
            db.execute("ALTER TABLE roles ADD COLUMN code TEXT")
            db.execute("INSERT INTO roles (role_id,code,name,created_at) VALUES ('old-admin','admin','관리자',?)", (auth.now(),))
            db.execute("INSERT INTO roles (role_id,code,name,created_at) VALUES ('old-member','member','일반 사용자',?)", (auth.now(),))
            db.execute("UPDATE users SET role_id=CASE WHEN employee_id='admin' THEN 'old-admin' ELSE 'old-member' END")
            before = {r['user_id']: r['password_hash'] for r in db.execute('SELECT * FROM users')}
            db.execute('ALTER TABLE users DROP COLUMN is_admin')
        auth.init_db()
        auth.init_db()
        with auth.database() as db:
            rows = db.execute(auth.USER_QUERY).fetchall()
            self.assertEqual({r['user_id']: r['password_hash'] for r in rows}, before)
            self.assertEqual({r['role_name'] for r in rows}, {'미지정'})
            self.assertEqual({r['employee_id']:r['is_admin'] for r in rows}, {'admin':1,'1001':0})
            self.assertNotIn('code', {r['name'] for r in db.execute('PRAGMA table_info(roles)')})
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertEqual(self.client.get('/api/admin/users').status_code, 200)

    def test_same_job_title_can_have_different_admin_permissions(self):
        _, body = self.create()
        ordinary = TestClient(app, headers=HEADERS)
        self.login('1001', auth.INITIAL_PASSWORD, ordinary)
        ordinary.post('/api/auth/password', json={'current_password':auth.INITIAL_PASSWORD,'new_password':'Changed123!'})
        created = self.client.post('/api/admin/users', json={**body,'employee_id':'1002','is_admin':True})
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()['role_id'], body['role_id'])
        self.assertEqual(created.json()['is_admin'], 1)
        admin = TestClient(app, headers=HEADERS)
        self.login('1002', auth.INITIAL_PASSWORD, admin)
        self.assertEqual(admin.get('/api/admin/users').status_code, 403)
        admin.post('/api/auth/password', json={'current_password':auth.INITIAL_PASSWORD,'new_password':'Changed123!'})
        self.assertEqual(admin.get('/api/admin/users').status_code, 200)
        self.assertEqual(ordinary.get('/api/admin/users').status_code, 403)
        self.assertEqual(admin.post('/api/domains/recommend', json={'topic':'AI'}).status_code, 403)

    def test_named_team_and_title_are_created_reused_and_atomic(self):
        self.login()
        body = {'employee_id':'2001','full_name':'이름 입력','team_name':'  AI   플랫폼팀  ', 'role_name':'신규 직급'}
        result = self.client.post('/api/admin/users', json=body)
        self.assertEqual(result.status_code,201,result.text)
        created=result.json()
        self.assertEqual(created['team_name'],'AI 플랫폼팀')
        self.assertEqual(created['role_name'],'신규 직급')
        self.assertFalse(created['is_admin'])
        reused=self.client.post('/api/admin/users',json={**body,'employee_id':'2002','team_name':'ai플랫폼팀','role_name':'신규직급'})
        self.assertEqual(reused.status_code,201)
        self.assertEqual(reused.json()['team_id'],created['team_id'])
        self.assertEqual(reused.json()['role_id'],created['role_id'])
        senior=self.client.post('/api/admin/users',json={**body,'employee_id':'2003','role_name':'책임매니저'})
        self.assertEqual(senior.status_code,201)
        self.assertEqual(senior.json()['role_name'],'책임매니저')
        duplicate=self.client.post('/api/admin/users',json={**body,'team_name':'실패시 생성금지팀','role_name':'실패시 생성금지직급'})
        self.assertEqual(duplicate.status_code,409)
        with auth.database() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM teams WHERE name='실패시 생성금지팀'").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT count(*) FROM roles WHERE name='실패시 생성금지직급'").fetchone()[0],0)
        for override in [{'team_name':'  '},{'role_name':'  '},{'team_name':None},{'role_name':'x'*81}]:
            self.assertEqual(self.client.post('/api/admin/users',json={**body,'employee_id':'2004',**override}).status_code,422)
        options=self.client.get('/api/admin/options').json()
        self.assertIn('AI 플랫폼팀',[t['name'] for t in options['teams']])
        self.assertIn('신규 직급',[r['name'] for r in options['roles']])

    def test_edit_delete_accounts_and_authorization(self):
        created,body=self.create()
        uid=created['user_id']
        member=TestClient(app,headers=HEADERS)
        self.login('1001',auth.INITIAL_PASSWORD,member)
        member.post('/api/auth/password',json={'current_password':auth.INITIAL_PASSWORD,'new_password':'Changed123!'})
        self.assertEqual(member.put('/api/admin/users/'+uid,json=body).status_code,403)
        self.assertEqual(member.delete('/api/admin/users/'+uid).status_code,403)
        self.assertEqual(TestClient(app,headers=HEADERS).delete('/api/admin/users/'+uid).status_code,401)
        with auth.database() as db:
            before=db.execute('SELECT password_hash,created_at FROM users WHERE user_id=?',(uid,)).fetchone()
        named={k:v for k,v in body.items() if k not in ('team_id','role_id')}
        named.update(full_name='수정 사용자',team_name='수정 팀',role_name='책임연구원',email='edit@example.org',is_admin=False)
        edited=self.client.put('/api/admin/users/'+uid,json=named)
        self.assertEqual(edited.status_code,200,edited.text)
        self.assertEqual(edited.json()['full_name'],'수정 사용자')
        self.assertEqual(edited.json()['role_name'],'책임연구원')
        self.assertFalse(edited.json()['must_change_password'])
        with auth.database() as db:
            after=db.execute('SELECT password_hash,created_at FROM users WHERE user_id=?',(uid,)).fetchone()
            self.assertEqual(tuple(before),tuple(after))
        duplicate=self.client.put('/api/admin/users/'+uid,json={**named,'employee_id':'admin','team_name':'롤백 팀'})
        self.assertEqual(duplicate.status_code,409)
        with auth.database() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM teams WHERE name='롤백 팀'").fetchone()[0],0)
        admin_id=self.client.get('/api/auth/me').json()['user_id']
        self.assertEqual(self.client.delete('/api/admin/users/'+admin_id).status_code,400)
        self.assertEqual(self.client.put('/api/admin/users/'+admin_id,json=named).status_code,400)
        self.assertEqual(self.client.put('/api/admin/users/missing',json=named).status_code,404)
        promoted=self.client.put('/api/admin/users/'+uid,json={**named,'is_admin':True})
        self.assertEqual(promoted.status_code,200)
        self.assertEqual(member.get('/api/auth/me').status_code,401)
        self.assertEqual(self.login('1001','Changed123!',member).status_code,200)
        self.assertEqual(member.get('/api/admin/users').status_code,200)
        self.assertEqual(self.client.delete('/api/admin/users/'+uid).status_code,200)
        self.assertEqual(member.get('/api/auth/me').status_code,401)
        self.assertEqual(self.login('1001','Changed123!',member).status_code,401)
        self.assertEqual(self.client.delete('/api/admin/users/'+uid).status_code,404)

    def test_new_employee_ids_are_up_to_seven_digits(self):
        _,body=self.create()
        for employee in ['abc','12345678','12a','-123','１２３']:
            self.assertEqual(self.client.post('/api/admin/users',json={**body,'employee_id':employee}).status_code,422)
        response=self.client.post('/api/admin/users',json={**body,'employee_id':'0012345'})
        self.assertEqual(response.status_code,201)
        self.assertEqual(response.json()['employee_id'],'0012345')

    def test_admin_password_reset_revokes_sessions_and_forces_change(self):
        created,_=self.create()
        uid=created['user_id']
        endpoint='/api/admin/users/'+uid+'/reset-password'
        member=TestClient(app,headers=HEADERS)
        self.login('1001',auth.INITIAL_PASSWORD,member)
        member.post('/api/auth/password',json={'current_password':auth.INITIAL_PASSWORD,'new_password':'Changed123!'})
        self.assertEqual(member.post(endpoint).status_code,403)
        self.assertEqual(TestClient(app,headers=HEADERS).post(endpoint).status_code,401)
        self.assertEqual(self.client.post('/api/admin/users/missing/reset-password').status_code,404)
        reset=self.client.post(endpoint)
        self.assertEqual(reset.status_code,200)
        self.assertTrue(reset.json()['must_change_password'])
        self.assertIsNone(reset.json()['password_changed_at'])
        self.assertNotIn('password_hash',reset.json())
        self.assertEqual(member.get('/api/auth/me').status_code,401)
        self.assertEqual(self.login('1001','Changed123!',member).status_code,401)
        self.assertEqual(self.login('1001',auth.INITIAL_PASSWORD,member).status_code,200)
        self.assertEqual(member.post('/api/domains/recommend',json={'topic':'AI'}).status_code,403)
        changed=member.post('/api/auth/password',json={'current_password':auth.INITIAL_PASSWORD,'new_password':'Another123!'})
        self.assertEqual(changed.status_code,200)
        self.assertFalse(changed.json()['must_change_password'])
        with auth.database() as db:
            row=db.execute('SELECT * FROM users WHERE user_id=?',(uid,)).fetchone()
            self.assertTrue(auth.verify_password('Another123!',row['password_hash']))
            self.assertEqual(row['role_id'],created['role_id'])
        admin=self.client.get('/api/auth/me').json()
        self.assertEqual(self.client.post('/api/admin/users/'+admin['user_id']+'/reset-password').status_code,200)
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)
        self.assertEqual(self.login(password=auth.INITIAL_PASSWORD).status_code,200)
        self.assertEqual(self.client.get('/api/admin/users').status_code,403)
