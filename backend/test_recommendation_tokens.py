import base64
import json
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from backend.recommendation_tokens import sign_recommendation, verify_recommendation


class RecommendationTokenTests(unittest.TestCase):
    def test_recommendation_is_bound_to_user_run_content_and_expiry(self):
        data={'host':'example.org','request_id':'request','desc':'description'}
        with patch('backend.recommendation_tokens.time.time',return_value=100):
            token=sign_recommendation('user','run',data)
            self.assertEqual(verify_recommendation(token,'user','run'),data)
            for user,run in [('other','run'),('user','other')]:
                with self.assertRaises(HTTPException):verify_recommendation(token,user,run)
            payload,signature=token.rsplit('.',1)
            decoded=json.loads(base64.urlsafe_b64decode(payload));decoded['data']['request_id']='forged'
            forged=base64.urlsafe_b64encode(json.dumps(decoded).encode()).decode()+'.'+signature
            with self.assertRaises(HTTPException):verify_recommendation(forged,'user','run')
        with patch('backend.recommendation_tokens.time.time',return_value=7301):
            with self.assertRaises(HTTPException):verify_recommendation(token,'user','run')
