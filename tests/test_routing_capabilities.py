from ai_foundation.routing_capabilities import ROUTE_CAPABILITIES,normalize_capability,supports

def test_one_unified_route_namespace_merges_overlap_and_keeps_distinct_functions():
 assert ROUTE_CAPABILITIES==('CHAT','SEARCH','CODE','DATA','FILES','PC_CONTROL','VISION')
 assert normalize_capability('TEXT')=='CHAT'
 assert normalize_capability('GENERAL')=='CHAT'
 assert normalize_capability('RESEARCH')=='SEARCH'
 assert normalize_capability('STRUCTURED_DATA')=='DATA'
 assert normalize_capability('COMPUTER_ACTION')=='PC_CONTROL'

def test_candidate_can_natively_supply_search_in_same_search_route():
 native={'kind':'CLOUD','protocol':'native','model':'search-model','capabilities':('CHAT','SEARCH')}
 plain={'kind':'LOCAL','capabilities':('CHAT','CODE')}
 assert supports(native,'SEARCH')
 assert not supports(plain,'SEARCH')
 assert supports(plain,'CHAT')

def test_data_is_distinct_bounded_function_not_generic_chat_claim():
 generic={'kind':'CLOUD','protocol':'openai-chat','model':'m','capabilities':('CHAT','CODE')}
 bounded={'kind':'LOCAL','capabilities':('DATA',)}
 assert not supports(generic,'DATA')
 assert supports(bounded,'DATA')
