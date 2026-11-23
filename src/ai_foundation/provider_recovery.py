import threading,time

class ProviderRecoveryLoop:
    """Background revalidation for excluded provider capacity; route policy remains host-owned."""
    def __init__(self,settings,interval=60,clock=time.sleep):
        self.settings=settings; self.interval=max(1,interval); self.clock=clock; self._stop=threading.Event(); self._tick_lock=threading.Lock(); self._next_probe={}
    def _delay(self,row):
        # RATE_LIMITED recovery must not consume a scarce inference quota every minute.
        # Prefer authoritative reset evidence when present; otherwise use a conservative backoff.
        seconds=getattr(getattr(self.settings,'routing',None),'_seconds',lambda x:None)
        resets=[seconds(row.get(k)) for k in ('short_reset','long_reset')]; resets=[x for x in resets if x]
        # Reset text schedules the next observation; it is never itself evidence
        # that quota has recovered.
        return max(resets) if resets else (3600 if row.get('health')=='RATE_LIMITED' else 60)
    def tick(self):
        # Never let overlapping manual/scheduled ticks multiply probes during a
        # prolonged outage. SettingsService separately serializes each mutation.
        if not self._tick_lock.acquire(blocking=False): return ()
        try:
            results=[]
            now=time.time()
            for row in self.settings.credentials():
                if row.get('health') not in {'RATE_LIMITED','DOWN'}: continue
                b=row['binding']
                if now < self._next_probe.get(b,0): continue
                self._next_probe[b]=now+self._delay(row)
                try:
                    result=self.settings.refresh_provider(b); results.append(result)
                    if result.get('health')=='ONLINE': self._next_probe.pop(b,None)
                except Exception: continue
            return tuple(results)
        finally:self._tick_lock.release()
    def run(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                # A transient storage outage must not permanently kill recovery.
                import logging
                logging.getLogger(__name__).exception("provider recovery tick failed; retrying")
            self._stop.wait(self.interval)
    def start(self):
        t=threading.Thread(target=self.run,name='foundation-provider-recovery',daemon=True);t.start();return t
    def stop(self):self._stop.set()
