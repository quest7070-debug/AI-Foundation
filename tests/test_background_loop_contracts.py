from pathlib import Path
from ai_foundation.provider_recovery import ProviderRecoveryLoop
from ai_foundation.attachment_handoff import AttachmentCleanupLoop
from ai_foundation.long_term_health import LongTermHealthLoop

def test_background_intervals_have_nonzero_rate_floors():
 class S:
  def credentials(self):return ()
 assert ProviderRecoveryLoop(S(),interval=0).interval==1
 class H: pass
 assert AttachmentCleanupLoop(H(),interval=0).interval==60
 assert LongTermHealthLoop(lambda:None,interval=0).interval==60

def test_webpush_loop_has_bounded_poll_interval():
 src=Path('scripts/operator_server.py').read_text()
 assert "max(5,int(os.getenv('AI_FOUNDATION_WEBPUSH_SECONDS','5')))" in src
 assert 'time.sleep(interval)' in src
