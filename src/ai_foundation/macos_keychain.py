"""macOS Keychain Services via Security.framework; secrets never enter process argv."""
import ctypes
import ctypes.util
import platform

class MacOSKeychain:
    def __init__(self, service='ai-foundation'):
        if platform.system()!='Darwin': raise RuntimeError('macOS Keychain requires Darwin')
        self.service=service.encode(); path=ctypes.util.find_library('Security') or '/System/Library/Frameworks/Security.framework/Security'
        self.lib=ctypes.CDLL(path)
        self.lib.SecKeychainAddGenericPassword.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_void_p]
        self.lib.SecKeychainAddGenericPassword.restype=ctypes.c_int32
        self.lib.SecKeychainFindGenericPassword.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32),ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(ctypes.c_void_p)]
        self.lib.SecKeychainFindGenericPassword.restype=ctypes.c_int32
        self.lib.SecKeychainItemModifyAttributesAndData.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_void_p]; self.lib.SecKeychainItemModifyAttributesAndData.restype=ctypes.c_int32
        self.lib.SecKeychainItemDelete.argtypes=[ctypes.c_void_p]; self.lib.SecKeychainItemDelete.restype=ctypes.c_int32
        self.lib.SecKeychainItemFreeContent.argtypes=[ctypes.c_void_p,ctypes.c_void_p]; self.lib.SecKeychainItemFreeContent.restype=ctypes.c_int32
        self.cf=ctypes.CDLL(ctypes.util.find_library('CoreFoundation')); self.cf.CFRelease.argtypes=[ctypes.c_void_p]
    def _find(self,binding,want_data=False):
        account=binding.encode(); length=ctypes.c_uint32(); data=ctypes.c_void_p(); item=ctypes.c_void_p()
        rc=self.lib.SecKeychainFindGenericPassword(None,len(self.service),self.service,len(account),account,ctypes.byref(length) if want_data else None,ctypes.byref(data) if want_data else None,ctypes.byref(item))
        return rc,length,data,item
    def available(self,binding):
        if not binding:return False
        rc,_,_,item=self._find(binding);
        if item.value:self.cf.CFRelease(item)
        return rc==0
    def unlock(self,password):
        """Explicit owner unlock in the same SSH process; never process argv."""
        if type(password) is not str or not 0 < len(password.encode()) <= 4096:
            raise ValueError('keychain password required')
        raw=password.encode()
        unlock=self.lib.SecKeychainUnlock
        unlock.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_ubyte]
        unlock.restype=ctypes.c_int32
        rc=unlock(None,len(raw),raw,True)
        if rc!=0: raise RuntimeError(f'native credential unlock failed ({rc})')
    def save(self,binding,secret):
        if not binding or not secret: raise ValueError('binding and secret required on Darwin')
        raw=secret.encode(); rc,_,_,item=self._find(binding)
        try:
            if rc==0: rc=self.lib.SecKeychainItemModifyAttributesAndData(item,None,len(raw),raw)
            elif rc==-25300: rc=self.lib.SecKeychainAddGenericPassword(None,len(self.service),self.service,len(binding.encode()),binding.encode(),len(raw),raw,None)
            if rc!=0: raise RuntimeError(f'native credential save failed ({rc})')
        finally:
            if item.value:self.cf.CFRelease(item)
    def load(self,binding):
        if not binding: raise ValueError('binding required on Darwin')
        rc,n,data,item=self._find(binding,True)
        try:
            if rc!=0: raise KeyError(binding)
            return ctypes.string_at(data,n.value).decode()
        finally:
            if data.value:self.lib.SecKeychainItemFreeContent(None,data)
            if item.value:self.cf.CFRelease(item)
    def delete(self,binding):
        if not binding:return False
        rc,_,_,item=self._find(binding)
        try:
            return rc==0 and self.lib.SecKeychainItemDelete(item)==0
        finally:
            if item.value:self.cf.CFRelease(item)

