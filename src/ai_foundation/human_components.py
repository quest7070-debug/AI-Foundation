"""Shared semantic HTML primitives. Geometry/role classes are common across surfaces/themes."""
import html

def e(x): return html.escape(str(x if x is not None else '—'))
def hidden(name,value): return f'<input type=hidden name="{e(name)}" value="{e(value)}">'
def button(label,*,role='secondary',disabled=False,title=''):
    attrs=f' class="ui-button role-{e(role)}"'
    if disabled: attrs+=' disabled'
    if title: attrs+=f' title="{e(title)}"'
    return f'<button{attrs}>{e(label)}</button>'
def action_form(action,csrf,label,*,role='secondary',fields=()):
    return f'<form class="ui-action" method="post" action="{e(action)}">{hidden("csrf",csrf)}'+''.join(hidden(k,v) for k,v in fields)+button(label,role=role)+'</form>'
def panel(content,*,kind='standard',classes=''):
    return f'<article class="ui-panel panel-{e(kind)} {e(classes)}">{content}</article>'
def section(section_id,title,content,hint='',fold=False):
    h=f'<small class=hint>{hint}</small>' if hint else ''
    if fold:
        return f'<details class="fold" id="{e(section_id)}"><summary>{e(title)}</summary>{h}{content}</details>'
    return f'<section id="{e(section_id)}">{section_header(title)}{h}{content}</section>'


def field(name,*,kind='text',placeholder='',required=False,autocomplete=None,value=None,minimum=None,maximum=None):
    attrs=[f'type="{e(kind)}"',f'name="{e(name)}"',f'class="ui-field field-{e(kind)}"']
    if placeholder: attrs.append(f'placeholder="{e(placeholder)}"')
    if required: attrs.append('required')
    if autocomplete is not None: attrs.append(f'autocomplete="{e(autocomplete)}"')
    if value is not None: attrs.append(f'value="{e(value)}"')
    if minimum is not None: attrs.append(f'min="{e(minimum)}"')
    if maximum is not None: attrs.append(f'max="{e(maximum)}"')
    return '<input '+' '.join(attrs)+'>'

def status_panel(title,lines=(),*,kind='status',classes='',strong=()):
    body=f'<b>{e(title)}</b>'+''.join(f'<span>{e(x)}</span>' for x in lines)+''.join(f'<strong>{e(x)}</strong>' for x in strong)
    return panel(body,kind=kind,classes=classes)

def metric(value,label): return f'<b class="ui-metric">{e(value)}<small>{e(label)}</small></b>'
def section_header(title): return f'<h2 class="ui-section-title">{e(title)}</h2>'
