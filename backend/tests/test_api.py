import unittest
from fastapi.testclient import TestClient
from main import app
class ApiTests(unittest.TestCase):
    def setUp(self):self.client=TestClient(app)
    def test_root(self):self.assertEqual(self.client.get('/').status_code,200)
    def test_csrf_required(self):
        self.assertEqual(self.client.post('/api/generate-report',headers={'Authorization':'Bearer unverified'}).status_code,403)
    def test_csrf_cookie(self):
        response=self.client.get('/api/csrf-token')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['csrf'],response.cookies['XSRF-TOKEN'])
if __name__=='__main__':unittest.main()
