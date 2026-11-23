from dataclasses import dataclass
import re

@dataclass(frozen=True)
class ProviderSpec:
 name:str
 endpoint:str|None=None
 model:str|None=None
 key_pattern:re.Pattern|None=None
 auth_style:str='bearer'
 quota_style:str|None=None
 probe_style:str='inference'
 models_endpoint:str|None=None
 protocol:str|None=None
 capabilities:tuple[str,...]=()

_SPECS=(
 ProviderSpec('GROQ','https://api.groq.com/openai/v1/chat/completions','openai/gpt-oss-20b',re.compile(r'^gsk_[0-9A-Za-z_-]{16,}$'),quota_style='groq',protocol='openai-chat',capabilities=('CHAT','SEARCH','CODE','DATA')),
 ProviderSpec('GEMINI','https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent','gemini-3.8-flash',re.compile(r'^AIza[0-9A-Za-z_-]{20,}$'),auth_style='gemini',protocol='gemini-generate',capabilities=('CHAT','CODE')),
 ProviderSpec('OPENROUTER','https://openrouter.ai/api/v1/chat/completions','openrouter/free',re.compile(r'^sk-or-v1-[0-9A-Za-z_-]{16,}$'),protocol='openai-chat',capabilities=('CHAT','CODE')),
 ProviderSpec('MISTRAL','https://api.mistral.ai/v1/chat/completions','mistral-small-latest',quota_style='mistral',protocol='openai-chat',capabilities=('CHAT','CODE')),
 ProviderSpec('NVIDIA','https://integrate.api.nvidia.com/v1/chat/completions','openai/gpt-oss-20b',re.compile(r'^nvapi-[0-9A-Za-z_-]{16,}$'),probe_style='models',models_endpoint='https://integrate.api.nvidia.com/v1/models',protocol='openai-chat',capabilities=('CHAT','CODE')),
 ProviderSpec('COHERE','https://api.cohere.com/v2/chat','command-a-plus-05-2026',None,probe_style='models',models_endpoint='https://api.cohere.com/v1/models',protocol='cohere-v2',capabilities=('CHAT','CODE')),
 ProviderSpec('EXA','https://api.exa.ai/search','exa-search',None,auth_style='x-api-key',probe_style='search',protocol='exa-search',capabilities=('SEARCH',)),
 ProviderSpec('TAVILY','https://api.tavily.com/search','tavily-search',re.compile(r'^tvly-[0-9A-Za-z_-]{16,}$'),auth_style='bearer',probe_style='search',protocol='tavily-search',capabilities=('SEARCH',)),
 ProviderSpec('GITHUB',None,None,re.compile(r'^github_pat_[0-9A-Za-z_]+$'),auth_style='github',probe_style='identity',models_endpoint='https://api.github.com/user'),
)
PROVIDERS={s.name:s for s in _SPECS}
PROVIDER_NAMES=tuple(PROVIDERS)

def spec(name):
    if not isinstance(name, str):
        return None
    return PROVIDERS.get(name.upper())

def detect(secret):
    if not isinstance(secret, str):
        return None
    for s in _SPECS:
        if s.key_pattern and s.key_pattern.match(secret):
            return s.name
    return None