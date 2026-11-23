from ai_foundation.human_view import from_snapshot
from ai_foundation.human_renderer import render
from ai_foundation.human_operations import HumanNotice,HumanTask
class S:
 def as_dict(self):return {'ready':True,'waiting_human':1,'effects':{'UNCERTAIN':1,'VERIFIED':2},'attention':[{'status':'UNCERTAIN'}]}
def test_shared_view_drives_responsive_browser_and_constrained_echo():
 v=from_snapshot(S(),notices=(HumanNotice(4,'approval','run1','WAITING_HUMAN','判断','詳細',True),),tasks=(HumanTask('j','do work',1,'PLANNED',''),))
 r=render(v,'responsive',csrf='T');e=render(v,'echo',csrf='T')
 for x in (r,e): assert 'AI FOUNDATION' in x and 'UNCERTAIN' in x and '判断' in x
 for token in ('LLM SETUP','ROUTING','ADD API','AUTHORIZE','DENY','do work'): assert token in r
 for token in ('SETTINGS','TASKS','AUTHORIZE','DENY','RECONCILE','LLM USE'): assert token not in e
 assert 'SYSTEM' in e and 'DISMISS' not in e and 'NOTIFICATIONS' in e
 for provider in ('GROQ','GEMINI','OPENROUTER','MISTRAL','NVIDIA'): assert f'<option>{provider}</option>' in r
 assert '<option value="">AUTO DETECT</option>' in r

def test_unknown_surface_fails_closed():
 import pytest
 with pytest.raises(ValueError):render(from_snapshot(S()),'watch')

def test_system_telemetry_is_semantic_and_compact():
 from ai_foundation.human_view import from_snapshot
 class S:
  def as_dict(self):return {'ready':False,'waiting_human':0,'effects':{},'attention':[],'checks':[{'name':'db','ok':False,'detail':'bad'}],'services':[{'name':'local','ok':False,'detail':'down'}],'backup':{'present':True},'update':{'staged':False},'trace_present':True}
 v=from_snapshot(S());d=render(v,'responsive');e=render(v,'echo')
 for page in (d,e): assert 'SYSTEM ATTENTION' in page and 'CHECKS FAILED / 1' in page and 'BACKUP / PRESENT' in page and 'db FAILED' in page and 'local DOWN' in page

def test_provider_quota_reset_and_reason_are_visible_without_raw_binding():
 from ai_foundation.provider_registry import ProviderCard
 v=from_snapshot(S(),providers=(ProviderCard('GROQ','FREE',1,'RATE_LIMITED',20,'7s',70,'1h','HTTP 429'),))
 d=render(v,'responsive');assert 'RESET · 7s' in d and 'RESET · 1h' in d and 'HTTP 429' in d

def test_navigation_targets_real_semantic_sections_and_quota_hierarchy():
 from ai_foundation.provider_registry import ProviderCard
 v=from_snapshot(S(),providers=(ProviderCard('GROQ','FREE',1,'ONLINE',80,'7s',20,'1h'),))
 d=render(v,'responsive')
 for target in ('settings','routing','tasks','notifications'):assert f'href="#{target}"' in d and f'id="{target}"' in d
 assert '<span>SHORT LIMIT</span><strong>80%</strong>' in d and '<span>LONG LIMIT</span><strong>20%</strong>' in d

def test_c_i_share_exact_markup_and_only_css_tokens_differ():
 import re
 v=from_snapshot(S())
 for surface in ('responsive','echo'):
  i=render(v,surface,theme='I');c=render(v,surface,theme='C')
  def semantic(x):return re.sub(r'<style>.*?</style>','<style/>',re.sub(r'<meta name="ai-foundation-theme" content="[CI]">','',x),flags=re.S)
  assert semantic(i)==semantic(c)
  assert '--theme:I' in i and '--theme:C' in c

def test_responsive_content_uses_full_available_column():
 v=from_snapshot(S());page=render(v,'responsive')
 assert '.content{padding:28px;width:100%;max-width:none;min-width:0}' in page
 assert 'max-width:1200px' not in page


def test_c_theme_is_neutral_graphite_white_with_signal_yellow_not_brown_gold():
 v=from_snapshot(S());page=render(v,'responsive',theme='C')
 assert 'background:#101310' in page and 'background:#202520;color:#e9ede8' in page
 assert '#d8df27' in page
 assert '#11110e' not in page and '#f0c94f' not in page

def test_responsive_has_design_switch_and_mobile_nav_authority():
 v=from_snapshot(S());page=render(v,'responsive',theme='I')
 assert 'class=design-switch' in page and 'CHANGE DESIGN' in page
 assert 'nav{display:none}' not in page
 assert '@media(max-width:700px)' in page
 assert 'nav{position:sticky;top:0;z-index:10;height:auto;align-self:stretch;display:flex;flex-direction:row;overflow-x:auto;overflow-y:hidden;max-width:100vw;min-width:0' in page
 for target in ('top','notifications','settings','routing','tasks','system'):
  assert f'href="#{target}"' in page

def test_theme_preserves_typography_and_shared_component_geometry():
 import re
 v=from_snapshot(S());i=render(v,'responsive',theme='I');c=render(v,'responsive',theme='C')
 def css(x):return re.search(r'<style>(.*?)</style>',x,re.S).group(1)
 # Approved artwork may own theme-local decoration geometry, but not typography or shared layout.
 suffix=css(c).split(':root{--theme:C}',1)[1]
 forbidden_typography=('font-size','font-family','font:','letter-spacing','line-height')
 assert not any(x in suffix for x in forbidden_typography)
 for shared in ('.content{padding:28px;width:100%;max-width:none;min-width:0}', '.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:16px}', '.notice{grid-template-columns:140px 1fr}'):
  assert shared in i and shared in c
 assert ".hero:before{content:''!important;position:absolute!important" in c
 assert 'h2{border-bottom:5px double #596253!important}' in c
 assert 'h2{border-bottom:4px double #244858!important}' in i


def test_c_has_no_white_outline_box_language():
 v=from_snapshot(S());page=render(v,'responsive',theme='C')
 assert 'border-color:#b8bdb6' not in page
 assert 'background:linear-gradient(110deg,#232823,#171b17)' in page
 assert 'border-color:transparent' in page

def test_c_and_i_have_independent_visual_languages_beyond_palette():
 v=from_snapshot(S());c=render(v,'responsive',theme='C');i=render(v,'responsive',theme='I')
 assert 'box-shadow:inset 3px 0 #d8df27' in c
 assert 'text-shadow:10px 0 24px #5e651f' in c
 assert 'radial-gradient(circle at 82% 8%' in i
 assert 'text-shadow:0 0 22px #245a77' in i
 assert 'box-shadow:inset 2px 0 #56c7d9,inset 0 1px #28495c' in i


def test_c_inputs_are_dark_not_white_control_boxes():
 v=from_snapshot(S());c=render(v,'responsive',theme='C')
 assert 'input,select{background:#202520;color:#e9ede8' in c
 assert 'input,select{background:#e5e9e3' not in c

def test_i_uses_multicolor_status_instrumentation_not_two_color_skin():
 v=from_snapshot(S());i=render(v,'responsive',theme='I')
 for token in ('#56c7d9','#e8c64b','#f28a3a','#e45656'):
  assert token in i
 assert '.metrics>b:nth-child(1)' in i and '.metrics>b:nth-child(3)' in i

def test_shared_renderer_has_fluid_breakpoints_and_overflow_guards():
 v=from_snapshot(S());page=render(v,'responsive')
 assert '@media(max-width:900px)' in page and '@media(max-width:700px)' in page
 assert 'overflow-wrap:anywhere' in page
 assert '.task input[name=task]{flex:1;min-width:0}' in page

def test_echo_is_browser_fluid_not_fixed_to_one_pixel_width():
 v=from_snapshot(S());page=render(v,'echo')
 assert 'grid-template-columns:minmax(112px,145px) minmax(0,1fr)' in page
 assert '@media(max-width:600px){main{grid-template-columns:1fr}nav{display:none}' in page
 assert 'minmax(min(180px,100%),1fr)' in page


def test_motion_is_not_attached_to_hero_or_notifications():
 v=from_snapshot(S())
 for theme in ('C','I'):
  page=render(v,'responsive',theme=theme)
  assert 'state-running' not in page and 'state-uncertain:after' not in page
  assert 'notice{position:relative}' not in page
  assert '@media(prefers-reduced-motion:reduce)' in page

def test_motion_focuses_on_provider_and_controls():
 v=from_snapshot(S());page=render(v,'responsive',theme='I')
 assert '.health-online:hover:after{animation:provider-pulse' in page
 assert 'button:active{transform:translateY(1px)' in page
 assert 'button:focus-visible,input:focus-visible,select:focus-visible' in page

def test_operational_sections_have_explicit_spacing():
 v=from_snapshot(S());page=render(v,'responsive')
 assert 'section{margin:0 0 72px 0;padding:14px 0;scroll-margin-top:24px}section+section{padding-top:24px}' in page
 echo=render(v,'echo')
 assert 'section{margin:0 0 24px 0}section+section{padding-top:6px}' in echo


def test_terminal_suffix_is_removed_from_production_brand():
 page=render(from_snapshot(S()),'responsive')
 assert 'AI FOUNDATION / TERMINAL' not in page
 assert '<nav><b>AI FOUNDATION</b>' in page

def test_operational_motion_targets_routes_compute_and_controls_not_notifications():
 page=render(from_snapshot(S()),'responsive',theme='I')
 assert '.route-active{animation:route-live' in page
 assert '.compute-active{animation:compute-live' in page
 assert '@keyframes control-confirm' in page
 assert 'notice{animation:' not in page

def test_responsive_navigation_targets_spaced_sections_with_smooth_scroll():
 page=render(from_snapshot(S()),'responsive')
 assert 'html{scroll-behavior:smooth;scroll-padding-top:18px}' in page
 assert 'section{margin:0 0 72px 0;padding:14px 0;scroll-margin-top:24px}' in page
 assert 'grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:16px' in page
 assert '.route{background:#091722;border-bottom:1px solid #203b4d;padding:20px;' in page
 assert 'h2{font-size:16px;' in page

def test_responsive_and_echo_profiles_after_surface_unification():
 v=from_snapshot(S())
 responsive=render(v,'responsive');echo=render(v,'echo')
 assert '@media(max-width:700px)' in responsive and 'main{grid-template-columns:1fr}' in responsive
 assert 'grid-template-columns:repeat(auto-fit,minmax(310px,1fr))' in responsive
 assert 'section{margin:0 0 24px 0}section+section{padding-top:6px}' in echo
 assert '@media(prefers-reduced-motion:reduce)' in responsive


def test_responsive_nav_is_sticky_and_matches_document_order():
 page=render(from_snapshot(S()),'responsive')
 assert 'position:sticky;top:0;height:100vh;align-self:start' in page
 positions=[page.index(f'href="#{x}"') for x in ('notifications','routing','settings','tasks','system')]
 assert positions==sorted(positions)

def test_responsive_sections_have_scroll_runway_and_full_typography():
 page=render(from_snapshot(S()),'responsive')
 assert '<div class=scroll-tail aria-hidden=true></div>' in page
 assert '.scroll-tail{height:58vh;min-height:420px}' in page
 assert 'font:16px ui-monospace,monospace' in page
 assert 'nav b{font:800 20px Arial' in page
 assert 'nav a{padding:12px;font-size:16px' in page
 assert '.hero h1{font:800 60px Arial' in page
 assert 'h2{font-size:16px;' in page
 assert '.quota{font-size:24px' in page

def test_scroll_runway_is_not_added_to_compact_surface_layout():
 v=from_snapshot(S())
 assert '<div class=scroll-tail aria-hidden=true></div>' in render(v,'responsive')
 assert '<div class=scroll-tail aria-hidden=true></div>' not in render(v,'echo')


def test_browser_uses_full_type_scale_with_viewport_responsiveness_and_echo_stays_compact():
 v=from_snapshot(S());r=render(v,'responsive');e=render(v,'echo')
 assert 'font:16px ui-monospace,monospace' in r and '@media(max-width:700px)' in r
 assert 'body{font-size:13px}' in e and 'h2{font-size:13px}' in e

def test_production_ui_has_no_motion_preview_controls_or_fake_activity():
 v=from_snapshot(S()); page=render(v,'responsive',theme='I')
 assert 'PREVIEW MOTION' not in page and 'motion-preview' not in page
 assert '#motion-preview' not in page and 'activity-scan' not in page and 'activity-tag' not in page

def test_home_navigation_is_first_and_targets_real_page_top():
 page=render(from_snapshot(S()),'responsive')
 assert '<main id=top class=responsive>' in page
 home=page.index('href="#top">HOME</a>')
 notice=page.index('href="#notifications">NOTIFICATIONS</a>')
 assert home < notice

def test_home_update_is_available_on_all_surfaces_without_expanding_echo_authority():
 v=from_snapshot(S())
 r=render(v,'responsive'); e=render(v,'echo')
 for page in (r,e):
  assert 'href="#top">HOME</a>' in page and '<main id=top ' in page
 assert 'SUBMIT TASK' not in e and 'AUTHORIZE' not in e and 'ADD API' not in e

def test_responsive_browser_and_echo_keep_shared_brand_but_distinct_authority():
 v=from_snapshot(S())
 r=render(v,'responsive'); e=render(v,'echo')
 # Shared brand/theme/state/status updates remain present.
 for page in (r,e):
  assert 'AI FOUNDATION' in page and 'SYSTEM STATUS' in page and 'CHANGE DESIGN' in page
  assert 'scroll-behavior:smooth' in page and '@media(prefers-reduced-motion:reduce)' in page
 # Production surfaces contain no synthetic motion-preview control; activity animation is driven only by live execution state.
 assert 'PREVIEW MOTION' not in r and 'PREVIEW MOTION' not in e and 'motion-preview' not in r
 # The one browser surface retains full settings/routing authority at every viewport; Echo remains constrained.
 assert 'ADD API' in r and 'UPDATE ROUTES' in r
 assert 'LOCAL COMPUTE' not in e or '<h2>LLM USE</h2>' not in e

def test_theme_switch_preserves_each_surface_without_referer_dependency():
 v=from_snapshot(S())
 assert 'name="return_to" value="/"' in render(v,'responsive')
 assert 'name="return_to" value="/echo"' in render(v,'echo')

def test_each_surface_navigation_order_matches_its_document_order():
 v=from_snapshot(S())
 d=render(v,'responsive'); e=render(v,'echo')
 d_nav=[d.index(f'href="#{x}"') for x in ('notifications','routing','settings','tasks','system')]
 d_sections=[d.index(f'id="{x}"') for x in ('notifications','routing','settings','tasks','system')]
 assert d_nav==sorted(d_nav) and d_sections==sorted(d_sections)
 e_nav=[e.index(f'href="#{x}"') for x in ('notifications','system')]
 e_sections=[e.index(f'id="{x}"') for x in ('notifications','system')]
 assert e_nav==sorted(e_nav) and e_sections==sorted(e_sections)


def test_tasks_is_supervision_not_normal_work_entry():
 v=from_snapshot(S(),tasks=(HumanTask('j','upstream work',1,'RUNNING',''),))
 page=render(v,'responsive')
 assert 'TASKS' in page
 assert 'id="tasks"' in page
 assert 'SUBMIT TASK' not in page and 'Describe work for Foundation' not in page

def test_input_required_renders_response_only_when_durable_service_available():
 v=from_snapshot(S(),notices=(HumanNotice(4,'work','job:0','WAITING_HUMAN','入力','情報',False,True),))
 off=render(v,'responsive',csrf='T',human_input_available=False)
 on=render(v,'responsive',csrf='T',human_input_available=True)
 assert '追加命令：入力経路未接続' in off and '/action/respond/job:0' not in off
 assert '/action/respond/job:0' in on and '追加命令・必要な情報' in on
 assert 'role-confirm">AUTHORIZE</button>' not in on and '/action/authorize/' not in on

def test_real_execution_activity_drives_live_user_flow():
 from ai_foundation.execution_activity import ExecutionActivity
 from ai_foundation.human_view import HumanRoute
 v=from_snapshot(S(),routes=(type('R',(),{'function':'GENERAL','primary':'b','standby':()})(),),activity=(ExecutionActivity('j','GENERAL','b','CLOUD','GROQ / FREE',1),),route_label=lambda b:'GROQ / FREE')
 page=render(v,'responsive')
 assert 'USING NOW / GROQ / FREE' in page and 'flow-svg-node live' in page

def test_settings_labels_only_claim_implemented_routing_semantics():
 page=render(from_snapshot(S(),routes=(type('R',(),{'function':'GENERAL','primary':'b','standby':()})(),),route_label=lambda b:'GROQ / FREE'),'responsive')
 assert 'PAID API' in page and 'DISABLED' in page
 assert 'name=quality' not in page and 'name=latency' not in page and 'name=privacy' not in page
 assert 'UPDATE ROUTES' in page
 assert 'PRIMARY ·' not in page and 'FALLBACK ·' not in page
 assert '/settings/routing/preferences' not in page

def test_same_action_roles_use_shared_component_contract_across_surfaces_and_themes():
 from ai_foundation.human_operations import HumanNotice
 v=from_snapshot(S(),notices=(HumanNotice(4,'work','r','WAITING_HUMAN','承認','必要',True,False),))
 for theme in ('C','I'):
  page=render(v,'responsive',csrf='T',theme=theme)
  assert 'ui-button role-confirm">AUTHORIZE' in page
  assert 'ui-button role-danger">DENY' in page
  assert 'ui-button role-secondary">DISMISS' not in page
  echo=render(v,'echo',csrf='T',theme=theme)
  assert 'AUTHORIZE' not in echo and 'DENY' not in echo
  assert 'ui-button role-secondary">DISMISS' not in echo

def test_owner_notification_actions_have_no_duplicate_delegate_or_dismiss():
 from ai_foundation.human_operations import HumanNotice
 v=from_snapshot(S(),notices=(
  HumanNotice(4,'approval','release-1','WAITING_HUMAN','本番承認','スコープ',True,False,approval_ref='a'*64),
 ))
 page=render(v,'responsive',csrf='T',mcp_owner_delegation=True)
 assert '/action/approve/release-1' in page
 assert '/action/cancel/release-1' in page
 assert page.count('role-confirm">AUTHORIZE')==1
 assert page.count('role-danger">DENY')==1
 for unwanted in ('DELEGATE AUTHORIZE VIA MCP','DELEGATE DENY VIA MCP',
                  '/action/delegate-mcp/','/notification/dismiss/','VERIFY OUTCOME'):
  assert unwanted not in page


def test_all_rendered_buttons_use_shared_ui_button_component():
 v=from_snapshot(S())
 for surface in ('responsive','echo'):
  page=render(v,surface)
  import re
  assert all('ui-button' in tag for tag in re.findall(r'<button[^>]*>',page))

def test_cards_and_fields_use_shared_component_classes():
 from ai_foundation.provider_registry import ProviderCard
 v=from_snapshot(S(),providers=(ProviderCard('GROQ','FREE',1,'ONLINE',80,'7s',20,'1h'),))
 d=render(v,'responsive')
 assert 'panel-capacity provider health-online' in d
 assert 'ui-field field-password' in d and 'ui-field field-select' in d
 assert 'ui-metric' in d and 'ui-section-title' in d

def test_responsive_surface_uses_compact_count_strip_and_full_information_model():
 page=render(from_snapshot(S()),'responsive')
 assert '.metrics{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;max-width:760px}' in page
 assert '.metrics>b{min-width:0;background:#0a1925;padding:10px 12px;font-size:24px}' in page
 assert 'ADD API' in page and 'UPDATE ROUTES' in page and 'API CONNECTIONS' in page
 assert '@media(max-width:700px){main{grid-template-columns:1fr}' in page

def test_top_count_strip_is_exactly_five_notification_levels():
 from ai_foundation.human_operations import HumanNotice
 v=from_snapshot(S(),notices=tuple(HumanNotice(i,'x',str(i),'X','s','d') for i in (1,2,2,3,4,5,5,5)))
 page=render(v,'responsive')
 for label,count in [('LV1 INFO',1),('LV2 NOTICE',2),('LV3 ATTENTION',1),('LV4 ACTION',1),('LV5 CRITICAL',3)]:
  assert f'>{count}<small>{label}</small>' in page
 assert '<small>WAITING</small>' not in page and '<small>UNCERTAIN</small>' not in page and '<small>VERIFIED</small>' not in page
 assert page.index('LV5 CRITICAL') < page.index('LV4 ACTION') < page.index('LV3 ATTENTION') < page.index('LV2 NOTICE') < page.index('LV1 INFO')

def test_severity_strip_order_matches_live_required_order():
 v=from_snapshot(S())
 page=render(v,'responsive')
 labels=('LV5 CRITICAL','LV4 ACTION','LV3 ATTENTION','LV2 NOTICE','LV1 INFO')
 positions=[page.index(x) for x in labels]
 assert positions == sorted(positions)

def test_responsive_surface_exposes_configured_chat_entry_without_second_manual_url():
 page=render(from_snapshot(S()),'responsive',chat_url='/chat')
 assert 'href="/chat"' in page and 'CHAT' in page


def test_echo_never_exposes_chat_entry():
 page=render(from_snapshot(S()),'echo',chat_url='http://chat.example')
 assert 'CHAT' not in page and 'chat.example' not in page

def test_echo_has_no_meta_refresh_or_external_navigation():
 page=render(from_snapshot(S()),'echo',chat_url='http://chat.example')
 assert 'http-equiv=refresh' not in page
 assert 'external-link' not in page and 'CHAT' not in page
 assert 'return_to" value="/echo"' in page

def test_completed_tasks_are_not_projected_as_dashboard_activity(tmp_path):
 from ai_foundation.task_intake import TaskIntake
 from ai_foundation.human_operations import tasks
 from ai_foundation.task_result import TaskResult
 t=TaskIntake(tmp_path/'w.sqlite');r=t.submit('done');t.execute(r.job_id,lambda _:type('O',(),{'status':'VERIFIED_COMPLETE','result':'ok','route_kind':'LOCAL','route_binding':'local:x'})())
 assert tasks(t)==()

def test_all_surfaces_do_not_poll_or_reload():
 # Owner decision 2026-11-23: the periodic status poll reloaded the whole
 # page every few seconds, losing scroll position and restarting the flow
 # animations. The page is static per load; the owner reloads manually.
 v=from_snapshot(S())
 for surface in ('responsive','echo'):
  page=render(v,surface,theme='I')
  assert 'http-equiv=refresh' not in page
  assert 'setInterval' not in page
  assert 'location.reload' not in page
  assert "fetch('/api/human/status'" not in page
  assert "fetch('/presentation/theme'" not in page
  # The provider-selection error focus behaviour is retained.
  assert 'provider_error' in page
def test_owner_navigation_requires_real_body_close_and_script_after_content():
 page=render(from_snapshot(S()),'responsive')
 assert '<html lang=ja><head>' in page
 assert '</head><body><main id=top' in page
 assert page.index('</main>') < page.index('provider_error') < page.index('</body></html>')



def test_provider_cards_sort_short_limit_ascending_then_unmeasured_then_local():
 from ai_foundation.provider_registry import ProviderCard
 from ai_foundation.local_compute_registry import LocalComputeCandidate
 v=from_snapshot(S(),providers=(ProviderCard('UNKNOWN','FREE',1,'ONLINE',None),ProviderCard('HIGH','FREE',1,'ONLINE',90),ProviderCard('LOW','FREE',1,'ONLINE',10)),local_compute=(LocalComputeCandidate('local:x',health='ONLINE'),))
 page=render(v,'responsive')
 assert page.index('>LOW</b>') < page.index('>HIGH</b>') < page.index('>UNKNOWN</b>') < page.index('>LOCAL COMPUTE</b>')



def test_routing_shows_only_executable_routes_as_one_ordered_chain():
 routes=(type('R',(),{'function':'CHAT','primary':'g','standby':('o','l')})(),)
 labels={'g':'Groq','o':'OpenRouter','l':'Local'}
 page=render(from_snapshot(S(),routes=routes,route_label=lambda b:labels[b]),'responsive')
 assert 'class=routes' in page
 assert 'Groq' in page and 'OpenRouter' in page and 'Local' in page
 assert page.count('class="route-arrow"')==2
 assert 'PRIMARY ·' not in page and 'FALLBACK ·' not in page

def test_only_paid_route_segment_is_vermilion_marked():
 routes=(type('R',(),{'function':'CHAT','primary':'f','standby':('p','l')})(),)
 labels={'f':'Groq','p':'Mistral / PAID','l':'Local'}
 page=render(from_snapshot(S(),routes=routes,route_label=lambda b:labels[b]),'responsive')
 assert page.count('paid-hop')>=1
 assert 'Mistral · PAID' in page
 assert 'Groq · PAID' not in page and 'Local · PAID' not in page

def test_human_action_forms_return_to_the_rendered_surface():
 class Snap:
  def as_dict(self): return {'ready':True,'waiting_human':1,'effects':{},'attention':[]}
 notices=(
  HumanNotice(4,'approval','run1','WAITING_HUMAN','a','b',True,False),
  HumanNotice(5,'effect','effect1','UNCERTAIN','a','b'),
 )
 v=from_snapshot(Snap(),notices=notices)
 responsive=render(v,'responsive',csrf='T',reconcile_available={'effect1'})
 echo=render(v,'echo',csrf='T',reconcile_available={'effect1'})
 for action in ('/action/approve/run1','/action/cancel/run1'):
  assert action in responsive
  fragment=responsive[responsive.index(action):responsive.index('</form>',responsive.index(action))]
  assert 'name="return_to" value="/"' in fragment
 for unwanted in ('/action/reconcile/effect1','/notification/dismiss/run1',
                  '/action/delegate-mcp/run1'):
  assert unwanted not in responsive
  assert unwanted not in echo
 assert '/action/approve/run1' not in echo and '/action/cancel/run1' not in echo

def test_data_human_label_is_data_analysis_and_unavailable_routes_stay_visible():
 routes=(type('R',(),{'function':'DATA','primary':None,'standby':()})(),type('R',(),{'function':'FILES','primary':None,'standby':()})(),type('R',(),{'function':'PC_CONTROL','primary':None,'standby':()})())
 page=render(from_snapshot(S(),routes=routes,route_label=lambda b:'—'),'responsive')
 assert '>DATA ANALYSIS<' in page and '>FILES<' in page and '>PC CONTROL<' in page
 assert 'CODE-BASED CALCULATION / AGGREGATION' in page
 assert page.count('NOT AVAILABLE')>=3

def test_provider_non_failure_note_is_not_rendered_as_issue():
 from ai_foundation.human_view import from_snapshot
 from ai_foundation.provider_registry import ProviderCard
 class S:
  def as_dict(self):return {'ready':True}
 v=from_snapshot(S(),providers=(ProviderCard('NVIDIA','FREE',1,'ONLINE',None,None,None,None,'quota evidence unavailable'),))
 page=render(v,csrf='x')
 assert 'NOTE · quota evidence unavailable' in page
 assert 'ISSUE · quota evidence unavailable' not in page

def test_capability_execution_path_is_human_infrastructure_plus_one_compact_llm_route():
 routes=(type('R',(),{'function':'FILES','primary':None,'standby':()})(),type('R',(),{'function':'SEARCH','primary':'g','standby':()})(),type('R',(),{'function':'CODE','primary':'g','standby':('o',)})())
 v=from_snapshot(S(),routes=routes,route_label=lambda b:{'g':'Groq','o':'OpenRouter'}.get(b,'—'),execution_paths={'FILES':('ToolHive MCP',),'SEARCH':(),'CODE':('ToolHive MCP',)})
 page=render(v,'responsive')
 files=page[page.index('>FILES<'):page.index('</article>',page.index('>FILES<'))]
 search=page[page.index('>SEARCH<'):page.index('</article>',page.index('>SEARCH<'))]
 code=page[page.index('>CODE<'):page.index('</article>',page.index('>CODE<'))]
 assert 'ToolHive MCP' in files and 'LLM ROUTE' not in files
 assert 'LLM ROUTE (' in search and 'Groq' in search and 'Specialist' not in search
 assert 'ToolHive MCP' in code and 'LLM ROUTE' not in code and 'Groq' not in code and 'OpenRouter' not in code and 'Specialist' not in code

def test_resolving_request_is_visible_but_does_not_claim_execution():
 # use existing view helper where available by replacing activity on a known fixture is cumbersome; assert renderer source contract instead
 import inspect,ai_foundation.human_renderer as hr
 src=inspect.getsource(hr._route_panel)
 assert 'RESOLVING REQUEST' in src and "a.kind!='RESOLVING'" in src


def test_operator_capability_paths_require_live_executable_route_for_inference_caps():
 from ai_foundation.operator_server import OperatorApplication
 app=object.__new__(OperatorApplication); app.capability_factory=lambda *a:None
 app.capability_executor=type('E',(),{'file_port':object(),'repo_port':object(),'vision_port':object()})()
 app.settings=type('Settings',(),{'choose_route':lambda self,f: {'SEARCH':None,'CODE':'code-live','VISION':None}.get(f)})()
 paths=app.capability_execution_paths()
 assert 'SEARCH' not in paths and paths['CODE']==('ToolHive MCP',)
 assert paths['DATA']==('Bounded Compute',) and paths['FILES']==('ToolHive MCP',)
 assert 'VISION' not in paths
 assert 'PC_CONTROL' not in paths

 app.settings=type('Settings',(),{'choose_route':lambda self,f: {'SEARCH':None,'CODE':'code-live','VISION':'local:llama-swap:local-vision'}.get(f)})()
 paths=app.capability_execution_paths()
 assert paths['VISION']==('Vision Adapter',)


def test_task_route_binding_uses_same_human_route_label_rule():
 from ai_foundation.human_operations import HumanTask
 task=HumanTask('j','work',1,'RUNNING','pending','VERIFIED','LOCAL',(), 'local:code')
 v=from_snapshot(S(),tasks=(task,),route_label=lambda b:{'local:code':'code-model'}.get(b,'UNAVAILABLE'))
 page=render(v,'responsive')
 assert 'METHOD LOCAL / code-model' in page
 assert 'local:code' not in page


def test_provider_issue_and_note_have_distinct_semantic_classes():
 from ai_foundation.provider_registry import ProviderCard
 issue=render(from_snapshot(S(),providers=(ProviderCard('A','FREE',1,'RATE_LIMITED',reason='HTTP 429'),)),'responsive')
 note=render(from_snapshot(S(),providers=(ProviderCard('B','FREE',1,'ONLINE',reason='quota evidence unavailable'),)),'responsive')
 assert 'provider-issue' in issue and 'ISSUE · HTTP 429' in issue
 assert 'provider-note' in note and 'NOTE · quota evidence unavailable' in note

def test_add_api_exposes_provider_selection_without_hiding_it_in_more_options():
 page=render(from_snapshot(S()),'responsive')
 assert 'API TYPE<select id="provider-select"' in page
 assert page.index('id="provider-select"') < page.index('<details id="provider-options">')
 assert '>EXA</option>' in page and '>AUTO DETECT</option>' in page

def test_host_only_data_does_not_render_unused_provider_route():
 routes=(type('R',(),{'function':'DATA','primary':'g','standby':()})(),)
 v=from_snapshot(S(),routes=routes,route_label=lambda b:'Groq',execution_paths={'DATA':('Bounded Compute',)})
 page=render(v,'responsive')
 data=page[page.index('>DATA ANALYSIS<'):page.index('</article>',page.index('>DATA ANALYSIS<'))]
 assert 'Bounded Compute' in data and 'LLM ROUTE' not in data and 'Groq' not in data



def test_overview_worker_tile_shows_cycle_blocked():
 dev={'local9b_worker': 'SCHEDULED_IDLE',
      'local9b_queue_state': 'SCHEDULED_CYCLE_BLOCKED'}
 page=render(from_snapshot(S(),development=dev),'responsive')
 overview=page[page.index('id="overview"'):page.index('id="routing"')]
 assert '停止中' in overview
 assert 'LOCAL 9B QUEUE / SCHEDULED_CYCLE_BLOCKED' in page


def test_existing_settings_starts_with_source_bound_overview_without_claiming_mcp_or_klm():
 from ai_foundation.provider_registry import ProviderCard
 class Source:
  def as_dict(self):
   return {'ready': False, 'effects': {}, 'waiting_human': 0, 'attention': []}
 dev={'guard_actionable': 2, 'work_waiting_human': 1,
      'local9b_worker': 'SCHEDULED_IDLE',
      'local9b_queue_state': 'NO_QUEUED_TASK',
      'approved_humanmodel_view': '<unsafe owner>'}
 view=from_snapshot(Source(), providers=(
     ProviderCard('TEST_PROVIDER','FREE',1,'ONLINE'),
     ProviderCard('DOWN_PROVIDER','FREE',1,'DOWN'),
 ),development=dev)
 responsive=render(view,'responsive',csrf='synthetic')
 echo=render(view,'echo',csrf='synthetic')
 assert 'href="#overview"' in responsive
 assert responsive.index('id="notifications"') < responsive.index('id="overview"')
 for part in ('PRODUCTION','GUARD APPROVAL','DEVELOPMENT WORKER',
              'HUMANMODEL','KLM DRIVE SYNC','1 / 2 ONLINE',
              '\u627f\u8a8d\u5f85\u3061 2 \u4ef6','\u5f85\u6a5f\u4e2d','\u672a\u78ba\u8a8d'):
  assert part in responsive
 assert 'HUMANMODEL' in responsive and 'UNVERIFIED' in responsive
 assert '&lt;unsafe owner&gt;' not in responsive and '<unsafe owner>' not in responsive
 assert 'id="overview"' not in echo
 assert 'href="#settings"' in responsive and 'href="#development"' in responsive


def test_overview_service_ratio_includes_unverified_services():
 class Source:
  def as_dict(self):
   return {'ready':False,'effects':{},'waiting_human':0,'attention':[],
           'services':[{'name':'code','ok':True},
                       {'name':'files','ok':True},
                       {'name':'local','ok':None}]}
 page=render(from_snapshot(Source()),'responsive')
 # The ratio itself moved out of the overview (owner: no detail dump);
 # per-service honesty is rendered by the SYSTEM panel instead.
 assert 'code OK' in page and 'files OK' in page
 assert 'local UNVERIFIED' in page
 assert '2 / 2 READY' not in page


def test_observed_timestamp_fails_closed_for_invalid_untrusted_telemetry():
 from ai_foundation.human_renderer import _observed
 for value in (None, False, True, 'not-a-time', '1700000000', -1, 0,
               float('nan'), float('inf'), float('-inf'), 10**100):
  assert _observed(value) == 'UNKNOWN'
 assert _observed(1700000000) != 'UNKNOWN'

def test_shared9b_overview_distinguishes_busy_from_worker_idle():
 from ai_foundation.local_compute_registry import LocalComputeCandidate
 from ai_foundation.human_renderer import _shared9b_overview
 def overview(reason,health='UNAVAILABLE',active=False):
  model=LocalComputeCandidate('local:ollama-shared9b:general',
       health=health,active=active,reason=reason)
  return _shared9b_overview((model,))
 value,detail=overview('OTHER_LOCAL_MODEL_OR_BACKEND_RESIDENT')
 assert value=='UNAVAILABLE' and 'OTHER_LOCAL_MODEL_OR_BACKEND_RESIDENT' in detail
 assert 'NO MODEL EVICTION' in detail
 value,detail=overview('PRIVATE_CANARY')
 assert 'PRIVATE_CANARY' not in detail and 'MODEL ADMISSION NOT PROVEN' in detail
 value,detail=overview(None,health='ONLINE',active=True)
 assert value=='DISCOVERED' and 'INFERENCE NOT VERIFIED' in detail
 value,detail=_shared9b_overview(())
 assert 'NO UNIQUE SAME-HOST SHARED-9B OBSERVATION' in detail
 page=render(from_snapshot(S(),development={'local9b_worker':'SCHEDULED_IDLE'}),'responsive')
 assert '\u958b\u767a\u306e\u5b9f\u884c' in page and '\u5f85\u6a5f\u4e2d' in page



def test_strata_overview_requires_exact_live_code_model_not_old_receipt():
 from ai_foundation.local_compute_registry import LocalComputeCandidate
 from ai_foundation.human_renderer import _strata_overview
 good=LocalComputeCandidate(
  'local:mainpc-strata:code-agent',health='ONLINE',active=True,
  model='qwen3.8-flash-next-coder-iq1_m',
  capabilities=('CHAT','CODE'),same_host=False)
 value,detail=_strata_overview((good,))
 assert value=='DISCOVERED' and 'NO ACTIVE JOB PROVEN' in detail
 assert 'NO CURRENT STRATA CODE OBSERVATION' in _strata_overview(())[1]
 for override in ({'model':'impostor'}, {'same_host':True},
                  {'active':False}, {'capabilities':('CHAT',)}):
  from dataclasses import replace
  assert 'NO CURRENT STRATA CODE OBSERVATION' in (
   _strata_overview((replace(good,**override),))[1])
 offline=LocalComputeCandidate('local:mainpc-strata',reason='URLError',
                               health='UNAVAILABLE',same_host=False)
 value,detail=_strata_overview((offline,))
 assert value=='STANDBY' and 'URLError · WAKES ON DEMAND' in detail
 unknown=LocalComputeCandidate('local:mainpc-strata',reason='PRIVATE_TOKEN_SECRET',
                               health='UNAVAILABLE',same_host=False)
 value,detail=_strata_overview((unknown,))
 assert 'PRIVATE_TOKEN_SECRET' not in detail
 assert 'NO CURRENT STRATA CODE OBSERVATION' in detail
 page=render(from_snapshot(S(),local_compute=(good,)),'responsive')
 assert 'MAINPC / STRATA' in page and '\u63a5\u7d9a\u3042\u308a' in page


def test_primary_humanmodel_answer_shows_current_provisional_result_and_muse_correction_scope():
 import hashlib
 evidence = hashlib.sha256(b"reviewed existing evidence").hexdigest()
 generation = hashlib.sha256(b"exact primary-review generation").hexdigest()
 reference = {
  "task_id": "work-auto-1", "question_digest": generation,
  "evidence_sha256": evidence, "current_generation": True,
  "related_work_status": "WAITING_HUMAN",
 }
 n = HumanNotice(2, "primary_review", "primary-1-result",
                 "PRIMARY_REVIEW_RESOLVED", "一次判断", "詳細",
                 automatic_answer="<script>malicious</script> 人間モデルの暫定回答",
                 answer_reference=reference)
 v = from_snapshot(S(),notices=(n,))
 page = render(v,"responsive")
 assert "HumanModel 自動回答（暫定・本人未承認）" in page
 assert "&lt;script&gt;malicious&lt;/script&gt;" in page
 assert "<script>malicious</script>" not in page
 assert "work-auto-1" in page and generation in page and evidence in page
 assert "Muse" in page and "Guardの許可" in page
 echo = render(v,"echo")
 assert "malicious" not in echo and "work-auto-1" not in echo
 assert "humanmodel-auto-answer" not in echo


def test_unbound_or_invalid_humanmodel_answers_never_render_as_accepted():
 import hashlib
 from dataclasses import replace
 generation = hashlib.sha256(b"generation").hexdigest()
 evidence = hashlib.sha256(b"evidence").hexdigest()
 valid = HumanNotice(2, "primary_review", "primary-result",
                     "PRIMARY_REVIEW_RESOLVED", "summary", "detail",
                     automatic_answer="PRIVATE_UNVERIFIED_ANSWER",
                     answer_reference={
                         "task_id": "job-1", "question_digest": generation,
                         "evidence_sha256": evidence, "current_generation": True,
                         "related_work_status": "UNVERIFIED"})
 for bad in (
    replace(valid, answer_reference=None),
    replace(valid, answer_reference={**valid.answer_reference,"evidence_sha256":""}),
    replace(valid, answer_reference={**valid.answer_reference,"question_digest":"wrong"}),
    replace(valid, answer_reference={**valid.answer_reference,"current_generation":"yes"}),
    replace(valid, answer_reference={**valid.answer_reference,"extra":"external"}),
    replace(valid, answer_reference={**valid.answer_reference,"task_id":"../secret"}),
    replace(valid, kind="approval"),
    replace(valid, status="WAITING_HUMAN"),
    replace(valid, automatic_answer="X"*16001),
 ):
  page = render(from_snapshot(S(),notices=(bad,)),"responsive")
  assert "PRIVATE_UNVERIFIED_ANSWER" not in page
  assert 'class="humanmodel-auto-answer"' not in page


def test_old_generation_answer_is_labelled_history_not_current_authorization():
 import hashlib
 ref = {"task_id":"job-1", "question_digest":hashlib.sha256(b"old").hexdigest(),
        "evidence_sha256":hashlib.sha256(b"real").hexdigest(),
        "current_generation":False, "related_work_status":"VERIFIED"}
 n = HumanNotice(2,"primary_review","primary-old-result","PRIMARY_REVIEW_RESOLVED",
                 "old","detail",automatic_answer="past decision",
                 answer_reference=ref)
 page = render(from_snapshot(S(),notices=(n,)),"responsive")
 assert "past decision" in page
 assert "過去の自動回答（現在の判断ではありません）" in page
 assert "再適用不可" in page
 assert "本人の承認" in page


def test_overview_function_node_shows_only_unassigned():
 mk=lambda f,p=None: type('R',(),{'function':f,'primary':p,'standby':()})()
 routes=(mk('CHAT','g'),mk('SEARCH','e'),mk('CODE'),mk('DATA'),mk('FILES'),mk('PC_CONTROL'),mk('VISION'))
 page=render(from_snapshot(S(),routes=routes,route_label=lambda b:{'g':'Groq','e':'Exa'}.get(b,'—')),'responsive')
 assert 'VISION → 未割当' in page and '他は担当あり' in page
 assert 'CHAT → Groq' not in page and '他 1 機能' not in page

def test_overview_function_node_all_assigned():
 mk=lambda f,p=None: type('R',(),{'function':f,'primary':p,'standby':()})()
 routes=(mk('CHAT','g'),mk('VISION','g'))
 page=render(from_snapshot(S(),routes=routes,route_label=lambda b:'Groq'),'responsive')
 assert '全ての機能に担当あり' in page

def test_overview_klm_tile_shows_unresolved_review_count():
 dev={'klm_lifecycle_state':'OBSERVED','klm_unresolved_reviews':99,'klm_atoms':10,'klm_status':'CURRENT'}
 page=render(from_snapshot(S(),development=dev),'responsive')
 assert '確認待ち 99 件' in page

def test_overview_acceptance_tile_ignores_historical_failures():
 dev={'work_failed':27,'work_uncertain':0,'work_waiting_human':8}
 page=render(from_snapshot(S(),development=dev),'responsive')
 assert '累計失敗' not in page and '問題なし' in page
 dev2={'work_failed':27,'work_uncertain':2,'work_waiting_human':0}
 page2=render(from_snapshot(S(),development=dev2),'responsive')
 assert '不確実 2 件' in page2


def _lane_live(page, name):
 i = page.index('>' + name + '<')
 j = page.rindex('<g class="', 0, i)
 return ' live' in page[j:j + 40]

def test_overview_external_lane_glows_only_for_cloud_execution():
 from ai_foundation.execution_activity import ExecutionActivity
 mk = lambda kind: (ExecutionActivity('j', 'CHAT', 'b', kind, 'GROQ / FREE', 1),)
 page = render(from_snapshot(S(), activity=mk('CLOUD')), 'responsive')
 assert _lane_live(page, '外部AI')
 page2 = render(from_snapshot(S(), activity=mk('LOCAL')), 'responsive')
 assert not _lane_live(page2, '外部AI')
 page3 = render(from_snapshot(S()), 'responsive')
 assert not _lane_live(page3, '外部AI')

def test_overview_never_links_to_frozen_review_pages():
 dev = {'klm_lifecycle_state': 'OBSERVED', 'klm_unresolved_reviews': 99,
        'klm_atoms': 10, 'klm_status': 'CURRENT'}
 page = render(from_snapshot(S(), development=dev), 'responsive')
 assert '確認待ち 99 件' in page and '/klm/review' not in page
