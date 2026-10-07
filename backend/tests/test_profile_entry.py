"""Opt-in PostgreSQL regression check; all fixture changes are rolled back.
Run with runtime environment and AX_SERVICE_CONFIG, AX_RUN_DB_TESTS=1.
"""
def main():
    import os,sys,uuid,time,hashlib,secrets
    from pathlib import Path
    from contextlib import contextmanager
    from types import SimpleNamespace
    if os.getenv('AX_RUN_DB_TESTS')!='1':raise SystemExit('Set AX_RUN_DB_TESTS=1 to run the rollback-only integration check')
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    from backend.pgstore import database,SERVICE
    from fastapi import FastAPI,Depends
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient
    with database() as db:
        @contextmanager
        def connection():yield db
        if SERVICE=='wianews':
            from backend.core import auth
            auth.database=connection
            router=auth.router;ready=auth.ready_user
        else:
            from backend.auth import Auth
            from backend.state import APIError
            auth=Auth(SimpleNamespace(connect=connection),True);router=auth.router;ready=auth.ready_user
        app=FastAPI();app.include_router(router)
        if SERVICE=='wiacoding':
            @app.exception_handler(APIError)
            async def error(request,exc):return JSONResponse({'error':exc.message},status_code=exc.status)
        @app.get('/ready')
        def check_ready(user=Depends(ready)):return user
        client=TestClient(app,base_url='https://axforwork.wia.co.kr')
        uid='profile-entry-'+uuid.uuid4().hex;token=secrets.token_urlsafe(32)
        try:
            refs={key:db.execute(f"SELECT {key} FROM platform.{table} WHERE btrim(name) NOT IN ('','미지정') LIMIT 1").fetchone()[0] for key,table in [('org_id','orgs'),('team_id','teams'),('role_id','roles')]}
            db.execute("INSERT INTO platform.users(user_id,employee_id,password_hash,full_name,email,is_admin,is_active,must_change_password,created_at,updated_at) VALUES(?,?,'unused','정보 검증','',false,true,false,now(),now())",(uid,uid))
            db.execute('INSERT INTO platform.sessions VALUES(?,?,now(),?)',(hashlib.sha256(token.encode()).hexdigest(),uid,time.time()+600))
            assert client.get('/api/auth/me').status_code==401
            client.cookies.set('ax_platform_session',token)
            r=client.get('/api/auth/me');assert r.status_code==200,r.text
            assert set(r.json()['missing_profile_fields'])=={'organization','team_name','role_name','email'}
            assert 'password_hash' not in r.json() and r.json()['user_id']==uid
            def complete():db.execute('UPDATE platform.users SET org_id=?,team_id=?,role_id=?,full_name=?,email=? WHERE user_id=?',(*refs.values(),'정보 검증','entry@example.com',uid))
            complete();assert client.get('/api/auth/me').json()['missing_profile_fields']==[]
            for column,key,value in [('org_id','organization',None),('team_id','team_name',None),('role_id','role_name',None),('email','email',''),('full_name','full_name',' 미지정 ')]:
                complete();db.execute(f'UPDATE platform.users SET {column}=? WHERE user_id=?',(value,uid))
                assert client.get('/api/auth/me').json()['missing_profile_fields']==[key],key
            db.execute('UPDATE platform.users SET is_admin=true,team_id=NULL,role_id=NULL WHERE user_id=?',(uid,))
            assert client.get('/api/auth/me').status_code==200 and client.get('/ready').status_code==200
            db.execute('UPDATE platform.users SET must_change_password=true WHERE user_id=?',(uid,))
            assert client.get('/ready').status_code==403
            db.execute('UPDATE platform.users SET is_active=false WHERE user_id=?',(uid,))
            assert client.get('/api/auth/me').status_code==401
            db.execute('UPDATE platform.users SET is_active=true WHERE user_id=?',(uid,));db.execute('UPDATE platform.sessions SET expires_at=0 WHERE user_id=?',(uid,))
            assert client.get('/api/auth/me').status_code==401
            print(SERVICE+': PASS NULL/blank/mijijeong fields, complete profile, admin, initial password, inactive/expired sessions, no credentials exposed')
        finally:client.close();db.rollback()
if __name__=='__main__':main()
