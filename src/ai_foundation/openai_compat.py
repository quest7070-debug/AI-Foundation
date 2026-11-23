import json,time,uuid
from .core import TaskPlan,CanonContract

def as_sse(result):
 import json
 choice=result['choices'][0]; msg=choice['message']; delta={'role':'assistant'}
 if msg.get('content') is not None: delta['content']=msg.get('content','')
 if msg.get('tool_calls'): delta['tool_calls']=msg['tool_calls']
 chunk={'id':result['id'],'object':'chat.completion.chunk','created':result['created'],'model':result['model'],'choices':[{'index':choice['index'],'delta':delta,'finish_reason':None}]}
 end={'id':result['id'],'object':'chat.completion.chunk','created':result['created'],'model':result['model'],'choices':[{'index':choice['index'],'delta':{},'finish_reason':choice.get('finish_reason') or 'stop'}]}
 return 'data: '+json.dumps(chunk,ensure_ascii=False)+'\n\n'+'data: '+json.dumps(end,ensure_ascii=False)+'\n\n'+'data: [DONE]\n\n'

class OpenAICompat:
 def __init__(self,inference,dispatch=None,auto_agent_factory=None,tracer=None): self.inference=inference; self.dispatch=dispatch; self.auto_agent_factory=auto_agent_factory; self.tracer=tracer
 def chat(self,payload,capability_request=None):
  if not isinstance(payload,dict): raise ValueError('invalid JSON object')
  messages=payload.get('messages')
  if not isinstance(messages,list) or not messages: raise ValueError('messages required')
  from contextlib import nullcontext
  from .observability import safe_attributes
  request_scope=self.tracer.span('openai_compat.request',safe_attributes({'message_count':len(messages)})) if self.tracer else nullcontext()
  with request_scope:
   return self._chat_validated(payload,capability_request,messages)

 def _chat_validated(self,payload,capability_request,messages):
  parts=[]; user_parts=[]; normalized=[]
  for m in messages:
   if not isinstance(m,dict) or m.get('role') not in {'system','user','assistant','tool'}: raise ValueError('invalid message')
   content=m.get('content')
   if isinstance(content,str): text=content
   elif isinstance(content,list):
    text_parts=[]
    for item in content:
     if not isinstance(item,dict): raise ValueError('invalid message content')
     if item.get('type')=='text' and isinstance(item.get('text'),str): text_parts.append(item['text'])
     elif item.get('type') in {'image_url','input_image','image'}:
      if capability_request is None or capability_request.capability!='VISION' or not capability_request.attachments:
       raise ValueError('unsupported attachment content')
      # Image bytes/paths are resolved only by the trusted host attachment envelope.
      # Client-provided URL/base64/path fields are deliberately ignored as authority.
      continue
     else: raise ValueError('unsupported attachment content')
    text='\n'.join(text_parts)
   elif content is None and m.get('role')=='assistant' and isinstance(m.get('tool_calls'),list): text=''
   else: raise ValueError('invalid message')
   normalized.append((m,text))
   parts.append(f"{m['role']}: {text}")
   if m['role']=='user': user_parts.append(text)
  run='chat-'+uuid.uuid4().hex
  plan=TaskPlan(run,'compute','llm',text='\n'.join(parts),canon_revision='openai-compat',effect_id=run+':inference',privacy_text='\n'.join(user_parts))
  function=capability_request.capability if capability_request is not None else (self.dispatch(plan.text) if callable(self.dispatch) and not hasattr(self.dispatch,'execute') else 'CHAT')
  # A trusted capability envelope must be consumed by the host capability
  # executor. Routing it as plain inference would preserve the label while
  # silently skipping the scoped specialist/MCP boundary.
  if capability_request is not None and capability_request.capability == 'CHAT' and self.auto_agent_factory is not None:
   from pydantic_ai.messages import ModelRequest,ModelResponse,UserPromptPart,TextPart,ToolCallPart,ToolReturnPart
   latest_index=next((i for i in range(len(normalized)-1,-1,-1) if normalized[i][0].get('role')=='user'),None)
   latest=normalized[latest_index][1] if latest_index is not None else ''
   history=[]
   tool_names={}
   if latest_index is not None:
    for m,text in normalized[:latest_index]:
     role=m.get('role')
     if role=='user':
      history.append(ModelRequest(parts=[UserPromptPart(text)]))
     elif role=='assistant':
      response_parts=[]
      if text:
       response_parts.append(TextPart(text))
      tool_calls=m.get('tool_calls')
      if isinstance(tool_calls,list):
       for call in tool_calls:
        if not isinstance(call,dict):
         continue
        call_id=call.get('id')
        fn=call.get('function')
        if not isinstance(call_id,str) or not isinstance(fn,dict):
         continue
        name=fn.get('name')
        args=fn.get('arguments','{}')
        if not isinstance(name,str) or not isinstance(args,(str,dict)):
         continue
        tool_names[call_id]=name
        response_parts.append(ToolCallPart(name,args,tool_call_id=call_id))
      if response_parts:
       history.append(ModelResponse(parts=response_parts))
     elif role=='tool':
      call_id=m.get('tool_call_id')
      name=tool_names.get(call_id)
      if isinstance(call_id,str) and isinstance(name,str):
       history.append(ModelRequest(parts=[ToolReturnPart(name,text,tool_call_id=call_id)]))
   result=self.auto_agent_factory(capability_request,run).run(latest,message_history=tuple(history))
   out=type('CapabilityOutput',(),{'status':'VERIFIED_COMPLETE','result':result,'route_binding':'foundation-auto'})()
  elif capability_request is not None and capability_request.capability != 'CHAT' and self.dispatch is not None and hasattr(self.dispatch,'execute'):
   # Specialist payload is the latest user message, not the OpenAICompat
   # role-prefixed transcript. Authority still comes only from the signed
   # CapabilityRequest; this merely preserves the user's exact data/path/query.
   user_text=''
   for m,text in reversed(normalized):
    if m.get('role')=='user':
     user_text=text
     break
   result=self.dispatch.execute(capability_request,user_text,run)
   out=type('CapabilityOutput',(),{'status':'VERIFIED_COMPLETE','result':result,'route_binding':'foundation-'+function.lower()})()
  elif hasattr(self.inference,'run'):
   out=self.inference.run(plan,CanonContract('openai-compat','openai-compat'),function)
  else:
   receipt=type('Receipt',(),{'job_id':run,'text':plan.text,'privacy_text':plan.privacy_text,'created_at':time.time(),'function':function,'capability_request':capability_request})()
   out=self.inference(receipt)
  if out.status!='VERIFIED_COMPLETE' or out.result is None: raise RuntimeError(out.status)
  message=out.result if isinstance(out.result,dict) else {'role':'assistant','content':out.result}
  if message.get('role')!='assistant': raise RuntimeError('invalid inference response role')
  finish_reason='tool_calls' if message.get('tool_calls') else 'stop'
  return {'id':'chatcmpl-'+uuid.uuid4().hex,'object':'chat.completion','created':int(time.time()),'model':out.route_binding or payload.get('model') or 'foundation-auto','choices':[{'index':0,'message':message,'finish_reason':finish_reason}],'usage':{'prompt_tokens':0,'completion_tokens':0,'total_tokens':0}}
