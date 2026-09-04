import os, tempfile, unittest
from pathlib import Path

os.environ['SESSION_SECRET'] = 'test-secret'
import sys
sys.path.insert(0, str(Path(__file__).parents[1]))
import server

class DPBossSecurityTests(unittest.TestCase):
    def setUp(self):
        self.original = server.DB_PATH
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False); self.tmp.close()
        server.DB_PATH = Path(self.tmp.name); server.init()
    def tearDown(self):
        os.unlink(server.DB_PATH); server.DB_PATH = self.original
    def test_password_hash_is_salted_and_verifiable(self):
        stored = server.password_hash('a-long-test-password')
        self.assertNotIn('a-long-test-password', stored)
        self.assertTrue(server.password_ok('a-long-test-password', stored))
        self.assertFalse(server.password_ok('incorrect-password', stored))
    def test_schema_has_unique_social_constraints(self):
        c = server.db()
        c.execute("INSERT INTO users(username,display_name,email,password_hash,created_at) VALUES(?,?,?,?,?)", ('valid_user','Valid User','valid@example.test',server.password_hash('password1234'),server.now()))
        with self.assertRaises(Exception):
            c.execute("INSERT INTO users(username,display_name,email,password_hash,created_at) VALUES(?,?,?,?,?)", ('VALID_USER','Other','other@example.test',server.password_hash('password1234'),server.now()))
        c.close()
if __name__ == '__main__': unittest.main()
