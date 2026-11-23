"""Production-shaped ResearchPort over Foundation inference with canonical evidence parsing."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from .core import CanonContract,TaskPlan
from .research import Evidence,ResearchResult
from .temporal_context import current_temporal_context

class ResearchGroundingError(RuntimeError): pass

@dataclass
class InferenceResearchPort:
    inference: object
    canon_revision: str = "research-v1"
    temporal_context_factory: object = current_temporal_context

    def research(self,query:str)->ResearchResult:
        import uuid
        run="research-"+uuid.uuid4().hex
        temporal=self.temporal_context_factory().search_context()
        grounded_query=temporal+"\nQuery: "+query
        # This instruction is consumed only by LLM-native SEARCH providers. Native
        # retrieval protocols use privacy_text as their query and return bounded
        # evidence directly from the provider adapter without an intermediate LLM.
        instruction=(
            "Return ONLY JSON with keys answer, evidence, uncertainty. "
            "evidence must be an array of objects with source, claim, excerpt, confidence, observed_at, published_at when those timestamps are present in retrieved data. "
            "Use SEARCH capability and cite only sources actually observed. "
            "For consequential factual claims, prefer primary sources or corroboration from independent sources when retrieval makes them available. "
            "Do not present a consequential claim supported only by a single retrieved secondary source as independently confirmed; preserve that limitation in uncertainty. "
            "Do not infer corroboration merely from multiple pages repeating the same originating report. "
            "Treat the observation time as the authority for relative dates such as today, yesterday, current, latest, and recent. "
            "Do not describe evidence as current merely because it was retrieved now; use source publication/event dates when available and state uncertainty when temporal fit cannot be established. "+grounded_query
        )
        plan=TaskPlan(run,"compute","research",text=instruction,canon_revision=self.canon_revision,effect_id=run+":inference",privacy_text=grounded_query)
        out=self.inference.run(plan,CanonContract("foundation-research",self.canon_revision),"SEARCH")
        if out.status!="VERIFIED_COMPLETE" or not out.result: raise RuntimeError(out.status)
        raw=out.result.strip()
        # LLM-native providers may preserve a fenced JSON block even when instructed
        # to return JSON only. Accept exactly one JSON object fence, never arbitrary prose.
        fenced=re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```",raw,re.DOTALL|re.IGNORECASE)
        if fenced: raw=fenced.group(1)
        try: data=json.loads(raw)
        except (TypeError,json.JSONDecodeError) as e: raise RuntimeError("invalid research result") from e
        if not isinstance(data,dict) or not isinstance(data.get("answer"),str) or not isinstance(data.get("evidence"),list):
            raise RuntimeError("invalid research result")
        if not data["evidence"]:
            raise ResearchGroundingError("research result has no observed evidence")
        evidence=[]
        for item in data["evidence"]:
            if not isinstance(item,dict) or not isinstance(item.get("source"),str) or not isinstance(item.get("claim"),str): raise RuntimeError("invalid research evidence")
            confidence=item.get("confidence")
            if confidence is None or isinstance(confidence,bool): confidence="unknown"
            elif not isinstance(confidence,(str,int,float)): confidence="unknown"
            else: confidence=str(confidence).strip() or "unknown"
            evidence.append(Evidence(item["source"],item["claim"],str(item.get("excerpt","")),confidence,False,str(item.get("observed_at") or (getattr(out,"observed_at",None).isoformat() if getattr(out,"observed_at",None) else "")) or None,str(item.get("published_at") or "") or None))
        uncertainty=data.get("uncertainty","")
        if not isinstance(uncertainty,str): raise RuntimeError("invalid research uncertainty")
        return ResearchResult(data["answer"],tuple(evidence),uncertainty)
