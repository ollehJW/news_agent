"""Shared platform accounts and revocable PostgreSQL browser sessions."""
from backend.core.paths import BACKEND_DIR
import hashlib
import hmac
import os
import re
import secrets
import psycopg
import time
import uuid
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, StrictBool, field_validator, model_validator

COOKIE = 'ax_platform_session'
SESSION_SECONDS = 8 * 3600
INITIAL_PASSWORD = 'wia1234!'
router = APIRouter(prefix='/api')


def now():
    return datetime.now(timezone.utc).isoformat()


from backend.pgstore import database, initialize


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600000).hex()
    return f'pbkdf2_sha256$600000${salt}${digest}'


def verify_password(password, encoded):
    try:
        algorithm, iterations, salt, expected = encoded.split('$')
        if algorithm != 'pbkdf2_sha256':
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), int(iterations)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


def init_db():
    initialize()


USER_QUERY = '''SELECT u.*, t.name AS team_name, r.name AS role_name
                FROM users u JOIN teams t ON t.team_id=u.team_id JOIN roles r ON r.role_id=u.role_id'''


def public_user(row):
    return {k: row[k] for k in ('user_id', 'employee_id', 'full_name', 'team_id', 'team_name',
            'role_id', 'role_name', 'is_admin', 'email', 'must_change_password', 'is_active',
            'created_at', 'updated_at', 'last_login_at', 'password_changed_at')}


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def set_session(*args, **kwargs):
    raise RuntimeError("Only the platform may issue sessions")


def current_user(request: Request):
    token = request.cookies.get(COOKIE)
    if token:
        with database() as db:
            row = db.execute(USER_QUERY + ''' JOIN sessions s ON s.user_id=u.user_id
                WHERE s.token_hash=? AND s.expires_at>? AND u.is_active=TRUE''', (token_hash(token), time.time())).fetchone()
            if row:
                return public_user(row)
    raise HTTPException(401, '로그인이 필요합니다.')


def ready_user(user=Depends(current_user)):
    if user['must_change_password']:
        raise HTTPException(403, '초기 비밀번호를 먼저 변경해 주세요.')
    return user


def admin_user(user=Depends(ready_user)):
    if not user['is_admin']:
        raise HTTPException(403, '관리자만 접근할 수 있습니다.')
    return user


def member_user(user=Depends(ready_user)):
    if user['is_admin']:
        raise HTTPException(403, '일반 사용자만 뉴스레터 기능을 사용할 수 있습니다.')
    return user


class LoginBody(BaseModel):
    employee_id: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=128)


class PasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator('new_password')
    @classmethod
    def strong_password(cls, value):
        if not (re.search('[A-Za-z]', value) and re.search('[0-9]', value) and re.search(r'[^\w\s]', value)):
            raise ValueError('영문, 숫자, 특수문자를 포함해 8자 이상 입력해 주세요.')
        if value in (INITIAL_PASSWORD, 'admin123'):
            raise ValueError('초기 비밀번호는 새 비밀번호로 사용할 수 없습니다.')
        return value


@router.post('/auth/login')
def login():
    raise HTTPException(409, 'AX for Works 통합 로그인 페이지를 이용해 주세요.')


@router.get('/auth/me')
def me(response: Response, user=Depends(current_user)):
    response.headers['Cache-Control'] = 'no-store'
    return user


@router.post('/auth/logout')
def logout(request: Request, response: Response):
    with database() as db:
        db.execute('DELETE FROM sessions WHERE token_hash=?', (token_hash(request.cookies.get(COOKIE, '')),))
    response.delete_cookie(COOKIE, path='/', httponly=True, samesite='strict')
    return {'ok': True}


@router.post('/auth/password')
def change_password():
    raise HTTPException(409, 'AX for Works에서 비밀번호를 변경해 주세요.')


class UserBody(BaseModel):
    employee_id: str = Field(pattern=r'^[A-Za-z0-9._-]{1,40}$')
    full_name: str = Field(min_length=1, max_length=80)
    team_id: str | None = None
    role_id: str | None = None
    team_name: str | None = Field(default=None, min_length=1, max_length=80)
    role_name: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator('team_name', 'role_name')
    @classmethod
    def clean_name(cls, value):
        if value is None:
            return value
        value = ' '.join(unicodedata.normalize('NFKC', value).split())
        if not value:
            raise ValueError('팀과 직급 이름을 입력해 주세요.')
        return value

    @model_validator(mode='after')
    def require_team_and_role(self):
        if not (self.team_id or self.team_name) or not (self.role_id or self.role_name):
            raise ValueError('소속 팀과 직급을 입력해 주세요.')
        if (self.team_id and self.team_name) or (self.role_id and self.role_name):
            raise ValueError('팀과 직급은 이름 또는 ID 중 하나로 지정해 주세요.')
        return self
    is_admin: StrictBool = False
    email: str = Field(default='', max_length=254)

    @field_validator('full_name', 'email')
    @classmethod
    def trimmed(cls, value, info):
        value = value.strip()
        if info.field_name == 'full_name' and not value:
            raise ValueError('이름을 입력해 주세요.')
        if info.field_name == 'email' and value and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError('이메일 주소를 확인해 주세요.')
        return value


@router.get('/users/directory')
def user_directory(response: Response, user=Depends(member_user)):
    response.headers['Cache-Control'] = 'no-store'
    ranks = ['대표이사','전무','상무','실장','팀장','책임매니저','책임연구원','매니저','연구원','사원']
    with database() as db:
        rows = [dict(row) for row in db.execute("""SELECT u.user_id,u.employee_id,u.full_name,u.email,
            t.name AS team_name,r.name AS role_name FROM users u
            LEFT JOIN teams t ON t.team_id=u.team_id LEFT JOIN roles r ON r.role_id=u.role_id
            WHERE u.is_active=TRUE AND u.is_admin=FALSE""")]
    return sorted(rows,key=lambda row: (row['team_name'] or '',
        ranks.index(row['role_name']) if row['role_name'] in ranks else len(ranks),
        row['full_name'],row['employee_id']))


@router.get('/admin/users')
def users(response: Response, user=Depends(admin_user)):
    response.headers['Cache-Control'] = 'no-store'
    with database() as db:
        return [public_user(row) for row in db.execute(USER_QUERY+' ORDER BY u.created_at DESC')]


@router.get('/admin/options')
def options(user=Depends(admin_user)):
    with database() as db:
        return {'teams': [dict(row) for row in db.execute('SELECT * FROM teams ORDER BY name')],
                'roles': [dict(row) for row in db.execute('SELECT * FROM roles ORDER BY name')]}


def name_key(value):
    return ''.join(unicodedata.normalize('NFKC', value).split()).casefold()


def resolve_team_or_role(db, kind, item_id, name):
    # kind is an internal constant, never request input.
    table, column = ('teams', 'team_id') if kind == 'team' else ('roles', 'role_id')
    if item_id:
        if not db.execute(f'SELECT 1 FROM {table} WHERE {column}=?', (item_id,)).fetchone():
            raise HTTPException(400, '팀 또는 직급을 확인해 주세요.')
        return item_id
    for row in db.execute(f'SELECT {column},name FROM {table}'):
        if name_key(row['name']) == name_key(name):
            return row[column]
    item_id = str(uuid.uuid4())
    if kind == 'team':
        db.execute('INSERT INTO teams VALUES (?,?,?)', (item_id, name, now()))
    else:
        db.execute('INSERT INTO roles VALUES (?,?,?)', (item_id, name, now()))
    return item_id


class CreateUserBody(UserBody):
    employee_id: str = Field(pattern=r'^[0-9]{1,7}$')


@router.post('/admin/users', status_code=201)
def create_user(body: CreateUserBody, user=Depends(admin_user)):
    try:
        with database() as db:
            # Serialize lookup + insertion so concurrent requests reuse the same names.
            # Any account creation failure also rolls back new teams and job titles.
            db.execute("SELECT pg_advisory_xact_lock(741902630)")
            team_id = resolve_team_or_role(db, 'team', body.team_id, body.team_name)
            role_id = resolve_team_or_role(db, 'role', body.role_id, body.role_name)
            uid, stamp = str(uuid.uuid4()), now()
            db.execute('''INSERT INTO users (user_id,employee_id,password_hash,full_name,team_id,role_id,is_admin,email,created_at,updated_at)
                          VALUES (?,?,?,?,?,?,?,?,?,?)''',
                       (uid, body.employee_id.lower(), hash_password(INITIAL_PASSWORD), body.full_name,
                        team_id, role_id, bool(body.is_admin), body.email, stamp, stamp))
            return public_user(db.execute(USER_QUERY+' WHERE u.user_id=?', (uid,)).fetchone())
    except psycopg.IntegrityError:
        raise HTTPException(409, '이미 등록된 사번입니다.') from None


class TeamBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator('name')
    @classmethod
    def name_not_blank(cls, value):
        if not value.strip():
            raise ValueError('팀 이름을 입력해 주세요.')
        return value.strip()


@router.post('/admin/teams', status_code=201)
def create_team(body: TeamBody, user=Depends(admin_user)):
    try:
        with database() as db:
            tid = str(uuid.uuid4())
            db.execute('INSERT INTO teams VALUES (?,?,?)', (tid, body.name, now()))
            return {'team_id': tid, 'name': body.name}
    except psycopg.IntegrityError:
        raise HTTPException(409, '이미 등록된 팀입니다.') from None


@router.put('/admin/users/{user_id}')
def edit_user(user_id: str, body: UserBody, user=Depends(admin_user)):
    if user_id == user['user_id'] and not body.is_admin:
        raise HTTPException(400, '로그인 중인 본인의 관리자 권한은 해제할 수 없습니다.')
    try:
        with database() as db:
            db.execute("SELECT pg_advisory_xact_lock(741902630)")
            existing = db.execute('SELECT * FROM users WHERE user_id=?', (user_id,)).fetchone()
            if not existing:
                raise HTTPException(404, '계정을 찾을 수 없습니다.')
            team_id = resolve_team_or_role(db, 'team', body.team_id, body.team_name)
            role_id = resolve_team_or_role(db, 'role', body.role_id, body.role_name)
            db.execute('''UPDATE users SET employee_id=?,full_name=?,team_id=?,role_id=?,is_admin=?,email=?,updated_at=?
                          WHERE user_id=?''', (body.employee_id.lower(), body.full_name, team_id, role_id,
                          bool(body.is_admin), body.email, now(), user_id))
            if existing['is_admin'] != bool(body.is_admin):
                db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
            return public_user(db.execute(USER_QUERY+' WHERE u.user_id=?', (user_id,)).fetchone())
    except psycopg.IntegrityError:
        raise HTTPException(409, '이미 등록된 사번입니다.') from None


@router.delete('/admin/users/{user_id}')
def delete_user(user_id: str, user=Depends(admin_user)):
    if user_id == user['user_id']:
        raise HTTPException(400, '로그인 중인 본인 계정은 삭제할 수 없습니다.')
    try:
        with database() as db:
            if db.execute('DELETE FROM users WHERE user_id=?', (user_id,)).rowcount != 1:
                raise HTTPException(404, '계정을 찾을 수 없습니다.')
    except psycopg.IntegrityError:
        raise HTTPException(409, '구독 또는 발행 이력에 연결된 계정은 삭제할 수 없습니다.') from None
    return {'ok': True}


@router.post('/admin/users/{user_id}/reset-password')
def reset_password(user_id: str, user=Depends(admin_user)):
    with database() as db:
        db.execute("SELECT pg_advisory_xact_lock(741902630)")
        if not db.execute('SELECT 1 FROM users WHERE user_id=?', (user_id,)).fetchone():
            raise HTTPException(404, '계정을 찾을 수 없습니다.')
        db.execute('''UPDATE users SET password_hash=?,must_change_password=TRUE,
                      password_changed_at=NULL,updated_at=? WHERE user_id=?''',
                   (hash_password(INITIAL_PASSWORD), now(), user_id))
        db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
        return public_user(db.execute(USER_QUERY+' WHERE u.user_id=?', (user_id,)).fetchone())
