from ai_foundation.notification_dismissal import NotificationDismissals
def test_dismiss_is_ui_state_only_and_status_scoped(tmp_path):
 d=NotificationDismissals(tmp_path/'w.db');d.dismiss('x','FAILED');assert d.hidden('x','FAILED');assert not d.hidden('x','UNCERTAIN')

def test_http_dismiss_hides_notice_without_mutating_authoritative_snapshot(tmp_path):
 import threading,urllib.request,urllib.parse
 from ai_foundation.operator_server import OperatorApplication,serve
 class C:data_dir=str(tmp_path);work_db='w.db'
 class A:pass
 class Snap:
  def as_dict(self):return {'ready':True,'waiting_human':0,'effects':{},'attention':[{'kind':'effect','id':'e1','run_id':'r1','status':'FAILED'}]}
 app=OperatorApplication(C(),A(),csrf_token='T');app.snapshot=lambda:Snap();srv=serve(app);threading.Thread(target=srv.serve_forever,daemon=True).start()
 try:
  assert '処理が失敗しました' in urllib.request.urlopen(f'http://127.0.0.1:{srv.server_port}/').read().decode()
  req=urllib.request.Request(f'http://127.0.0.1:{srv.server_port}/notification/dismiss/r1',data=urllib.parse.urlencode({'csrf':'T'}).encode(),method='POST');urllib.request.urlopen(req)
  assert '処理が失敗しました' not in urllib.request.urlopen(f'http://127.0.0.1:{srv.server_port}/').read().decode()
  assert app.snapshot().as_dict()['attention'][0]['status']=='FAILED'
 finally:srv.shutdown();srv.server_close()


def test_dismissal_persists_across_service_restart_and_new_status_reappears(tmp_path):
 path=tmp_path/'w.db'; first=NotificationDismissals(path); first.dismiss('job:0','FAILED')
 restarted=NotificationDismissals(path)
 assert restarted.hidden('job:0','FAILED')
 assert not restarted.hidden('job:0','WAITING_HUMAN')
