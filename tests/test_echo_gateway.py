from scripts.echo_gateway import allowed
def test_echo_gateway_contract():
 assert allowed('GET','/echo')
 assert allowed('GET','/presentation/theme')
 assert allowed('POST','/presentation/theme/toggle')
 assert allowed('POST','/notification/dismiss/x')
 assert allowed('GET','/api/human') and not allowed('POST','/api/human')
 for p in ['/action/approve/x','/action/respond/x','/settings/provider/add']:
  assert not allowed('POST',p) and not allowed('GET',p)


def test_echo_theme_redirect_stays_inside_echo_gateway():
 import scripts.echo_gateway as g
 assert '127.0.0.1:8788' in open('scripts/echo_gateway.py').read()
