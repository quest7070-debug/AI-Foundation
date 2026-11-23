"""Bounded stdlib HTTP concurrency for Foundation-owned presentation gateways."""
import threading
from http.server import ThreadingHTTPServer

class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads=True
    block_on_close=False
    request_queue_size=32
    max_concurrent_requests=32
    def server_bind(self):
        if isinstance(self.max_concurrent_requests, bool) or not isinstance(self.max_concurrent_requests, int) or self.max_concurrent_requests <= 0:
            raise ValueError("max_concurrent_requests must be a strictly positive integer")
        if isinstance(self.request_queue_size,bool) or not isinstance(self.request_queue_size,int) or self.request_queue_size<=0:
            raise ValueError("request_queue_size must be a strictly positive integer")
        self._request_slots=threading.BoundedSemaphore(self.max_concurrent_requests)
        super().server_bind()
    def process_request(self,request,client_address):
        if not self._request_slots.acquire(blocking=False):
            # Bound memory/thread growth under overload. Closing the accepted socket
            # is an explicit transport rejection; no handler/thread is allocated.
            try: request.shutdown(2)
            except OSError: pass
            request.close();return
        try: super().process_request(request,client_address)
        except Exception:
            self._request_slots.release();raise
    def process_request_thread(self,request,client_address):
        try: super().process_request_thread(request,client_address)
        finally:self._request_slots.release()