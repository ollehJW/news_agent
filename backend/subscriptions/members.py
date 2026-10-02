"""Internal account recipients and external email-only recipients."""
import re
import uuid
from typing import Literal
from pydantic import BaseModel,ConfigDict,model_validator
from fastapi import HTTPException
from backend.core.auth import now


class MemberBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    member_type: Literal['internal','external']
    user_id: str | None=None
    email_address: str | None=None

    @model_validator(mode='after')
    def valid_identity(self):
        self.user_id=(self.user_id or '').strip() or None
        self.email_address=(self.email_address or '').strip().lower() or None
        if self.member_type=='internal':
            if not self.user_id or self.email_address:raise ValueError('사내 멤버는 user_id만 지정해야 합니다.')
        elif self.user_id or not self.email_address or len(self.email_address)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',self.email_address):
            raise ValueError('사외 멤버는 올바른 이메일 주소만 지정해야 합니다.')
        return self


def write_members(db,sid,members):
    normalized={}
    for member in members:
        if member.member_type=='internal':
            user=db.execute("SELECT user_id FROM users WHERE user_id=? AND is_active=TRUE AND is_admin=FALSE",(member.user_id,)).fetchone()
            if not user:raise HTTPException(422,'활성 사내 사용자를 선택해 주세요.')
        key=(member.member_type,member.user_id or member.email_address)
        normalized[key]=member
    # Preserve creation timestamps for retained memberships.
    existing={(r['member_type'],r['user_id'] or r['email_address']):r for r in db.execute('SELECT * FROM subscription_members WHERE subscription_id=?',(sid,))}
    for key,row in existing.items():
        if key not in normalized:db.execute('DELETE FROM subscription_members WHERE member_id=?',(row['member_id'],))
    for key,member in normalized.items():
        if key not in existing:
            db.execute('INSERT INTO subscription_members(member_id,subscription_id,member_type,user_id,email_address,created_at) VALUES(?,?,?,?,?,?)',
                (str(uuid.uuid4()),sid,member.member_type,member.user_id,member.email_address,now()))


def members_info(db,sid):
    return [dict(r) for r in db.execute("""SELECT m.*,COALESCE(u.email,m.email_address,'') AS email,
        COALESCE(u.full_name,m.email_address) AS full_name,u.employee_id,t.name AS team_name,r.name AS role_name
        FROM subscription_members m LEFT JOIN users u ON u.user_id=m.user_id
        LEFT JOIN teams t ON t.team_id=u.team_id LEFT JOIN roles r ON r.role_id=u.role_id
        WHERE m.subscription_id=? ORDER BY m.created_at,m.member_id""",(sid,))]


# The alias s must refer to subscriptions. Bind the requesting user twice.
ACCESS="(s.user_id=? OR EXISTS(SELECT 1 FROM subscription_members sm WHERE sm.subscription_id=s.subscription_id AND sm.member_type='internal' AND sm.user_id=?))"
