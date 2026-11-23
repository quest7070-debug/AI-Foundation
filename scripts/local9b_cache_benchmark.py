#!/usr/bin/env python3
"""Finite owned f16/q8_0 decode benchmark; never modifies production settings."""
import json,os,time,socket,subprocess,tempfile,sys
from pathlib import Path
from urllib import request
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/"modules"))
from ai_foundation.host_compute_lease import HostComputeLease,HostComputeBusy
OP=request.build_opener(request.ProxyHandler({}))
def api(port,path,payload=None,timeout=5):
    req=request.Request("http://127.0.0.1:"+str(port)+path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type":"application/json"})
    with OP.open(req,timeout=timeout) as r:return json.load(r)
def run():
    out=ROOT/"speed-benchmark.json"
    if out.exists():raise RuntimeError("BENCHMARK_ALREADY_RECORDED")
    results=[]
    with HostComputeLease().hold(max_wait_s=600):
        if api(11434,"/api/ps")["models"]:raise RuntimeError("SHARED_MODEL_BUSY")
        with socket.socket() as s:s.bind(("127.0.0.1",11436))
        store=Path.home()/"Library/Application Support/AI-Foundation/direct-apfs-releases/ollama-qwen3-5-9b-56671c2ab9385f9c/models"
        for cache in ["f16","q8_0"]:
            with tempfile.TemporaryDirectory(prefix="9b-cache-bench-") as t:
                with (Path(t)/"server.log").open("w") as log:
                    env=dict(os.environ,OLLAMA_HOST="127.0.0.1:11436",
                        OLLAMA_MODELS=str(store),OLLAMA_NUM_PARALLEL="1",
                        OLLAMA_MAX_LOADED_MODELS="1",OLLAMA_CONTEXT_LENGTH="32768",
                        OLLAMA_FLASH_ATTENTION="1",OLLAMA_KV_CACHE_TYPE=cache)
                    daemon=subprocess.Popen(["/opt/homebrew/Cellar/ollama/0.34.4/libexec/ollama","serve"],env=env,stdout=log,stderr=log)
                    try:
                        for _ in range(50):
                            try:
                                tags=api(11436,"/api/tags")
                                if not any(x["name"]=="qwen3.5:9b" and x["digest"]=="56671c2ab9385f9cfcb404638e32cd62d88e3501d44822208363c010179a3c90" for x in tags["models"]):raise RuntimeError("MODEL_IDENTITY_MISMATCH")
                                break
                            except OSError:time.sleep(.2)
                        else:raise RuntimeError("OWNED_BACKEND_START_FAILED")
                        req={"model":"qwen3.5:9b","stream":False,"think":False,
                            "messages":[{"role":"user","content":"Output consecutive integers separated by commas, starting at 1 and continuing through at least 1000. Output numbers only. Do not stop early."}],
                            "options":{"temperature":0,"num_predict":128,"num_ctx":32768}}
                        for sample in range(2):
                            row=api(11436,"/api/chat",req,timeout=3600)
                            count=row.get("eval_count",0);ns=row.get("eval_duration",0)
                            if row.get("done") is not True or count<96 or not ns:raise RuntimeError("INCOMPARABLE_BENCHMARK_SAMPLE")
                            results.append({"cache":cache,"sample":sample,
                                "eval_count":count,"eval_duration_ns":ns,
                                "tokens_s":count/(ns/1e9),
                                "prompt_tokens":row.get("prompt_eval_count"),
                                "load_duration_ns":row.get("load_duration")})
                    finally:
                        daemon.terminate();daemon.wait(timeout=15)
    out.write_text(json.dumps({"samples":results,"production_changed":False,
        "thinking_disabled_for_synthetic_benchmark_only":True},indent=2))
    print(out.read_text(),flush=True)
if __name__=="__main__":run()
