"""Short-lived signed recommendations; no candidate history is persisted."""
import base64
import hashlib
import hmac
import json
import secrets
import time
from fastapi import HTTPException

_SECRET=secrets.token_bytes(32)


def sign_recommendation(user_id,sample_id,data):
    payload=base64.urlsafe_b64encode(json.dumps({'user_id':user_id,'sample_id':sample_id,'expires':time.time()+7200,'data':data},ensure_ascii=False).encode()).decode()
    signature=hmac.new(_SECRET,payload.encode(),hashlib.sha256).hexdigest()
    return payload+'.'+signature


def verify_recommendation(token,user_id,sample_id):
    try:
        payload,signature=token.rsplit('.',1)
        expected=hmac.new(_SECRET,payload.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature,expected):
            raise ValueError()
        decoded=json.loads(base64.urlsafe_b64decode(payload))
        if decoded['user_id']!=user_id or decoded['sample_id']!=sample_id or decoded['expires']<time.time():
            raise ValueError()
        return decoded['data']
    except (ValueError,KeyError,TypeError):
        raise HTTPException(400,'추천 정보가 유효하지 않거나 만료되었습니다. 다시 추천받아 주세요.') from None
