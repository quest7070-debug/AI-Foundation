import sqlite3
class NotificationDismissals:
 def __init__(self,path,storage_admission=None):self.path=str(path);self.storage_admission=storage_admission;self._schema()
 def _schema(self):
  with sqlite3.connect(self.path) as db:db.execute('CREATE TABLE IF NOT EXISTS notification_dismissals(subject TEXT,status TEXT,PRIMARY KEY(subject,status))')
 def dismiss(self,subject,status):
  if self.storage_admission:self.storage_admission.require('notification dismissal')
  with sqlite3.connect(self.path) as db:db.execute('INSERT OR IGNORE INTO notification_dismissals VALUES(?,?)',(subject,status))
 def hidden(self,subject,status):
  with sqlite3.connect(self.path) as db:return db.execute('SELECT 1 FROM notification_dismissals WHERE subject=? AND status=?',(subject,status)).fetchone() is not None
