"""Per-user workflow errors without prompts, credentials, or provider payloads."""
import logging
import sqlite3
import uuid
from fastapi import Depends, HTTPException, Request
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from .auth import database, member_user, now

log = logging.getLogger(__name__)


def record_error(user_id, step, error, request_id=None):
    if not user_id or getattr(error, '_wianews_error_logged', False):
        return
    if isinstance(error, HTTPException) and isinstance(error.detail, str):
        message = error.detail[:1000]
    else:
        message = {
            'RequestValidationError': '입력 형식이 올바르지 않습니다.',
            'ConfigurationError': 'LLM 연결 설정이 필요합니다.',
            'InvalidLLMResponse': 'LLM 응답 형식이 올바르지 않습니다.',
            'RateLimitError': 'LLM 요청 한도를 초과했습니다.',
            'APIConnectionError': 'LLM 서비스에 연결하지 못했습니다.',
            'APITimeoutError': 'LLM 응답 시간이 초과되었습니다.',
            'TimeoutError': '처리 시간이 초과되었습니다.',
        }.get(type(error).__name__, '단계 처리 중 오류가 발생했습니다.')
    try:
        with database() as db:
            db.execute('INSERT INTO errors (error_id,user_id,step,error_type,message,request_id,created_at) VALUES (?,?,?,?,?,?,?)',
                       (str(uuid.uuid4()),user_id,step,type(error).__name__,message,request_id,now()))
        error._wianews_error_logged = True
    except sqlite3.Error:
        # Failure to record an error must not replace the original failure.
        log.error('Could not persist workflow error (step=%s, type=%s)', step, type(error).__name__)


def record_sample_error(sample_id, step, error):
    if not sample_id or getattr(error, '_wianews_error_logged', False):
        return
    with database() as db:
        row=db.execute('SELECT user_id FROM sample_newsletters WHERE sample_id=?',(sample_id,)).fetchone()
    if row:
        record_error(row['user_id'],step,error)


def tracked_member_user(request: Request, user=Depends(member_user)):
    request.state.error_user_id = user['user_id']
    return user


def request_step(path):
    if '/domains/recommend' in path:
        return 'sample_domain_recommendation'
    if path.startswith('/api/samples'):
        return {'sources':'sample_domain_selection','period':'sample_period_setting',
                'collect-demo':'sample_article_collection','selection':'sample_issue_selection',
                'newsletter':'sample_newsletter_generation'}.get(path.rsplit('/',1)[-1],'sample_creation')
    if path.startswith('/api/newsletters'):
        return {'save':'sample_newsletter_save','download':'sample_newsletter_download'}.get(path.rsplit('/',1)[-1],'sample_newsletter_list')
    return 'sample_request'


class ErrorRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def wrapped(request):
            try:
                return await handler(request)
            except Exception as error:
                record_error(getattr(request.state,'error_user_id',None),request_step(request.url.path),error)
                raise
        return wrapped
