from ai_foundation.human_components import button,action_form,panel

def test_button_roles_have_one_shared_markup_contract():
 assert button('X',role='confirm')=='<button class="ui-button role-confirm">X</button>'
 assert 'ui-button role-danger' in action_form('/x','T','DELETE',role='danger')
 assert 'ui-panel panel-notice' in panel('x',kind='notice',classes='notice lv4')

def test_shared_fields_and_sections_have_stable_semantic_classes():
 from ai_foundation.human_components import field,section,metric
 assert 'ui-field field-password' in field('key',kind='password')
 assert '<section id="settings">' in section('settings','SETTINGS','x')
 assert 'ui-metric' in metric(2,'WAITING')
